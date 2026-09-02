"""Batch identity. See architecture.md §5: re-uploading the same four files
returns the existing run instead of double-counting."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from settlesense.contracts.refs import batch_id
from settlesense.ingest.loader import RawFile, read_csv


@dataclass(frozen=True)
class Batch:
    id: str
    payments: RawFile
    settlements: RawFile
    refunds: RawFile
    ledger: RawFile


def load_batch(
    payments_path: str | Path,
    settlements_path: str | Path,
    refunds_path: str | Path,
    ledger_path: str | Path,
) -> Batch:
    payments = read_csv(payments_path)
    settlements = read_csv(settlements_path)
    refunds = read_csv(refunds_path)
    ledger = read_csv(ledger_path)

    bid = batch_id(
        [
            payments.content_hash,
            settlements.content_hash,
            refunds.content_hash,
            ledger.content_hash,
        ]
    )
    return Batch(
        id=bid,
        payments=payments,
        settlements=settlements,
        refunds=refunds,
        ledger=ledger,
    )
