"""Converting real Razorpay exports into the canonical batch files.

The two risks worth testing are both silent: an unrecognised row type
disappearing (which would break the control-total proof without any error),
and the amount unit being guessed wrong (a 100x error that still looks like a
plausible figure).
"""
from __future__ import annotations

import pytest

from settlesense.ingest.razorpay import (
    convert_payments,
    convert_recon,
)

# Shaped after the settlement recon response in razorpay/razorpay-node:
# one file, several entity kinds, amounts in integer paise.
RECON_ROWS = [
    {
        "entity_id": "pay_MK1", "type": "payment", "debit": "0", "credit": "97000",
        "amount": "100000", "currency": "INR", "fee": "2500", "tax": "500",
        "on_hold": "false", "settled": "true",
        "created_at": "2026-08-01T10:00:00Z", "settled_at": "2026-08-03T10:00:00Z",
        "settlement_id": "setl_MK9", "payment_id": "pay_MK1", "order_id": "order_MK1",
    },
    {
        "entity_id": "rfnd_MK2", "type": "refund", "debit": "20000", "credit": "0",
        "amount": "20000", "currency": "INR", "fee": "0", "tax": "0",
        "on_hold": "false", "settled": "true",
        "created_at": "2026-08-02T11:00:00Z", "settled_at": "2026-08-03T10:00:00Z",
        "settlement_id": "setl_MK9", "payment_id": "pay_MK1", "order_id": "order_MK1",
    },
    {
        "entity_id": "adj_MK3", "type": "adjustment", "debit": "5000", "credit": "0",
        "amount": "5000", "currency": "INR", "fee": "0", "tax": "0",
        "on_hold": "false", "settled": "true",
        "created_at": "2026-08-02T12:00:00Z", "settled_at": "2026-08-03T10:00:00Z",
        "settlement_id": "setl_MK9", "payment_id": "", "order_id": "",
    },
]


def test_splits_a_single_recon_file_by_entity_type() -> None:
    out = convert_recon(RECON_ROWS, unit="paise")
    assert len(out.settlements) == 1
    assert len(out.refunds) == 1


def test_an_adjustment_is_reported_not_dropped() -> None:
    """An adjustment moves money. Discarding it silently would leave the
    control-total proof unable to balance while the run looked clean."""
    out = convert_recon(RECON_ROWS, unit="paise")
    assert len(out.unmapped) == 1
    assert out.unmapped[0]["type"] == "adjustment"
    assert "UNMAPPED" in out.report()
    assert "adjustment: 1" in out.report()


def test_paise_from_the_api_become_rupee_strings() -> None:
    [settlement] = convert_recon(RECON_ROWS, unit="paise").settlements
    assert settlement["gross_amount"] == "1000.00"
    assert settlement["fee"] == "25.00"
    assert settlement["tax"] == "5.00"
    assert settlement["net_amount"] == "970.00"


def test_rupees_from_a_dashboard_export_pass_through() -> None:
    rows = [dict(RECON_ROWS[0], amount="1000.00", credit="970.00", fee="25.00", tax="5.00")]
    [settlement] = convert_recon(rows, unit="rupees").settlements
    assert settlement["gross_amount"] == "1000.00"
    assert settlement["net_amount"] == "970.00"


def test_the_unit_is_never_guessed() -> None:
    """The same row read as paise and as rupees differs by 100x, so the caller
    has to say which it is."""
    as_paise = convert_recon(RECON_ROWS, unit="paise").settlements[0]
    as_rupees = convert_recon(RECON_ROWS, unit="rupees").settlements[0]
    assert as_paise["gross_amount"] == "1000.00"
    assert as_rupees["gross_amount"] == "100000.00"


def test_net_amount_comes_from_credit_not_from_arithmetic() -> None:
    """`credit` is what actually reached the bank. Recomputing it as
    amount - fee - tax would hide a discrepancy the report is telling us
    about."""
    rows = [dict(RECON_ROWS[0], credit="96000")]  # deliberately not 100000-2500-500
    [settlement] = convert_recon(rows, unit="paise").settlements
    assert settlement["net_amount"] == "960.00"


@pytest.mark.parametrize(
    "settled,on_hold,expected",
    [("true", "false", "processed"), ("false", "true", "pending"), ("false", "false", "pending")],
)
def test_status_follows_the_settled_and_on_hold_flags(settled, on_hold, expected) -> None:
    rows = [dict(RECON_ROWS[0], settled=settled, on_hold=on_hold)]
    assert convert_recon(rows, unit="paise").settlements[0]["status"] == expected


def test_column_aliases_are_accepted() -> None:
    """Dashboard CSV headings have been seen to differ from API field names."""
    rows = [
        {
            "entity_type": "payment", "id": "pay_A", "payment_id": "pay_A",
            "order_id": "order_A", "gross_amount": "50000", "net_amount": "48000",
            "fees": "1800", "tax": "200", "settled": "true",
            "settled_at": "2026-08-03T10:00:00Z", "settlement_id": "setl_A",
        }
    ]
    [s] = convert_recon(rows, unit="paise").settlements
    assert s["payment_id"] == "pay_A"
    assert s["gross_amount"] == "500.00"
    assert s["fee"] == "18.00"


def test_payments_export_maps_to_the_canonical_shape() -> None:
    rows = [
        {
            "id": "pay_MK1", "order_id": "order_MK1", "amount": "100000",
            "currency": "INR", "status": "captured",
            "created_at": "2026-08-01T10:00:00Z", "customer_id": "cust_1",
        }
    ]
    [payment] = convert_payments(rows, unit="paise")
    assert payment["payment_id"] == "pay_MK1"
    assert payment["amount"] == "1000.00"
    assert payment["currency"] == "INR"


def test_converted_rows_survive_the_engine_validator() -> None:
    """The whole point: what comes out of here has to be readable downstream."""
    from settlesense.validate.rules import validate_payment, validate_settlement

    [settlement] = convert_recon(RECON_ROWS, unit="paise").settlements
    model, err = validate_settlement({**settlement, "__source_line__": 2}, "s.csv")
    assert err is None, err
    assert model.net_amount == 97_000

    [payment] = convert_payments(
        [{"id": "pay_MK1", "order_id": "o1", "amount": "100000", "currency": "INR",
          "status": "captured", "created_at": "2026-08-01T10:00:00Z"}],
        unit="paise",
    )
    model, err = validate_payment({**payment, "__source_line__": 2}, "p.csv", ["INR"])
    assert err is None, err
    assert model.amount == 100_000


def test_one_payout_batch_does_not_collapse_its_settlement_rows() -> None:
    """A Razorpay settlement_id names a payout batch that many payments share.
    Using it as the row's identity made the second row overwrite the first, so
    only one payment could ever claim the batch and the other fell through to
    unresolved."""
    rows = [
        dict(RECON_ROWS[0], entity_id="pay_A", payment_id="pay_A", settlement_id="setl_BATCH"),
        dict(RECON_ROWS[0], entity_id="pay_B", payment_id="pay_B", settlement_id="setl_BATCH"),
    ]
    out = convert_recon(rows, unit="paise")

    ids = [s["settlement_id"] for s in out.settlements]
    assert len(set(ids)) == 2, "two payout lines collapsed onto one identity"
    # The batch is still recorded — "these all failed in the same payout" is
    # exactly the grouping a controller wants.
    assert {s["settlement_batch_id"] for s in out.settlements} == {"setl_BATCH"}


def test_both_payments_in_one_payout_can_be_matched() -> None:
    """End to end: the collapse used to leave one payment unresolved."""
    from settlesense.contracts.config import MatchingConfig
    from settlesense.recon.index import MatchContext
    from settlesense.recon.resolver import resolve
    from settlesense.recon.rules.r1_exact_id import r1_exact_id
    from settlesense.validate.rules import validate_payment, validate_settlement

    rows = [
        dict(RECON_ROWS[0], entity_id="pay_A", payment_id="pay_A",
             settlement_id="setl_BATCH", amount="100000", credit="97000"),
        dict(RECON_ROWS[0], entity_id="pay_B", payment_id="pay_B",
             settlement_id="setl_BATCH", amount="50000", credit="48500",
             fee="1250", tax="250"),
    ]
    settlements = []
    for raw in convert_recon(rows, unit="paise").settlements:
        model, err = validate_settlement({**raw, "__source_line__": 2}, "s.csv")
        assert err is None, err
        settlements.append(model)

    payments = []
    for pid, amount in (("pay_A", "1000.00"), ("pay_B", "500.00")):
        model, err = validate_payment(
            {
                "payment_id": pid, "order_id": f"order_{pid}", "amount": amount,
                "currency": "INR", "status": "captured",
                "captured_at": "2026-08-01T10:00:00Z", "__source_line__": 2,
            },
            "p.csv",
            ["INR"],
        )
        assert err is None, err
        payments.append(model)

    ctx = MatchContext(
        config=MatchingConfig(tolerance_paise=100, settlement_window_days=2, score_epsilon=0.01),
        payments=payments, settlements=settlements, refunds=[], ledger=[],
    )
    candidates = [c for p in payments for c in r1_exact_id(p, ctx)]
    results = resolve("run_x", payments, candidates, ctx)

    assert [r.status.value for r in results] == ["matched", "matched"], (
        "a shared payout batch starved one of its own payments"
    )
