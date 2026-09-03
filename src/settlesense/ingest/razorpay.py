"""Convert Razorpay exports into the four canonical batch files.

Razorpay's settlement recon report is one file holding several entity kinds —
`payment`, `refund`, `adjustment` and others — keyed by a `type` column, while
this engine reads four separate files. The mapping is mechanical, but two
things about it are not:

**Unknown row types are reported, never dropped.** An `adjustment` row moves
money. Silently discarding it would leave the control-total proof unable to
balance, and the run would look fine while being wrong. Anything this adapter
does not understand comes back in `unmapped` for a human to look at.

**Amounts are ambiguous between sources.** The API returns integer paise; the
dashboard CSV export writes rupees with decimals. Guessing wrong is a 100x
error, so the unit is a required argument rather than something inferred.

Field names follow the settlement recon response documented in
razorpay/razorpay-node. CSV column headings have been seen to differ from API
field names, so lookups accept either and anything unrecognised is surfaced.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Literal

AmountUnit = Literal["paise", "rupees"]

# Row kinds this adapter understands. Anything else is reported.
SETTLEMENT_TYPES = {"payment"}
REFUND_TYPES = {"refund"}

# Razorpay's own aliases, so an API dump and a dashboard CSV both work.
ALIASES: dict[str, tuple[str, ...]] = {
    "type": ("type", "entity_type"),
    "entity_id": ("entity_id", "id"),
    "payment_id": ("payment_id",),
    "order_id": ("order_id",),
    "settlement_id": ("settlement_id",),
    "amount": ("amount", "gross_amount"),
    "credit": ("credit", "net_amount"),
    "debit": ("debit",),
    "fee": ("fee", "fees"),
    "tax": ("tax",),
    "settled": ("settled",),
    "on_hold": ("on_hold",),
    "settled_at": ("settled_at",),
    "created_at": ("created_at",),
}


@dataclass
class Conversion:
    settlements: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    unmapped: list[dict] = field(default_factory=list)
    type_counts: Counter = field(default_factory=Counter)

    def report(self) -> str:
        lines = [
            f"settlements  {len(self.settlements)}",
            f"refunds      {len(self.refunds)}",
        ]
        if self.unmapped:
            lines.append(f"UNMAPPED     {len(self.unmapped)}  (money that would go missing)")
            for kind, n in Counter(
                _get(r, "type") or "?" for r in self.unmapped
            ).most_common():
                lines.append(f"               {kind}: {n}")
        return "\n".join(lines)


def _get(row: dict, name: str) -> str | None:
    for key in ALIASES.get(name, (name,)):
        if key in row and row[key] not in (None, ""):
            return str(row[key]).strip()
    return None


def _amount(row: dict, name: str, unit: AmountUnit) -> str:
    """Return a rupee string, which is what the canonical CSVs carry."""
    raw = _get(row, name)
    if raw is None:
        return "0.00"
    cleaned = raw.replace(",", "")
    if unit == "paise":
        # Integer paise from the API: shift the point rather than divide, so
        # no float ever touches the value.
        value = Decimal(cleaned) / Decimal(100)
    else:
        value = Decimal(cleaned)
    return f"{value:.2f}"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _status(row: dict) -> str:
    if _truthy(_get(row, "settled")):
        return "processed"
    if _truthy(_get(row, "on_hold")):
        return "pending"
    return "pending"


def convert_recon(rows: Iterable[dict], unit: AmountUnit) -> Conversion:
    """Split a settlement recon export into settlement and refund rows."""
    out = Conversion()

    for row in rows:
        kind = (_get(row, "type") or "").lower()
        out.type_counts[kind or "?"] += 1

        if kind in SETTLEMENT_TYPES:
            out.settlements.append(
                {
                    # entity_id identifies the recon line; settlement_id names
                    # the payout batch that many lines share, so it cannot be
                    # this row's identity without collapsing rows together.
                    "settlement_id": _get(row, "entity_id") or "",
                    "settlement_batch_id": _get(row, "settlement_id") or "",
                    "payment_id": _get(row, "payment_id") or "",
                    "order_id": _get(row, "order_id") or "",
                    "gross_amount": _amount(row, "amount", unit),
                    "fee": _amount(row, "fee", unit),
                    "tax": _amount(row, "tax", unit),
                    # `credit` is what actually reached the bank account.
                    "net_amount": _amount(row, "credit", unit),
                    "settled_at": _get(row, "settled_at") or _get(row, "created_at") or "",
                    "status": _status(row),
                }
            )
        elif kind in REFUND_TYPES:
            out.refunds.append(
                {
                    "refund_id": _get(row, "entity_id") or "",
                    "payment_id": _get(row, "payment_id") or "",
                    "refund_amount": _amount(row, "amount", unit),
                    "created_at": _get(row, "created_at") or "",
                    "status": "processed",
                }
            )
        else:
            # An adjustment, transfer or anything new. It moves money, so it
            # is reported rather than dropped — a silently discarded row makes
            # the control-total proof unable to balance.
            out.unmapped.append(dict(row))

    return out


def convert_payments(rows: Iterable[dict], unit: AmountUnit) -> list[dict]:
    """A payments export into the canonical payments shape."""
    return [
        {
            "payment_id": _get(row, "entity_id") or _get(row, "payment_id") or "",
            "order_id": _get(row, "order_id") or "",
            "amount": _amount(row, "amount", unit),
            "currency": (_get(row, "currency") or "INR").upper(),
            "status": (_get(row, "status") or "captured").lower(),
            "captured_at": _get(row, "captured_at") or _get(row, "created_at") or "",
            "customer_id": _get(row, "customer_id") or "",
        }
        for row in rows
    ]


def read_csv(path: str | Path) -> list[dict]:
    text = Path(path).read_bytes().decode("utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


def write_csv(path: str | Path, rows: list[dict], headers: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


SETTLEMENT_HEADERS = [
    "settlement_id", "settlement_batch_id", "payment_id", "order_id", "gross_amount",
    "fee", "tax", "net_amount", "settled_at", "status",
]
REFUND_HEADERS = ["refund_id", "payment_id", "refund_amount", "created_at", "status"]
PAYMENT_HEADERS = [
    "payment_id", "order_id", "amount", "currency",
    "status", "captured_at", "customer_id",
]
