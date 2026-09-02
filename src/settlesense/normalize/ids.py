"""Identifier canonicalization — trims whitespace and normalizes case so
"pay_1042" and "PAY_1042 " are recognized as the same identifier rather than
silently becoming an unresolved/missing-identifier case."""
from __future__ import annotations


def canonical_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None
