"""SettleSense CLI — the deterministic engine end to end.

    settlesense run                     # reconcile data/, print control totals
    settlesense run --evaluate          # also score against ground truth
    settlesense run --data-dir demo/failure-fixtures/duplicate-batch

No AI in this path at all (ADR-001): reconciliation, metrics and the exception
queue are produced with the network cable unplugged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from settlesense.contracts.config import load_config
from settlesense.contracts.enums import ResultStatus
from settlesense.contracts.money import format_inr
from settlesense.evaluate.evaluator import evaluate, load_ground_truth
from settlesense.ingest.batch import load_batch
from settlesense.ledger.crosscheck import crosscheck
from settlesense.recon.engine import RunOutput, run as run_engine
from settlesense.store.repository import Repository


def _print_table(title: str, rows: list[tuple[str, str]]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    width = max((len(k) for k, _ in rows), default=0)
    for key, value in rows:
        print(f"  {key.ljust(width)}   {value}")


def _control_totals(output: RunOutput) -> list[tuple[str, str]]:
    matched = sum(1 for r in output.results if r.status is ResultStatus.MATCHED)
    review = sum(1 for r in output.results if r.status is ResultStatus.REVIEW)
    unresolved = sum(1 for r in output.results if r.status is ResultStatus.UNRESOLVED)
    gross = sum(int(p.amount) for p in output.payments)
    settled = sum(int(r.settled_amount) for r in output.results)
    unexplained = sum(
        abs(int(r.difference_amount)) + int(r.pending_amount)
        for r in output.results
        if r.status is not ResultStatus.MATCHED
    )
    return [
        ("Records processed", str(output.record_count)),
        ("Matched", str(matched)),
        ("Needs review", str(review)),
        ("Unresolved", str(unresolved)),
        ("Gross payments", format_inr(gross)),
        ("Settled net amount", format_inr(settled)),
        ("Unexplained amount", format_inr(unexplained)),
        ("Validation errors", str(len(output.validation_errors))),
        ("Duplicates collapsed", str(len(output.duplicate_row_hashes))),
        ("Elapsed", f"{output.elapsed_seconds * 1000:.0f} ms"),
    ]


def _exception_rows(output: RunOutput) -> list[tuple[str, str]]:
    counts: dict[str, int] = {}
    for r in output.results:
        if r.status is ResultStatus.MATCHED:
            continue
        key = r.reason_code.value if r.reason_code else "unclassified"
        counts[key] = counts.get(key, 0) + 1
    return [(k, str(v)) for k, v in sorted(counts.items())]


def _convert(args) -> int:
    """Razorpay exports in, a canonical four-file batch out."""
    import shutil

    from settlesense.ingest import razorpay as rz

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    recon = rz.convert_recon(rz.read_csv(args.recon), unit=args.unit)
    payments = rz.convert_payments(rz.read_csv(args.payments), unit=args.unit)

    rz.write_csv(out_dir / "sample_payments.csv", payments, rz.PAYMENT_HEADERS)
    rz.write_csv(out_dir / "sample_settlements.csv", recon.settlements, rz.SETTLEMENT_HEADERS)
    rz.write_csv(out_dir / "sample_refunds.csv", recon.refunds, rz.REFUND_HEADERS)

    if args.ledger:
        shutil.copyfile(args.ledger, out_dir / "sample_ledger.csv")
    else:
        # An empty ledger is honest: the third leg simply was not supplied.
        rz.write_csv(
            out_dir / "sample_ledger.csv",
            [],
            ["ledger_entry_id", "order_id", "debit", "credit", "posted_at", "description"],
        )

    _print_table(
        "Converted",
        [
            ("payments", str(len(payments))),
            ("settlements", str(len(recon.settlements))),
            ("refunds", str(len(recon.refunds))),
            ("unmapped rows", str(len(recon.unmapped))),
        ],
    )

    if recon.unmapped:
        print(
            "\n  Rows this adapter does not understand were NOT written."
            " They move money, so the batch will not balance until they"
            " are handled:"
        )
        from collections import Counter

        for kind, n in Counter(
            (r.get("type") or r.get("entity_type") or "?") for r in recon.unmapped
        ).most_common():
            print(f"    {kind}: {n}")
        print("\n  Reconciling this batch is not safe yet.")
        return 2

    print(f"\nwrote {out_dir}/  — reconcile it with --data-dir {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="settlesense")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="reconcile a batch")
    run_cmd.add_argument("--data-dir", default="data")
    run_cmd.add_argument("--config", default="recon.config.yaml")
    run_cmd.add_argument("--db", default="settlesense.db")
    run_cmd.add_argument("--evaluate", action="store_true", help="score vs ground truth")
    run_cmd.add_argument("--no-store", action="store_true", help="skip persistence")
    run_cmd.add_argument(
        "--ai",
        action="store_true",
        help="generate explanations after reconciling (never changes a figure)",
    )
    run_cmd.add_argument(
        "--no-ai",
        action="store_true",
        help="explicitly disable the AI sidecar (the failure-demo path)",
    )

    conv = sub.add_parser(
        "convert", help="turn Razorpay exports into a canonical batch"
    )
    conv.add_argument("--recon", required=True, help="settlement recon export")
    conv.add_argument("--payments", required=True, help="payments export")
    conv.add_argument("--ledger", help="your accounting export (copied as-is)")
    conv.add_argument("--out", default="data/real", help="directory to write")
    conv.add_argument(
        "--unit",
        required=True,
        choices=["paise", "rupees"],
        help="API dumps are paise; dashboard CSVs are rupees. Guessing is a 100x error.",
    )

    args = parser.parse_args(argv)
    if args.command == "convert":
        return _convert(args)

    data_dir = Path(args.data_dir)
    config = load_config(args.config)

    batch = load_batch(
        data_dir / "sample_payments.csv",
        data_dir / "sample_settlements.csv",
        data_dir / "sample_refunds.csv",
        data_dir / "sample_ledger.csv",
    )
    output = run_engine(batch, config)
    findings = crosscheck(output.payments, output.ledger)

    print(f"Batch {batch.id[:12]}   run {output.run_id}")
    _print_table("Control totals", _control_totals(output))

    exceptions = _exception_rows(output)
    if exceptions:
        _print_table("Exceptions by reason", exceptions)

    if findings:
        _print_table(
            "Ledger findings",
            [(f.reason.value, f.detail) for f in findings[:10]],
        )
        if len(findings) > 10:
            print(f"  ... {len(findings) - 10} more")

    metrics = None
    truth_path = data_dir / "ground_truth.csv"
    if args.evaluate:
        if not truth_path.exists():
            print(f"\nno ground truth at {truth_path}", file=sys.stderr)
            return 1
        metrics = evaluate(output, load_ground_truth(truth_path))
        _print_table("Benchmark", metrics.as_rows())
        if metrics.false_matches:
            print(f"\n  FALSE MATCHES: {metrics.false_matches}", file=sys.stderr)

    if not args.no_store:
        with Repository(args.db) as repo:
            repo.save_run(
                output,
                config_json=config.model_dump_json(),
                findings=findings,
                metrics=metrics,
            )

            # The AI sidecar runs only after results and metrics are persisted
            # (ADR-001). Every figure printed above this line is already final.
            if args.ai and not args.no_ai:
                from settlesense.ai.client import AIClient
                from settlesense.ai.explain import explain_run

                client = AIClient(config.ai)
                report = explain_run(output.run_id, repo, client)
                _print_table(
                    "Explanations",
                    [
                        ("AI explanations", str(report.from_ai)),
                        ("Template fallbacks", str(report.from_template)),
                        ("Served from cache", str(report.from_cache)),
                        ("Rejected by grounding", str(report.rejected_by_grounding)),
                        ("Evidence coverage", f"{report.evidence_coverage:.0%}"),
                        (
                            "AI available",
                            "yes"
                            if report.ai_available
                            else f"no ({report.unavailable_reason})",
                        ),
                    ],
                )
                if not report.ai_available:
                    print(
                        "\n  Explanations fell back to deterministic templates. "
                        "Every figure above is unchanged (ADR-001)."
                    )

        print(f"\nsaved to {args.db}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
