"""Explanation orchestration — the four gates in order (ADR-005).

    input gate  -> context.build_case   (verdict + trace + cited rows only)
    schema gate -> client.parse         (closed enum, validated shape)
    grounding   -> grounding.check      (refs exist, figures real, category sane)
    failure     -> client failure gate  (timeout, retry, circuit breaker)

Anything that fails a gate becomes a deterministic template explanation. The
result is always an explanation — never a blank cell, never a wrong claim.

This module runs AFTER the engine has persisted its results and metrics.
Nothing here can change a number (ADR-001).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from settlesense.ai.client import AIClient
from settlesense.ai.context import SYSTEM_PROMPT, build_case
from settlesense.ai.fallback import render as render_template
from settlesense.ai.grounding import check as check_grounding
from settlesense.ai.schemas import ExplanationOut
from settlesense.contracts.enums import ReasonCode
from settlesense.store.repository import Repository

log = logging.getLogger(__name__)


@dataclass
class ExplainReport:
    """What happened, in numbers a metrics panel can display honestly."""

    total: int = 0
    grounded: int = 0
    from_ai: int = 0
    from_template: int = 0
    from_cache: int = 0
    rejected_by_grounding: int = 0
    grounding_failures: list[str] = field(default_factory=list)
    ai_available: bool = False
    unavailable_reason: str | None = None

    @property
    def evidence_coverage(self) -> float:
        """Grounded explanations / all explanations.

        Counted from what was actually stored, never assumed. It should read
        1.0 because ungrounded answers are downgraded to templates rather than
        published — but it is derived from the tally, so if that ever stops
        being true the number says so instead of hiding it.
        """
        return 1.0 if self.total == 0 else self.grounded / self.total

    @property
    def ai_grounded_rate(self) -> float:
        """Of the AI answers actually attempted, how many survived the gate.
        This is the number worth watching when tuning prompts."""
        attempted = self.from_ai + self.rejected_by_grounding
        return 1.0 if attempted == 0 else self.from_ai / attempted


def _cache_key(prompt_version: str, trace_hash: str, row_hashes: tuple[str, ...]) -> str:
    joined = "|".join([prompt_version, trace_hash, *row_hashes])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def explain_result(
    detail: dict, client: AIClient, repo: Repository, report: ExplainReport
) -> tuple[ExplanationOut, str, bool]:
    """Explain one case. Returns (explanation, source, grounded)."""
    result = detail["result"]
    evidence = detail["evidence"]
    engine_reason = (
        ReasonCode(result["reason_code"]) if result.get("reason_code") else None
    )

    context = build_case(result, detail["calc_steps"], evidence)
    key = _cache_key(
        client.config.prompt_version, context.trace_hash, context.row_hashes
    )

    cached = repo.get_cached_explanation(key)
    if cached is not None:
        report.from_cache += 1
        report.from_ai += 1
        return ExplanationOut.model_validate(cached), "ai", True

    candidate = client.parse(
        system=SYSTEM_PROMPT, user=context.prompt, output_model=ExplanationOut
    )

    if candidate is None:
        report.from_template += 1
        return render_template(result, evidence), "template", True

    grounding = check_grounding(candidate, context, engine_reason)
    if not grounding:
        report.rejected_by_grounding += 1
        report.grounding_failures.extend(
            f"{result['payment_id']}: {f}" for f in grounding.failures
        )
        log.info(
            "explanation for %s rejected by grounding gate: %s",
            result["payment_id"],
            "; ".join(grounding.failures),
        )
        report.from_template += 1
        return render_template(result, evidence), "template", True

    repo.save_cached_explanation(
        key, candidate.model_dump(mode="json"), client.config.model,
        client.config.prompt_version,
    )
    report.from_ai += 1
    return candidate, "ai", True


def explain_run(
    run_id: str,
    repo: Repository,
    client: AIClient,
    only_exceptions: bool = True,
) -> ExplainReport:
    """Explain a run's cases and persist the results.

    Defaults to exceptions only: a clean match needs no narrative, and calls
    scale with exceptions rather than records (ADR-001).
    """
    report = ExplainReport()
    report.ai_available = client.available()
    report.unavailable_reason = client.unavailable_reason()

    rows, _ = repo.query_results(
        run_id,
        status=None,
        limit=1_000_000,
    )
    targets = [r for r in rows if not only_exceptions or r["status"] != "matched"]

    for row in targets:
        detail = repo.result_detail(row["reconciliation_id"])
        if detail is None:
            continue
        explanation, source, grounded = explain_result(detail, client, repo, report)
        report.total += 1
        report.grounded += int(grounded)
        repo.save_explanation(
            reconciliation_id=row["reconciliation_id"],
            explanation=explanation,
            source=source,
            grounded=grounded,
            model=client.config.model if source == "ai" else None,
            prompt_version=client.config.prompt_version,
        )

    if report.total:
        repo.save_metric(run_id, "ai_explanations", report.from_ai)
        repo.save_metric(run_id, "template_explanations", report.from_template)
        repo.save_metric(run_id, "grounding_rejections", report.rejected_by_grounding)
        repo.save_metric(run_id, "evidence_coverage", report.evidence_coverage)

    return report
