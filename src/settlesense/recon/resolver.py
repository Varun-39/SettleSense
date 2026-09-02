"""The only component that decides. See docs/adr/ADR-002.

Rules propose candidates; this module arbitrates between them under two hard
constraints:

  1. A settlement row can be claimed once. Double-claiming is impossible by
     construction, not by test coverage.
  2. When two explanations are equally good, neither is chosen — the case goes
     to review with both cited. That is the guard against the false match a
     reviewer can produce by duplicating one CSV row.

Nothing here recomputes arithmetic; candidates carry their own figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from settlesense.contracts.enums import MatchType, ReasonCode, ResultStatus
from settlesense.contracts.models import (
    Candidate,
    Payment,
    ReconciliationResult,
    SettlementClaim,
)
from settlesense.contracts.money import Paise
from settlesense.contracts.refs import RowRef
from settlesense.recon.index import MatchContext
from settlesense.recon.rules.common import payment_ref


class ClaimLedger:
    """Tracks paise consumed per settlement row.

    Claims today are whole-row, but capacity is tracked in paise so splitting
    one settlement across several payments is an extension rather than a
    redesign.
    """

    def __init__(self, ctx: MatchContext) -> None:
        self._capacity: dict[str, int] = {
            s.settlement_id: int(s.net_amount) for s in ctx.settlements
        }
        self._claimed: dict[str, int] = {sid: 0 for sid in self._capacity}
        self._claimed_by: dict[str, str] = {}

    def available(self, settlement_id: str) -> bool:
        return self._claimed.get(settlement_id, 0) == 0

    def can_claim(self, settlement_ids: tuple[str, ...]) -> bool:
        return all(self.available(sid) for sid in settlement_ids)

    def claim(self, settlement_ids: tuple[str, ...], payment_id: str) -> None:
        for sid in settlement_ids:
            if not self.available(sid):
                raise RuntimeError(
                    f"invariant violated: {sid} already claimed by "
                    f"{self._claimed_by.get(sid)}"
                )
            self._claimed[sid] = self._capacity[sid]
            self._claimed_by[sid] = payment_id

    def claims_for(self, settlement_ids: tuple[str, ...]) -> tuple[SettlementClaim, ...]:
        return tuple(
            SettlementClaim(settlement_id=sid, claimed_paise=Paise(self._claimed[sid]))
            for sid in settlement_ids
        )

    def total_claimed(self) -> int:
        return sum(self._claimed.values())


@dataclass
class _Ambiguity:
    payment_ids: set[str] = field(default_factory=set)
    evidence: dict[str, list[Candidate]] = field(default_factory=dict)

    def mark(self, payment_id: str, contenders: list[Candidate]) -> None:
        self.payment_ids.add(payment_id)
        self.evidence.setdefault(payment_id, []).extend(contenders)


def _rank(candidate: Candidate) -> tuple[int, float, str]:
    """Deterministic ordering: strongest evidence tier first, then score,
    then id — so a run is byte-reproducible."""
    return (candidate.tier, -candidate.score, candidate.payment_id)


def _tied(a: Candidate, b: Candidate, epsilon: float) -> bool:
    return a.tier == b.tier and abs(a.score - b.score) < epsilon


def detect_ambiguity(
    candidates: list[Candidate], epsilon: float
) -> _Ambiguity:
    """Two independent ambiguity checks, both of which force `review`."""
    ambiguity = _Ambiguity()

    # (a) One payment, two equally good but *different* explanations.
    by_payment: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_payment.setdefault(c.payment_id, []).append(c)
    for payment_id, group in by_payment.items():
        ranked = sorted(group, key=_rank)
        if len(ranked) < 2:
            continue
        best, second = ranked[0], ranked[1]
        if best.settlement_ids != second.settlement_ids and _tied(best, second, epsilon):
            ambiguity.mark(payment_id, [best, second])

    # (b) Two payments contending for the same settlement row, equally well.
    # This is the ADR-002 scenario: two identical payments, one settlement.
    by_settlement: dict[str, list[Candidate]] = {}
    for c in candidates:
        for sid in c.settlement_ids:
            by_settlement.setdefault(sid, []).append(c)
    for sid, group in by_settlement.items():
        ranked = sorted(group, key=_rank)
        if len(ranked) < 2:
            continue
        best, second = ranked[0], ranked[1]
        if best.payment_id != second.payment_id and _tied(best, second, epsilon):
            ambiguity.mark(best.payment_id, [best, second])
            ambiguity.mark(second.payment_id, [best, second])

    return ambiguity


def _result(
    run_id: str,
    payment: Payment,
    candidate: Candidate | None,
    status: ResultStatus,
    reason: ReasonCode | None,
    claims: tuple[SettlementClaim, ...] = (),
    extra_evidence: tuple[RowRef, ...] = (),
) -> ReconciliationResult:
    if candidate is None:
        # `difference_amount` and `pending_amount` describe DIFFERENT money and
        # must never both carry the same rupees: difference is a discrepancy
        # against a settlement that exists, pending is money not settled at all.
        # Unexplained totals sum the two, so double-filling them double-counts.
        # Nothing settled here, so the whole amount is pending, not a difference.
        return ReconciliationResult(
            reconciliation_id=f"{run_id}:{payment.payment_id}",
            run_id=run_id,
            payment_id=payment.payment_id,
            match_type=MatchType.UNRESOLVED,
            match_score=0.0,
            expected_net=payment.amount,
            actual_net=None,
            difference_amount=Paise(0),
            status=status,
            reason_code=reason,
            settled_amount=Paise(0),
            pending_amount=payment.amount,
            settlements=(),
            trace=(),
            evidence=(payment_ref(payment),) + extra_evidence,
        )

    return ReconciliationResult(
        reconciliation_id=f"{run_id}:{payment.payment_id}",
        run_id=run_id,
        payment_id=payment.payment_id,
        match_type=candidate.match_type,
        match_score=candidate.score,
        expected_net=candidate.expected_net,
        actual_net=candidate.actual_net,
        difference_amount=candidate.difference,
        status=status,
        reason_code=reason,
        settled_amount=candidate.settled_amount,
        pending_amount=candidate.pending_amount,
        settlements=claims,
        trace=candidate.trace,
        evidence=candidate.evidence + extra_evidence,
    )


def resolve(
    run_id: str,
    payments: list[Payment],
    candidates: list[Candidate],
    ctx: MatchContext,
) -> list[ReconciliationResult]:
    epsilon = ctx.config.score_epsilon
    ledger = ClaimLedger(ctx)
    ambiguity = detect_ambiguity(candidates, epsilon)

    by_payment: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_payment.setdefault(c.payment_id, []).append(c)

    results: dict[str, ReconciliationResult] = {}

    # Ambiguous payments never claim: neither explanation gets to win.
    for payment in payments:
        if payment.payment_id in ambiguity.payment_ids:
            contenders = ambiguity.evidence[payment.payment_id]
            merged_evidence: tuple[RowRef, ...] = ()
            for c in contenders:
                for ref in c.evidence:
                    if ref not in merged_evidence:
                        merged_evidence += (ref,)
            best = sorted(contenders, key=_rank)[0]
            results[payment.payment_id] = _result(
                run_id,
                payment,
                best,
                ResultStatus.REVIEW,
                ReasonCode.AMBIGUOUS_CANDIDATES,
                claims=(),
                extra_evidence=tuple(
                    r for r in merged_evidence if r not in best.evidence
                ),
            )

    # Everything else competes for claims, strongest evidence first.
    ordered = sorted(
        (c for c in candidates if c.payment_id not in ambiguity.payment_ids), key=_rank
    )
    for candidate in ordered:
        if candidate.payment_id in results:
            continue  # this payment already resolved
        if not ledger.can_claim(candidate.settlement_ids):
            continue  # demoted: its settlements went to stronger evidence
        ledger.claim(candidate.settlement_ids, candidate.payment_id)

        settled_clean = candidate.difference == 0 and candidate.pending_amount == 0
        status = ResultStatus.MATCHED if settled_clean else ResultStatus.REVIEW
        reason = candidate.reason_hint if not settled_clean else None

        payment = next(p for p in payments if p.payment_id == candidate.payment_id)
        results[candidate.payment_id] = _result(
            run_id,
            payment,
            candidate,
            status,
            reason,
            claims=ledger.claims_for(candidate.settlement_ids),
        )

    # R6 — no candidate survived. Never force a match.
    for payment in payments:
        if payment.payment_id in results:
            continue
        had_candidates = bool(by_payment.get(payment.payment_id))
        reason = (
            ReasonCode.INSUFFICIENT_EVIDENCE
            if had_candidates
            else ReasonCode.MISSING_SETTLEMENT
        )
        results[payment.payment_id] = _result(
            run_id, payment, None, ResultStatus.UNRESOLVED, reason
        )

    return [results[p.payment_id] for p in payments]
