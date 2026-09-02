"""Metric shapes. See architecture.md §8 — the false-match count is the
headline and is displayed even when it is zero."""
from __future__ import annotations

from pydantic import BaseModel


class RunMetrics(BaseModel):
    records_processed: int
    correct_verdicts: int
    match_rate: float

    accepted_matches: int
    false_matches: int
    match_precision: float

    known_exceptions: int
    exceptions_caught: int
    exception_recall: float

    review_count: int
    unresolved_count: int
    exception_rate: float

    gross_payments_paise: int
    settled_net_paise: int
    unexplained_paise: int
    amount_accuracy: float

    validation_errors: int
    duplicates_collapsed: int

    throughput_records_per_second: float
    elapsed_seconds: float

    def as_rows(self) -> list[tuple[str, str]]:
        """Terminal/report rendering — order matters, false matches sit high."""
        return [
            ("Records processed", str(self.records_processed)),
            ("Correct verdicts", str(self.correct_verdicts)),
            ("Match rate", f"{self.match_rate:.1%}"),
            ("False matches", str(self.false_matches)),
            ("Match precision", f"{self.match_precision:.1%}"),
            ("Exception recall", f"{self.exception_recall:.1%}"),
            ("Needs review", str(self.review_count)),
            ("Unresolved", str(self.unresolved_count)),
            ("Exception rate", f"{self.exception_rate:.1%}"),
            ("Unexplained amount", f"{self.unexplained_paise / 100:,.2f}"),
            ("Amount accuracy", f"{self.amount_accuracy:.2%}"),
            ("Validation errors", str(self.validation_errors)),
            ("Duplicates collapsed", str(self.duplicates_collapsed)),
            ("Throughput", f"{self.throughput_records_per_second:,.0f} rec/s"),
        ]
