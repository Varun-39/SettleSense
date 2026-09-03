"""The batches a client is allowed to reconcile by name.

A client may not name a filesystem path. An earlier version resolved the
`fixture` form field with `Path(fixture)` directly, which let a caller walk the
tree looking for any directory holding four CSVs with the expected names — a
narrow read primitive, but a real one. Names are resolved here against a fixed
registry instead, so traversal is not expressible.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Fixture:
    name: str
    label: str
    description: str
    path: Path

    def exists(self) -> bool:
        return self.path.is_dir()


FIXTURES: dict[str, Fixture] = {
    f.name: f
    for f in (
        Fixture(
            name="benchmark",
            label="Benchmark batch",
            description=(
                "100 records with known ground truth across nine case types. "
                "Scored against a held-out answer file."
            ),
            path=ROOT / "data",
        ),
        Fixture(
            name="malformed",
            label="Malformed rows",
            description=(
                "Eight payments, six of them invalid: bad amount, bad date, "
                "missing id, unsupported currency, sub-paise precision. The "
                "batch continues and the good rows still reconcile."
            ),
            path=ROOT / "demo" / "failure-fixtures" / "malformed",
        ),
        Fixture(
            name="ambiguous",
            label="Ambiguous match",
            description=(
                "Two identical payments and a single settlement that could "
                "belong to either. The engine refuses to choose and routes "
                "both to review rather than reporting a false match."
            ),
            path=ROOT / "demo" / "failure-fixtures" / "ambiguous",
        ),
        Fixture(
            name="duplicate-id",
            label="Duplicate payment id",
            description=(
                "The same payment id exported twice with different amounts. "
                "Neither row is matched and neither claims the settlement, so "
                "one export cannot be counted as two payments."
            ),
            path=ROOT / "demo" / "failure-fixtures" / "duplicate-id",
        ),
    )
}


def get(name: str) -> Fixture | None:
    return FIXTURES.get(name)


def listing() -> list[dict]:
    return [
        {
            "name": f.name,
            "label": f.label,
            "description": f.description,
            "available": f.exists(),
        }
        for f in FIXTURES.values()
    ]
