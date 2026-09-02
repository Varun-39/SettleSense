"""Shared helpers for the rule cascade.

Every rule in this package is a PURE function: no I/O, no mutation, no
knowledge of other rules or of what has already been claimed (ADR-002).
"""
from __future__ import annotations

from settlesense.contracts.models import Payment, Refund, Settlement
from settlesense.contracts.money import Paise
from settlesense.contracts.refs import RowRef

SETTLED_STATUSES = {"processed", "partial"}


def payment_ref(payment: Payment) -> RowRef:
    return RowRef("payments", payment.payment_id, payment.row_hash)


def settlement_ref(s: Settlement) -> RowRef:
    return RowRef("settlements", s.settlement_id, s.row_hash)


def refund_ref(r: Refund) -> RowRef:
    return RowRef("refunds", r.refund_id, r.row_hash)


def is_settled(s: Settlement) -> bool:
    """A failed or pending settlement is evidence, not money that moved."""
    return s.status in SETTLED_STATUSES


def amount_score(difference: Paise, tolerance: int) -> float:
    """Deterministic score in [0, 1] from an absolute paise difference.

    Documented formula (ADR-002 action item: no magic constants):
        score = 1 - min(|difference|, tolerance) / tolerance
    An exact hit scores 1.0; a difference at the tolerance edge scores 0.0.
    """
    if tolerance <= 0:
        return 1.0 if difference == 0 else 0.0
    return 1.0 - min(abs(int(difference)), tolerance) / tolerance
