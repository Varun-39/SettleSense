"""The golden benchmark: 100 controlled records with known ground truth.

These assertions are the numbers reported in the pitch. If a rule change moves
them, the diff shows up here rather than in a demo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from settlesense.contracts.config import load_config
from settlesense.contracts.enums import ResultStatus
from settlesense.evaluate.evaluator import evaluate, load_ground_truth
from settlesense.ingest.batch import load_batch
from settlesense.recon.engine import run

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def load(data_dir: Path = DATA):
    return load_batch(
        data_dir / "sample_payments.csv",
        data_dir / "sample_settlements.csv",
        data_dir / "sample_refunds.csv",
        data_dir / "sample_ledger.csv",
    )


@pytest.fixture(scope="module")
def result():
    config = load_config(ROOT / "recon.config.yaml")
    output = run(load(), config)
    metrics = evaluate(output, load_ground_truth(DATA / "ground_truth.csv"))
    return output, metrics


def test_benchmark_has_no_false_matches(result) -> None:
    """The headline metric. Never trade this for a higher raw match rate."""
    _, metrics = result
    assert metrics.false_matches == 0


def test_benchmark_verdicts_all_correct(result) -> None:
    _, metrics = result
    assert metrics.records_processed == 100
    assert metrics.correct_verdicts == 100
    assert metrics.match_rate == 1.0


def test_benchmark_catches_every_known_exception(result) -> None:
    _, metrics = result
    assert metrics.exception_recall == 1.0
    assert metrics.known_exceptions == 25


def test_benchmark_status_distribution(result) -> None:
    """35 exact + 15 fee + 10 refund + 10 partial + 5 dup-ledger = 75 matched;
    4 amount-mismatch + 3 failed = 7 review; 10 delayed + 8 missing = 18."""
    output, _ = result
    counts = {s: 0 for s in ResultStatus}
    for r in output.results:
        counts[r.status] += 1
    assert counts[ResultStatus.MATCHED] == 75
    assert counts[ResultStatus.REVIEW] == 7
    assert counts[ResultStatus.UNRESOLVED] == 18


def test_benchmark_accepts_no_invalid_rows(result) -> None:
    output, _ = result
    assert output.validation_errors == []


def test_every_result_carries_evidence(result) -> None:
    """Evidence coverage for the deterministic layer: no conclusion without a
    citation, including the unresolved ones."""
    output, _ = result
    for r in output.results:
        assert r.evidence, f"{r.payment_id} has no evidence"
        assert any(ref.table == "payments" for ref in r.evidence)


def test_matched_results_carry_a_calculation_trace(result) -> None:
    output, _ = result
    for r in output.results:
        if r.status is ResultStatus.MATCHED:
            assert r.trace, f"{r.payment_id} matched with no calculation trace"


def test_run_is_reproducible(result) -> None:
    """Same four files -> same run_id and byte-identical results."""
    output, _ = result
    config = load_config(ROOT / "recon.config.yaml")
    again = run(load(), config)
    assert again.run_id == output.run_id
    assert again.batch_id == output.batch_id
    assert [r.model_dump_json() for r in again.results] == [
        r.model_dump_json() for r in output.results
    ]


def test_throughput_is_reported_and_fast(result) -> None:
    _, metrics = result
    assert metrics.throughput_records_per_second > 100
