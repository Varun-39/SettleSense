"""The queries the results table runs must not scan.

Both subqueries on the results page once did. At a hundred rows that is
invisible; the cost grows with results x history, so it only shows up on the
batch you most wanted to work. An index is easy to drop by accident during a
schema edit, and nothing else in the suite would notice — the answers stay
correct, they just get slower.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "src" / "settlesense" / "store" / "schema.sql"
)

# The query behind the results table, which reads review state and the payment
# capture time for every row it displays.
RESULTS_QUERY = """
SELECT r.*,
       (SELECT COUNT(*) FROM review_actions a
         WHERE a.reconciliation_id = r.reconciliation_id) AS review_count,
       (SELECT a.action FROM review_actions a
         WHERE a.reconciliation_id = r.reconciliation_id
         ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS last_action,
       (SELECT json_extract(s.raw_json, '$.captured_at') FROM source_rows s
         WHERE s.run_id = r.run_id
           AND s.table_name = 'payments'
           AND s.natural_id = r.payment_id) AS captured_at
  FROM reconciliation_results r
 WHERE r.run_id = ?
 ORDER BY r.payment_id LIMIT 100
"""


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn


def plan(conn: sqlite3.Connection, query: str, params: tuple) -> list[str]:
    return [row[-1] for row in conn.execute(f"EXPLAIN QUERY PLAN {query}", params)]


def test_the_results_query_never_scans(db) -> None:
    steps = plan(db, RESULTS_QUERY, ("run_x",))
    scans = [s for s in steps if s.strip().startswith("SCAN")]
    assert not scans, "full table scan per result row:\n  " + "\n  ".join(steps)


def test_review_state_is_read_through_an_index(db) -> None:
    steps = " | ".join(plan(db, RESULTS_QUERY, ("run_x",)))
    assert "idx_review_actions_recon" in steps


def test_the_capture_time_lookup_uses_all_three_columns(db) -> None:
    """run_id and table_name alone still leave a scan within the partition."""
    steps = " | ".join(plan(db, RESULTS_QUERY, ("run_x",)))
    assert "idx_source_rows_lookup" in steps
    assert "natural_id=?" in steps


def test_bulk_sign_off_checks_only_the_ids_it_was_given(db) -> None:
    """It used to load every id ever written, which grows with run history
    rather than with the size of the request."""
    ids = ["a", "b", "c"]
    placeholders = ",".join("?" * len(ids))
    steps = plan(
        db,
        "SELECT reconciliation_id FROM reconciliation_results "
        f"WHERE reconciliation_id IN ({placeholders})",
        tuple(ids),
    )
    assert not [s for s in steps if s.strip().startswith("SCAN")], steps
