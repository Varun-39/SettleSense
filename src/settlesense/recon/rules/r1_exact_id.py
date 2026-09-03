"""Rule 1 — exact payment identifier.

Tier 1 evidence. Fires when exactly one settlement carries this payment's id.
A mismatched amount does NOT suppress the candidate: identifier evidence is
strong, so the case must surface as `review` with the residual shown, never
as an unmatched payment (architecture.md §4).
"""
from __future__ import annotations

from settlesense.contracts.enums import MatchType, ReasonCode, RuleId
from settlesense.contracts.models import Candidate, Payment
from settlesense.contracts.money import Paise
from settlesense.recon.index import MatchContext
from settlesense.recon.rules.common import (
    is_settled,
    payment_ref,
    refund_ref,
    settlement_ref,
)
from settlesense.recon.trace import TraceBuilder, difference, expected_net


def r1_exact_id(payment: Payment, ctx: MatchContext) -> list[Candidate]:
    settlements = ctx.settlements_by_payment_id.get(payment.payment_id, [])
    if len(settlements) != 1:
        return []  # 0 -> nothing to propose; >1 -> R5's territory

    settlement = settlements[0]
    refunds = ctx.refunds_for(payment.payment_id)
    refunds_total = ctx.processed_refunds_total(payment.payment_id)

    trace = TraceBuilder()
    expected = expected_net(
        trace, payment.amount, refunds_total, settlement.fee, settlement.tax
    )

    if not is_settled(settlement):
        # Identifier is certain, but no money moved. Report the full amount as
        # pending rather than as a difference to be explained.
        return [
            Candidate(
                rule=RuleId.R1_EXACT_ID,
                tier=1,
                score=0.5,
                payment_id=payment.payment_id,
                # Claims nothing: no money moved, so there is nothing to take.
                # Listing the row here would have the result hold a claim on
                # cash it reports as unsettled — and on a row with a negative
                # net, claim a negative amount. The settlement is still cited
                # as evidence below, which is where it belongs.
                settlement_ids=(),
                match_type=MatchType.EXACT_ID,
                expected_net=expected,
                actual_net=Paise(0),
                difference=Paise(0),
                settled_amount=Paise(0),
                pending_amount=expected,
                reason_hint=ReasonCode.FAILED_SETTLEMENT,
                trace=trace.build(),
                evidence=(payment_ref(payment), settlement_ref(settlement))
                + tuple(refund_ref(r) for r in refunds),
            )
        ]

    actual = settlement.net_amount
    diff = difference(trace, expected, actual)

    if diff == 0:
        reason = ReasonCode.REFUND_ADJUSTED if refunds_total else None
        score = 1.0
    elif refunds_total and abs(int(diff)) == int(refunds_total):
        # The gap is exactly the refund — a recorded, explainable difference.
        reason = ReasonCode.REFUND_ADJUSTED
        score = 0.5
    elif settlement.fee or settlement.tax:
        reason = ReasonCode.FEE_MISMATCH
        score = 0.5
    else:
        reason = ReasonCode.AMOUNT_MISMATCH
        score = 0.5

    match_type = MatchType.REFUND_ADJUSTED if refunds_total else MatchType.EXACT_ID

    return [
        Candidate(
            rule=RuleId.R1_EXACT_ID,
            tier=1,
            score=score,
            payment_id=payment.payment_id,
            settlement_ids=(settlement.settlement_id,),
            match_type=match_type,
            expected_net=expected,
            actual_net=actual,
            difference=diff,
            settled_amount=actual,
            pending_amount=Paise(0),
            reason_hint=reason,
            trace=trace.build(),
            evidence=(payment_ref(payment), settlement_ref(settlement))
            + tuple(refund_ref(r) for r in refunds),
        )
    ]
