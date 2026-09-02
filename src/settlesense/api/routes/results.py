"""Result rows and the evidence drawer.

The drawer is the product: it returns the stored source rows and the stored
calculation steps, not a re-derivation. Nothing here recomputes finance.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from settlesense.api.deps import get_repository
from settlesense.api.schemas import (
    CalcStepOut,
    EvidenceOut,
    ResultDetail,
    ResultPage,
    ReviewRequest,
    money,
    to_result_row,
)
from settlesense.store.repository import Repository

router = APIRouter(prefix="/runs/{run_id}/results", tags=["results"])


@router.get("", response_model=ResultPage)
def list_results(
    run_id: str,
    status: str | None = Query(None, pattern="^(matched|review|unresolved)$"),
    match_type: str | None = None,
    reason_code: str | None = None,
    min_difference: int | None = Query(
        None, ge=0, description="minimum absolute difference in paise"
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    repo: Repository = Depends(get_repository),
) -> ResultPage:
    if repo.get_run(run_id) is None:
        raise HTTPException(404, f"unknown run: {run_id}")

    rows, total = repo.query_results(
        run_id,
        status=status,
        match_type=match_type,
        reason_code=reason_code,
        min_difference=min_difference,
        limit=limit,
        offset=offset,
    )
    return ResultPage(
        total=total,
        limit=limit,
        offset=offset,
        results=[to_result_row(dict(r)) for r in rows],
    )


@router.get("/{reconciliation_id:path}", response_model=ResultDetail)
def result_detail(
    run_id: str,
    reconciliation_id: str,
    repo: Repository = Depends(get_repository),
) -> ResultDetail:
    detail = repo.result_detail(reconciliation_id)
    if detail is None or detail["result"]["run_id"] != run_id:
        raise HTTPException(404, f"unknown result: {reconciliation_id}")

    return ResultDetail(
        result=to_result_row(detail["result"]),
        calc_steps=[
            CalcStepOut(
                seq=s["seq"],
                label=s["label"],
                expression=s["expression"],
                inputs=s["inputs"],
                result=money(s["result_paise"]),
            )
            for s in detail["calc_steps"]
        ],
        settlements=[
            {
                "settlement_id": s["settlement_id"],
                "claimed": money(s["claimed_paise"]),
            }
            for s in detail["settlements"]
        ],
        evidence=[EvidenceOut(**e) for e in detail["evidence"]],
        review_actions=detail["review_actions"],
        # Null whenever the sidecar has not run or had nothing to say. That is a
        # valid, fully-functional state: every number above is already present
        # without it (ADR-001).
        explanation=repo.explanation_for(reconciliation_id),
    )


@router.post("/{reconciliation_id:path}/review", status_code=201)
def record_review(
    run_id: str,
    reconciliation_id: str,
    body: ReviewRequest,
    repo: Repository = Depends(get_repository),
) -> dict:
    """A human's decision on an exception. Recorded alongside the result, never
    overwriting the engine's verdict — the audit trail keeps both."""
    detail = repo.result_detail(reconciliation_id)
    if detail is None or detail["result"]["run_id"] != run_id:
        raise HTTPException(404, f"unknown result: {reconciliation_id}")

    repo.save_review_action(
        reconciliation_id, actor=body.actor, action=body.action, note=body.note
    )
    return {
        "reconciliation_id": reconciliation_id,
        "action": body.action,
        "engine_status": detail["result"]["status"],
        "note": "engine verdict is unchanged; the review is recorded alongside it",
    }
