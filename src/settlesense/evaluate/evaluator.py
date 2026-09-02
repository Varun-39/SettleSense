"""Ground-truth evaluation. This is the ONLY module that reads
data/ground_truth.csv — the engine never sees it at runtime.

A "false match" is deliberately strict: a result counts as one if it is
`matched` when the truth says it should not be, OR if it is matched to a
different settlement set than the truth records. Matching the right payment to
the wrong settlement is still a wrong answer.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from settlesense.contracts.enums import ResultStatus
from settlesense.evaluate.metrics import RunMetrics
from settlesense.recon.engine import RunOutput


@dataclass(frozen=True)
class TruthRow:
    payment_id: str
    expected_category: str
    expected_status: str
    expected_settlement_ids: tuple[str, ...]


def load_ground_truth(path: str | Path) -> dict[str, TruthRow]:
    truth: dict[str, TruthRow] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ids = row.get("expected_settlement_ids", "") or ""
            truth[row["payment_id"]] = TruthRow(
                payment_id=row["payment_id"],
                expected_category=row["expected_category"],
                expected_status=row["expected_status"],
                expected_settlement_ids=tuple(s for s in ids.split("|") if s),
            )
    return truth


def evaluate(output: RunOutput, truth: dict[str, TruthRow]) -> RunMetrics:
    correct = 0
    accepted = 0
    false_matches = 0
    known_exceptions = 0
    exceptions_caught = 0
    review = 0
    unresolved = 0
    unexplained = 0

    for result in output.results:
        expected = truth.get(result.payment_id)
        status = result.status

        if status is ResultStatus.REVIEW:
            review += 1
        elif status is ResultStatus.UNRESOLVED:
            unresolved += 1

        if status is not ResultStatus.MATCHED:
            unexplained += abs(int(result.difference_amount)) + int(result.pending_amount)

        if expected is None:
            # A result with no ground-truth row cannot be scored as correct.
            continue

        expected_is_exception = expected.expected_status != "matched"
        if expected_is_exception:
            known_exceptions += 1
            if status is not ResultStatus.MATCHED:
                exceptions_caught += 1

        if status is ResultStatus.MATCHED:
            accepted += 1
            claimed = tuple(sorted(c.settlement_id for c in result.settlements))
            expected_ids = tuple(sorted(expected.expected_settlement_ids))
            if expected_is_exception or claimed != expected_ids:
                false_matches += 1

        if status.value == expected.expected_status:
            correct += 1

    total = len(output.results)
    gross = sum(int(p.amount) for p in output.payments)
    settled = sum(int(r.settled_amount) for r in output.results)
    elapsed = output.elapsed_seconds or 1e-9

    return RunMetrics(
        records_processed=total,
        correct_verdicts=correct,
        match_rate=correct / total if total else 0.0,
        accepted_matches=accepted,
        false_matches=false_matches,
        match_precision=(accepted - false_matches) / accepted if accepted else 1.0,
        known_exceptions=known_exceptions,
        exceptions_caught=exceptions_caught,
        exception_recall=(
            exceptions_caught / known_exceptions if known_exceptions else 1.0
        ),
        review_count=review,
        unresolved_count=unresolved,
        exception_rate=(review + unresolved) / total if total else 0.0,
        gross_payments_paise=gross,
        settled_net_paise=settled,
        unexplained_paise=unexplained,
        amount_accuracy=1.0 - (unexplained / gross) if gross else 1.0,
        validation_errors=len(output.validation_errors),
        duplicates_collapsed=len(output.duplicate_row_hashes),
        throughput_records_per_second=total / elapsed,
        elapsed_seconds=output.elapsed_seconds,
    )
