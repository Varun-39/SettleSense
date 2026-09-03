"""The fixture registry resolves names, never paths.

An earlier version passed the `fixture` form field to `Path()` directly, so a
caller could walk the filesystem looking for any directory holding four CSVs
with the expected names. These tests keep that closed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = tmp_path_factory.mktemp("fixtures") / "test.db"
    from settlesense.api import deps

    deps.settings.db_path = str(db)
    deps.settings.config_path = str(ROOT / "recon.config.yaml")
    deps.settings.data_dir = ROOT / "data"

    from settlesense.api.main import app

    with TestClient(app) as c:
        yield c


def test_listing_reports_installed_fixtures(client) -> None:
    body = client.get("/fixtures").json()
    names = {f["name"] for f in body}
    assert {"benchmark", "malformed", "ambiguous"} <= names
    for f in body:
        assert f["label"] and f["description"]
        assert f["available"] is True, f"{f['name']} is not installed"


@pytest.mark.parametrize(
    "attempt",
    [
        "../../../etc",
        "..",
        "/etc",
        "C:\\Windows",
        "data",  # a real directory, but not a registered name
        "demo/failure-fixtures/malformed",  # the old path form
        "",
    ],
)
def test_paths_are_not_accepted_as_fixture_names(client, attempt) -> None:
    response = client.post("/runs", data={"fixture": attempt})
    # An empty value falls through to the default batch; everything else that
    # looks like a path must be refused.
    if attempt == "":
        assert response.status_code == 201
    else:
        assert response.status_code == 404, f"{attempt!r} was accepted"


def test_named_fixture_runs(client) -> None:
    body = client.post("/runs", data={"fixture": "ambiguous"}).json()
    assert body["records_processed"] == 3

    run_id = body["run_id"]
    page = client.get(f"/runs/{run_id}/results").json()
    statuses = [r["status"] for r in page["results"]]
    assert statuses.count("review") == 2
    assert statuses.count("matched") == 1


def test_malformed_fixture_quarantines_rows(client) -> None:
    body = client.post("/runs", data={"fixture": "malformed"}).json()
    run_id = body["run_id"]

    errors = client.get(f"/runs/{run_id}/validation-errors").json()
    assert len(errors) == 6
    assert {e["field"] for e in errors} == {
        "amount",
        "captured_at",
        "payment_id",
        "currency",
        "status",
    }
    for e in errors:
        assert e["source_line"] >= 2
        assert e["reason"]


def test_reconciling_the_same_fixture_twice_reuses_the_run(client) -> None:
    first = client.post("/runs", data={"fixture": "ambiguous"}).json()
    second = client.post("/runs", data={"fixture": "ambiguous"}).json()
    assert second["run_id"] == first["run_id"]
    assert second["already_existed"] is True
