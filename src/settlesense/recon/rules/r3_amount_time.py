"""Rule 3 — amount and time inference.

Tier 3, the weakest evidence in the system. Fires only when no identifier
links a payment to a settlement. All three conditions from the guide must
hold; a close amount alone is never sufficient.

    abs(payment.amount - settlement.gross_amount) <= tolerance
    settlement.settled_at >= payment.captured_at
    settlement.settled_at <= payment.captured_at + settlement_window
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


def r3_amount_time(payment: Payment, ctx: MatchContext) -> list[Candidate]:
    tolerance = ctx.config.tolerance_paise
    window = ctx.config.settlement_window_days
    refunds = ctx.refunds_for(payment.payment_id)
    refunds_total = ctx.processed_refunds_total(payment.payment_id)

    candidates: list[Candidate] = []
    for settlement in ctx.settlements_near_amount(payment.amount, tolerance):
        if settlement.payment_id:
            continue
        if settlement.order_id and settlement.order_id == payment.order_id:
            continue  # R2 owns this one — don't propose it twice at a weaker tier
        if not is_settled(settlement):
            continue
        if not within_settlement_window(payment.captured_at, settlement.settled_at, window):
            continue

        trace = TraceBuilder()
        expected = expected_net(
            trace, payment.amount, refunds_total, settlement.fee, settlement.tax
        )
        diff = difference(trace, expected, settlement.net_amount)
        gross_gap = abs(int(payment.amount) - int(settlement.gross_amount))

        candidates.append(
            Candidate(
                rule=RuleId.R3_AMOUNT_TIME,
                tier=3,
                score=amount_score(Paise(gross_gap), tolerance),
                payment_id=payment.payment_id,
                settlement_ids=(settlement.settlement_id,),
                match_type=MatchType.AMOUNT_TIME,
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
