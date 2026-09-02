"""Closed vocabularies shared across the engine, storage, and AI schemas.

Keeping these in one module means the AI layer's structured-output enum
(ADR-005) and the resolver's status values can never drift from each other.
"""
from __future__ import annotations

from enum import StrEnum


class RuleId(StrEnum):
    R1_EXACT_ID = "exact_id"
    R2_ORDER_ID = "order_id"
    R3_AMOUNT_TIME = "amount_time"
    R4_REFUND_ADJUSTED = "refund_adjusted"
    R5_PARTIAL = "partial"
    R6_UNRESOLVED = "unresolved"


class MatchType(StrEnum):
    EXACT_ID = "exact_id"
    AMOUNT_TIME = "amount_time"
    PARTIAL = "partial"
    REFUND_ADJUSTED = "refund_adjusted"
    UNRESOLVED = "unresolved"


class ResultStatus(StrEnum):
    MATCHED = "matched"
    REVIEW = "review"
    UNRESOLVED = "unresolved"


class ReasonCode(StrEnum):
    FEE_MISMATCH = "fee_mismatch"
    TIMING_DIFFERENCE = "timing_difference"
    MISSING_SETTLEMENT = "missing_settlement"
    PARTIAL_SETTLEMENT = "partial_settlement"
    REFUND_ADJUSTED = "refund_adjusted"
    DUPLICATE_RECORD = "duplicate_record"
    AMOUNT_MISMATCH = "amount_mismatch"
    FAILED_SETTLEMENT = "failed_settlement"
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RecommendedAction(StrEnum):
    HUMAN_REVIEW = "human_review"
    WAIT_NEXT_BATCH = "wait_next_batch"
    VERIFY_REFUND = "verify_refund"
    INVESTIGATE_DUPLICATE = "investigate_duplicate"
    NO_ACTION = "no_action"


class ExplanationSource(StrEnum):
    AI = "ai"
    TEMPLATE = "template"
