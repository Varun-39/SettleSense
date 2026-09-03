"""Generated batches, built to collide.

Every defect this project has had was a collision: two payments sharing an id,
two payments contesting one settlement, many settlement rows sharing a payout
batch. Ids drawn from a large random space never collide, so a generator that
looks thorough would pass everything and find nothing.

So the pools here are deliberately tiny — a handful of ids, a handful of
amounts, a handful of timestamps. Duplicates, ties and contention are the
common case rather than the rare one, and the properties below have to hold
anyway.

The strongest property is the control-total proof: for any batch at all,
gross must decompose exactly into settled cash, fees, tax, refunds and what
remains unexplained. It is a checksum over the whole run, so it fails on
classes of error no single assertion was written to look for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from factories import T0, make_payment, make_refund, make_settlement
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from settlesense.contracts.config import MatchingConfig
from settlesense.contracts.enums import ResultStatus
from settlesense.evaluate.proof import prove
from settlesense.recon.index import MatchContext
from settlesense.recon.resolver import resolve
from settlesense.recon.rules.r1_exact_id import r1_exact_id
from settlesense.recon.rules.r2_order_id import r2_order_id
from settlesense.recon.rules.r3_amount_time import r3_amount_time
from settlesense.recon.rules.r4_refund_adjusted import r4_refund_adjusted
from settlesense.recon.rules.r5_partial import r5_partial

RULES = (r1_exact_id, r2_order_id, r3_amount_time, r4_refund_adjusted, r5_partial)

CONFIG = MatchingConfig(
    tolerance_paise=100, settlement_window_days=2, score_epsilon=0.01
)

# Small pools, so collisions are the common case.
PAYMENT_IDS = ["pay_1", "pay_2", "pay_3"]
ORDER_IDS = ["order_1", "order_2", None]
SETTLEMENT_IDS = ["setl_1", "setl_2", "setl_3"]

# Amounts clustered around the tolerance boundary (100 paise), where the
# accept/refuse decision actually lives.
AMOUNTS = [0, 1, 99, 100, 101, 100_000, 100_099, 100_100, 100_101, 200_000]

# Around the settlement window edge (2 days), including before capture.
OFFSETS = [-1, 0, 1, 2, 3, 9]

STATUSES = ["processed", "pending", "failed", "partial"]


@dataclass
class Batch:
    payments: list = field(default_factory=list)
    settlements: list = field(default_factory=list)
    refunds: list = field(default_factory=list)
    ledger: list = field(default_factory=list)
    results: list = field(default_factory=list)


@st.composite
def payments(draw) -> Any:
    return make_payment(
        payment_id=draw(st.sampled_from(PAYMENT_IDS)),
        order_id=draw(st.sampled_from(ORDER_IDS)),
        amount=draw(st.sampled_from(AMOUNTS)),
        captured_at=T0 + timedelta(hours=draw(st.integers(0, 48))),
    )


@st.composite
def settlements(draw) -> Any:
    gross = draw(st.sampled_from(AMOUNTS))
    fee = draw(st.sampled_from([0, 1, 100, 2_500]))
    tax = draw(st.sampled_from([0, 1, 450]))
    return make_settlement(
        settlement_id=draw(st.sampled_from(SETTLEMENT_IDS)),
        payment_id=draw(st.sampled_from([*PAYMENT_IDS, None])),
        order_id=draw(st.sampled_from(ORDER_IDS)),
        gross=gross,
        fee=fee,
        tax=tax,
        # Sometimes the arithmetic net, sometimes a figure that disagrees with
        # it — a provider reporting a net that does not follow is exactly the
        # discrepancy this engine exists to surface.
        net=draw(st.sampled_from([gross - fee - tax, gross, draw(st.sampled_from(AMOUNTS))])),
        settled_at=T0 + timedelta(days=draw(st.sampled_from(OFFSETS))),
        status=draw(st.sampled_from(STATUSES)),
    )


@st.composite
def refunds(draw) -> Any:
    return make_refund(
        refund_id=draw(st.sampled_from(["rfnd_1", "rfnd_2"])),
        payment_id=draw(st.sampled_from(PAYMENT_IDS)),
        # Refunds are allowed to exceed the payment: a provider can report it,
        # and the engine must not fall over or invent money.
        amount=draw(st.sampled_from(AMOUNTS)),
        status=draw(st.sampled_from(["processed", "created", "failed"])),
    )


@st.composite
def batches(draw) -> Batch:
    batch = Batch(
        payments=draw(st.lists(payments(), min_size=1, max_size=6)),
        settlements=draw(st.lists(settlements(), max_size=6)),
        refunds=draw(st.lists(refunds(), max_size=3)),
    )
    # Deduplicate exactly as the pipeline does, so the resolver sees what it
    # would really see: identical rows collapsed, conflicting ones kept.
    for name in ("payments", "settlements", "refunds"):
        seen: set[str] = set()
        kept = []
        for row in getattr(batch, name):
            if row.row_hash not in seen:
                seen.add(row.row_hash)
                kept.append(row)
        setattr(batch, name, kept)

    ctx = MatchContext(
        config=CONFIG,
        payments=batch.payments,
        settlements=batch.settlements,
        refunds=batch.refunds,
        ledger=[],
    )
    candidates = [c for p in batch.payments for rule in RULES for c in rule(p, ctx)]
    batch.results = resolve("run_fuzz", batch.payments, candidates, ctx)
    return batch


SETTINGS = settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


# -- the whole-run checksum -------------------------------------------------


@given(batches())
@SETTINGS
def test_every_rupee_is_accounted_for(batch: Batch) -> None:
    """gross = settled + fees + tax + refunds + unexplained, for any batch."""
    proof = prove(batch)
    assert proof.balances, (
        f"gross {proof.gross} != accounted {proof.accounted} "
        f"(difference {proof.difference}); settled={proof.settled} "
        f"fees={proof.fees} tax={proof.tax} refunds={proof.refunds} "
        f"unexplained={proof.unexplained}"
    )


# -- identity ---------------------------------------------------------------


@given(batches())
@SETTINGS
def test_every_payment_produces_exactly_one_result(batch: Batch) -> None:
    """The property that would have caught a payment being silently deleted."""
    assert len(batch.results) == len(batch.payments)


@given(batches())
@SETTINGS
def test_reconciliation_ids_are_unique(batch: Batch) -> None:
    """A collision here means a row is lost the moment it is persisted."""
    ids = [r.reconciliation_id for r in batch.results]
    assert len(ids) == len(set(ids))


# -- the claim ledger -------------------------------------------------------


@given(batches())
@SETTINGS
def test_no_settlement_row_is_claimed_twice(batch: Batch) -> None:
    claimed = [c.settlement_id for r in batch.results for c in r.settlements]
    assert len(claimed) == len(set(claimed))


@given(batches())
@SETTINGS
def test_no_settlement_is_over_claimed(batch: Batch) -> None:
    capacity = {s.settlement_id: int(s.net_amount) for s in batch.settlements}
    consumed: dict[str, int] = {}
    for result in batch.results:
        for claim in result.settlements:
            consumed[claim.settlement_id] = consumed.get(claim.settlement_id, 0) + int(
                claim.claimed_paise
            )
    for sid, total in consumed.items():
        assert total <= capacity[sid], f"{sid} over-claimed"


@given(batches())
@SETTINGS
def test_reported_settled_cash_equals_what_was_claimed(batch: Batch) -> None:
    """The exact relationship, rather than a bound. A result may only report
    the money on the rows it actually took — which is how a contested
    settlement came to be reported as settled by two payments at once."""
    for result in batch.results:
        claimed = sum(int(c.claimed_paise) for c in result.settlements)
        assert int(result.settled_amount) == claimed, (
            f"{result.payment_id} reports {result.settled_amount} settled "
            f"against {claimed} claimed"
        )


# -- verdicts ---------------------------------------------------------------


@given(batches())
@SETTINGS
def test_matched_implies_nothing_left_over(batch: Batch) -> None:
    for result in batch.results:
        if result.status is ResultStatus.MATCHED:
            assert result.difference_amount == 0
            assert result.pending_amount == 0


@given(batches())
@SETTINGS
def test_difference_and_pending_never_both_carry_money(batch: Batch) -> None:
    """They describe different money; filling both counts the same rupees
    twice in every unexplained total."""
    for result in batch.results:
        assert not (result.difference_amount != 0 and result.pending_amount != 0)


@given(batches())
@SETTINGS
def test_a_result_that_claimed_nothing_reports_nothing_settled(batch: Batch) -> None:
    for result in batch.results:
        if not result.settlements:
            assert result.settled_amount == 0


@given(batches())
@SETTINGS
def test_every_result_cites_its_own_payment(batch: Batch) -> None:
    """No conclusion without a citation, including the unresolved ones."""
    for result in batch.results:
        assert result.evidence
        cited = {ref.natural_id for ref in result.evidence if ref.table == "payments"}
        assert result.payment_id in cited


# -- determinism ------------------------------------------------------------


@given(batches())
@SETTINGS
def test_the_same_batch_resolves_the_same_way_twice(batch: Batch) -> None:
    ctx = MatchContext(
        config=CONFIG,
        payments=batch.payments,
        settlements=batch.settlements,
        refunds=batch.refunds,
        ledger=[],
    )
    candidates = [c for p in batch.payments for rule in RULES for c in rule(p, ctx)]
    again = resolve("run_fuzz", batch.payments, candidates, ctx)
    assert [r.model_dump_json() for r in again] == [
        r.model_dump_json() for r in batch.results
    ]
