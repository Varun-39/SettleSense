"""Pipeline orchestration: batch -> validate -> normalize -> dedupe -> index
-> rules -> resolver.

This module must never import `anthropic`, an HTTP client, or anything from
`settlesense.ai` (ADR-001). The whole pipeline runs with the network cable
unplugged, and the run_id is derived from the batch content so re-running the
same input is byte-reproducible.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from settlesense.contracts.config import EngineConfig
from settlesense.contracts.models import (
    LedgerEntry,
    Payment,
    ReconciliationResult,
    Refund,
    Settlement,
)
from settlesense.ingest.batch import Batch
from settlesense.normalize.dedupe import dedupe_exact
from settlesense.recon.index import MatchContext
from settlesense.recon.resolver import resolve
from settlesense.recon.rules.r1_exact_id import r1_exact_id
from settlesense.recon.rules.r2_order_id import r2_order_id
from settlesense.recon.rules.r3_amount_time import r3_amount_time
from settlesense.recon.rules.r4_refund_adjusted import r4_refund_adjusted
from settlesense.recon.rules.r5_partial import r5_partial
from settlesense.validate.errors import RowError
from settlesense.validate.rules import (
    validate_ledger_entry,
    validate_payment,
    validate_refund,
    validate_settlement,
)

ENGINE_VERSION = "0.1.0"
RULES_VERSION = "r1-r6/2026-09-02"

RULES = (r1_exact_id, r2_order_id, r3_amount_time, r4_refund_adjusted, r5_partial)


@dataclass
class RunOutput:
    run_id: str
    batch_id: str
    engine_version: str
    rules_version: str
    payments: list[Payment]
    settlements: list[Settlement]
    refunds: list[Refund]
    ledger: list[LedgerEntry]
    results: list[ReconciliationResult]
    validation_errors: list[RowError] = field(default_factory=list)
    duplicate_row_hashes: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def record_count(self) -> int:
        return len(self.payments)


def _validate_all(batch: Batch, config: EngineConfig):
    errors: list[RowError] = []
    payments: list[Payment] = []
    settlements: list[Settlement] = []
    refunds: list[Refund] = []
    ledger: list[LedgerEntry] = []

    for raw in batch.payments.rows:
        model, err = validate_payment(
            raw, batch.payments.path.name, config.currency.supported
        )
        (payments.append(model) if model else errors.append(err))
    for raw in batch.settlements.rows:
        model, err = validate_settlement(raw, batch.settlements.path.name)
        (settlements.append(model) if model else errors.append(err))
    for raw in batch.refunds.rows:
        model, err = validate_refund(raw, batch.refunds.path.name)
        (refunds.append(model) if model else errors.append(err))
    for raw in batch.ledger.rows:
        model, err = validate_ledger_entry(raw, batch.ledger.path.name)
        (ledger.append(model) if model else errors.append(err))

    return payments, settlements, refunds, ledger, errors


def run(batch: Batch, config: EngineConfig) -> RunOutput:
    started = time.perf_counter()
    run_id = f"run_{batch.id[:12]}"

    payments, settlements, refunds, ledger, errors = _validate_all(batch, config)

    duplicates: list[str] = []
    for rows in (payments, settlements, refunds, ledger):
        result = dedupe_exact(rows, lambda r: r.row_hash)
        duplicates.extend(result.duplicate_row_hashes)
        rows[:] = result.kept

    ctx = MatchContext(
        config=config.matching,
        payments=payments,
        settlements=settlements,
        refunds=refunds,
        ledger=ledger,
    )

    candidates = []
    for payment in payments:
        for rule in RULES:
            candidates.extend(rule(payment, ctx))

    results = resolve(run_id, payments, candidates, ctx)

    return RunOutput(
        run_id=run_id,
        batch_id=batch.id,
        engine_version=ENGINE_VERSION,
        rules_version=RULES_VERSION,
        payments=payments,
        settlements=settlements,
        refunds=refunds,
        ledger=ledger,
        results=results,
        validation_errors=errors,
        duplicate_row_hashes=duplicates,
        elapsed_seconds=time.perf_counter() - started,
    )
