"""Rule 4 — refund-adjusted inference.

Rules 1, 2 and 5 already fold processed refunds into `expected_net`, so this
rule exists for the case they cannot see: an *unidentified* settlement whose
gross amount reflects the post-refund figure rather than the original payment
amount. R3 would miss it, because R3 compares against the full payment amount.

Per the guide: a refund is never treated as a fee. It stays separate evidence
and is cited as its own row.
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


def r4_refund_adjusted(payment: Payment, ctx: MatchContext) -> list[Candidate]:
    refunds_total = ctx.processed_refunds_total(payment.payment_id)
    if refunds_total == 0:
        return []

    tolerance = ctx.config.tolerance_paise
    window = ctx.config.settlement_window_days
    refunds = ctx.refunds_for(payment.payment_id)
    post_refund_amount = Paise(int(payment.amount) - int(refunds_total))

    candidates: list[Candidate] = []
    for settlement in ctx.settlements_near_amount(post_refund_amount, tolerance):
        if settlement.payment_id:
            continue
        if not is_settled(settlement):
            continue
        if not within_settlement_window(payment.captured_at, settlement.settled_at, window):
            continue

        trace = TraceBuilder()
        trace.step(
            label="post-refund collection",
            expression="payment_amount - processed_refunds",
            inputs={
                "payment_amount": int(payment.amount),
                "processed_refunds": int(refunds_total),
            },
            result=post_refund_amount,
        )
        expected = expected_net(
            trace, payment.amount, refunds_total, settlement.fee, settlement.tax
        )
        diff = difference(trace, expected, settlement.net_amount)
        gross_gap = abs(int(post_refund_amount) - int(settlement.gross_amount))

        candidates.append(
            Candidate(
                rule=RuleId.R4_REFUND_ADJUSTED,
                tier=3,
                score=amount_score(Paise(gross_gap), tolerance),
                payment_id=payment.payment_id,
                settlement_ids=(settlement.settlement_id,),
                match_type=MatchType.REFUND_ADJUSTED,
                expected_net=expected,
                actual_net=settlement.net_amount,
                difference=diff,
                settled_amount=settlement.net_amount,
                pending_amount=Paise(0),
                reason_hint=ReasonCode.REFUND_ADJUSTED,
                trace=trace.build(),
                evidence=(payment_ref(payment), settlement_ref(settlement))
                + tuple(refund_ref(r) for r in refunds),
            )
        )
    return candidates
