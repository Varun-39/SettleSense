"""The non-negotiable invariants from CLAUDE.md / ADR-002.

If any of these fail, the engine is producing a number a finance team cannot
defend — these are the tests that matter most in the repository.
"""
from __future__ import annotations

from datetime import timedelta

from factories import T0, make_payment, make_refund, make_settlement, rupees

from settlesense.contracts.enums import ReasonCode, ResultStatus
from settlesense.recon.index import MatchContext
from settlesense.recon.resolver import resolve
from settlesense.recon.rules.r1_exact_id import r1_exact_id
from settlesense.recon.rules.r2_order_id import r2_order_id
from settlesense.recon.rules.r3_amount_time import r3_amount_time
from settlesense.recon.rules.r4_refund_adjusted import r4_refund_adjusted
from settlesense.recon.rules.r5_partial import r5_partial

RULES = (r1_exact_id, r2_order_id, r3_amount_time, r4_refund_adjusted, r5_partial)


def run_engine(config, payments, settlements, refunds=(), ledger=()):
    ctx = MatchContext(
        config=config,
        payments=list(payments),
        settlements=list(settlements),
        refunds=list(refunds),
        ledger=list(ledger),
    )
    candidates = [c for p in payments for rule in RULES for c in rule(p, ctx)]
    return resolve("run_test", list(payments), candidates, ctx)


# -- The headline invariant -------------------------------------------------


def test_two_identical_payments_one_settlement_produces_no_false_match(config) -> None:
    """ADR-002's motivating defect, and the one a judge can trigger by
    duplicating a CSV row: a first-wins cascade silently gives the settlement
    to whichever payment it visits first. Neither may be marked matched."""
    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1000))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1000))
    s = make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1000))

    results = run_engine(config, [p1, p2], [s])

    assert [r.status for r in results] == [ResultStatus.REVIEW] * 2
    assert all(r.reason_code is ReasonCode.AMBIGUOUS_CANDIDATES for r in results)
    assert not any(r.status is ResultStatus.MATCHED for r in results)


def test_ambiguous_case_cites_both_contenders(config) -> None:
    """The reviewer must see what the engine could not choose between."""
    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1000))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1000))
    s = make_settlement("setl_1", payment_id=None, order_id=None, gross=rupees(1000))

    results = run_engine(config, [p1, p2], [s])

    for r in results:
        payments_cited = {ref.natural_id for ref in r.evidence if ref.table == "payments"}
        assert payments_cited == {"pay_1", "pay_2"}


def test_no_settlement_row_is_ever_claimed_twice(config) -> None:
    """Even when several payments could plausibly claim the same rows."""
    payments = [
        make_payment(f"pay_{i}", order_id=f"order_{i}", amount=rupees(1000 + i))
        for i in range(10)
    ]
    settlements = [
        make_settlement(f"setl_{i}", payment_id=f"pay_{i}", gross=rupees(1000 + i))
        for i in range(10)
    ]
    # Plus unidentified decoys at the same amounts.
    settlements += [
        make_settlement(f"decoy_{i}", payment_id=None, order_id=None, gross=rupees(1000 + i))
        for i in range(10)
    ]

    results = run_engine(config, payments, settlements)

    claimed: list[str] = []
    for r in results:
        claimed.extend(c.settlement_id for c in r.settlements)
    assert len(claimed) == len(set(claimed)), "a settlement row was claimed twice"


def test_sum_of_claims_never_exceeds_settlement_net(config) -> None:
    payments = [make_payment(f"pay_{i}", order_id=f"order_{i}") for i in range(5)]
    settlements = [
        make_settlement(f"setl_{i}", payment_id=f"pay_{i}") for i in range(5)
    ]
    results = run_engine(config, payments, settlements)

    capacity = {s.settlement_id: int(s.net_amount) for s in settlements}
    consumed: dict[str, int] = {}
    for r in results:
        for claim in r.settlements:
            consumed[claim.settlement_id] = consumed.get(claim.settlement_id, 0) + int(
                claim.claimed_paise
            )
    for sid, total in consumed.items():
        assert total <= capacity[sid], f"{sid} over-claimed"


def test_matched_always_implies_zero_residual(config) -> None:
    """A nonzero difference or pending amount can never be `matched`."""
    payments = [
        make_payment("pay_1", order_id="order_1", amount=rupees(1000)),
        make_payment("pay_2", order_id="order_2", amount=rupees(2000)),
        make_payment("pay_3", order_id="order_3", amount=rupees(3000)),
    ]
    settlements = [
        make_settlement("setl_1", payment_id="pay_1", gross=rupees(1000)),
        make_settlement("setl_2", payment_id="pay_2", gross=rupees(2000), net=rupees(1900)),
        make_settlement("setl_3", payment_id="pay_3", gross=rupees(3000), status="failed"),
    ]
    results = run_engine(config, payments, settlements)

    for r in results:
        if r.status is ResultStatus.MATCHED:
            assert r.difference_amount == 0
            assert r.pending_amount == 0


def test_every_payment_gets_exactly_one_result(config) -> None:
    payments = [make_payment(f"pay_{i}", order_id=f"order_{i}") for i in range(20)]
    results = run_engine(config, payments, [])
    assert len(results) == len(payments)
    assert {r.payment_id for r in results} == {p.payment_id for p in payments}


def test_unmatched_payment_is_unresolved_never_guessed(config) -> None:
    """Rule 6: no settlement evidence at all -> unresolved, full amount pending."""
    p = make_payment("pay_1", amount=rupees(2500))
    [r] = run_engine(config, [p], [])
    assert r.status is ResultStatus.UNRESOLVED
    assert r.reason_code is ReasonCode.MISSING_SETTLEMENT
    assert r.pending_amount == rupees(2500)


def test_stronger_evidence_wins_the_claim_regardless_of_rule_order(config) -> None:
    """Tier-1 identifier evidence must beat a tier-3 inference for the same
    settlement, whichever order the rules happened to run in."""
    p1 = make_payment("pay_1", order_id="order_1", amount=rupees(1000))
    p2 = make_payment("pay_2", order_id="order_2", amount=rupees(1000))
    s = make_settlement("setl_1", payment_id="pay_1", order_id=None, gross=rupees(1000))

    results = {r.payment_id: r for r in run_engine(config, [p1, p2], [s])}

    assert results["pay_1"].status is ResultStatus.MATCHED
    assert results["pay_2"].status is ResultStatus.UNRESOLVED


def test_results_are_reproducible_across_runs(config) -> None:
    """Same input -> byte-identical output. This is what makes the metrics
    defensible and the run-diff regression test possible."""
    payments = [
        make_payment(f"pay_{i}", order_id=f"order_{i}", amount=rupees(1000 + i))
        for i in range(15)
    ]
    settlements = [
        make_settlement(f"setl_{i}", payment_id=f"pay_{i}", gross=rupees(1000 + i))
        for i in range(15)
    ]
    refunds = [make_refund("rfnd_1", payment_id="pay_3", amount=rupees(100))]

    first = run_engine(config, payments, settlements, refunds)
    second = run_engine(config, payments, settlements, refunds)

    assert [r.model_dump_json() for r in first] == [r.model_dump_json() for r in second]


def test_partial_settlement_reports_every_row_and_the_pending_amount(config) -> None:
    p = make_payment("pay_1", amount=rupees(1000))
    s1 = make_settlement("setl_1", payment_id="pay_1", gross=rupees(400), net=rupees(400))
    s2 = make_settlement("setl_2", payment_id="pay_1", gross=rupees(300), net=rupees(300))

    [r] = run_engine(config, [p], [s1, s2])

    assert r.status is ResultStatus.REVIEW
    assert r.reason_code is ReasonCode.PARTIAL_SETTLEMENT
    assert r.settled_amount == rupees(700)
    assert r.pending_amount == rupees(300)
    assert {c.settlement_id for c in r.settlements} == {"setl_1", "setl_2"}


def test_delayed_settlement_without_identifier_is_not_forced(config) -> None:
    p = make_payment("pay_1", amount=rupees(1000))
    s = make_settlement(
        "setl_1",
        payment_id=None,
        order_id=None,
        gross=rupees(1000),
        settled_at=T0 + timedelta(days=9),
    )
    [r] = run_engine(config, [p], [s])
    assert r.status is ResultStatus.UNRESOLVED
