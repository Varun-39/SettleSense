"""Third-leg cross-check: the merchant's accounting view against the payments.

This runs alongside the payment<->settlement reconciliation and never alters
its verdicts (architecture.md §3). It produces its own findings so a duplicate
ledger import or a missing accounting entry surfaces as an exception class of
its own rather than corrupting a settlement match.
"""
from __future__ import annotations

from dataclasses import dataclass

from settlesense.contracts.enums import ReasonCode
from settlesense.contracts.models import LedgerEntry, Payment
from settlesense.contracts.money import Paise
from settlesense.contracts.refs import RowRef


@dataclass(frozen=True)
class LedgerFinding:
    order_id: str
    payment_id: str | None
    reason: ReasonCode
    detail: str
    amount: Paise
    evidence: tuple[RowRef, ...]


def _ref(entry: LedgerEntry) -> RowRef:
    return RowRef("ledger_entries", entry.ledger_entry_id, entry.row_hash)


def crosscheck(
    payments: list[Payment], ledger: list[LedgerEntry]
) -> list[LedgerFinding]:
    by_order: dict[str, list[LedgerEntry]] = {}
    for entry in ledger:
        by_order.setdefault(entry.order_id, []).append(entry)

    findings: list[LedgerFinding] = []

    for payment in payments:
        if not payment.order_id:
            continue
        entries = by_order.get(payment.order_id, [])

        if not entries:
            findings.append(
                LedgerFinding(
                    order_id=payment.order_id,
                    payment_id=payment.payment_id,
                    reason=ReasonCode.MISSING_SETTLEMENT,
                    detail="no ledger entry for this order",
                    amount=payment.amount,
                    evidence=(),
                )
            )
            continue

        # Duplicate accounting rows: same order, same credit, same date.
        seen: dict[tuple[int, str], LedgerEntry] = {}
        for entry in entries:
            key = (int(entry.credit), entry.posted_at.isoformat())
            if key in seen:
                findings.append(
                    LedgerFinding(
                        order_id=payment.order_id,
                        payment_id=payment.payment_id,
                        reason=ReasonCode.DUPLICATE_RECORD,
                        detail=(
                            f"{entry.ledger_entry_id} duplicates "
                            f"{seen[key].ledger_entry_id}"
                        ),
                        amount=entry.credit,
                        evidence=(_ref(seen[key]), _ref(entry)),
                    )
                )
            else:
                seen[key] = entry

        distinct_credit = Paise(sum(int(e.credit) for e in seen.values()))
        if distinct_credit != payment.amount:
            findings.append(
                LedgerFinding(
                    order_id=payment.order_id,
                    payment_id=payment.payment_id,
                    reason=ReasonCode.AMOUNT_MISMATCH,
                    detail=(
                        f"ledger credit {distinct_credit} != payment "
                        f"{int(payment.amount)}"
                    ),
                    amount=Paise(int(distinct_credit) - int(payment.amount)),
                    evidence=tuple(_ref(e) for e in entries),
                )
            )

    return findings
