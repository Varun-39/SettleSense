"""The grounding gate (ADR-005).

An explanation is only stored as an AI explanation if every claim in it is
traceable to something the engine actually computed:

  1. Every id in `evidence_refs` exists in the context that was sent.
  2. Every money figure in `summary` appears in the calculation trace or in a
     cited row.
  3. The category belongs to the same family as the deterministic reason code.

Failing any check is not an error — it downgrades the case to a deterministic
template explanation. `evidence coverage` is computed from these outcomes,
which is what makes it a measured property rather than an assertion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from settlesense.ai.context import CaseContext
from settlesense.ai.schemas import ExplanationOut
from settlesense.contracts.enums import ReasonCode
from settlesense.contracts.money import InvalidAmountError, parse_amount

# Money figures the gate will check. Deliberately conservative: a bare small
# integer ("2 settlement rows") is prose, not an amount, and checking it would
# reject good explanations. A figure is checked when it is currency-marked,
# comma-grouped, or written with decimal places.
MONEY_PATTERN = re.compile(
    r"(?:Rs\.?|₹|INR)\s*(-?[\d,]+(?:\.\d{1,2})?)"  # Rs 1,000.00 / ₹1000
    r"|(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)"  # 1,000.00
    r"|(-?\d+\.\d{1,2})\b",  # 1000.00
    re.IGNORECASE,
)

# A deterministic reason code constrains, but does not fully determine, the
# category: the engine knows *that* a settlement is missing, the model may
# legitimately characterise it as a timing difference.
CATEGORY_FAMILIES: dict[ReasonCode, set[ReasonCode]] = {
    ReasonCode.FEE_MISMATCH: {
        ReasonCode.FEE_MISMATCH,
        ReasonCode.AMOUNT_MISMATCH,
    },
    ReasonCode.AMOUNT_MISMATCH: {
        ReasonCode.AMOUNT_MISMATCH,
        ReasonCode.FEE_MISMATCH,
    },
    ReasonCode.MISSING_SETTLEMENT: {
        ReasonCode.MISSING_SETTLEMENT,
        ReasonCode.TIMING_DIFFERENCE,
        ReasonCode.INSUFFICIENT_EVIDENCE,
    },
    ReasonCode.TIMING_DIFFERENCE: {
        ReasonCode.TIMING_DIFFERENCE,
        ReasonCode.MISSING_SETTLEMENT,
    },
    ReasonCode.PARTIAL_SETTLEMENT: {
        ReasonCode.PARTIAL_SETTLEMENT,
        ReasonCode.TIMING_DIFFERENCE,
    },
    ReasonCode.REFUND_ADJUSTED: {ReasonCode.REFUND_ADJUSTED},
    ReasonCode.DUPLICATE_RECORD: {ReasonCode.DUPLICATE_RECORD},
    ReasonCode.FAILED_SETTLEMENT: {
        ReasonCode.FAILED_SETTLEMENT,
        ReasonCode.MISSING_SETTLEMENT,
    },
    ReasonCode.AMBIGUOUS_CANDIDATES: {
        ReasonCode.AMBIGUOUS_CANDIDATES,
        ReasonCode.INSUFFICIENT_EVIDENCE,
    },
    ReasonCode.INSUFFICIENT_EVIDENCE: {
        ReasonCode.INSUFFICIENT_EVIDENCE,
        ReasonCode.MISSING_SETTLEMENT,
        ReasonCode.AMBIGUOUS_CANDIDATES,
    },
}


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    failures: tuple[str, ...]

    def __bool__(self) -> bool:
        return self.grounded


def extract_money_paise(text: str) -> list[int]:
    """Money-looking figures in prose, as paise. Non-money numbers are ignored
    by construction — see MONEY_PATTERN."""
    found: list[int] = []
    for match in MONEY_PATTERN.finditer(text):
        raw = next((g for g in match.groups() if g), None)
        if raw is None:
            continue
        try:
            found.append(parse_amount(raw))
        except InvalidAmountError:
            continue
    return found


def check(
    explanation: ExplanationOut,
    context: CaseContext,
    engine_reason: ReasonCode | None,
) -> GroundingResult:
    failures: list[str] = []

    # 1. Reference existence.
    unknown = [
        ref for ref in explanation.evidence_refs if ref not in context.allowed_ids
    ]
    if unknown:
        failures.append(f"cites unknown row id(s): {', '.join(sorted(unknown))}")

    if not explanation.evidence_refs:
        failures.append("cites no evidence at all")

    # 2. Every money figure must come from the trace or a cited row.
    invented = [
        paise
        for paise in extract_money_paise(explanation.summary)
        if paise not in context.allowed_amounts_paise
    ]
    if invented:
        rendered = ", ".join(f"{p / 100:,.2f}" for p in sorted(set(invented)))
        failures.append(f"states figure(s) not present in the evidence: {rendered}")

    # 3. Category must be consistent with what the engine determined.
    if engine_reason is not None:
        family = CATEGORY_FAMILIES.get(engine_reason, {engine_reason})
        if explanation.category not in family:
            failures.append(
                f"category {explanation.category.value!r} contradicts engine "
                f"reason {engine_reason.value!r}"
            )

    return GroundingResult(grounded=not failures, failures=tuple(failures))
