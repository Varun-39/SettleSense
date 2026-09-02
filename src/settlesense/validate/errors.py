"""Row-level validation errors. See architecture.md §3: a bad row is
quarantined, never fatal — the batch continues."""
from __future__ import annotations

from pydantic import BaseModel


class RowError(BaseModel):
    source_file: str
    source_line: int
    field: str | None
    reason: str
    raw_row: dict
