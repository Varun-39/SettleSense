"""Content-addressed row identity. See architecture.md §5."""
from __future__ import annotations

import hashlib
import json
from typing import NamedTuple


def canonical_json(row: dict) -> str:
    """Deterministic JSON serialization used as the input to row hashing."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def row_hash(row: dict) -> str:
    return hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()


def batch_id(file_content_hashes: list[str]) -> str:
    """Idempotent batch identity: same 4 files -> same run, in any file order."""
    joined = "|".join(sorted(file_content_hashes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class RowRef(NamedTuple):
    """A tamper-evident reference to a source row, used as an evidence citation
    and as an AI-explanation cache key ingredient.
    """

    table: str
    natural_id: str
    row_hash: str
