"""Time handling. See architecture.md §5: store UTC, compare on the IST
business calendar. A settlement window (T+2) is a calendar concept, not a
raw 48-hour duration.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


class InvalidTimestampError(ValueError):
    pass


def parse_timestamp(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp (with or without an explicit offset) and
    return it normalized to UTC. Naive timestamps are assumed to already be
    UTC (source-system convention documented in the README)."""
    if not raw or not raw.strip():
        raise InvalidTimestampError("timestamp is empty")
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidTimestampError(f"unparseable timestamp: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ist_calendar_date(dt: datetime) -> date:
    """The IST calendar date a UTC timestamp falls on — the unit settlement
    windows are actually measured in, per Razorpay's T+N convention."""
    return dt.astimezone(IST).date()


def within_settlement_window(
    captured_at: datetime, settled_at: datetime, window_days: int
) -> bool:
    """True iff settled_at falls within [captured_at, captured_at + window_days]
    on the IST calendar (inclusive), and settled_at is not before captured_at.
    """
    if settled_at < captured_at:
        return False
    captured_date = ist_calendar_date(captured_at)
    settled_date = ist_calendar_date(settled_at)
    return (settled_date - captured_date) <= timedelta(days=window_days)
