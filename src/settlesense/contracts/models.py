"""Pydantic contracts for source records and engine output.

These are the frozen shapes every stage of the pipeline passes around.
Mirrors the table definitions in architecture.md §6 — keep the two in step;
tests/unit/test_schema_roundtrip.py (Day 1) should assert they don't drift.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from settlesense.contracts.enums import (
    MatchType,
    ReasonCode,
    RecommendedAction,
    ResultStatus,
    RuleId,
)
from settlesense.contracts.money import Paise
from settlesense.contracts.refs import RowRef


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Source records (normalized)
# ---------------------------------------------------------------------------


class Payment(Frozen):
    row_hash: str
    payment_id: str
    order_id: str | None
    amount: Paise
    currency: str
    status: Literal["captured", "failed", "refunded", "partially_refunded"]
    captured_at: datetime  # UTC
    customer_id: str | None = None


class Settlement(Frozen):
    row_hash: str
    settlement_id: str
    payment_id: str | None
    # Optional extension to the spec's settlement schema: real settlement files
    # commonly carry the merchant order reference, and Rule 2 (order-id
    # fallback) is unimplementable without it. Files that omit the column
    # still parse — the field is nullable and R2 simply never fires.
    order_id: str | None
    # The payout batch this row belongs to. A provider's settlement id names
    # the batch, not the line, so it is carried separately from the row's own
    # identity — several settlement rows legitimately share one.
    settlement_batch_id: str | None = None
    gross_amount: Paise
    fee: Paise
    tax: Paise
    net_amount: Paise
    settled_at: datetime  # UTC
    status: Literal["processed", "pending", "failed", "partial"]


class Refund(Frozen):
    row_hash: str
    refund_id: str
    payment_id: str
    refund_amount: Paise
    created_at: datetime  # UTC
    status: Literal["created", "processed", "failed"]


class LedgerEntry(Frozen):
    row_hash: str
    ledger_entry_id: str
    order_id: str
    debit: Paise
    credit: Paise
    posted_at: datetime  # UTC
    description: str


# ---------------------------------------------------------------------------
# Matching intermediates (recon/)
# ---------------------------------------------------------------------------


class CalcStep(Frozen):
    seq: int
    label: str
    expression: str
    inputs: dict[str, int]
    result_paise: Paise


class Candidate(Frozen):
    """A proposal from a single rule. Pure data — rules never decide.

    The candidate carries every figure it computed, so the resolver performs
    arbitration only and never re-derives arithmetic (ADR-002).
    """

    rule: RuleId
    tier: int  # 1 = identifier evidence, 2 = identifier+tolerance, 3 = inferred
    score: float
    payment_id: str
    settlement_ids: tuple[str, ...]
    match_type: MatchType
    expected_net: Paise
    actual_net: Paise
    difference: Paise
    settled_amount: Paise
    pending_amount: Paise
    reason_hint: ReasonCode | None
    trace: tuple[CalcStep, ...]
    evidence: tuple[RowRef, ...]


# ---------------------------------------------------------------------------
# Reconciliation output (store/)
# ---------------------------------------------------------------------------


class SettlementClaim(Frozen):
    settlement_id: str
    claimed_paise: Paise


class ReconciliationResult(Frozen):
    reconciliation_id: str
    run_id: str
    payment_id: str
    match_type: MatchType
    match_score: float
    expected_net: Paise
    actual_net: Paise | None
    difference_amount: Paise
    status: ResultStatus
    reason_code: ReasonCode | None
    settled_amount: Paise
    pending_amount: Paise
    settlements: tuple[SettlementClaim, ...] = ()
    trace: tuple[CalcStep, ...] = ()
    evidence: tuple[RowRef, ...] = ()


class Explanation(Frozen):
    """Structured AI output. See docs/adr/ADR-005 — every field here is
    validated against the grounding gate before it reaches this shape.
    """

    reconciliation_id: str
    source: Literal["ai", "template"]
    category: ReasonCode
    summary: str
    evidence_refs: tuple[str, ...]
    recommended_action: RecommendedAction
    needs_human_review: bool
    grounded: bool
