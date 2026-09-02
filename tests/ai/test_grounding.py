"""The grounding gate (ADR-005) — the reason `evidence coverage` is a
measurement and not a claim.

The failure this file exists to prevent: a fluent, confident explanation citing
`rfnd_88` when no such row exists, sitting next to perfectly correct numbers.
"""
from __future__ import annotations

import pytest

from settlesense.ai.context import build_case
from settlesense.ai.grounding import (
    CATEGORY_FAMILIES,
    check,
    extract_money_paise,
)
from settlesense.ai.schemas import ExplanationOut
from settlesense.contracts.enums import ReasonCode, RecommendedAction

RESULT = {
    "payment_id": "pay_1042",
    "run_id": "run_x",
    "status": "review",
    "reason_code": "fee_mismatch",
    "match_type": "exact_id",
    "expected_net": 97_000,
    "actual_net": 92_000,
    "difference_amount": -5_000,
    "settled_amount": 92_000,
    "pending_amount": 0,
}

CALC_STEPS = [
    {
        "seq": 1,
        "label": "expected net settlement",
        "expression": "payment_amount - refunds - fee - tax",
        "inputs": {"payment_amount": 100_000, "refunds": 0, "fee": 3_000, "tax": 0},
        "result_paise": 97_000,
    },
    {
        "seq": 2,
        "label": "difference vs settled amount",
        "expression": "actual_net - expected_net",
        "inputs": {"expected_net": 97_000, "actual_net": 92_000},
        "result_paise": -5_000,
    },
]

EVIDENCE = [
    {
        "table": "payments",
        "natural_id": "pay_1042",
        "row_hash": "h1",
        "role": None,
        "row": {"payment_id": "pay_1042", "amount": 100_000, "customer_id": "cust_9"},
    },
    {
        "table": "settlements",
        "natural_id": "setl_77",
        "row_hash": "h2",
        "role": None,
        "row": {
            "settlement_id": "setl_77",
            "gross_amount": 100_000,
            "fee": 3_000,
            "tax": 0,
            "net_amount": 92_000,
        },
    },
]


@pytest.fixture
def context():
    return build_case(RESULT, CALC_STEPS, EVIDENCE)


def explanation(**overrides) -> ExplanationOut:
    base = dict(
        category=ReasonCode.FEE_MISMATCH,
        summary="Payment pay_1042 expected Rs 970.00 but Rs 920.00 was settled.",
        evidence_refs=["pay_1042", "setl_77"],
        recommended_action=RecommendedAction.HUMAN_REVIEW,
        needs_human_review=True,
    )
    base.update(overrides)
    return ExplanationOut(**base)


# -- the input gate ---------------------------------------------------------


def test_customer_id_never_reaches_the_prompt(context) -> None:
    """PII is stripped before rendering — the model never needs it."""
    assert "cust_9" not in context.prompt
    assert "customer_id" not in context.prompt


def test_context_contains_the_verdict_and_the_trace(context) -> None:
    assert "pay_1042" in context.prompt
    assert "expected net settlement" in context.prompt
    assert "setl_77" in context.prompt


# -- reference existence ----------------------------------------------------


def test_accepts_a_well_grounded_explanation(context) -> None:
    assert check(explanation(), context, ReasonCode.FEE_MISMATCH).grounded


def test_rejects_a_hallucinated_row_reference(context) -> None:
    """The headline case: a refund id that does not exist anywhere."""
    result = check(
        explanation(evidence_refs=["pay_1042", "rfnd_88"]),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert not result.grounded
    assert any("rfnd_88" in f for f in result.failures)


def test_rejects_an_explanation_citing_nothing(context) -> None:
    result = check(explanation(evidence_refs=[]), context, ReasonCode.FEE_MISMATCH)
    assert not result.grounded
    assert any("no evidence" in f for f in result.failures)


# -- money figures ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Rs 1,000.00 was settled", [100_000]),
        ("₹500.50 refunded", [50_050]),
        ("INR 250.00", [25_000]),
        ("the figure 1,000.00 appears", [100_000]),
        ("a bare 970.00 amount", [97_000]),
        ("2 settlement rows were found", []),  # counts are prose, not money
        ("split across 3 batches", []),
    ],
)
def test_money_extraction_targets_money_not_counts(text, expected) -> None:
    assert extract_money_paise(text) == expected


def test_rejects_an_invented_figure(context) -> None:
    """Rs 250.00 appears nowhere in the trace or the cited rows."""
    result = check(
        explanation(summary="The unexplained gap is Rs 250.00 in fees."),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert not result.grounded
    assert any("250.00" in f for f in result.failures)


def test_accepts_figures_drawn_from_the_trace(context) -> None:
    result = check(
        explanation(
            summary=(
                "Payment pay_1042 expected Rs 970.00 net after a Rs 30.00 fee; "
                "Rs 920.00 was settled, leaving Rs 50.00 unexplained."
            )
        ),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert result.grounded, result.failures


def test_accepts_a_negative_figure_stated_positively(context) -> None:
    """The trace holds -5000; an explanation may reasonably say 'Rs 50.00'."""
    result = check(
        explanation(summary="A shortfall of Rs 50.00 remains."),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert result.grounded, result.failures


# -- category consistency ---------------------------------------------------


def test_rejects_a_category_contradicting_the_engine(context) -> None:
    result = check(
        explanation(category=ReasonCode.DUPLICATE_RECORD),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert not result.grounded
    assert any("contradicts" in f for f in result.failures)


def test_allows_a_related_category_within_the_family(context) -> None:
    """The engine knows the amount is off; calling it an amount mismatch rather
    than a fee mismatch is a legitimate characterisation."""
    result = check(
        explanation(category=ReasonCode.AMOUNT_MISMATCH),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert result.grounded, result.failures


def test_every_reason_code_has_a_declared_family() -> None:
    """A missing family would silently accept any category for that reason."""
    for reason in ReasonCode:
        assert reason in CATEGORY_FAMILIES, f"{reason} has no category family"
        assert reason in CATEGORY_FAMILIES[reason]


def test_no_engine_reason_means_no_category_constraint(context) -> None:
    result = check(
        explanation(category=ReasonCode.DUPLICATE_RECORD), context, None
    )
    assert result.grounded


def test_multiple_failures_are_all_reported(context) -> None:
    result = check(
        explanation(
            category=ReasonCode.DUPLICATE_RECORD,
            summary="Rs 999.99 is missing.",
            evidence_refs=["nope_1"],
        ),
        context,
        ReasonCode.FEE_MISMATCH,
    )
    assert len(result.failures) == 3
