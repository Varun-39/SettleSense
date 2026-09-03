"""Triage as a workflow, not a single action.

An analyst clears a queue over several sittings, so the table has to carry
review state, and eighteen cases waiting on the same provider batch have to be
signable in one go.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("review") / "test.db"
    from settlesense.api import deps

    deps.settings.db_path = str(db)
    deps.settings.config_path = str(ROOT / "recon.config.yaml")
    deps.settings.data_dir = ROOT / "data"

    from settlesense.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def run_id(client) -> str:
    return client.post("/runs", data={}).json()["run_id"]


# -- what the table needs to show progress ----------------------------------


def test_rows_carry_review_state(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"limit": 5}).json()
    for row in page["results"]:
        assert row["review_count"] == 0
        assert row["last_action"] is None


def test_rows_carry_the_payment_capture_time(client, run_id) -> None:
    """Aging an exception needs the capture time on the row; a request per row
    would be 100 requests to draw one column."""
    page = client.get(f"/runs/{run_id}/results", params={"limit": 5}).json()
    for row in page["results"]:
        assert row["captured_at"], "no capture time to age the exception from"
        assert "20" in row["captured_at"]


def test_signing_off_shows_up_in_the_table(client, run_id) -> None:
    page = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    rid = page["results"][0]["reconciliation_id"]

    client.post(
        f"/runs/{run_id}/results/{rid}/review",
        json={"action": "accept", "actor": "VB", "note": "confirmed"},
    )

    again = client.get(f"/runs/{run_id}/results", params={"status": "review"}).json()
    row = next(r for r in again["results"] if r["reconciliation_id"] == rid)
    assert row["review_count"] == 1
    assert row["last_action"] == "accept"


# -- bulk sign-off ----------------------------------------------------------


def test_bulk_sign_off_records_every_selected_case(client, run_id) -> None:
    page = client.get(
        f"/runs/{run_id}/results", params={"reason_code": "missing_settlement"}
    ).json()
    ids = [r["reconciliation_id"] for r in page["results"]]
    assert len(ids) == 18

    body = client.post(
        f"/runs/{run_id}/results/review-batch",
        json={
            "reconciliation_ids": ids,
            "action": "annotate",
            "actor": "VB",
            "note": "chasing the provider",
        },
    ).json()

    assert body["requested"] == 18
    assert body["recorded"] == 18

    again = client.get(
        f"/runs/{run_id}/results", params={"reason_code": "missing_settlement"}
    ).json()
    for row in again["results"]:
        assert row["review_count"] >= 1
        assert row["last_action"] == "annotate"


def test_bulk_sign_off_ignores_ids_outside_the_run(client, run_id) -> None:
    """A stale selection must not fail the whole request and lose the
    reviewer's work — the returned count says what was actually recorded."""
    page = client.get(f"/runs/{run_id}/results", params={"limit": 2}).json()
    ids = [r["reconciliation_id"] for r in page["results"]]

    body = client.post(
        f"/runs/{run_id}/results/review-batch",
        json={
            "reconciliation_ids": [*ids, "run_nope:pay_9999", "garbage"],
            "action": "accept",
            "actor": "VB",
        },
    ).json()

    assert body["requested"] == 4
    assert body["recorded"] == 2


def test_bulk_sign_off_rejects_an_empty_selection(client, run_id) -> None:
    response = client.post(
        f"/runs/{run_id}/results/review-batch",
        json={"reconciliation_ids": [], "action": "accept", "actor": "VB"},
    )
    assert response.status_code == 400


def test_bulk_sign_off_404s_for_unknown_run(client) -> None:
    response = client.post(
        "/runs/run_nope/results/review-batch",
        json={"reconciliation_ids": ["x"], "action": "accept", "actor": "VB"},
    )
    assert response.status_code == 404


def test_review_batch_is_not_read_as_a_result_id(client, run_id) -> None:
    """The literal path must not be swallowed by the {reconciliation_id:path}
    route registered after it."""
    response = client.post(
        f"/runs/{run_id}/results/review-batch",
        json={"reconciliation_ids": ["x"], "action": "accept", "actor": "VB"},
    )
    assert response.status_code == 201


def test_sign_off_never_changes_a_figure(client, run_id) -> None:
    before = client.get(f"/runs/{run_id}/summary").json()
    page = client.get(f"/runs/{run_id}/results", params={"limit": 3}).json()

    client.post(
        f"/runs/{run_id}/results/review-batch",
        json={
            "reconciliation_ids": [r["reconciliation_id"] for r in page["results"]],
            "action": "reject",
            "actor": "VB",
        },
    )

    assert client.get(f"/runs/{run_id}/summary").json() == before
