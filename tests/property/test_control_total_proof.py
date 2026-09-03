"""The control-total proof is a checksum over a whole run.

Its value is that it fails on money bugs no single assertion was written to
catch. Both money bugs this project has had would have broken it, and each is
reconstructed below so a regression cannot pass quietly.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from factories import make_payment, make_refund, make_settlement, rupees

from settlesense.contracts.config import load_config
from settlesense.evaluate.proof import prove
from settlesense.ingest.batch import load_batch
from settlesense.recon.engine import run

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "demo" / "failure-fixtures"


def run_dir(directory: Path):
    return run(
        load_batch(
            directory / "sample_payments.csv",
            directory / "sample_settlements.csv",
            directory / "sample_refunds.csv",
            directory / "sample_ledger.csv",
        ),
        load_config(ROOT / "recon.config.yaml"),
    )


@pytest.mark.parametrize(
    "directory",
    [ROOT / "data", FIXTURES / "ambiguous", FIXTURES / "duplicate-id", FIXTURES / "malformed"],
    ids=["benchmark", "ambiguous", "duplicate-id", "malformed"],
)
def test_every_rupee_is_accounted_for(directory: Path) -> None:
    """Across every batch the project ships, including the ones built to fail."""
    proof = prove(run_dir(directory))
    assert proof.balances, (
        f"{directory.name}: gross {proof.gross} != accounted {proof.accounted}; "
        f"difference {proof.difference}"
    )


def test_the_benchmark_decomposes_to_the_documented_figures() -> None:
    proof = prove(run_dir(ROOT / "data"))
    assert proof.gross == 16_796_350
    assert proof.settled == 11_819_766
    assert proof.unexplained == 4_463_711
    assert proof.difference == 0


# -- the two money bugs this proof exists to catch --------------------------


def test_it_catches_settled_cash_exceeding_the_settlements_that_exist(config) -> None:
    """The contested-payment bug: two payments each reported one settlement as
    theirs, so the run settled Rs 3,000 against a Rs 1,500 settlement."""
    from test_invariants import run_engine

    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1500))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1500))
    s = make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1500))

    results = run_engine(config, [p1, p2], [s])
    settled = sum(int(r.settled_amount) for r in results)

    assert settled <= int(s.net_amount)
    # And the identity still holds for the run as a whole.
    unexplained = sum(
        abs(int(r.difference_amount)) + int(r.pending_amount)
        for r in results
        if r.status.value != "matched"
    )
    assert settled + unexplained == rupees(3000)


def test_it_catches_the_same_rupees_counted_as_difference_and_pending(config) -> None:
    """The double-count bug: unresolved rows filled both fields, so unexplained
    came out at roughly twice the money actually outstanding."""
    from test_invariants import run_engine

    p = make_payment("pay_1", amount=rupees(2500))
    [r] = run_engine(config, [p], [])

    unexplained = abs(int(r.difference_amount)) + int(r.pending_amount)
    assert unexplained == rupees(2500), "the same rupees were counted twice"


# -- the decomposition itself -----------------------------------------------


def test_fees_are_only_counted_where_a_settlement_was_claimed(config) -> None:
    """A fee on a settlement nobody claimed never left the merchant's money."""
    from test_invariants import run_engine

    p = make_payment("pay_1", amount=rupees(1000))
    unclaimed = make_settlement(
        "setl_orphan",
        payment_id=None,
        order_id=None,
        gross=rupees(9999),
        fee=rupees(500),
        tax=rupees(90),
    )

    results = run_engine(config, [p], [unclaimed])

    assert all(r.settlements == () for r in results), "claimed an unrelated settlement"


def test_a_refund_on_an_unresolved_payment_is_not_double_counted(config) -> None:
    """The full amount already sits in `unexplained`; adding the refund on top
    would count part of it twice."""
    from test_invariants import run_engine

    p = make_payment("pay_1", amount=rupees(1000))
    refund = make_refund("rfnd_1", payment_id="pay_1", amount=rupees(300))

    [r] = run_engine(config, [p], [], [refund])

    assert r.settlements == ()
    assert int(r.pending_amount) == rupees(1000)
