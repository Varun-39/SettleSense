"""The failure gate, the template fallback, and ADR-001's central promise:
turning the AI layer on or off changes no number anywhere.

No network is touched. The client is scripted so every branch — success,
timeout, refusal, circuit break, hallucination — is exercised deterministically.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from settlesense.ai.client import AIClient
from settlesense.ai.explain import explain_run
from settlesense.ai.fallback import render as render_template
from settlesense.ai.schemas import ExplanationOut
from settlesense.contracts.config import AIConfig, load_config
from settlesense.contracts.enums import ReasonCode, RecommendedAction
from settlesense.evaluate.evaluator import evaluate, load_ground_truth
from settlesense.ingest.batch import load_batch
from settlesense.recon.engine import run as run_engine
from settlesense.store.repository import Repository

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@pytest.fixture
def ai_config() -> AIConfig:
    return AIConfig(
        model="claude-opus-5",
        effort="low",
        max_tokens=2000,
        timeout_seconds=8,
        max_retries=1,
        circuit_breaker_failures=3,
        prompt_version="test-v1",
    )


class ScriptedClient(AIClient):
    """An AIClient whose `parse` follows a script instead of calling the API."""

    def __init__(self, config: AIConfig, script) -> None:
        super().__init__(config, api_key="test-key")
        self._script = script
        self.call_count = 0

    def available(self) -> bool:
        return not self.stats.circuit_open

    def unavailable_reason(self):
        return "circuit open" if self.stats.circuit_open else None

    def parse(self, system, user, output_model):
        if self.stats.circuit_open:
            return None
        self.call_count += 1
        outcome = self._script(self.call_count, user)
        if outcome is None:
            return self._fail("scripted failure")
        self.stats.consecutive_failures = 0
        return outcome


def good_explanation(
    payment_id: str, category: ReasonCode = ReasonCode.MISSING_SETTLEMENT
) -> ExplanationOut:
    return ExplanationOut(
        category=category,
        summary=f"Payment {payment_id} needs a reviewer's attention.",
        evidence_refs=[payment_id],
        recommended_action=RecommendedAction.WAIT_NEXT_BATCH,
        needs_human_review=True,
    )


def _field(user: str, name: str) -> str:
    return next(
        line.split(": ", 1)[1] for line in user.splitlines() if line.startswith(f"{name}: ")
    )


def grounded_script(n: int, user: str) -> ExplanationOut:
    """A well-behaved model: echoes the engine's own category and cites only
    the payment it was given. Always passes the grounding gate."""
    return good_explanation(
        _field(user, "payment_id"), ReasonCode(_field(user, "reason_code"))
    )


@pytest.fixture
def persisted_run(tmp_path):
    """A real reconciled run in a real database."""
    config = load_config(ROOT / "recon.config.yaml")
    output = run_engine(
        load_batch(
            DATA / "sample_payments.csv",
            DATA / "sample_settlements.csv",
            DATA / "sample_refunds.csv",
            DATA / "sample_ledger.csv",
        ),
        config,
    )
    metrics = evaluate(output, load_ground_truth(DATA / "ground_truth.csv"))
    repo = Repository(tmp_path / "run.db")
    repo.save_run(output, config_json=config.model_dump_json(), metrics=metrics)
    yield repo, output.run_id
    repo.close()


# -- the failure gate -------------------------------------------------------


def test_no_api_key_means_unavailable_not_an_exception(ai_config, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = AIClient(ai_config)
    assert client.available() is False
    assert "ANTHROPIC_API_KEY" in client.unavailable_reason()
    assert client.parse("sys", "user", ExplanationOut) is None


def test_empty_api_key_is_treated_as_missing(ai_config, monkeypatch) -> None:
    """An empty env var must not become an auth error later."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    client = AIClient(ai_config)
    assert client.available() is False
    assert "not set" in client.unavailable_reason()


def test_circuit_breaker_opens_after_consecutive_failures(ai_config) -> None:
    client = ScriptedClient(ai_config, script=lambda n, u: None)

    for _ in range(ai_config.circuit_breaker_failures):
        client.parse("sys", "user", ExplanationOut)

    assert client.stats.circuit_open
    calls_before = client.call_count
    client.parse("sys", "user", ExplanationOut)
    assert client.call_count == calls_before, "circuit did not stop further calls"


def test_a_success_resets_the_consecutive_failure_count(ai_config) -> None:
    script = lambda n, u: None if n < 3 else good_explanation("pay_1")
    client = ScriptedClient(ai_config, script)

    client.parse("s", "u", ExplanationOut)
    client.parse("s", "u", ExplanationOut)
    assert client.stats.consecutive_failures == 2

    client.parse("s", "u", ExplanationOut)
    assert client.stats.consecutive_failures == 0
    assert not client.stats.circuit_open


# -- the template fallback --------------------------------------------------


@pytest.mark.parametrize("reason", list(ReasonCode))
def test_every_reason_code_has_a_template_explanation(reason) -> None:
    """ADR-005 requires the fallback to explain everything the engine can
    conclude — otherwise a strict grounding gate would leave blank cells."""
    result = {
        "payment_id": "pay_1",
        "status": "review",
        "reason_code": reason.value,
        "match_type": "exact_id",
        "expected_net": 100_000,
        "actual_net": 95_000,
        "difference_amount": -5_000,
        "settled_amount": 95_000,
        "pending_amount": 0,
    }
    evidence = [{"natural_id": "pay_1", "table": "payments"}]
    explanation = render_template(result, evidence)

    assert explanation.summary.strip()
    assert "pay_1" in explanation.summary
    assert explanation.evidence_refs == ["pay_1"]
    assert explanation.needs_human_review is True


def test_template_for_a_matched_case_recommends_no_action() -> None:
    result = {
        "payment_id": "pay_1",
        "status": "matched",
        "reason_code": None,
        "match_type": "exact_id",
        "expected_net": 100_000,
        "actual_net": 100_000,
        "difference_amount": 0,
        "settled_amount": 100_000,
        "pending_amount": 0,
    }
    explanation = render_template(result, [{"natural_id": "pay_1"}])
    assert explanation.recommended_action is RecommendedAction.NO_ACTION
    assert explanation.needs_human_review is False


# -- orchestration ----------------------------------------------------------


def test_ai_unavailable_produces_templates_for_every_exception(
    persisted_run, ai_config, monkeypatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    repo, run_id = persisted_run

    report = explain_run(run_id, repo, AIClient(ai_config))

    assert report.total == 25
    assert report.from_template == 25
    assert report.from_ai == 0
    assert report.evidence_coverage == 1.0


def test_ungrounded_answers_are_downgraded_to_templates(
    persisted_run, ai_config
) -> None:
    """A hallucinated reference must never reach the database as an AI
    explanation."""
    hallucinating = ExplanationOut(
        category=ReasonCode.MISSING_SETTLEMENT,
        summary="A refund of Rs 9,999.99 explains this.",
        evidence_refs=["rfnd_does_not_exist"],
        recommended_action=RecommendedAction.VERIFY_REFUND,
        needs_human_review=True,
    )
    repo, run_id = persisted_run
    client = ScriptedClient(ai_config, script=lambda n, u: hallucinating)

    report = explain_run(run_id, repo, client)

    assert report.rejected_by_grounding == report.total
    assert report.from_ai == 0
    assert report.from_template == report.total
    assert report.grounding_failures

    stored = repo.explanation_for(f"{run_id}:pay_1070")
    assert stored["source"] == "template"
    assert "9,999.99" not in stored["summary"]


def test_grounded_answers_are_stored_as_ai(persisted_run, ai_config) -> None:
    repo, run_id = persisted_run
    report = explain_run(run_id, repo, ScriptedClient(ai_config, grounded_script))

    assert report.from_ai > 0
    assert report.rejected_by_grounding == 0
    stored = repo.explanation_for(f"{run_id}:pay_1070")
    assert stored["source"] == "ai"
    assert stored["grounded"] is True


def test_explanations_are_cached_by_content(persisted_run, ai_config) -> None:
    """Re-running a demo must not re-pay for identical work."""
    repo, run_id = persisted_run

    client = ScriptedClient(ai_config, grounded_script)
    first = explain_run(run_id, repo, client)
    calls_after_first = client.call_count

    second = explain_run(run_id, repo, client)

    assert first.from_cache == 0
    assert second.from_cache == second.total
    assert client.call_count == calls_after_first, "cache did not prevent re-calls"


def test_circuit_break_midway_falls_back_for_the_remainder(
    persisted_run, ai_config
) -> None:
    """The stage demo: the API dies partway through and nothing breaks."""
    repo, run_id = persisted_run

    def script(n: int, user: str):
        if n <= 2:
            return grounded_script(n, user)
        return None  # everything after this fails

    report = explain_run(run_id, repo, ScriptedClient(ai_config, script))

    assert report.from_ai == 2
    assert report.from_template == report.total - 2
    assert report.total == 25  # every case still got an explanation


# -- ADR-001: the central promise -------------------------------------------


def test_ai_layer_changes_no_reconciliation_figure(persisted_run, ai_config) -> None:
    """Run the sidecar and assert that every stored result row and every
    deterministic metric is byte-identical afterwards."""
    repo, run_id = persisted_run

    before_results = [dict(r) for r in repo.results_for(run_id)]
    before_metrics = repo.metrics_for(run_id)

    explain_run(
        run_id,
        repo,
        ScriptedClient(ai_config, grounded_script),
    )

    after_results = [dict(r) for r in repo.results_for(run_id)]
    after_metrics = repo.metrics_for(run_id)

    assert after_results == before_results
    for name, value in before_metrics.items():
        assert after_metrics[name] == value, f"metric {name} changed"


def test_deleting_every_explanation_changes_no_number(
    persisted_run, ai_config
) -> None:
    """The literal statement in ADR-001: truncate `explanations` and the
    screens still show the same figures."""
    repo, run_id = persisted_run
    explain_run(
        run_id,
        repo,
        ScriptedClient(ai_config, grounded_script),
    )
    summary_with = repo.summary_for(run_id)

    repo._conn.execute("DELETE FROM explanations")
    repo._conn.commit()

    assert repo.summary_for(run_id) == summary_with
    assert repo.explanation_for(f"{run_id}:pay_1070") is None
