"""Settlement windows are an IST calendar concept, not 48 hours of elapsed
time. See architecture.md §5."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from settlesense.normalize.dates import (
    IST,
    InvalidTimestampError,
    ist_calendar_date,
    parse_timestamp,
    within_settlement_window,
)


def test_parse_normalizes_to_utc() -> None:
    dt = parse_timestamp("2026-08-12T10:00:00+05:30")
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 4 and dt.minute == 30


def test_parse_accepts_z_suffix_and_naive() -> None:
    assert parse_timestamp("2026-08-12T04:30:00Z").hour == 4
    assert parse_timestamp("2026-08-12T04:30:00").tzinfo == timezone.utc


@pytest.mark.parametrize("raw", ["", "   ", "not-a-date", "2026-13-45"])
def test_parse_rejects_garbage(raw: str) -> None:
    with pytest.raises(InvalidTimestampError):
        parse_timestamp(raw)


def test_ist_calendar_date_uses_ist_not_utc() -> None:
    # 23:50 IST on the 12th is 18:20 UTC on the 12th — same day either way.
    # 00:10 IST on the 13th is 18:40 UTC on the *12th* — the trap.
    late = datetime(2026, 8, 13, 0, 10, tzinfo=IST)
    assert ist_calendar_date(late).day == 13
    assert late.astimezone(timezone.utc).day == 12


def test_window_counts_calendar_days_not_elapsed_hours() -> None:
    """The case a naive 48-hour subtraction gets wrong: captured late on day 0,
    settled just after midnight on day 2 is 2 calendar days (inside T+2) but
    50+ elapsed hours."""
    captured = datetime(2026, 8, 12, 23, 50, tzinfo=IST)
    settled = datetime(2026, 8, 14, 0, 10, tzinfo=IST)
    assert (settled - captured) > timedelta(hours=24)
    assert within_settlement_window(captured, settled, window_days=2) is True


def test_window_rejects_settlement_before_capture() -> None:
    captured = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    settled = datetime(2026, 8, 11, 10, 0, tzinfo=IST)
    assert within_settlement_window(captured, settled, window_days=2) is False


def test_window_rejects_beyond_window() -> None:
    captured = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    settled = datetime(2026, 8, 16, 10, 0, tzinfo=IST)
    assert within_settlement_window(captured, settled, window_days=2) is False


def test_window_boundary_is_inclusive() -> None:
    captured = datetime(2026, 8, 12, 10, 0, tzinfo=IST)
    settled = datetime(2026, 8, 14, 23, 59, tzinfo=IST)
    assert within_settlement_window(captured, settled, window_days=2) is True
