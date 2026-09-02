"""AI endpoints over HTTP, with no API key present — the state a judge's
machine will actually be in.

Everything must return 200 and useful content. "AI unavailable" is a normal
operating mode, not an error.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("aiapi") / "test.db"
    from settlesense.api import deps

    deps.settings.db_path = str(db)
    deps.settings.config_path = str(ROOT / "recon.config.yaml")
    deps.settings.data_dir = DATA

    from settlesense.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def run_id(client) -> str:
    return client.post("/runs", data={}).json()["run_id"]


@pytest.fixture(autouse=True)
def _no_key(no_ai_keys):
    """Every test in this module runs as a judge's machine would: no key."""


def test_health_reports_ai_unavailable_with_a_reason(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["ai_enabled"] is False
    assert "is not set" in body["ai_unavailable_reason"]


def test_explain_succeeds_without_a_key(client, run_id) -> None:
    """Returns 200 with template counts, not a 500."""
    body = client.post(f"/runs/{run_id}/explain").json()
    assert body["explained"] == 25
    assert body["from_template"] == 25
    assert body["from_ai"] == 0
    assert body["ai_available"] is False
    assert body["evidence_coverage"] == 1.0


def test_explanations_appear_in_the_evidence_drawer(client, run_id) -> None:
    client.post(f"/runs/{run_id}/explain")
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    rid = page["results"][0]["reconciliation_id"]

    detail = client.get(f"/runs/{run_id}/results/{rid}").json()

    assert detail["explanation"] is not None
    assert detail["explanation"]["source"] == "template"
    assert detail["explanation"]["summary"]
    assert detail["explanation"]["evidence_refs"]
    # The badge the UI shows, so a reviewer always knows what wrote the text.
    assert detail["explanation"]["grounded"] is True


def test_matched_results_are_not_explained_by_default(client, run_id) -> None:
    """Calls scale with exceptions, not records — a clean match needs no
    narrative."""
    client.post(f"/runs/{run_id}/explain")
    page = client.get(f"/runs/{run_id}/results", params={"status": "matched"}).json()
    rid = page["results"][0]["reconciliation_id"]
    detail = client.get(f"/runs/{run_id}/results/{rid}").json()
    assert detail["explanation"] is None


def test_explaining_does_not_change_any_figure(client, run_id) -> None:
    """ADR-001 at the HTTP boundary."""
    before_summary = client.get(f"/runs/{run_id}/summary").json()
    before_metrics = client.get(f"/runs/{run_id}/metrics").json()

    client.post(f"/runs/{run_id}/explain")

    after_summary = client.get(f"/runs/{run_id}/summary").json()
    after_metrics = client.get(f"/runs/{run_id}/metrics").json()

    assert after_summary == before_summary
    for key, value in before_metrics.items():
        assert after_metrics[key] == value


def test_clustering_falls_back_to_reason_codes(client, run_id) -> None:
    body = client.post(f"/runs/{run_id}/cluster").json()
    clusters = body["clusters"]

    assert body["ai_available"] is False
    assert clusters
    assert all(c["source"] == "reason_code" for c in clusters)
    # Nothing is hidden: every exception lands in exactly one group.
    members = [pid for c in clusters for pid in c["member_payment_ids"]]
    assert len(members) == len(set(members)) == 25


def test_explain_404s_for_unknown_run(client) -> None:
    assert client.post("/runs/run_nope/explain").status_code == 404
