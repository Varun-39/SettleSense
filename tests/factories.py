"""Model builders for tests. Fixtures live in conftest.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from settlesense.contracts.models import LedgerEntry, Payment, Refund, Settlement
from settlesense.contracts.refs import row_hash

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 8, 12, 10, 0, tzinfo=IST)


def rupees(amount: float | int) -> int:
    """Test-readability helper: rupees(1000) -> 100_000 paise."""
    return int(round(amount * 100))


def make_payment(
    payment_id: str = "pay_1",
    order_id: str | None = "order_1",
    amount: int = rupees(1000),
    captured_at: datetime = T0,
    status: str = "captured",
) -> Payment:
    core = dict(
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        currency="INR",
        status=status,
        captured_at=captured_at,
        customer_id="cust_1",
    )
    return Payment(row_hash=row_hash(core), **core)


def make_settlement(
    settlement_id: str = "setl_1",
    payment_id: str | None = "pay_1",
    order_id: str | None = None,
    gross: int = rupees(1000),
    fee: int = 0,
    tax: int = 0,
    net: int | None = None,
    settled_at: datetime | None = None,
    status: str = "processed",
) -> Settlement:
    core = dict(
        settlement_id=settlement_id,
        payment_id=payment_id,
        order_id=order_id,
        gross_amount=gross,
        fee=fee,
        tax=tax,
        net_amount=gross - fee - tax if net is None else net,
        settled_at=settled_at or (T0 + timedelta(days=1)),
        status=status,
    )
    return Settlement(row_hash=row_hash(core), **core)


def make_refund(
    refund_id: str = "rfnd_1",
    payment_id: str = "pay_1",
    amount: int = rupees(200),
    status: str = "processed",
) -> Refund:
    core = dict(
        refund_id=refund_id,
        payment_id=payment_id,
        refund_amount=amount,
        created_at=T0 + timedelta(hours=2),
        status=status,
    )
    return Refund(row_hash=row_hash(core), **core)


def make_ledger(
    ledger_entry_id: str = "led_1",
    order_id: str = "order_1",
    credit: int = rupees(1000),
    posted_at: datetime = T0,
    description: str = "Sale",
) -> LedgerEntry:
    core = dict(
        ledger_entry_id=ledger_entry_id,
        order_id=order_id,
        debit=0,
        credit=credit,
        posted_at=posted_at,
        description=description,
    )
    return LedgerEntry(row_hash=row_hash(core), **core)
