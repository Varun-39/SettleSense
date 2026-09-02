"""Money as integer paise. See docs/adr/ADR-004-money-integer-paise.md.

`float` must never appear in a monetary code path. `Decimal` is confined to
`parse_amount` — it exists only to get from a string to an exact integer.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import NewType

Paise = NewType("Paise", int)


class InvalidAmountError(ValueError):
    """Raised when a raw amount string cannot be parsed to an exact paise value."""


def parse_amount(raw: str) -> Paise:
    """Parse a rupee-denominated string into exact integer paise.

    Accepts "1000", "1000.00", "1,000.00", "-500.5". Rejects anything with
    sub-paise precision (e.g. "1000.005") as a validation error rather than
    silently rounding it away — the caller should route the row to
    `validation_errors` instead of trusting a guessed value.
    """
    if raw is None:
        raise InvalidAmountError("amount is missing")

    cleaned = raw.strip().replace(",", "")
    if not cleaned:
        raise InvalidAmountError("amount is empty")

    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise InvalidAmountError(f"amount is not a valid number: {raw!r}") from exc

    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise InvalidAmountError(
            f"amount has sub-paise precision, refusing to round: {raw!r}"
        )

    quantized = scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return Paise(int(quantized))


def format_inr(amount: Paise) -> str:
    """Format paise as a display string, e.g. Paise(100_000) -> 'Rs 1,000.00'.

    This is the single conversion point back to rupees. Nothing upstream of
    the API/UI boundary should call this — comparisons and arithmetic stay
    in paise.
    """
    negative = amount < 0
    whole, frac = divmod(abs(amount), 100)
    grouped = f"{whole:,}"
    sign = "-" if negative else ""
    return f"{sign}Rs {grouped}.{frac:02d}"
