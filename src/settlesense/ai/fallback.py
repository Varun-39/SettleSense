"""Deterministic template explanations (ADR-005).

This is what makes a strict grounding gate affordable. Without a fallback, a
rejected explanation would leave a blank cell and create pressure to loosen the
checks; with one, the worst case is a plainer sentence built from the same
trace the drawer already shows.

Every reason code must be explicable here — there is a test that asserts it.
No model is involved, so this path also covers "AI unavailable" entirely.
"""
from __future__ import annotations

from settlesense.ai.schemas import ExplanationOut
from settlesense.contracts.enums import ReasonCode, RecommendedAction
from settlesense.contracts.money import format_inr

_ACTIONS: dict[ReasonCode, RecommendedAction] = {
    ReasonCode.FEE_MISMATCH: RecommendedAction.HUMAN_REVIEW,
    ReasonCode.AMOUNT_MISMATCH: RecommendedAction.HUMAN_REVIEW,
    ReasonCode.MISSING_SETTLEMENT: RecommendedAction.WAIT_NEXT_BATCH,
    ReasonCode.TIMING_DIFFERENCE: RecommendedAction.WAIT_NEXT_BATCH,
    ReasonCode.PARTIAL_SETTLEMENT: RecommendedAction.WAIT_NEXT_BATCH,
    ReasonCode.REFUND_ADJUSTED: RecommendedAction.VERIFY_REFUND,
    ReasonCode.DUPLICATE_RECORD: RecommendedAction.INVESTIGATE_DUPLICATE,
    ReasonCode.FAILED_SETTLEMENT: RecommendedAction.HUMAN_REVIEW,
    ReasonCode.AMBIGUOUS_CANDIDATES: RecommendedAction.HUMAN_REVIEW,
    ReasonCode.INSUFFICIENT_EVIDENCE: RecommendedAction.HUMAN_REVIEW,
}


def _sentence(result: dict, reason: ReasonCode | None) -> str:
    payment = result["payment_id"]
    expected = format_inr(result["expected_net"])
    settled = format_inr(result["settled_amount"])
    pending = format_inr(result["pending_amount"])
    difference = format_inr(result["difference_amount"])

    if result["status"] == "matched":
        return (
            f"Payment {payment} reconciles exactly. Expected net {expected} and "
            f"the settled amount agree, so no difference remains."
        )

    match reason:
        case ReasonCode.FEE_MISMATCH | ReasonCode.AMOUNT_MISMATCH:
            return (
                f"Payment {payment} expected a net settlement of {expected} but "
                f"{settled} was settled, leaving {difference} unexplained by the "
                f"recorded fee and tax."
            )
        case ReasonCode.MISSING_SETTLEMENT:
            return (
                f"Payment {payment} has no settlement row inside the expected "
                f"window. The full {pending} remains unsettled."
            )
        case ReasonCode.TIMING_DIFFERENCE:
            return (
                f"Payment {payment} has no settlement inside the expected window; "
                f"{pending} is outstanding and may appear in a later batch."
            )
        case ReasonCode.PARTIAL_SETTLEMENT:
            return (
                f"Payment {payment} is partially settled: {settled} received "
                f"against an expected {expected}, leaving {pending} pending."
            )
        case ReasonCode.REFUND_ADJUSTED:
            return (
                f"Payment {payment} has a processed refund. The expected net after "
                f"the refund is {expected} and {settled} was settled."
            )
        case ReasonCode.FAILED_SETTLEMENT:
            return (
                f"Payment {payment} has a settlement row that did not complete. "
                f"No money moved, so the full {pending} is outstanding."
            )
        case ReasonCode.DUPLICATE_RECORD:
            return (
                f"Payment {payment} is associated with duplicate records. Both "
                f"rows are preserved and neither has been double-counted."
            )
        case ReasonCode.AMBIGUOUS_CANDIDATES:
            return (
                f"Payment {payment} had more than one equally good settlement "
                f"match, so none was accepted. Both candidates are cited for "
                f"review."
            )
        case _:
            return (
                f"Payment {payment} could not be reconciled from the available "
                f"evidence. Expected net {expected}, {settled} settled, "
                f"{pending} pending."
            )


def render(result: dict, evidence: list[dict]) -> ExplanationOut:
    """Build an explanation from stored data alone. Always grounded by
    construction: every figure comes from the result row and every id from the
    engine's own evidence list."""
    reason = ReasonCode(result["reason_code"]) if result.get("reason_code") else None
    category = reason or (
        ReasonCode.INSUFFICIENT_EVIDENCE
        if result["status"] != "matched"
        else ReasonCode.REFUND_ADJUSTED
        if result["match_type"] == "refund_adjusted"
        else ReasonCode.PARTIAL_SETTLEMENT
        if result["match_type"] == "partial"
        else ReasonCode.AMOUNT_MISMATCH
    )

    return ExplanationOut(
        category=category,
        summary=_sentence(result, reason),
        evidence_refs=[item["natural_id"] for item in evidence],
        recommended_action=(
            RecommendedAction.NO_ACTION
            if result["status"] == "matched"
            else _ACTIONS.get(category, RecommendedAction.HUMAN_REVIEW)
        ),
        needs_human_review=result["status"] != "matched",
    )
