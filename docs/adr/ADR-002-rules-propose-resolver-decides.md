# ADR-002: Rules propose candidates; a single resolver decides

**Status:** Accepted
**Date:** 2026-09-02
**Deciders:** Project owner (solo build)

## Context

Six matching rules are required (exact payment ID, order ID, amount+time, refund-adjusted, partial/multi-row, unresolved). The obvious implementation is an ordered cascade where the first rule that fires wins and marks the payment matched.

That implementation has a specific, demonstrable defect. Given two payments of ₹1,000 captured the same day and exactly one settlement of ₹1,000, an amount+time rule matches whichever payment it visits first and reports success. The other payment reports "missing settlement". Both statements look plausible on screen, and one of them is a **false match** — the metric we lead the pitch with, and the one a reviewer can break in the first minute by duplicating a row in the CSV.

There are three related requirements the cascade cannot express:

- A settlement row is a finite resource: it can back one payment, or portions of several, never two full claims.
- Evidence strength is not the same as rule order. A later partial-settlement match on identifiers is stronger evidence than an earlier inferred amount+time match.
- "Two equally good explanations exist" must be a representable outcome, because that is precisely the case a human should adjudicate.

## Decision

Split proposal from decision.

**Rules are pure proposer functions.** `rule(payment, ctx) -> list[Candidate]`. No mutation, no I/O, no awareness of other rules or of what has already been matched. Each `Candidate` carries `rule`, `tier` (evidence strength: 1 identifier, 2 identifier+tolerance, 3 inferred), `score`, the settlement ids it wants, a `CalcTrace`, and `evidence` row refs.

**One resolver decides.** It collects all candidates across all payments, sorts by `(tier, score)`, and walks them claiming settlement rows into a `ClaimLedger` that tracks claimed paise per settlement row. Conflicts have explicit, honest outcomes:

| Situation | Outcome |
|---|---|
| Best candidate, settlements free, residual = 0 | `matched` |
| Two candidates for one payment, same tier, within `score_epsilon` | `review` / `ambiguous_candidates`, both cited as evidence |
| Candidate's settlements already claimed | demote and re-evaluate; if nothing remains → `unresolved` |
| Claim succeeds but `difference_amount != 0` | `review` (never `matched`) |
| Settlement partially consumed by several payments | `partial`, with `claimed_paise` per row and `pending_amount` |
| Nothing left to propose | `unresolved` / `insufficient_evidence` / `human_review` |

## Options Considered

### Option A: Ordered first-wins cascade

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | Free |
| Scalability | O(n) |
| Team familiarity | High |

**Pros:** fastest to write; easy to read for a single record.
**Cons:** permits double-claiming a settlement (false matches); rule order becomes correctness, so every new rule risks regressing existing behaviour; ambiguity is unrepresentable; the exception queue is "whatever fell through" rather than a considered output.

### Option B: Rules propose, resolver decides with a claim ledger (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — one extra concept (`Candidate`) and one arbitration pass |
| Cost | Free |
| Scalability | O(n log n) on candidates; ~100–1000 records is instant |
| Team familiarity | High |

**Pros:** double-claiming is impossible by construction; rules become independently unit-testable pure functions; rule order stops mattering so Day-2 rules cannot regress Day-1 ones; ambiguity is a first-class status; every verdict carries the trace that produced it.
**Cons:** one more layer to build and explain; the resolver becomes the highest-risk file in the repo and needs property tests.

### Option C: Global optimal assignment (min-cost bipartite matching / Hungarian)

| Dimension | Assessment |
|---|---|
| Complexity | High — cost-function design, library dependency, partial-settlement modelling |
| Cost | Free at this size |
| Scalability | O(n³) naive; fine at 10³, needs care beyond |
| Team familiarity | Low |

**Pros:** provably maximal matching; elegant.
**Cons:** the output is not explainable in audit terms — "why was this settlement paired with that payment?" answers with "it minimised total global cost", which no finance reviewer will accept. Partial and multi-row settlements need an awkward flow formulation. And a globally optimal pairing can silently *reassign* an identifier-exact match to satisfy the objective, which is a worse failure than an exception.

## Trade-off Analysis

Option C wins on match count. Option B wins on defensibility, and defensibility is the product.

The key insight is that a greedy tiered claim never produces a *wrong* pairing that a strong-evidence rule contradicts — it only ever produces *fewer* pairings than the optimum, and every shortfall lands in the review queue where a human sees it. The failure direction is asymmetric and points the safe way: Option B's errors are visible and cheap; Option A's and C's errors are invisible and expensive.

Cost of Option B over Option A is roughly half a day of implementation and one extra concept in the README. Given that it removes the single defect a judge is most likely to find by hand, that is the cheapest half day in the plan.

## Consequences

**Easier**
- Each rule is a pure function with a table-driven unit test.
- Adding a rule is additive; no reordering, no regression risk.
- Property tests become possible and meaningful: "no settlement row is claimed twice", "Σ claimed ≤ gross", "every `matched` has residual 0".
- The exception queue is a designed output with reason codes, not leftovers.

**Harder**
- The resolver is the most complex file in the codebase; it needs the most tests.
- Scores must be genuinely comparable across rules within a tier, so `score` needs a documented formula per rule rather than an arbitrary constant.
- More cases land in `review` than a first-wins cascade would report as matched. That number must be explained in the pitch as a feature, with the false-match count next to it as proof.

**To revisit**
- If review volume becomes the bottleneck, the fix is a better tie-break *rule* (deterministic, explainable), or min-cost flow restricted to a single tier, not a loosening of the conflict policy.

## Action Items

1. [ ] Define `Candidate`, `CalcTrace`, `RowRef` in `contracts/` before writing any rule.
2. [ ] Document the score formula for each of R1–R5 in the README; no magic constants.
3. [ ] Implement `ClaimLedger` with paise-level partial consumption.
4. [ ] Property tests: no double claim; Σ claimed ≤ gross; `matched` implies residual == 0.
5. [ ] Fixture: two identical payments, one settlement → assert exactly one `review`/`ambiguous_candidates` pair and zero false matches.
