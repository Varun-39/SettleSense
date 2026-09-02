"""AI sidecar endpoints.

Every route here is optional in the strongest sense: the application is fully
usable without ever calling one, and calling one changes no reconciliation
figure. Explanations and clusters are written to their own tables (ADR-001).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from settlesense.ai.client import AIClient
from settlesense.ai.cluster import cluster_run
from settlesense.ai.explain import explain_run
from settlesense.api.deps import Settings, get_repository, get_settings
from settlesense.store.repository import Repository

router = APIRouter(prefix="/runs/{run_id}", tags=["ai"])


def _require_run(repo: Repository, run_id: str) -> None:
    if repo.get_run(run_id) is None:
        raise HTTPException(404, f"unknown run: {run_id}")


@router.post("/explain")
def explain(
    run_id: str,
    only_exceptions: bool = Query(
        True, description="Explain exceptions only; a clean match needs no narrative."
    ),
    settings: Settings = Depends(get_settings),
    repo: Repository = Depends(get_repository),
) -> dict:
    """Generate explanations for a run.

    Always succeeds. With no API key, an unreachable API, or an ungrounded
    answer, cases fall back to deterministic template explanations — so this
    returns 200 with `from_template` counts rather than an error.
    """
    _require_run(repo, run_id)
    client = AIClient(settings.config().ai)
    report = explain_run(run_id, repo, client, only_exceptions=only_exceptions)

    return {
        "run_id": run_id,
        "explained": report.total,
        "from_ai": report.from_ai,
        "from_template": report.from_template,
        "from_cache": report.from_cache,
        "rejected_by_grounding": report.rejected_by_grounding,
        "grounding_failures": report.grounding_failures[:20],
        "evidence_coverage": report.evidence_coverage,
        "ai_grounded_rate": report.ai_grounded_rate,
        "ai_available": report.ai_available,
        "unavailable_reason": report.unavailable_reason,
        "note": (
            "Explanations are additive. Reconciliation figures and metrics are "
            "unchanged by this call."
        ),
    }


@router.post("/cluster")
def cluster(
    run_id: str,
    settings: Settings = Depends(get_settings),
    repo: Repository = Depends(get_repository),
) -> dict:
    """Group exceptions by root cause. Falls back to grouping by reason code
    when the AI layer is unavailable — still useful, entirely deterministic."""
    _require_run(repo, run_id)
    client = AIClient(settings.config().ai)
    clusters = cluster_run(run_id, repo, client)
    return {
        "run_id": run_id,
        "clusters": [
            {
                "label": c.label,
                "rationale": c.rationale,
                "member_payment_ids": list(c.member_payment_ids),
                "source": c.source,
            }
            for c in clusters
        ],
        "ai_available": client.available(),
    }


@router.get("/clusters")
def list_clusters(
    run_id: str, repo: Repository = Depends(get_repository)
) -> list[dict]:
    _require_run(repo, run_id)
    return repo.clusters_for(run_id)
