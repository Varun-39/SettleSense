"""Structured-output contracts for the AI sidecar (ADR-005 schema gate).

A closed `category` enum means an off-menu answer is a parse failure, not a new
unhandled state in the UI. These models are what `client.messages.parse` is
asked to fill, so the shape is guaranteed before the grounding gate even runs.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from settlesense.contracts.enums import ReasonCode, RecommendedAction


class ExplanationOut(BaseModel):
    """What the model is allowed to return for a single reconciliation case."""

    category: ReasonCode = Field(
        description="The single category that best describes this case."
    )
    summary: str = Field(
        description=(
            "Two or three sentences for a finance reviewer. Reference the source "
            "rows by id. Every rupee figure you state must appear in the "
            "calculation trace or in a cited row — never compute a new one."
        )
    )
    evidence_refs: list[str] = Field(
        description=(
            "Ids of the source rows this explanation relies on. Use only ids "
            "present in the case context."
        )
    )
    recommended_action: RecommendedAction = Field(
        description="The next step a human should take."
    )
    needs_human_review: bool = Field(
        description="True when a person must look at this before it is closed."
    )


class ClusterOut(BaseModel):
    """One group of exceptions sharing a root cause."""

    label: str = Field(description="Short human label, e.g. 'delayed August batch'.")
    rationale: str = Field(description="Why these cases belong together.")
    member_payment_ids: list[str] = Field(
        description="Payment ids in this group. Use only ids present in the input."
    )


class ClusterSetOut(BaseModel):
    clusters: list[ClusterOut]
