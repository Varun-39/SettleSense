"""The failure cases from architecture.md §10, each handled structurally
rather than by a special-case branch."""
from __future__ import annotations

from pathlib import Path

import pytest

from settlesense.contracts.config import load_config
from settlesense.contracts.enums import ReasonCode
from settlesense.ingest.batch import load_batch
from settlesense.ledger.crosscheck import crosscheck
from settlesense.recon.engine import run

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MALFORMED = ROOT / "demo" / "failure-fixtures" / "malformed"


def load(data_dir: Path):
    return load_batch(
        data_dir / "sample_payments.csv",
        data_dir / "sample_settlements.csv",
        data_dir / "sample_refunds.csv",
        data_dir / "sample_ledger.csv",
    )


@pytest.fixture(scope="module")
def config():
    return load_config(ROOT / "recon.config.yaml")


# -- Duplicate input batch --------------------------------------------------


def test_same_files_produce_the_same_batch_id(config) -> None:
    """Re-uploading the identical batch is detected at the front door, so the
    totals cannot be double-counted."""
    assert load(DATA).id == load(DATA).id


def test_reingesting_the_same_batch_does_not_double_count(config) -> None:
    first = run(load(DATA), config)
    second = run(load(DATA), config)
    assert first.run_id == second.run_id
    assert first.record_count == second.record_count == 100
    assert sum(int(p.amount) for p in first.payments) == sum(
        int(p.amount) for p in second.payments
    )


# -- Invalid amount or date -------------------------------------------------


def test_malformed_rows_are_quarantined_and_the_batch_continues(config) -> None:
    output = run(load(MALFORMED), config)

    # 8 payment rows in, 6 invalid, 2 good ones still reconcile.
    assert len(output.validation_errors) == 6
    assert output.record_count == 2
    assert output.results, "the batch aborted instead of continuing"


def test_each_validation_error_names_its_file_line_and_field(config) -> None:
    output = run(load(MALFORMED), config)
    for err in output.validation_errors:
        assert err.source_file == "sample_payments.csv"
        assert err.source_line >= 2  # header is line 1
        assert err.field
        assert err.reason


def test_validation_catches_each_distinct_defect(config) -> None:
    output = run(load(MALFORMED), config)
    fields = {e.field for e in output.validation_errors}
    assert fields == {"amount", "captured_at", "payment_id", "currency", "status"}


def test_sub_paise_amount_is_rejected_not_rounded(config) -> None:
    output = run(load(MALFORMED), config)
    reasons = [e.reason for e in output.validation_errors if e.field == "amount"]
    assert any("sub-paise" in r for r in reasons)


def test_unsupported_currency_is_rejected_not_summed(config) -> None:
    output = run(load(MALFORMED), config)
    assert any(e.field == "currency" for e in output.validation_errors)


# -- Duplicate ledger rows --------------------------------------------------


def test_duplicate_ledger_rows_are_flagged_not_silently_summed(config) -> None:
    output = run(load(DATA), config)
    findings = crosscheck(output.payments, output.ledger)
    duplicates = [f for f in findings if f.reason is ReasonCode.DUPLICATE_RECORD]
    assert len(duplicates) == 5
    for f in duplicates:
        assert len(f.evidence) == 2, "both rows must be preserved and cited"


def test_ledger_duplicates_do_not_break_payment_reconciliation(config) -> None:
    """The third leg reports its own findings and never alters a settlement
    verdict."""
    output = run(load(DATA), config)
    findings = crosscheck(output.payments, output.ledger)
    dup_orders = {
        f.payment_id for f in findings if f.reason is ReasonCode.DUPLICATE_RECORD
    }
    affected = [r for r in output.results if r.payment_id in dup_orders]
    assert affected
    assert all(r.status.value == "matched" for r in affected)


def test_no_amount_mismatch_findings_on_clean_ledger(config) -> None:
    """Duplicate rows are excluded from the credit total, so a duplicated
    import must not look like an amount discrepancy."""
    output = run(load(DATA), config)
    findings = crosscheck(output.payments, output.ledger)
    assert not [f for f in findings if f.reason is ReasonCode.AMOUNT_MISMATCH]


# -- Engine independence (ADR-001) ------------------------------------------


FORBIDDEN_ROOTS = {
    "anthropic",
    "openai",
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "http",
    "socket",
    "aiohttp",
}


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names actually imported by a source file, from the
    AST — docstrings and comments are not imports."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("settlesense."):
                roots.add(".".join(node.module.split(".")[:2]))
    return roots


def test_deterministic_core_imports_nothing_ai_or_network_related() -> None:
    """The structural guarantee behind the 'AI is down' demo (ADR-001): if this
    fails, the outage story is no longer true.

    Enforced across the whole deterministic core, not just one file.
    """
    core = ROOT / "src" / "settlesense"
    packages = ["recon", "contracts", "ingest", "validate", "normalize", "ledger"]

    offenders: list[str] = []
    for package in packages:
        for source in (core / package).rglob("*.py"):
            roots = _imported_roots(source)
            if roots & FORBIDDEN_ROOTS or "settlesense.ai" in roots:
                offenders.append(
                    f"{source.relative_to(ROOT)} imports "
                    f"{sorted((roots & FORBIDDEN_ROOTS) | (roots & {'settlesense.ai'}))}"
                )

    assert not offenders, "deterministic core reached the network:\n" + "\n".join(
        offenders
    )


def test_engine_runs_with_ai_package_absent(monkeypatch) -> None:
    """Belt and braces: block `settlesense.ai` at import time and reconcile
    the full benchmark anyway."""
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith("settlesense.ai") or name == "anthropic":
            raise ImportError(f"{name} is unavailable in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)

    config = load_config(ROOT / "recon.config.yaml")
    output = run(load(DATA), config)
    assert output.record_count == 100
    assert sum(1 for r in output.results if r.status.value == "matched") == 75
