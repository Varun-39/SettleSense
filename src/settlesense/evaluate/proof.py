"""The control-total proof: does every rupee collected have somewhere to go?

    gross = settled cash + provider fees + tax + refunds + unexplained

If that identity holds, nothing leaked. If it does not, some figure on some
screen is wrong and the run says so rather than waiting for someone to notice.

This is not decoration. Run against the two money bugs this project has
already had, it fails loudly:

  * when contested payments copied a settlement's amount into their own
    `settled_amount`, settled cash exceeded the settlements that existed;
  * when unresolved rows filled both `difference_amount` and
    `pending_amount`, unexplained overshot by the amount counted twice and
    the identity broke by Rs 37,400.

A checksum over the whole run is worth more than the sum of the assertions
that would otherwise have to catch each case separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from settlesense.contracts.enums import ResultStatus
from settlesense.contracts.money import Paise
from settlesense.recon.engine import RunOutput


@dataclass(frozen=True)
class ControlTotalProof:
    gross: Paise
    settled: Paise
    fees: Paise
    tax: Paise
    refunds: Paise
    #: Signed: money still owed, less any surplus received. See `prove`.
    unexplained: Paise

    @property
    def accounted(self) -> Paise:
        return Paise(
            int(self.settled)
            + int(self.fees)
            + int(self.tax)
            + int(self.refunds)
            + int(self.unexplained)
        )

    @property
    def difference(self) -> Paise:
        """Zero when every rupee is accounted for."""
        return Paise(int(self.gross) - int(self.accounted))

    @property
    def balances(self) -> bool:
        return self.difference == 0



def prove(output: RunOutput) -> ControlTotalProof:
    """Decompose gross collections across a completed run.

    Fees, tax and refunds count only where a settlement was actually claimed.
    A fee on a settlement nobody claimed never left the merchant's money, so
    counting it would be inventing an outflow.
    """
    # A settlement id is not unique in a source file, so this mapping can
    # only be safe because the resolver refuses to claim a contested row.
    # Assert the link rather than depend on it silently: if that ever changes,
    # this fails here instead of quietly attributing the wrong fee.
    settlements: dict[str, Any] = {}
    contested: set[str] = set()
    for s in output.settlements:
        if s.settlement_id in settlements:
            contested.add(s.settlement_id)
        settlements[s.settlement_id] = s

    if contested:
        claimed = {
            c.settlement_id for r in output.results for c in r.settlements
        }
        overlap = claimed & contested
        assert not overlap, (
            f"a contested settlement was claimed: {sorted(overlap)}. Its fee "
            "and tax cannot be attributed to one payment."
        )
    refunds_by_payment: dict[str, int] = {}
    for refund in output.refunds:
        if refund.status == "processed":
            refunds_by_payment[refund.payment_id] = refunds_by_payment.get(
                refund.payment_id, 0
            ) + int(refund.refund_amount)

    settled = fees = tax = refunds = unexplained = 0

    for result in output.results:
        settled += int(result.settled_amount)

        for claim in result.settlements:
            settlement = settlements.get(claim.settlement_id)
            if settlement is None:
                continue
            fees += int(settlement.fee)
            tax += int(settlement.tax)

        # A refund is only money out once its payment has been settled
        # against; on an unresolved payment the whole amount is already
        # sitting in `unexplained` and counting the refund too would double it.
        if result.settlements:
            refunds += refunds_by_payment.get(result.payment_id, 0)

        if result.status is not ResultStatus.MATCHED:
            # Signed, not absolute. `difference` is actual minus expected, so
            # a settlement that paid MORE than expected is a surplus that
            # reduces what is unaccounted for — the money did arrive. Using
            # the magnitude here made a surplus look like a second outflow and
            # broke the identity by twice the surplus.
            #
            # This is deliberately not the same quantity as the "unexplained"
            # figure a reviewer sees on the totals screen, which is the
            # magnitude of trouble and stays absolute. They coincide whenever
            # nothing is over-settled, which is the normal case.
            unexplained += int(result.pending_amount) - int(
                result.difference_amount
            )

    return ControlTotalProof(
        gross=Paise(sum(int(p.amount) for p in output.payments)),
        settled=Paise(settled),
        fees=Paise(fees),
        tax=Paise(tax),
        refunds=Paise(refunds),
        unexplained=Paise(unexplained),
    )
