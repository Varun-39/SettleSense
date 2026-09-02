"""ADR-004's `no-float-money` guard, enforced rather than documented.

`float()` is how a monetary value silently loses exactness. It is banned
outright in the packages that touch money. `match_score` is the one legitimate
float in the system, and it is a `float` literal/annotation — never a
`float(...)` conversion of an amount.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "settlesense"

# Packages that handle amounts. `evaluate` is exempt: it computes ratios
# (match rate, amount accuracy) which are genuinely fractional and never
# feed back into a stored amount.
MONETARY_PACKAGES = ["contracts", "recon", "normalize", "validate", "ingest", "ledger"]


def _float_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]


def _monetary_sources() -> list[Path]:
    return [
        source
        for package in MONETARY_PACKAGES
        for source in (CORE / package).rglob("*.py")
    ]


def test_monetary_packages_exist() -> None:
    """Guards against the check silently passing because it found no files."""
    assert len(_monetary_sources()) >= 15


@pytest.mark.parametrize(
    "source", _monetary_sources(), ids=lambda p: str(p.relative_to(CORE))
)
def test_no_float_conversion_in_monetary_code(source: Path) -> None:
    offenders = _float_calls(source)
    assert not offenders, (
        f"{source.relative_to(ROOT)} calls float() at line(s) {offenders}. "
        "Money is integer paise (ADR-004); parse via contracts.money.parse_amount."
    )


def test_store_layer_writes_amounts_as_integers() -> None:
    """The DB columns for amounts are INTEGER — a REAL column would reintroduce
    the drift the paise representation exists to prevent."""
    import re

    schema = (CORE / "store" / "schema.sql").read_text(encoding="utf-8")
    for column in (
        "expected_net",
        "actual_net",
        "difference_amount",
        "settled_amount",
        "pending_amount",
        "claimed_paise",
        "result_paise",
        "amount",
    ):
        declaration = re.search(rf"^\s*{column}\s+(\w+)", schema, re.MULTILINE)
        assert declaration, f"{column} is not declared in schema.sql"
        assert declaration.group(1) == "INTEGER", (
            f"{column} is {declaration.group(1)} in schema.sql; money columns must "
            "be INTEGER (ADR-004) — a REAL column reintroduces float drift."
        )
