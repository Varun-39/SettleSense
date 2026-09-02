"""Each rule tested in isolation — the payoff of making rules pure functions
with no ordering dependency (ADR-002)."""
from __future__ import annotations

from datetime import timedelta

from factories import T0, make_payment, make_refund, make_settlement, rupees

from settlesense.contracts.enums import ReasonCode, RuleId
from settlesense.recon.index import MatchContext
from settlesense.recon.rules.r1_exact_id import r1_exact_id
from settlesense.recon.rules.r2_order_id import r2_order_id
from settlesense.recon.rules.r3_amount_time import r3_amount_time
from settlesense.recon.rules.r4_refund_adjusted import r4_refund_adjusted
from settlesense.recon.rules.r5_partial import r5_partial


def ctx_for(config, payments, settlements, refunds=(), ledger=()) -> MatchContext:
    return MatchContext(
        config=config,
        payments=list(payments),
        settlements=list(settlements),
        refunds=list(refunds),
        ledger=list(ledger),
    )


# -- R1 ---------------------------------------------------------------------


def test_r1_clean_match_scores_one_and_has_zero_difference(config) -> None:
    p = make_payment()
    s = make_settlement()
    [c] = r1_exact_id(p, ctx_for(config, [p], [s]))
    assert c.rule is RuleId.R1_EXACT_ID
    assert c.tier == 1
    assert c.score == 1.0
    assert c.difference == 0
    assert c.reason_hint is None


def test_r1_fee_is_explained_not_an_exception(config) -> None:
    """The guide's worked example: Rs 1000 captured, Rs 970 settled, Rs 30 fee
    -> matched, no exception."""
    p = make_payment(amount=rupees(1000))
    s = make_settlement(gross=rupees(1000), fee=rupees(30), net=rupees(970))
    [c] = r1_exact_id(p, ctx_for(config, [p], [s]))
    assert c.expected_net == rupees(970)
    assert c.difference == 0


def test_r1_amount_mismatch_still_proposes_at_tier_1(config) -> None:
    """Identifier evidence is strong: a wrong amount must surface as review
    with the residual shown, never as an unmatched payment."""
    p = make_payment(amount=rupees(1000))
    s = make_settlement(gross=rupees(1000), net=rupees(950))
    [c] = r1_exact_id(p, ctx_for(config, [p], [s]))
    assert c.tier == 1
    assert c.difference == rupees(-50)
    assert c.reason_hint is ReasonCode.AMOUNT_MISMATCH


def test_r1_failed_settlement_reports_pending_not_difference(config) -> None:
    p = make_payment()
    s = make_settlement(status="failed")
    [c] = r1_exact_id(p, ctx_for(config, [p], [s]))
    assert c.reason_hint is ReasonCode.FAILED_SETTLEMENT
    assert c.settled_amount == 0
    assert c.pending_amount == rupees(1000)


def test_r1_defers_multi_row_to_r5(config) -> None:
    p = make_payment()
    s1 = make_settlement("setl_1", net=rupees(400))
    s2 = make_settlement("setl_2", net=rupees(600))
    assert r1_exact_id(p, ctx_for(config, [p], [s1, s2])) == []


def test_r1_subtracts_only_processed_refunds(config) -> None:
    p = make_payment(amount=rupees(1000))
    processed = make_refund("rfnd_1", amount=rupees(200), status="processed")
    failed = make_refund("rfnd_2", amount=rupees(500), status="failed")
    s = make_settlement(gross=rupees(1000), net=rupees(800))
    [c] = r1_exact_id(p, ctx_for(config, [p], [s], [processed, failed]))
    assert c.expected_net == rupees(800)
    assert c.difference == 0


# -- R2 ---------------------------------------------------------------------


def test_r2_matches_on_order_id_when_payment_id_absent(config) -> None:
    p = make_payment(order_id="order_9")
    s = make_settlement(payment_id=None, order_id="order_9")
    [c] = r2_order_id(p, ctx_for(config, [p], [s]))
    assert c.rule is RuleId.R2_ORDER_ID
    assert c.tier == 2


def test_r2_requires_amount_within_tolerance(config) -> None:
    p = make_payment(order_id="order_9", amount=rupees(1000))
    s = make_settlement(payment_id=None, order_id="order_9", gross=rupees(1500))
    assert r2_order_id(p, ctx_for(config, [p], [s])) == []


def test_r2_requires_settlement_inside_window(config) -> None:
    p = make_payment(order_id="order_9")
    s = make_settlement(
        payment_id=None, order_id="order_9", settled_at=T0 + timedelta(days=9)
    )
    assert r2_order_id(p, ctx_for(config, [p], [s])) == []


# -- R3 ---------------------------------------------------------------------


def test_r3_matches_unidentified_settlement_in_window(config) -> None:
    p = make_payment()
    s = make_settlement(payment_id=None, order_id=None)
    [c] = r3_amount_time(p, ctx_for(config, [p], [s]))
    assert c.rule is RuleId.R3_AMOUNT_TIME
    assert c.tier == 3


def test_r3_refuses_amount_outside_tolerance(config) -> None:
    p = make_payment(amount=rupees(1000))
    s = make_settlement(payment_id=None, order_id=None, gross=rupees(1002))
    assert r3_amount_time(p, ctx_for(config, [p], [s])) == []


def test_r3_refuses_settlement_outside_window(config) -> None:
    """Delayed settlement with no identifier: the honest answer is 'no match'."""
    p = make_payment()
    s = make_settlement(
        payment_id=None, order_id=None, settled_at=T0 + timedelta(days=9)
    )
    assert r3_amount_time(p, ctx_for(config, [p], [s])) == []


def test_r3_refuses_settlement_before_capture(config) -> None:
    p = make_payment()
    s = make_settlement(
        payment_id=None, order_id=None, settled_at=T0 - timedelta(days=1)
    )
    assert r3_amount_time(p, ctx_for(config, [p], [s])) == []


def test_r3_does_not_duplicate_r2s_proposal(config) -> None:
    p = make_payment(order_id="order_9")
    s = make_settlement(payment_id=None, order_id="order_9")
    assert r3_amount_time(p, ctx_for(config, [p], [s])) == []


# -- R4 ---------------------------------------------------------------------


def test_r4_matches_post_refund_amount(config) -> None:
    """R3 can't see this: the settlement gross is the post-refund figure."""
    p = make_payment(amount=rupees(1000))
    r = make_refund(amount=rupees(200))
    s = make_settlement(payment_id=None, order_id=None, gross=rupees(800))
    [c] = r4_refund_adjusted(p, ctx_for(config, [p], [s], [r]))
    assert c.rule is RuleId.R4_REFUND_ADJUSTED
    assert c.reason_hint is ReasonCode.REFUND_ADJUSTED
    assert c.difference == 0


def test_r4_silent_without_processed_refunds(config) -> None:
    p = make_payment()
    s = make_settlement(payment_id=None, order_id=None, gross=rupees(800))
    assert r4_refund_adjusted(p, ctx_for(config, [p], [s])) == []


def test_r4_keeps_refund_as_separate_evidence(config) -> None:
    p = make_payment(amount=rupees(1000))
    r = make_refund(amount=rupees(200))
    s = make_settlement(payment_id=None, order_id=None, gross=rupees(800))
    [c] = r4_refund_adjusted(p, ctx_for(config, [p], [s], [r]))
    assert any(ref.table == "refunds" for ref in c.evidence)


# -- R5 ---------------------------------------------------------------------


def test_r5_sums_multiple_rows_to_a_full_match(config) -> None:
    p = make_payment(amount=rupees(1000))
    s1 = make_settlement("setl_1", gross=rupees(400), net=rupees(400))
    s2 = make_settlement("setl_2", gross=rupees(600), net=rupees(600))
    [c] = r5_partial(p, ctx_for(config, [p], [s1, s2]))
    assert c.rule is RuleId.R5_PARTIAL
    assert c.settled_amount == rupees(1000)
    assert c.difference == 0
    assert c.pending_amount == 0
    assert len(c.settlement_ids) == 2


def test_r5_reports_pending_when_short_settled(config) -> None:
    p = make_payment(amount=rupees(1000))
    s1 = make_settlement("setl_1", gross=rupees(400), net=rupees(400))
    s2 = make_settlement("setl_2", gross=rupees(300), net=rupees(300))
    [c] = r5_partial(p, ctx_for(config, [p], [s1, s2]))
    assert c.settled_amount == rupees(700)
    assert c.pending_amount == rupees(300)
    assert c.reason_hint is ReasonCode.PARTIAL_SETTLEMENT


def test_r5_cites_every_settlement_row_including_failed(config) -> None:
    p = make_payment(amount=rupees(1000))
    s1 = make_settlement("setl_1", gross=rupees(400), net=rupees(400))
    s2 = make_settlement("setl_2", gross=rupees(600), net=rupees(600))
    s3 = make_settlement("setl_3", gross=rupees(600), net=rupees(600), status="failed")
    [c] = r5_partial(p, ctx_for(config, [p], [s1, s2, s3]))
    cited = {ref.natural_id for ref in c.evidence if ref.table == "settlements"}
    assert cited == {"setl_1", "setl_2", "setl_3"}
    assert "setl_3" not in c.settlement_ids  # cited, but never claimed as money
