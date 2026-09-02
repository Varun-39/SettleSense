"""Rule 5 — partial / multi-row settlement.

Tier 1 evidence: several settlement rows carry the same payment id. The guide
requires showing every contributing row and the amount still pending, so this
rule always proposes the whole set rather than a single "best" row.

Fully settled  -> difference 0, pending 0            (resolver: matched)
Short-settled  -> pending = expected - settled       (resolver: review)
Over-settled   -> difference > 0                     (resolver: review)
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


def r5_partial(payment: Payment, ctx: MatchContext) -> list[Candidate]:
    settlements = ctx.settlements_by_payment_id.get(payment.payment_id, [])
    if len(settlements) < 2:
        return []  # single-row case belongs to R1

    settled_rows = [s for s in settlements if is_settled(s)]
    if not settled_rows:
        return []

    refunds = ctx.refunds_for(payment.payment_id)
    refunds_total = ctx.processed_refunds_total(payment.payment_id)
    total_fee = Paise(sum(int(s.fee) for s in settled_rows))
    total_tax = Paise(sum(int(s.tax) for s in settled_rows))
    settled_total = Paise(sum(int(s.net_amount) for s in settled_rows))

    trace = TraceBuilder()
    trace.step(
        label=f"sum of {len(settled_rows)} settlement rows",
        expression=" + ".join(s.settlement_id for s in settled_rows),
        inputs={s.settlement_id: int(s.net_amount) for s in settled_rows},
        result=settled_total,
    )
    expected = expected_net(trace, payment.amount, refunds_total, total_fee, total_tax)
    diff = difference(trace, expected, settled_total)

    # `difference` and `pending` describe different money and must not both
    # carry the same rupees — unexplained totals add them, so filling both
    # double-counts the shortfall. A short settlement is *pending* (more rows
    # may arrive); only an over-settlement is a genuine discrepancy.
    fully_settled = diff == 0
    shortfall = int(expected) - int(settled_total)

    if fully_settled:
        reported_difference, pending = Paise(0), Paise(0)
        reason = None
    elif shortfall > 0:
        reported_difference, pending = Paise(0), Paise(shortfall)
        reason = ReasonCode.PARTIAL_SETTLEMENT
    else:
        reported_difference, pending = diff, Paise(0)  # over-settled
        reason = ReasonCode.AMOUNT_MISMATCH

    return [
        Candidate(
            rule=RuleId.R5_PARTIAL,
            tier=1,
            score=1.0 if fully_settled else 0.5,
            payment_id=payment.payment_id,
            settlement_ids=tuple(s.settlement_id for s in settled_rows),
            match_type=MatchType.PARTIAL,
            expected_net=expected,
            actual_net=settled_total,
            difference=reported_difference,
            settled_amount=settled_total,
            pending_amount=pending,
            reason_hint=reason,
            trace=trace.build(),
            evidence=(payment_ref(payment),)
            + tuple(settlement_ref(s) for s in settlements)
            + tuple(refund_ref(r) for r in refunds),
        )
    ]
