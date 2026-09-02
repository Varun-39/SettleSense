"""Generates the controlled 100-record benchmark and its ground-truth file.

Deterministic by construction (no RNG): the same script always emits the same
bytes, so `batch_id` is stable and the golden test can assert exact metrics.

Case mix follows the build guide §5. Every payment gets a distinct amount
spaced far wider than the matching tolerance, so no two payments can be
confused by the amount+time rule — the benchmark measures the engine, not
coincidences in the fixture.

Usage:  python scripts/generate_benchmark.py
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
BASE = datetime(2026, 8, 3, 10, 0, tzinfo=IST)
OUT = Path(__file__).resolve().parent.parent / "data"

# category -> count (build guide §5)
MIX = [
    ("exact_match", 35),
    ("fee_difference", 15),
    ("refund_adjusted", 10),
    ("partial_settlement", 10),
    ("delayed_settlement", 10),
    ("missing_settlement", 8),
    ("duplicate_ledger", 5),
    ("amount_mismatch", 4),
    ("failed_settlement", 3),
]

FEE_BPS = 200  # 2.00% processing fee
TAX_BPS = 1800  # 18% GST on the fee


def rupees(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    whole, frac = divmod(abs(paise), 100)
    return f"{sign}{whole}.{frac:02d}"


def fee_for(amount_paise: int) -> tuple[int, int]:
    fee = amount_paise * FEE_BPS // 10_000
    tax = fee * TAX_BPS // 10_000
    return fee, tax


def main() -> None:
    payments: list[dict] = []
    settlements: list[dict] = []
    refunds: list[dict] = []
    ledger: list[dict] = []
    truth: list[dict] = []

    index = 0
    settlement_seq = 0

    for category, count in MIX:
        for _ in range(count):
            i = index
            index += 1
            pid = f"pay_{1000 + i}"
            oid = f"order_{1000 + i}"
            amount = 100_000 + i * 1_373  # distinct, >> tolerance apart
            captured = BASE + timedelta(hours=i)
            settled = captured + timedelta(days=1)

            expected_settlements: list[str] = []
            expected_status = "matched"

            payments.append(
                {
                    "payment_id": pid,
                    "order_id": oid,
                    "amount": rupees(amount),
                    "currency": "INR",
                    "status": "captured",
                    "captured_at": captured.isoformat(),
                    "customer_id": f"cust_{200 + (i % 40)}",
                }
            )
            ledger.append(
                {
                    "ledger_entry_id": f"led_{5000 + i}",
                    "order_id": oid,
                    "debit": "0.00",
                    "credit": rupees(amount),
                    "posted_at": captured.isoformat(),
                    "description": f"Sale {oid}",
                }
            )

            def add_settlement(
                *,
                payment_id: str | None,
                order_id: str | None,
                gross: int,
                fee: int,
                tax: int,
                net: int,
                when: datetime,
                status: str = "processed",
            ) -> str:
                nonlocal settlement_seq
                sid = f"setl_{9000 + settlement_seq}"
                settlement_seq += 1
                settlements.append(
                    {
                        "settlement_id": sid,
                        "payment_id": payment_id or "",
                        "order_id": order_id or "",
                        "gross_amount": rupees(gross),
                        "fee": rupees(fee),
                        "tax": rupees(tax),
                        "net_amount": rupees(net),
                        "settled_at": when.isoformat(),
                        "status": status,
                    }
                )
                return sid

            if category == "exact_match":
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=0, tax=0, net=amount, when=settled,
                )
                expected_settlements = [sid]

            elif category == "fee_difference":
                fee, tax = fee_for(amount)
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=fee, tax=tax,
                    net=amount - fee - tax, when=settled,
                )
                expected_settlements = [sid]

            elif category == "refund_adjusted":
                refund = amount // 5
                refunds.append(
                    {
                        "refund_id": f"rfnd_{7000 + i}",
                        "payment_id": pid,
                        "refund_amount": rupees(refund),
                        "created_at": (captured + timedelta(hours=6)).isoformat(),
                        "status": "processed",
                    }
                )
                fee, tax = fee_for(amount)
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=fee, tax=tax,
                    net=amount - refund - fee - tax, when=settled,
                )
                expected_settlements = [sid]

            elif category == "partial_settlement":
                fee, tax = fee_for(amount)
                expected_net = amount - fee - tax
                first = expected_net // 3
                sid1 = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount // 3, fee=fee, tax=tax, net=first, when=settled,
                )
                sid2 = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount - amount // 3, fee=0, tax=0,
                    net=expected_net - first, when=settled + timedelta(days=1),
                )
                expected_settlements = [sid1, sid2]

            elif category == "delayed_settlement":
                # No identifier at all, settled far outside the window ->
                # the amount+time rule must refuse it.
                add_settlement(
                    payment_id=None, order_id=None,
                    gross=amount, fee=0, tax=0, net=amount,
                    when=captured + timedelta(days=9),
                )
                expected_status = "unresolved"

            elif category == "missing_settlement":
                expected_status = "unresolved"

            elif category == "duplicate_ledger":
                ledger.append(
                    {
                        "ledger_entry_id": f"led_{6000 + i}",
                        "order_id": oid,
                        "debit": "0.00",
                        "credit": rupees(amount),
                        "posted_at": captured.isoformat(),
                        "description": f"Sale {oid} (duplicate import)",
                    }
                )
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=0, tax=0, net=amount, when=settled,
                )
                expected_settlements = [sid]

            elif category == "amount_mismatch":
                fee, tax = fee_for(amount)
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=fee, tax=tax,
                    net=amount - fee - tax - 5_000,  # Rs 50 unexplained
                    when=settled,
                )
                expected_settlements = [sid]
                expected_status = "review"

            elif category == "failed_settlement":
                sid = add_settlement(
                    payment_id=pid, order_id=oid,
                    gross=amount, fee=0, tax=0, net=amount,
                    when=settled, status="failed",
                )
                expected_settlements = [sid]
                expected_status = "review"

            truth.append(
                {
                    "payment_id": pid,
                    "expected_category": category,
                    "expected_status": expected_status,
                    "expected_settlement_ids": "|".join(expected_settlements),
                }
            )

    OUT.mkdir(parents=True, exist_ok=True)
    _write(OUT / "sample_payments.csv", payments)
    _write(OUT / "sample_settlements.csv", settlements)
    _write(OUT / "sample_refunds.csv", refunds)
    _write(OUT / "sample_ledger.csv", ledger)
    _write(OUT / "ground_truth.csv", truth)

    print(f"payments      {len(payments)}")
    print(f"settlements   {len(settlements)}")
    print(f"refunds       {len(refunds)}")
    print(f"ledger        {len(ledger)}")
    print(f"ground truth  {len(truth)}")


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
