"""HTTP response shapes.

Every monetary field is returned twice: `*_paise` as the exact integer, and a
`*_display` string formatted once at this boundary. The client never does
money arithmetic, and never has to guess the unit (ADR-004).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from settlesense.contracts.money import format_inr


def money(paise: int | None) -> dict[str, Any]:
    if paise is None:
        return {"paise": None, "display": None}
    return {"paise": int(paise), "display": format_inr(int(paise))}


class RunCreated(BaseModel):
    run_id: str
    batch_id: str
    records_processed: int
    already_existed: bool
    elapsed_seconds: float


class RunSummary(BaseModel):
    run_id: str
    batch_id: str
    engine_version: str
    rules_version: str
    records_processed: int
    matched: int
    needs_review: int
    unresolved: int
    validation_errors: int
    gross_payments: dict
    settled_net: dict
    unexplained: dict


class ResultRow(BaseModel):
    reconciliation_id: str
    payment_id: str
    match_type: str
    match_score: float
    status: str
    reason_code: str | None
    expected_net: dict
    actual_net: dict
    difference: dict
    settled_amount: dict
    pending_amount: dict


class ResultPage(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[ResultRow]


class CalcStepOut(BaseModel):
    seq: int
    label: str
    expression: str
    inputs: dict[str, int]
    result: dict


class EvidenceOut(BaseModel):
    table: str
    natural_id: str
    row_hash: str
    role: str | None
    row: dict | None


class ResultDetail(BaseModel):
    result: ResultRow
    calc_steps: list[CalcStepOut]
    settlements: list[dict]
    evidence: list[EvidenceOut]
    review_actions: list[dict]
    explanation: dict | None = None


class ExceptionGroup(BaseModel):
    reason_code: str
    status: str
    count: int
    unexplained: dict


class ReviewRequest(BaseModel):
    action: Literal["accept", "reject", "annotate"]
    note: str | None = None
    actor: str = "reviewer"


def to_result_row(row: dict) -> ResultRow:
    return ResultRow(
        reconciliation_id=row["reconciliation_id"],
        payment_id=row["payment_id"],
        match_type=row["match_type"],
        match_score=row["match_score"],
        status=row["status"],
        reason_code=row["reason_code"],
        expected_net=money(row["expected_net"]),
        actual_net=money(row["actual_net"]),
        difference=money(row["difference_amount"]),
        settled_amount=money(row["settled_amount"]),
        pending_amount=money(row["pending_amount"]),
    )
