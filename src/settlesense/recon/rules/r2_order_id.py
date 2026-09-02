"""Rule 2 — merchant order identifier fallback.

Tier 2 evidence: the payment identifier is absent from the settlement row, but
the merchant order reference links them. The guide requires amount and date to
be inside tolerance before this match is accepted — an order reference alone is
not enough to move money against.
"""
from __future__ import annotations

from settlesense.contracts.enums import MatchType, ReasonCode, RuleId
from settlesense.contracts.models import Candidate, Payment
from settlesense.contracts.money import Paise
from settlesense.normalize.dates import within_settlement_window
from settlesense.recon.index import MatchContext
from settlesense.recon.rules.common import (
    amount_score,
    is_settled,
    payment_ref,
    refund_ref,
    settlement_ref,
)
from settlesense.recon.trace import TraceBuilder, difference, expected_net


def r2_order_id(payment: Payment, ctx: MatchContext) -> list[Candidate]:
    if not payment.order_id:
        return []

    tolerance = ctx.config.tolerance_paise
    window = ctx.config.settlement_window_days
    refunds = ctx.refunds_for(payment.payment_id)
    refunds_total = ctx.processed_refunds_total(payment.payment_id)

    candidates: list[Candidate] = []
    for settlement in ctx.settlements_by_order_id.get(payment.order_id, []):
        if settlement.payment_id:
            continue  # identified rows belong to R1/R5
        if not is_settled(settlement):
            continue
        if abs(int(payment.amount) - int(settlement.gross_amount)) > tolerance:
            continue
        if not within_settlement_window(payment.captured_at, settlement.settled_at, window):
            continue

        trace = TraceBuilder()
        expected = expected_net(
            trace, payment.amount, refunds_total, settlement.fee, settlement.tax
        )
        diff = difference(trace, expected, settlement.net_amount)

        candidates.append(
            Candidate(
                rule=RuleId.R2_ORDER_ID,
                tier=2,
                score=amount_score(diff, tolerance),
                payment_id=payment.payment_id,
                settlement_ids=(settlement.settlement_id,),
                match_type=MatchType.EXACT_ID,
                expected_net=expected,
                actual_net=settlement.net_amount,
                difference=diff,
                settled_amount=settlement.net_amount,
                pending_amount=Paise(0),
                reason_hint=None if diff == 0 else ReasonCode.AMOUNT_MISMATCH,
                trace=trace.build(),
                evidence=(payment_ref(payment), settlement_ref(settlement))
                + tuple(refund_ref(r) for r in refunds),
            )
        )
    return candidates
