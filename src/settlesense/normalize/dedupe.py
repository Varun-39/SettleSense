"""Exact-duplicate collapsing via row_hash. Near-duplicates are *flagged*,
never deleted — see architecture.md §3 (`dedupe` responsibilities)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class DedupeResult:
    kept: list
    duplicate_row_hashes: list[str]


def dedupe_exact(rows: list[T], row_hash_of) -> DedupeResult:
    """Collapse rows whose row_hash has already been seen. `row_hash_of` is a
    callable extracting the hash from a row (rows are frozen Pydantic models
    with a `row_hash` field, but this stays generic for testability)."""
    seen: set[str] = set()
    kept: list[T] = []
    duplicates: list[str] = []
    for row in rows:
        h = row_hash_of(row)
        if h in seen:
            duplicates.append(h)
            continue
        seen.add(h)
        kept.append(row)
    return DedupeResult(kept=kept, duplicate_row_hashes=duplicates)
