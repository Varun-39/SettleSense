"""Lookup structures for matching. Builds the indexes once so the rule cascade
stays O(n) rather than O(n^2) — see architecture.md §2 stage 5.

This module decides nothing; it only makes lookups cheap.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from settlesense.contracts.config import MatchingConfig
from settlesense.contracts.models import LedgerEntry, Payment, Refund, Settlement
from settlesense.contracts.money import Paise


@dataclass
class MatchContext:
    config: MatchingConfig
    payments: list[Payment]
    settlements: list[Settlement]
    refunds: list[Refund]
    ledger: list[LedgerEntry]

    settlements_by_payment_id: dict[str, list[Settlement]] = field(default_factory=dict)
    settlements_by_order_id: dict[str, list[Settlement]] = field(default_factory=dict)
    settlements_by_id: dict[str, Settlement] = field(default_factory=dict)
    refunds_by_payment_id: dict[str, list[Refund]] = field(default_factory=dict)
    ledger_by_order_id: dict[str, list[LedgerEntry]] = field(default_factory=dict)

    # Sorted (gross_amount, settlement_id) for range lookups in Rule 3.
    _sorted_gross: list[tuple[int, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for s in self.settlements:
            self.settlements_by_id[s.settlement_id] = s
            if s.payment_id:
                self.settlements_by_payment_id.setdefault(s.payment_id, []).append(s)
            if s.order_id:
                self.settlements_by_order_id.setdefault(s.order_id, []).append(s)
        for r in self.refunds:
            self.refunds_by_payment_id.setdefault(r.payment_id, []).append(r)
        for entry in self.ledger:
            self.ledger_by_order_id.setdefault(entry.order_id, []).append(entry)

        self._sorted_gross = sorted(
            (int(s.gross_amount), s.settlement_id) for s in self.settlements
        )

    def processed_refunds_total(self, payment_id: str) -> Paise:
        """Only *processed* refunds reduce the expected settlement. A created
        or failed refund is evidence, not money that moved."""
        return Paise(
            sum(
                int(r.refund_amount)
                for r in self.refunds_by_payment_id.get(payment_id, [])
                if r.status == "processed"
            )
        )

    def refunds_for(self, payment_id: str) -> list[Refund]:
        return self.refunds_by_payment_id.get(payment_id, [])

    def settlements_near_amount(self, amount: Paise, tolerance: int) -> list[Settlement]:
        """All settlements whose gross_amount is within `tolerance` paise."""
        lo = bisect.bisect_left(self._sorted_gross, (int(amount) - tolerance, ""))
        hi = bisect.bisect_right(
            self._sorted_gross, (int(amount) + tolerance, "￿")
        )
        return [self.settlements_by_id[sid] for _, sid in self._sorted_gross[lo:hi]]
