"""Row-level validation + normalization into typed contracts.

Architecture.md §3: a bad row is quarantined into `validation_errors` with its
file and line, and the batch continues. Nothing here aborts a run.

The row_hash is computed over *normalized* values, so "1000.00" and "1000"
are recognized as the same row by the deduplicator rather than surviving as
two records that differ only in formatting.
"""
from __future__ import annotations

from typing import Callable

from settlesense.contracts.models import LedgerEntry, Payment, Refund, Settlement
from settlesense.contracts.money import InvalidAmountError, parse_amount
from settlesense.contracts.refs import row_hash
from settlesense.normalize.dates import InvalidTimestampError, parse_timestamp
from settlesense.normalize.ids import canonical_id
from settlesense.validate.errors import RowError

PAYMENT_STATUSES = {"captured", "failed", "refunded", "partially_refunded"}
SETTLEMENT_STATUSES = {"processed", "pending", "failed", "partial"}
REFUND_STATUSES = {"created", "processed", "failed"}


class _FieldError(Exception):
    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def _required_id(raw: dict, field: str) -> str:
    value = canonical_id(raw.get(field))
    if value is None:
        raise _FieldError(field, "missing required identifier")
    return value


def _optional_id(raw: dict, field: str) -> str | None:
    return canonical_id(raw.get(field))


def _amount(raw: dict, field: str) -> int:
    try:
        return parse_amount(raw.get(field, ""))
    except InvalidAmountError as exc:
        raise _FieldError(field, str(exc)) from exc


def _timestamp(raw: dict, field: str):
    try:
        return parse_timestamp(raw.get(field, ""))
    except InvalidTimestampError as exc:
        raise _FieldError(field, str(exc)) from exc


def _enum(raw: dict, field: str, allowed: set[str]) -> str:
    value = (raw.get(field) or "").strip().lower()
    if value not in allowed:
        raise _FieldError(field, f"expected one of {sorted(allowed)}, got {value!r}")
    return value


def _currency(raw: dict, field: str, supported: list[str]) -> str:
    value = (raw.get(field) or "").strip().upper()
    if value not in supported:
        raise _FieldError(field, f"unsupported currency {value!r}")
    return value


def _validate(
    raw: dict, source_file: str, build: Callable[[dict], object]
) -> tuple[object | None, RowError | None]:
    """Shared wrapper: run a builder, convert any field failure into a RowError."""
    try:
        return build(raw), None
    except _FieldError as exc:
        clean = {k: v for k, v in raw.items() if k != "__source_line__"}
        return None, RowError(
            source_file=source_file,
            source_line=int(raw.get("__source_line__", 0)),
            field=exc.field,
            reason=exc.reason,
            raw_row=clean,
        )


def validate_payment(
    raw: dict, source_file: str, supported_currencies: list[str]
) -> tuple[Payment | None, RowError | None]:
    def build(r: dict) -> Payment:
        core = {
            "payment_id": _required_id(r, "payment_id"),
            "order_id": _optional_id(r, "order_id"),
            "amount": _amount(r, "amount"),
            "currency": _currency(r, "currency", supported_currencies),
            "status": _enum(r, "status", PAYMENT_STATUSES),
            "captured_at": _timestamp(r, "captured_at"),
            "customer_id": _optional_id(r, "customer_id"),
        }
        return Payment(row_hash=row_hash(core), **core)

    return _validate(raw, source_file, build)


def validate_settlement(
    raw: dict, source_file: str
) -> tuple[Settlement | None, RowError | None]:
    def build(r: dict) -> Settlement:
        core = {
            "settlement_id": _required_id(r, "settlement_id"),
            "payment_id": _optional_id(r, "payment_id"),
            "order_id": _optional_id(r, "order_id"),
            "settlement_batch_id": _optional_id(r, "settlement_batch_id"),
            "gross_amount": _amount(r, "gross_amount"),
            "fee": _amount(r, "fee"),
            "tax": _amount(r, "tax"),
            "net_amount": _amount(r, "net_amount"),
            "settled_at": _timestamp(r, "settled_at"),
            "status": _enum(r, "status", SETTLEMENT_STATUSES),
        }
        return Settlement(row_hash=row_hash(core), **core)

    return _validate(raw, source_file, build)


def validate_refund(raw: dict, source_file: str) -> tuple[Refund | None, RowError | None]:
    def build(r: dict) -> Refund:
        core = {
            "refund_id": _required_id(r, "refund_id"),
            "payment_id": _required_id(r, "payment_id"),
            "refund_amount": _amount(r, "refund_amount"),
            "created_at": _timestamp(r, "created_at"),
            "status": _enum(r, "status", REFUND_STATUSES),
        }
        return Refund(row_hash=row_hash(core), **core)

    return _validate(raw, source_file, build)


def validate_ledger_entry(
    raw: dict, source_file: str
) -> tuple[LedgerEntry | None, RowError | None]:
    def build(r: dict) -> LedgerEntry:
        core = {
            "ledger_entry_id": _required_id(r, "ledger_entry_id"),
            "order_id": _required_id(r, "order_id"),
            "debit": _amount(r, "debit"),
            "credit": _amount(r, "credit"),
            "posted_at": _timestamp(r, "posted_at"),
            "description": (r.get("description") or "").strip(),
        }
        return LedgerEntry(row_hash=row_hash(core), **core)

    return _validate(raw, source_file, build)
