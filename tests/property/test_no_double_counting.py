"""Regression tests for a double-counting bug found while building the API.

`difference_amount` and `pending_amount` describe DIFFERENT money:

  difference — a discrepancy against a settlement that exists
  pending    — money that has not been settled at all

Unexplained totals add the two, so any result that fills both counts the same
rupees twice. The original code set both to the full payment amount for
unresolved cases, and both to the shortfall for short-settled partials, which
inflated the reported unexplained amount by ~84% (Rs 82,037 vs the correct
Rs 44,637) and pushed amount accuracy down to 51% from 73%.

The invariant below is what makes that class of bug impossible to reintroduce.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from factories import make_payment, make_settlement, rupees

from settlesense.contracts.config import load_config
from settlesense.contracts.enums import ResultStatus
from settlesense.evaluate.evaluator import evaluate, load_ground_truth
from settlesense.ingest.batch import load_batch
from settlesense.recon.engine import run
from test_invariants import run_engine

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def benchmark():
    config = load_config(ROOT / "recon.config.yaml")
    output = run(
        load_batch(
            DATA / "sample_payments.csv",
            DATA / "sample_settlements.csv",
            DATA / "sample_refunds.csv",
            DATA / "sample_ledger.csv",
        ),
        config,
    )
    return output, evaluate(output, load_ground_truth(DATA / "ground_truth.csv"))


def test_no_result_carries_both_a_difference_and_a_pending_amount(benchmark) -> None:
    """The core invariant. If both are set, the unexplained total is wrong."""
    output, _ = benchmark
    offenders = [
        r.payment_id
        for r in output.results
        if r.difference_amount != 0 and r.pending_amount != 0
    ]
    assert not offenders, (
        f"{offenders} report both a difference and a pending amount; "
        "the same rupees would be counted twice in the unexplained total"
    )


def test_unresolved_money_is_pending_not_a_difference(config) -> None:
    """Nothing settled means nothing to compare against — the whole amount is
    pending, and the discrepancy is zero."""
    p = make_payment("pay_1", amount=rupees(2500))
    [r] = run_engine(config, [p], [])
    assert r.status is ResultStatus.UNRESOLVED
    assert r.difference_amount == 0
    assert r.pending_amount == rupees(2500)


def test_short_settled_partial_reports_shortfall_once(config) -> None:
    p = make_payment("pay_1", amount=rupees(1000))
    s1 = make_settlement("setl_1", payment_id="pay_1", gross=rupees(400), net=rupees(400))
    s2 = make_settlement("setl_2", payment_id="pay_1", gross=rupees(300), net=rupees(300))

    [r] = run_engine(config, [p], [s1, s2])

    assert r.pending_amount == rupees(300)
    assert r.difference_amount == 0
    assert abs(int(r.difference_amount)) + int(r.pending_amount) == rupees(300)


def test_over_settled_partial_is_a_difference_not_pending(config) -> None:
    """Receiving more than expected is a genuine discrepancy, not pending money."""
    p = make_payment("pay_1", amount=rupees(1000))
    s1 = make_settlement("setl_1", payment_id="pay_1", gross=rupees(700), net=rupees(700))
    s2 = make_settlement("setl_2", payment_id="pay_1", gross=rupees(500), net=rupees(500))

    [r] = run_engine(config, [p], [s1, s2])

    assert r.difference_amount == rupees(200)
    assert r.pending_amount == 0


def test_unexplained_total_equals_the_sum_of_its_parts(benchmark) -> None:
    """The reported total must decompose exactly into the cases that produced
    it — no rupee counted twice, none missing."""
    output, metrics = benchmark

    by_hand = sum(
        abs(int(r.difference_amount)) + int(r.pending_amount)
        for r in output.results
        if r.status is not ResultStatus.MATCHED
    )
    assert metrics.unexplained_paise == by_hand


def test_unexplained_never_exceeds_gross_payments(benchmark) -> None:
    """The bug's visible symptom: unexplained money exceeding the money that
    actually came in should be arithmetically impossible."""
    _, metrics = benchmark
    assert metrics.unexplained_paise <= metrics.gross_payments_paise
    assert 0.0 <= metrics.amount_accuracy <= 1.0


def test_matched_results_contribute_nothing_unexplained(benchmark) -> None:
    output, _ = benchmark
    for r in output.results:
        if r.status is ResultStatus.MATCHED:
            assert r.difference_amount == 0
            assert r.pending_amount == 0
