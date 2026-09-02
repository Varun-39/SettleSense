"""Calculation traces. Every rupee figure a rule produces must be reachable
from an ordered list of steps — this is what the evidence drawer renders and
what the AI grounding gate (ADR-005) checks explanation figures against.
"""
from __future__ import annotations

from settlesense.contracts.models import CalcStep
from settlesense.contracts.money import Paise


class TraceBuilder:
    def __init__(self) -> None:
        self._steps: list[CalcStep] = []

    def step(
        self, label: str, expression: str, inputs: dict[str, int], result: Paise
    ) -> Paise:
        self._steps.append(
            CalcStep(
                seq=len(self._steps) + 1,
                label=label,
                expression=expression,
                inputs=dict(inputs),
                result_paise=result,
            )
        )
        return result

    def build(self) -> tuple[CalcStep, ...]:
        return tuple(self._steps)


def expected_net(
    trace: TraceBuilder,
    payment_amount: Paise,
    refunds_total: Paise,
    fee: Paise,
    tax: Paise,
) -> Paise:
    """expected_net = payment_amount - refunds - fee - tax.

    Recorded as one labelled step so the drawer can show the arithmetic
    rather than asserting the conclusion.
    """
    result = payment_amount - refunds_total - fee - tax
    return trace.step(
        label="expected net settlement",
        expression="payment_amount - refunds - fee - tax",
        inputs={
            "payment_amount": int(payment_amount),
            "refunds": int(refunds_total),
            "fee": int(fee),
            "tax": int(tax),
        },
        result=result,
    )


def difference(trace: TraceBuilder, expected: Paise, actual: Paise) -> Paise:
    result = actual - expected
    return trace.step(
        label="difference vs settled amount",
        expression="actual_net - expected_net",
        inputs={"expected_net": int(expected), "actual_net": int(actual)},
        result=result,
    )
