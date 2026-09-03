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


def _reconciliation_id(run_id: str, payment: Payment, disambiguate: bool) -> str:
    """`payment_id` is not guaranteed unique within a batch, so it cannot be
    the whole identity. Conflicting rows get a content suffix; everything else
    keeps the readable form."""
    base = f"{run_id}:{payment.payment_id}"
    return f"{base}#{payment.row_hash[:8]}" if disambiguate else base


def _result(
    run_id: str,
    payment: Payment,
    candidate: Candidate | None,
    status: ResultStatus,
    reason: ReasonCode | None,
    claims: tuple[SettlementClaim, ...] = (),
    extra_evidence: tuple[RowRef, ...] = (),
    disambiguate: bool = False,
) -> ReconciliationResult:
    recon_id = _reconciliation_id(run_id, payment, disambiguate)
    if candidate is None:
        # `difference_amount` and `pending_amount` describe DIFFERENT money and
        # must never both carry the same rupees: difference is a discrepancy
        # against a settlement that exists, pending is money not settled at all.
        # Unexplained totals sum the two, so double-filling them double-counts.
        # Nothing settled here, so the whole amount is pending, not a difference.
        return ReconciliationResult(
            reconciliation_id=recon_id,
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

    if not claims:
        # A candidate that never claimed its settlements did not move money.
        # Copying its settled_amount would report cash that was never taken:
        # two payments contesting one settlement would each report it as
        # settled, and the run's settled total would exceed the settlements
        # that exist. The evidence and the trace are still worth showing —
        # they are what the reviewer has to adjudicate — but the figures
        # revert to "nothing settled, everything pending".
        return ReconciliationResult(
            reconciliation_id=recon_id,
            run_id=run_id,
            payment_id=payment.payment_id,
            match_type=candidate.match_type,
            match_score=candidate.score,
            expected_net=candidate.expected_net,
            actual_net=None,
            difference_amount=Paise(0),
            status=status,
            reason_code=reason,
            settled_amount=Paise(0),
            # The whole collection is outstanding, not the figure net of
            # fees. No settlement was claimed, so no fee was actually
            # deducted — netting them off here would report money as gone
            # that nobody took, and leave the run unable to balance.
            # This matches the no-candidate branch above.
            pending_amount=payment.amount,
            settlements=(),
            trace=candidate.trace,
            evidence=candidate.evidence + extra_evidence,
        )

    return ReconciliationResult(
        reconciliation_id=recon_id,
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

    # `payment_id` is not unique by construction — dedup collapses identical
    # rows, but two rows sharing an id and differing in content survive it.
    # Those are conflicting source records: neither may claim a settlement
    # (both would report the same money as theirs), and both must survive to
    # be looked at rather than one silently overwriting the other.
    rows_by_id: dict[str, list[Payment]] = {}
    for p in payments:
        rows_by_id.setdefault(p.payment_id, []).append(p)
    conflicted = {pid for pid, rows in rows_by_id.items() if len(rows) > 1}

    if conflicted:
        candidates = [c for c in candidates if c.payment_id not in conflicted]

    # `settlement_id` is not unique either. A provider's id can name a whole
    # payout batch, so two rows sharing one are conflicting records rather
    # than two settlements — and a rule collecting both would hand the
    # resolver the same row twice, which the claim ledger rejects outright.
    rows_by_settlement: dict[str, list] = {}
    for s in ctx.settlements:
        rows_by_settlement.setdefault(s.settlement_id, []).append(s)
    contested_settlements = {
        sid for sid, rows in rows_by_settlement.items() if len(rows) > 1
    }

    blocked: set[str] = set()
    if contested_settlements:
        def touches_contested(candidate: Candidate) -> bool:
            return any(sid in contested_settlements for sid in candidate.settlement_ids)

        blocked = {c.payment_id for c in candidates if touches_contested(c)}
        candidates = [c for c in candidates if not touches_contested(c)]

    ambiguity = detect_ambiguity(candidates, epsilon)

    by_payment: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_payment.setdefault(c.payment_id, []).append(c)

    # Keyed by row_hash: unique even when payment_id is not.
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
            results[payment.row_hash] = _result(
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
        payment = next(p for p in payments if p.payment_id == candidate.payment_id)
        if payment.row_hash in results:
            continue  # this payment already resolved
        if not ledger.can_claim(candidate.settlement_ids):
            continue  # demoted: its settlements went to stronger evidence
        ledger.claim(candidate.settlement_ids, candidate.payment_id)

        # Matching requires having actually taken a settlement. A candidate
        # that claims nothing can still show a zero difference — a payment
        # fully refunded against an unsettled settlement nets to zero — and
        # calling that "matched" reports money as reconciled when none moved.
        # That is a false match, which is the one outcome this engine exists
        # to avoid.
        settled_clean = (
            bool(candidate.settlement_ids)
            and candidate.difference == 0
            and candidate.pending_amount == 0
        )
        status = ResultStatus.MATCHED if settled_clean else ResultStatus.REVIEW
        reason = candidate.reason_hint if not settled_clean else None

        results[payment.row_hash] = _result(
            run_id,
            payment,
            candidate,
            status,
            reason,
            claims=ledger.claims_for(candidate.settlement_ids),
        )

    # Conflicting source records: preserved, cited against each other, and
    # never matched. Reporting either as settled would double-count the one
    # settlement between them.
    for payment_id in conflicted:
        peers = rows_by_id[payment_id]
        refs = tuple(payment_ref(p) for p in peers)
        for payment in peers:
            results[payment.row_hash] = _result(
                run_id,
                payment,
                None,
                ResultStatus.UNRESOLVED,
                ReasonCode.DUPLICATE_RECORD,
                extra_evidence=tuple(r for r in refs if r != payment_ref(payment)),
                disambiguate=True,
            )

    # R6 — no candidate survived. Never force a match.
    for payment in payments:
        if payment.row_hash in results:
            continue
        if payment.payment_id in blocked:
            # Its settlement exists but is duplicated in the source, so it
            # cannot be claimed without deciding which row is real.
            reason = ReasonCode.DUPLICATE_RECORD
        elif by_payment.get(payment.payment_id):
            reason = ReasonCode.INSUFFICIENT_EVIDENCE
        else:
            reason = ReasonCode.MISSING_SETTLEMENT
        results[payment.row_hash] = _result(
            run_id, payment, None, ResultStatus.UNRESOLVED, reason
        )

    return [results[p.row_hash] for p in payments]
