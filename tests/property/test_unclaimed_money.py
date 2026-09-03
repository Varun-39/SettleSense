"""A result that claimed nothing must report nothing settled.

Found by building the `ambiguous` demo fixture: two payments contesting one
settlement each copied that settlement's amount into their own
`settled_amount`, so a run with a single Rs 1,500 settlement reported Rs 3,000
settled. The candidates carried figures describing a claim that the resolver
had refused to grant.

The invariant below is what makes that unrepresentable.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from factories import make_payment, make_settlement, rupees

from settlesense.contracts.config import load_config
from settlesense.contracts.enums import ReasonCode, ResultStatus
from settlesense.ingest.batch import load_batch
from settlesense.recon.engine import run
from test_invariants import run_engine

ROOT = Path(__file__).resolve().parents[2]
AMBIGUOUS = ROOT / "demo" / "failure-fixtures" / "ambiguous"


def test_ambiguous_case_reports_no_settled_money(config) -> None:
    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1500))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1500))
    s = make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1500))

    results = run_engine(config, [p1, p2], [s])

    for r in results:
        assert r.status is ResultStatus.REVIEW
        assert r.reason_code is ReasonCode.AMBIGUOUS_CANDIDATES
        assert r.settled_amount == 0, "reported money it never claimed"
        assert r.actual_net is None
        assert r.settlements == ()
        assert r.pending_amount == rupees(1500)


def test_settled_total_never_exceeds_available_settlements(config) -> None:
    """The symptom the bug produced: a run settling more than exists."""
    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1500))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1500))
    s = make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1500))

    results = run_engine(config, [p1, p2], [s])

    reported = sum(int(r.settled_amount) for r in results)
    available = int(s.net_amount)
    assert reported <= available, (
        f"run reports {reported} settled against {available} of settlements"
    )


def test_a_result_with_no_claims_has_no_settled_amount(config) -> None:
    """Stated generally, so it holds for any future status that declines to
    claim, not just the ambiguous one."""
    payments = [
        make_payment(f"pay_{i}", order_id=f"order_{i}", amount=rupees(1500))
        for i in range(4)
    ]
    settlements = [
        make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1500))
    ]
    for r in run_engine(config, payments, settlements):
        if not r.settlements:
            assert r.settled_amount == 0
            assert r.difference_amount == 0


# -- the fixture the bug came from ------------------------------------------


@pytest.fixture(scope="module")
def ambiguous_run():
    config = load_config(ROOT / "recon.config.yaml")
    return run(
        load_batch(
            AMBIGUOUS / "sample_payments.csv",
            AMBIGUOUS / "sample_settlements.csv",
            AMBIGUOUS / "sample_refunds.csv",
            AMBIGUOUS / "sample_ledger.csv",
        ),
        config,
    )


def test_ambiguous_fixture_produces_no_false_match(ambiguous_run) -> None:
    statuses = [r.status for r in ambiguous_run.results]
    assert statuses.count(ResultStatus.REVIEW) == 2
    assert statuses.count(ResultStatus.MATCHED) == 1


def test_ambiguous_fixture_totals_are_consistent(ambiguous_run) -> None:
    settled = sum(int(r.settled_amount) for r in ambiguous_run.results)
    available = sum(int(s.net_amount) for s in ambiguous_run.settlements)
    assert settled <= available
    assert settled == rupees(2685.10)


def test_both_contested_payments_cite_each_other(ambiguous_run) -> None:
    contested = [
        r
        for r in ambiguous_run.results
        if r.reason_code is ReasonCode.AMBIGUOUS_CANDIDATES
    ]
    assert len(contested) == 2
    for r in contested:
        cited = {ref.natural_id for ref in r.evidence if ref.table == "payments"}
        assert cited == {"pay_3000", "pay_3001"}
