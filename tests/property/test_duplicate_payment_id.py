"""`payment_id` is not unique by construction, and the engine used to assume
it was.

Two rows sharing an id but differing in content survive deduplication — dedup
collapses identical rows, not conflicting ones. The resolver keyed its results
dict by `payment_id` and derived `reconciliation_id` from it, so the second row
overwrote the first: a Rs 2,000 payment vanished, both results reported
`matched`, and a single Rs 1,000 settlement was reported as settled twice.

The build guide requires this case to be detected, not absorbed.
"""
from __future__ import annotations

from factories import make_payment, make_settlement, rupees

from settlesense.contracts.enums import ReasonCode, ResultStatus
from test_invariants import run_engine


def conflicting_rows():
    """Same id, different amount — a genuine conflict between sources."""
    return (
        make_payment("pay_1", amount=rupees(1000)),
        make_payment("pay_1", amount=rupees(2000)),
    )


def test_neither_conflicting_row_is_lost(config) -> None:
    a, b = conflicting_rows()
    s = make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000))

    results = run_engine(config, [a, b], [s])

    assert len(results) == 2
    assert len({r.reconciliation_id for r in results}) == 2, (
        "both rows collapsed onto one reconciliation id; one result is lost "
        "the moment it is persisted"
    )
    assert {int(r.expected_net) for r in results} == {rupees(1000), rupees(2000)}


def test_conflicting_rows_are_never_matched(config) -> None:
    a, b = conflicting_rows()
    s = make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000))

    for r in run_engine(config, [a, b], [s]):
        assert r.status is ResultStatus.UNRESOLVED
        assert r.reason_code is ReasonCode.DUPLICATE_RECORD


def test_conflicting_rows_do_not_double_count_a_settlement(config) -> None:
    """The symptom: one Rs 1,000 settlement reported as Rs 2,000 settled."""
    a, b = conflicting_rows()
    s = make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000))

    results = run_engine(config, [a, b], [s])

    reported = sum(int(r.settled_amount) for r in results)
    assert reported == 0, "reported money against a settlement it never claimed"
    assert all(r.settlements == () for r in results)


def test_each_conflicting_row_cites_the_other(config) -> None:
    """Preserve both records and show the reviewer what they have to choose
    between — the same treatment an ambiguous match gets."""
    a, b = conflicting_rows()
    results = run_engine(config, [a, b], [])

    for r in results:
        hashes = {ref.row_hash for ref in r.evidence if ref.table == "payments"}
        assert hashes == {a.row_hash, b.row_hash}


def test_a_conflicting_id_does_not_starve_other_payments(config) -> None:
    """The conflict must be contained: unrelated payments still reconcile."""
    a, b = conflicting_rows()
    clean = make_payment("pay_2", order_id="order_2", amount=rupees(500))
    settlements = [
        make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000)),
        make_settlement("setl_2", payment_id="pay_2", gross=rupees(500)),
    ]

    results = {r.payment_id: r for r in run_engine(config, [a, b, clean], settlements)}
    assert results["pay_2"].status is ResultStatus.MATCHED


def test_identical_duplicate_rows_still_collapse(config) -> None:
    """A row duplicated exactly is not a conflict — dedup removes it upstream,
    so the resolver must not see two rows and cry conflict."""
    p = make_payment("pay_1", amount=rupees(1000))
    s = make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000))

    # One row, as the deduplicator would leave it.
    [result] = run_engine(config, [p], [s])
    assert result.status is ResultStatus.MATCHED
    assert result.reconciliation_id.endswith(":pay_1"), (
        "an unambiguous payment should keep the readable id"
    )
