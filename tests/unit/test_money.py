"""ADR-004 action item: parser tests for every shape a CSV can hand us."""
from __future__ import annotations

import pytest

from settlesense.contracts.money import InvalidAmountError, format_inr, parse_amount


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1000", 100_000),
        ("1000.00", 100_000),
        ("1,000.00", 100_000),
        ("0", 0),
        ("0.01", 1),
        ("-500", -50_000),
        ("-500.50", -50_050),
        ("  1000.50  ", 100_050),
        ("1e3", 100_000),
    ],
)
def test_parse_amount_valid(raw: str, expected: int) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["1000.005", "0.001", "12.3456"])
def test_parse_amount_rejects_sub_paise(raw: str) -> None:
    """Refusing to round is the point: the row goes to validation_errors
    rather than being silently altered."""
    with pytest.raises(InvalidAmountError, match="sub-paise"):
        parse_amount(raw)


@pytest.mark.parametrize("raw", ["", "   ", "abc", "1,00,0.0.0", None])
def test_parse_amount_rejects_garbage(raw) -> None:
    with pytest.raises(InvalidAmountError):
        parse_amount(raw)


def test_no_float_drift_over_many_additions() -> None:
    """The bug integer paise exists to prevent: 0.1 + 0.2 != 0.3."""
    total = sum(parse_amount("0.10") for _ in range(1000))
    assert total == 10_000  # exactly Rs 100.00, no epsilon needed
    assert total == parse_amount("100.00")


@pytest.mark.parametrize(
    "paise,expected",
    [
        (100_000, "Rs 1,000.00"),
        (0, "Rs 0.00"),
        (1, "Rs 0.01"),
        (-50_050, "-Rs 500.50"),
        (123_456_789, "Rs 1,234,567.89"),
    ],
)
def test_format_inr(paise: int, expected: str) -> None:
    assert format_inr(paise) == expected


def test_round_trip() -> None:
    for raw in ["1000.00", "0.01", "99999.99"]:
        paise = parse_amount(raw)
        assert parse_amount(format_inr(paise).replace("Rs ", "")) == paise
