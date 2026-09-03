"""Run creation and batch-level reads.

POST /runs is idempotent on batch_id: re-uploading the same four files returns
the existing run instead of double-counting it (architecture.md §5).
"""
from __future__ import annotations

import csv
import io
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from settlesense.api import fixtures
from settlesense.api.deps import Settings, get_repository, get_settings
from settlesense.api.schemas import (
    ExceptionGroup,
    RunCreated,
    RunSummary,
    money,
)
from settlesense.evaluate.evaluator import evaluate, load_ground_truth
from settlesense.ingest.batch import load_batch
from settlesense.ledger.crosscheck import crosscheck
from settlesense.recon.engine import run as run_engine
from settlesense.store.repository import Repository

router = APIRouter(prefix="/runs", tags=["runs"])

FILE_NAMES = (
    "sample_payments.csv",
    "sample_settlements.csv",
    "sample_refunds.csv",
    "sample_ledger.csv",
)


def _execute_run(data_dir: Path, settings: Settings, repo: Repository) -> RunCreated:
    config = settings.config()
    batch = load_batch(*(data_dir / name for name in FILE_NAMES))

    existing = repo.find_run_by_batch(batch.id)
    if existing:
        summary = repo.summary_for(existing)
        return RunCreated(
            run_id=existing,
            batch_id=batch.id,
            records_processed=summary["records_processed"],
            already_existed=True,
            elapsed_seconds=0.0,
        )

    output = run_engine(batch, config)
    findings = crosscheck(output.payments, output.ledger)

    metrics = None
    truth_path = data_dir / "ground_truth.csv"
    if truth_path.exists():
        metrics = evaluate(output, load_ground_truth(truth_path))

    repo.save_run(
        output,
        config_json=config.model_dump_json(),
        findings=findings,
        metrics=metrics,
    )
    return RunCreated(
        run_id=output.run_id,
        batch_id=output.batch_id,
        records_processed=output.record_count,
        already_existed=False,
        elapsed_seconds=output.elapsed_seconds,
    )


@router.post("", response_model=RunCreated, status_code=201)
async def create_run(
    payments: UploadFile | None = File(None),
    settlements: UploadFile | None = File(None),
    refunds: UploadFile | None = File(None),
    ledger: UploadFile | None = File(None),
    fixture: str | None = Form(None),
    settings: Settings = Depends(get_settings),
    repo: Repository = Depends(get_repository),
) -> RunCreated:
    """Reconcile a batch: four uploaded CSVs, or a fixture named in the
    registry. `fixture` is a name, never a path — see api/fixtures.py."""
    uploads = [payments, settlements, refunds, ledger]

    if all(u is not None for u in uploads):
        tmp = Path(tempfile.mkdtemp(prefix="settlesense_"))
        try:
            for upload, name in zip(uploads, FILE_NAMES):
                (tmp / name).write_bytes(await upload.read())
            return _execute_run(tmp, settings, repo)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if any(u is not None for u in uploads):
        raise HTTPException(
            400,
            "provide all four files (payments, settlements, refunds, ledger) "
            "or none with a `fixture` name",
        )

    if not fixture:
        return _execute_run(settings.data_dir, settings, repo)

    known = fixtures.get(fixture)
    if known is None:
        raise HTTPException(404, f"unknown fixture: {fixture!r}")
    if not known.exists():
        raise HTTPException(404, f"fixture {fixture!r} is not installed")
    missing = [n for n in FILE_NAMES if not (known.path / n).exists()]
    if missing:
        raise HTTPException(400, f"fixture is missing: {', '.join(missing)}")
    return _execute_run(known.path, settings, repo)



@router.get("")
def list_runs(repo: Repository = Depends(get_repository)) -> list[dict]:
    return [dict(r) for r in repo.list_runs()]


def _require_run(repo: Repository, run_id: str):
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"unknown run: {run_id}")
    return run


@router.get("/{run_id}/summary", response_model=RunSummary)
def run_summary(run_id: str, repo: Repository = Depends(get_repository)) -> RunSummary:
    run = _require_run(repo, run_id)
    s = repo.summary_for(run_id)
    return RunSummary(
        run_id=run_id,
        batch_id=run["batch_id"],
        engine_version=run["engine_version"],
        rules_version=run["rules_version"],
        records_processed=s["records_processed"],
        matched=s["matched"],
        needs_review=s["needs_review"],
        unresolved=s["unresolved"],
        validation_errors=s["validation_errors"],
        gross_payments=money(s["gross_payments_paise"]),
        settled_net=money(s["settled_net_paise"]),
        unexplained=money(s["unexplained_paise"]),
    )


@router.get("/{run_id}/exceptions", response_model=list[ExceptionGroup])
def run_exceptions(
    run_id: str, repo: Repository = Depends(get_repository)
) -> list[ExceptionGroup]:
    _require_run(repo, run_id)
    return [
        ExceptionGroup(
            reason_code=g["reason_code"],
            status=g["status"],
            count=g["count"],
            unexplained=money(g["unexplained_paise"]),
        )
        for g in repo.exception_groups(run_id)
    ]


@router.get("/{run_id}/metrics")
def run_metrics(run_id: str, repo: Repository = Depends(get_repository)) -> dict:
    _require_run(repo, run_id)
    metrics = repo.metrics_for(run_id)
    if not metrics:
        raise HTTPException(
            404, "no metrics for this run (ground_truth.csv was not present)"
        )
    return metrics


@router.get("/{run_id}/validation-errors")
def run_validation_errors(
    run_id: str, repo: Repository = Depends(get_repository)
) -> list[dict]:
    _require_run(repo, run_id)
    return [dict(r) for r in repo.validation_errors_for(run_id)]


@router.get("/{run_id}/ledger-findings")
def run_ledger_findings(
    run_id: str, repo: Repository = Depends(get_repository)
) -> list[dict]:
    _require_run(repo, run_id)
    return [dict(r) for r in repo.ledger_findings_for(run_id)]


@router.get("/{run_id}/export.csv")
def export_csv(run_id: str, repo: Repository = Depends(get_repository)):
    _require_run(repo, run_id)
    rows, _ = repo.query_results(run_id, limit=1_000_000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "payment_id",
            "status",
            "match_type",
            "reason_code",
            "expected_net_paise",
            "actual_net_paise",
            "difference_paise",
            "settled_paise",
            "pending_paise",
            "settlement_ids",
        ]
    )
    for row in rows:
        detail = repo.result_detail(row["reconciliation_id"])
        ids = "|".join(s["settlement_id"] for s in detail["settlements"])
        writer.writerow(
            [
                row["payment_id"],
                row["status"],
                row["match_type"],
                row["reason_code"] or "",
                row["expected_net"],
                "" if row["actual_net"] is None else row["actual_net"],
                row["difference_amount"],
                row["settled_amount"],
                row["pending_amount"],
                ids,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_results.csv"'},
    )
