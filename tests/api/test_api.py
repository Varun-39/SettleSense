"""API tests. These run the real engine against the real benchmark and a real
(temporary) SQLite file — no mocks, so a passing test means the endpoint
actually works end to end.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MALFORMED = ROOT / "demo" / "failure-fixtures" / "malformed"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """A fresh DB per test module, with the app pointed at it."""
    db = tmp_path_factory.mktemp("api") / "test.db"

    from settlesense.api import deps

    deps.settings.db_path = str(db)
    deps.settings.config_path = str(ROOT / "recon.config.yaml")
    deps.settings.data_dir = DATA

    from settlesense.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def run_id(client) -> str:
    response = client.post("/runs", data={})
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


# -- meta -------------------------------------------------------------------


def test_health_reports_engine_and_rules_version(client) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["engine_version"]
    assert body["rules_version"]
    assert body["ai_enabled"] is False


# -- run creation -----------------------------------------------------------


def test_create_run_reconciles_the_benchmark(client) -> None:
    body = client.post("/runs", data={}).json()
    assert body["records_processed"] == 100


def test_create_run_is_idempotent_on_batch_id(client, run_id) -> None:
    """The duplicate-batch failure case, at the HTTP boundary."""
    again = client.post("/runs", data={}).json()
    assert again["run_id"] == run_id
    assert again["already_existed"] is True


def test_create_run_from_uploaded_files(client) -> None:
    files = {
        name: (f"{name}.csv", (MALFORMED / filename).read_bytes(), "text/csv")
        for name, filename in [
            ("payments", "sample_payments.csv"),
            ("settlements", "sample_settlements.csv"),
            ("refunds", "sample_refunds.csv"),
            ("ledger", "sample_ledger.csv"),
        ]
    }
    response = client.post("/runs", files=files)
    assert response.status_code == 201, response.text
    # 8 rows in, 6 malformed, 2 survive — the batch did not abort.
    assert response.json()["records_processed"] == 2


def test_partial_upload_is_rejected(client) -> None:
    files = {"payments": ("p.csv", b"payment_id\n", "text/csv")}
    assert client.post("/runs", files=files).status_code == 400


def test_unknown_fixture_returns_404(client) -> None:
    assert client.post("/runs", data={"fixture": "no/such/dir"}).status_code == 404


# -- summary ----------------------------------------------------------------


def test_summary_returns_control_totals(client, run_id) -> None:
    s = client.get(f"/runs/{run_id}/summary").json()
    assert s["records_processed"] == 100
    assert s["matched"] == 75
    assert s["needs_review"] == 7
    assert s["unresolved"] == 18
    assert s["matched"] + s["needs_review"] + s["unresolved"] == 100


def test_money_is_returned_as_paise_and_display(client, run_id) -> None:
    """The client never guesses the unit and never does the arithmetic."""
    s = client.get(f"/runs/{run_id}/summary").json()
    assert isinstance(s["gross_payments"]["paise"], int)
    assert s["gross_payments"]["display"].startswith("Rs ")
    assert s["gross_payments"]["paise"] == 16_796_350


def test_summary_404s_for_unknown_run(client) -> None:
    assert client.get("/runs/run_nope/summary").status_code == 404


# -- results ----------------------------------------------------------------


def test_results_are_paginated(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"limit": 10}).json()
    assert page["total"] == 100
    assert len(page["results"]) == 10


def test_results_filter_by_status(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    assert page["total"] == 7
    assert all(r["status"] == "review" for r in page["results"])


def test_results_filter_by_reason_code(client, run_id) -> None:
    page = client.get(
        f"/runs/{run_id}/results", params={"reason_code": "failed_settlement"}
    ).json()
    assert page["total"] == 3


def test_results_filter_by_minimum_difference(client, run_id) -> None:
    page = client.get(
        f"/runs/{run_id}/results", params={"min_difference": 1}
    ).json()
    assert page["total"] == 4  # only the Rs 50 amount-mismatch cases carry a
    # nonzero difference; unresolved money is `pending`, not a discrepancy
    assert all(abs(r["difference"]["paise"]) >= 1 for r in page["results"])


def test_invalid_status_filter_is_rejected(client, run_id) -> None:
    response = client.get(f"/runs/{run_id}/results", params={"status": "excellent"})
    assert response.status_code == 422


# -- evidence drawer --------------------------------------------------------


def test_evidence_drawer_returns_rows_and_arithmetic(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    rid = page["results"][0]["reconciliation_id"]

    detail = client.get(f"/runs/{run_id}/results/{rid}").json()

    assert detail["calc_steps"], "no calculation trace"
    assert detail["evidence"], "no evidence rows"
    # Evidence resolves to the actual stored source row, not just an id.
    payment_rows = [e for e in detail["evidence"] if e["table"] == "payments"]
    assert payment_rows and payment_rows[0]["row"]["payment_id"]


def test_calculation_trace_is_arithmetically_consistent(client, run_id) -> None:
    """The drawer's numbers must reconcile with each other — this is what makes
    'the Rs 30 difference is the fee' verifiable rather than asserted."""
    page = client.get(
        f"/runs/{run_id}/results", params={"reason_code": "fee_mismatch"}
    ).json()
    rid = page["results"][0]["reconciliation_id"]
    detail = client.get(f"/runs/{run_id}/results/{rid}").json()

    steps = {s["label"]: s for s in detail["calc_steps"]}
    expected = steps["expected net settlement"]
    i = expected["inputs"]
    assert (
        i["payment_amount"] - i["refunds"] - i["fee"] - i["tax"]
        == expected["result"]["paise"]
    )

    diff = steps["difference vs settled amount"]
    assert (
        diff["inputs"]["actual_net"] - diff["inputs"]["expected_net"]
        == diff["result"]["paise"]
    )
    assert diff["result"]["paise"] == detail["result"]["difference"]["paise"]


def test_partial_settlement_shows_every_claimed_row(client, run_id) -> None:
    page = client.get(
        f"/runs/{run_id}/results", params={"match_type": "partial", "limit": 1}
    ).json()
    rid = page["results"][0]["reconciliation_id"]
    detail = client.get(f"/runs/{run_id}/results/{rid}").json()
    assert len(detail["settlements"]) == 2


def test_explanation_is_null_and_that_is_a_valid_state(client, run_id) -> None:
    """ADR-001: with no AI sidecar, the drawer still works and every number is
    present. Explanation absence degrades copy, not correctness."""
    page = client.get(f"/runs/{run_id}/results", params={"limit": 1}).json()
    rid = page["results"][0]["reconciliation_id"]
    detail = client.get(f"/runs/{run_id}/results/{rid}").json()
    assert detail["explanation"] is None
    assert detail["result"]["expected_net"]["paise"] is not None


def test_unknown_result_404s(client, run_id) -> None:
    assert client.get(f"/runs/{run_id}/results/nope").status_code == 404


# -- exceptions and metrics -------------------------------------------------


def test_exceptions_are_grouped_by_reason(client, run_id) -> None:
    groups = client.get(f"/runs/{run_id}/exceptions").json()
    by_reason = {g["reason_code"]: g for g in groups}
    assert by_reason["missing_settlement"]["count"] == 18
    assert by_reason["fee_mismatch"]["count"] == 4
    assert by_reason["failed_settlement"]["count"] == 3
    assert sum(g["count"] for g in groups) == 25


def test_metrics_report_zero_false_matches(client, run_id) -> None:
    metrics = client.get(f"/runs/{run_id}/metrics").json()
    assert metrics["false_matches"] == 0
    assert metrics["records_processed"] == 100
    assert metrics["match_rate"] == 1.0


def test_ledger_findings_expose_duplicates(client, run_id) -> None:
    findings = client.get(f"/runs/{run_id}/ledger-findings").json()
    assert len([f for f in findings if f["reason"] == "duplicate_record"]) == 5


# -- review queue -----------------------------------------------------------


def test_review_action_is_recorded_without_changing_the_verdict(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    rid = page["results"][0]["reconciliation_id"]

    response = client.post(
        f"/runs/{run_id}/results/{rid}/review",
        json={"action": "accept", "note": "confirmed with bank", "actor": "varun"},
    )
    assert response.status_code == 201

    detail = client.get(f"/runs/{run_id}/results/{rid}").json()
    assert detail["result"]["status"] == "review"  # engine verdict untouched
    assert detail["review_actions"][-1]["action"] == "accept"
    assert detail["review_actions"][-1]["actor"] == "varun"


def test_invalid_review_action_is_rejected(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    rid = page["results"][0]["reconciliation_id"]
    response = client.post(
        f"/runs/{run_id}/results/{rid}/review", json={"action": "delete_everything"}
    )
    assert response.status_code == 422


# -- export -----------------------------------------------------------------


def test_csv_export_has_a_row_per_payment(client, run_id) -> None:
    response = client.get(f"/runs/{run_id}/export.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    lines = [line for line in response.text.splitlines() if line.strip()]
    assert len(lines) == 101  # header + 100
    assert lines[0].startswith("payment_id,status,match_type")
