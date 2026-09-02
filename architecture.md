# SettleSense — Architecture

**Settlement Reconciliation Controller**
Evidence-first reconciliation of payments ↔ settlements ↔ refunds ↔ merchant ledger.

**Status:** Proposed (pre-implementation)
**Date:** 2026-09-02
**Stack:** Python 3.11 · FastAPI · SQLite · Pydantic v2 · React (Vite + Tailwind) · Claude API (`claude-opus-5`)

---

## 0. The one sentence the whole architecture serves

> **AI explains and prioritizes. Deterministic code calculates and controls.**

Every structural decision below is downstream of that sentence. If a design choice would let a model influence a rupee figure, a match/no-match verdict, or a total, the architecture forbids it structurally — not by prompt instruction.

Second-order goal, equally structural:

> **The system must be able to say "I do not know" and still be correct.**

An unresolved case is a *first-class output*, not an error path.

---

## 1. Constraints that shaped this design

| Constraint | Consequence |
|---|---|
| 4-day build, one developer | Single process, single language for the core, zero infra to provision. No Kafka, no Postgres, no Docker Compose, no queue. |
| Judge runs it from a fresh clone | Storage must be file-backed and self-creating. `pip install -e . && settlesense run` must work first try. |
| Batch of 100–1000 records, offline | No streaming, no partitioning, no horizontal scale. Whole batch fits in memory; throughput is a demo metric, not a bottleneck. |
| Money correctness is the product | Integer arithmetic only; every number traceable to a source row. |
| Demo must survive an AI outage on stage | AI must be architecturally removable at runtime, not just wrapped in a try/except. |
| Score is measured against ground truth | Results must be a persisted table joinable to `ground_truth.csv`, not screen state. |
| Reviewer will click into one exception | Evidence and calculation trace must be persisted per result, not recomputed or re-narrated. |

---

## 2. System overview

```
                    ┌───────────────────────────────────────────┐
   CSV / JSON  ────► │  1. INGEST      batch identity = content  │
   (4 files)         │                 hash → idempotent reruns  │
                     └───────────────────┬───────────────────────┘
                                         ▼
                     ┌───────────────────────────────────────────┐
                     │  2. VALIDATE    row-level; bad rows are   │──► validation_errors
                     │                 quarantined, never fatal  │    (its own exception class)
                     └───────────────────┬───────────────────────┘
                                         ▼
                     ┌───────────────────────────────────────────┐
                     │  3. NORMALIZE   paise ints, UTC, ID case  │
                     │  4. DEDUPE      content hash + near-dupe  │──► duplicate_flags
                     └───────────────────┬───────────────────────┘
                                         ▼
                     ┌───────────────────────────────────────────┐
                     │  5. INDEX       by payment_id, order_id,  │
                     │                 amount bucket, date bucket│
                     └───────────────────┬───────────────────────┘
                                         ▼
        ╔════════════════════════════════════════════════════════════════════╗
        ║  6. RULE CASCADE — rules PROPOSE candidates (pure functions)        ║
        ║     R1 exact_id · R2 order_id · R3 amount+time · R4 refund-adj      ║
        ║     R5 partial / multi-row · R6 unresolved                          ║
        ║                              │                                      ║
        ║  7. RESOLVER — the only component that DECIDES                      ║
        ║     one settlement row claimed once · conflicts → review            ║
        ║     emits: verdict + match_score + CalcTrace + EvidenceRefs         ║
        ╚════════════════════════════════════╤═══════════════════════════════╝
                                             ▼
                     ┌───────────────────────────────────────────┐
                     │  8. LEDGER CROSS-CHECK  (3rd leg)         │
                     │  9. PERSIST  reconciliation_results       │
                     │              + calc_steps + evidence_refs │
                     └───────────────────┬───────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
   ┌────────────────────┐   ┌──────────────────────┐   ┌────────────────────┐
   │ 10. EVALUATOR      │   │ 11. AI SIDECAR       │   │ 12. API (FastAPI)  │
   │ join ground_truth  │   │ (async, optional)    │   │ + React dashboard  │
   │ match rate,        │   │ explain · classify   │   │ 4 screens,         │
   │ FALSE MATCHES = 0  │   │ cluster · next action│   │ evidence drawer    │
   │ amount accuracy    │   │ → grounding gate     │   │                    │
   └────────────────────┘   └──────────────────────┘   └────────────────────┘
              │                          │                          ▲
              └──────────────────────────┴──────────────────────────┘
                     metrics and explanations are ADDITIVE columns;
                     neither can change a match verdict or a total.
```

The horizontal line in the middle matters more than the boxes: **everything above the AI sidecar runs with the network cable unplugged.** The sidecar writes to its own table behind a foreign key. Delete every row in `explanations` and the UI copy degrades while every number stays identical.

---

## 3. Component responsibilities

| # | Component | Responsibility | Must NOT |
|---|---|---|---|
| 1 | `ingest` | Read 4 files, compute `batch_id` from content, store raw bytes, create `run` | Mutate source data |
| 2 | `validate` | Per-row schema/type/range checks; emit `Rejected` records | Abort the batch |
| 3 | `normalize` | Paise ints, UTC timestamps, ID canonicalization, currency guard | Round or coerce silently |
| 4 | `dedupe` | Collapse exact duplicates; *flag* near-duplicates | Delete a near-duplicate |
| 5 | `index` | Build lookup structures for O(n) matching | Decide anything |
| 6 | `recon.rules` | Propose `Candidate(rule, tier, score, trace, evidence)` | Assign, mutate, or pick |
| 7 | `recon.resolver` | Arbitrate candidates, enforce single-claim, emit verdict | Touch the network |
| 8 | `ledger` | Third-leg cross-check, duplicate ledger detection | Alter payment↔settlement verdicts |
| 9 | `store` | Append-only persistence of runs, results, traces, evidence | Update prior runs in place |
| 10 | `evaluate` | Join ground truth → metrics, headline false-match count | Hide unresolved cases |
| 11 | `ai` | Explain, classify, cluster, recommend, answer Q&A | Produce or alter any number |
| 12 | `api` / `web` | Serve results and evidence | Recompute finance in the browser |

---

## 4. The core design decision: rules propose, the resolver decides

This is what separates a reconciliation engine from a `for` loop full of `if` statements.

**Naive design (rejected):** iterate payments, try R1, else R2, else R3… first hit wins, mark matched.

It breaks in three ways a finance reviewer will find in thirty seconds:

1. Two payments of ₹1,000 on the same day and one settlement of ₹1,000 — first-wins silently steals the settlement and produces a **false match**, the one metric we promise to keep at zero.
2. A rule that fires later (partial settlement) can be strictly stronger evidence than one that fired earlier (loose amount+time). Rule order becomes correctness, and correctness becomes fragile.
3. There is nowhere to record "two equally good explanations existed" — which is exactly the case a human should see.

**Chosen design.** Rules are pure proposers:

```python
# No I/O, no mutation, no ordering dependency. Trivially unit-testable.
def r3_amount_time(payment: Payment, ctx: MatchContext) -> list[Candidate]: ...

@dataclass(frozen=True)
class Candidate:
    rule: RuleId                  # R1..R5
    tier: int                     # evidence strength: 1 = identifier, 3 = inferred
    score: float                  # deterministic, derived only from rule inputs
    settlement_ids: tuple[str, ...]
    trace: CalcTrace              # ordered, replayable arithmetic
    evidence: tuple[RowRef, ...]
```

The **resolver** then runs a constrained assignment:

1. Collect all candidates for all payments.
2. Sort by `(tier, score)`. Tier-1 identifier evidence always beats tier-3 inference.
3. Walk in order, claiming settlement rows into a `ClaimLedger`. A settlement row is consumable **once**; a partial match consumes a *portion*, tracked in paise.
4. **Conflict rules — where honesty is enforced:**
   - Two candidates for the same payment, same tier, within `score_epsilon` → `status = review`, reason `ambiguous_candidates`, with *both* recorded as evidence.
   - A candidate whose settlements are already claimed → demoted and re-evaluated; if nothing remains → `unresolved`.
   - Any residual `difference_amount != 0` after a claim → `review`, never `matched`.
5. Everything unclaimed → `unresolved / insufficient_evidence / human_review` (R6).

Consequences:

- Double-claiming a settlement is **impossible by construction**, not by test coverage.
- Rule order stops being load-bearing, so Day-2 rules cannot regress Day-1 results.
- Ambiguity becomes *representable*. That is what makes the exception queue honest rather than a bucket of leftovers.

**What we gave up:** globally optimal assignment (min-cost bipartite matching / Hungarian). Greedy tiered claiming can, on adversarial data, land one match short of optimal. That is deliberate — an optimal solver's output is not explainable to a finance reviewer ("why this pairing?" → "global cost minimisation" is not an audit answer), and every case greedy cannot settle goes to review rather than being mis-matched. The cost is exception volume, never a false match. Upgrade path noted in §11.

---

## 5. Money, time, and identity

Three primitives that cause most real reconciliation bugs. Each gets its own module and its own test file.

**Money — integer paise, everywhere, no exceptions.**

```python
Paise = int   # NewType; ₹1,000.00 == 100_000
def parse_amount(raw: str) -> Paise:   # Decimal(str) → quantize(0.01) → int; never float()
```

`float` is banned inside `src/settlesense/` by a `no-float-money` lint check. `0.1 + 0.2 != 0.3` is not a philosophical curiosity when the output is a settlement variance report — it is the bug that makes a reviewer distrust every other number on the screen. Tolerances are paise too (`tolerance_paise: 100` = ₹1), so the value and its comparison share a unit.

**Time — store UTC, compare on the IST business calendar.**

A settlement window is a calendar concept (`T+2`), not a duration. `captured_at 23:50 IST` and `settled_at 00:10 IST two days later` is inside T+2 by business rules and outside it by naive 48-hour subtraction. The engine normalises to UTC for storage, evaluates windows on IST calendar dates, and records the timezone in the trace so the drawer can show the reasoning instead of asserting it.

**Identity — content-addressed rows.**

Every normalised row carries `row_hash = sha256(canonical_json(row))`, and evidence is `RowRef = (table, natural_id, row_hash)`. One primitive, four benefits: exact-duplicate detection, tamper-evident evidence references, a cache key for AI explanations, and idempotent reruns.

**Batch identity.** `batch_id = sha256(sorted(file_content_hashes))`. Re-uploading the same four files returns the existing run instead of double-counting — the "duplicate input batch" failure case is caught at the front door rather than by hunting repeated `payment_id`s later. That per-row check still exists one layer deeper, for *partially* overlapping batches, which is the harder and more realistic case.

---

## 6. Data and storage model

SQLite, one file (`settlesense.db`), schema created on first run.

```
runs(run_id PK, batch_id, engine_version, rules_version, config_json,
     started_at, finished_at, status)

payments / settlements / refunds / ledger_entries
     (row_hash PK, run_id FK, natural_id, ...typed columns..., raw_json,
      source_file, source_line, duplicate_of NULL)

validation_errors(id PK, run_id FK, source_file, source_line, field, reason, raw_row)

reconciliation_results(
     reconciliation_id PK, run_id FK, payment_id,
     match_type, match_score, expected_net, actual_net, difference_amount,
     status,          -- matched | review | unresolved
     reason_code,     -- fee_mismatch | timing | missing_settlement | ...
     settled_amount, pending_amount)

result_settlements(reconciliation_id FK, settlement_id, claimed_paise)   -- multi-row partials
calc_steps(reconciliation_id FK, seq, label, expression, inputs_json, result_paise)
evidence_refs(reconciliation_id FK, table_name, natural_id, row_hash, role)

explanations(reconciliation_id FK PK, source,      -- 'ai' | 'template'
     category, summary, recommended_action, needs_human_review,
     evidence_refs_json, model, prompt_version, grounded BOOL, created_at)

exception_clusters(cluster_id PK, run_id FK, label, rationale, member_ids_json)
review_actions(id PK, reconciliation_id FK, actor, action, note, created_at)
metrics(run_id FK, name, value, computed_at)
```

Four properties this buys:

- **Results are a table, not a screen.** The evaluator, the API, the Q&A layer and the CSV export all read the same rows. There is exactly one definition of "what matched".
- **The trace is data.** `calc_steps` holds the evidence drawer's arithmetic, written once at compute time. The UI renders it; nothing re-derives or re-narrates it. This is what makes "the ₹30 difference equals the recorded fee" *verifiable* rather than asserted.
- **Runs are append-only.** Nothing is updated in place, so the same batch can be re-run after a rule change and the two runs diffed — that diff is the regression test on Day 4.
- **Real SQL for Q&A.** The finance-question layer queries this schema through fixed parameterised tools. No vector store, no embedding drift, exact numbers.

**Why SQLite over Postgres:** zero provisioning, a single file a judge can open, in-process (no pool, no container), and entirely sufficient at 10³–10⁵ rows. The schema uses plain SQL types with no SQLite-only constructs, so moving to Postgres is a connection-string change if this ever runs multi-tenant. **Why not pandas/CSV:** the results table needs foreign keys, joins, and durability across runs; a DataFrame offers none of those and would push evidence storage into pickles.

---

## 7. The AI layer — where it sits and why it cannot hurt you

**Placement: sidecar — downstream, additive, cached.** The engine finishes, persists, and computes metrics *before* the first token is generated.

```python
class Explanation(BaseModel):           # structured-output contract
    category: Literal["fee_mismatch", "timing_difference", "missing_settlement",
                      "partial_settlement", "refund_adjusted", "duplicate_record",
                      "amount_mismatch", "failed_settlement", "insufficient_evidence"]
    summary: str
    evidence_refs: list[str]            # must be row ids present in the prompt context
    recommended_action: Literal["human_review", "wait_next_batch", "verify_refund",
                                "investigate_duplicate", "no_action"]
    needs_human_review: bool

resp = client.messages.parse(
    model="claude-opus-5",
    max_tokens=2000,
    output_format=Explanation,          # validated → resp.parsed_output
    system=[{"type": "text", "text": RULES_DOC,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": render_case(result, trace, rows)}],
)
```

Four gates make this safe:

1. **Input gate.** The prompt contains only the deterministic verdict, the `CalcTrace`, and the specific source rows already cited as evidence. No full batch, no browsing. `customer_id` is dropped before rendering — the model never needs it, and it is the only PII-shaped field in the schema.
2. **Schema gate.** Structured output with a closed `category` enum. An off-menu category is a parse failure, not a new bug class.
3. **Grounding gate — the important one.** Before an explanation is written to the DB:
   - every entry in `evidence_refs` must exist in the context that was sent, else reject;
   - every money token parsed out of `summary` must appear in `calc_steps` or in a referenced row, else reject;
   - `category` must be consistent with the deterministic `reason_code` family, else store with `grounded = false` and route to review.
   A rejected explanation falls back to a deterministic **template** explanation rendered from the trace, stored as `source = 'template'`. *Evidence coverage* in the metrics panel is measured on this gate — the number is earned, not claimed.
4. **Failure gate.** 8s timeout, one retry, circuit-breaker after three consecutive failures in a run. Outcome: "explanation unavailable — deterministic result stands". Totals, match rate and the exception queue are untouched. That is the Day-4 stage demo, and it works because of *placement*, not because of a try/except.

**Caching.** Explanation key = `sha256(prompt_version + trace_hash + sorted(row_hashes))`. Re-running the demo batch is free and instant — which matters when you are demoing live on venue wifi.

**Clustering and Q&A ride the same rails.** Clustering receives only exception summaries and returns group labels plus member IDs, which are validated against the actual ID set before display. Q&A gets a small set of parameterised query tools over the results schema rather than free-form SQL, so a question can never surface a number the engine did not compute.

**Model choice: `claude-opus-5` with adaptive thinking.** This is a low-volume path — roughly 10–40 calls per run, all cached — so the cost difference between model tiers is rounding error, while the failure mode we actually fear (a fluent, plausible, *wrong* explanation sitting next to a correct number) is exactly what reasoning quality buys down. Explanations for a cluster sharing one root cause are batched into a single call.

---

## 8. Evaluation is a component, not a script

`evaluate/` is a first-class module that joins `reconciliation_results` to `data/ground_truth.csv` and writes into `metrics`:

| Metric | Definition |
|---|---|
| Match rate | correct verdicts / eligible records |
| **False matches** | `matched` in results but not in truth — **headline, target 0** |
| Precision of accepted matches | correct accepted / all accepted |
| Exception recall | truth-exceptions correctly routed to review or unresolved |
| Amount accuracy | 1 − (Σ\|unexplained\| / Σ processed) |
| Exception rate | (review + unresolved) / total |
| Throughput | records per second, engine only, labelled as excluding AI |
| Evidence coverage | grounded explanations / all explanations |

Ground truth lives in a file the engine never reads at runtime; the evaluator is its only importer. Metrics are persisted per run, so the UI shows *this run's* numbers and two runs can be compared after a rule change.

The false-match count is displayed even when it is zero. A reconciliation tool that reports only its wins is the thing finance teams already do not trust.

---

## 9. Interfaces

**API (FastAPI):**

```
POST /runs                            4 files (multipart) or {"fixture": "demo_100"} → run_id
                                      idempotent on batch_id
GET  /runs/{id}/summary               control totals: processed, matched, review, unresolved,
                                      gross, net, unexplained
GET  /runs/{id}/results               filters: status, match_type, reason_code, min_difference
GET  /runs/{id}/results/{rid}         evidence bundle: rows + calc_steps + explanation + cluster
GET  /runs/{id}/exceptions            grouped by reason_code and cluster
GET  /runs/{id}/metrics               benchmark panel
POST /runs/{id}/results/{rid}/review  {action: accept | reject | annotate, note}
POST /runs/{id}/ask                   finance Q&A scoped to this run
GET  /runs/{id}/export.csv            results + evidence refs
```

**UI (React + Vite + Tailwind) — four screens mirroring the API:**

1. **Control totals** — batch header; the six numbers a controller checks first.
2. **Results table** — payment, expected net, actual net, difference, match type, confidence, status, action. Filter chips by reason code.
3. **Evidence drawer** — the source rows, the `calc_steps` arithmetic rendered line by line, the explanation with its refs as links, and a visible `source: ai | template` badge.
4. **Benchmark** — metrics, exception-category breakdown, and a **Load failure fixture** button (duplicate batch · malformed rows · AI disabled).

The drawer is the product. It gets built before any chart does.

---

## 10. How each required failure case is handled *structurally*

| Failure | Where it is handled | Behaviour |
|---|---|---|
| Duplicate input batch | §5 `batch_id` content hash + per-row `row_hash` | Existing run returned; overlapping rows collapsed via `duplicate_of`; totals never double-count |
| Missing payment identifier | Rule cascade R2 → R3, resolver tiering | Falls back to `order_id`, then conservative amount+time; ambiguity → review, never a guess |
| AI service unavailable | §7 failure gate + sidecar placement | Deterministic results and all totals stand; explanation cell reads "unavailable" |
| Conflicting source records | Resolver conflict rules | Both records preserved and cited; `status = review`, reason `ambiguous_candidates` |
| Partial settlement | R5 + `result_settlements.claimed_paise` | Settled amount, pending amount, and every contributing row shown |
| Invalid amount or date | §3 row-level quarantine | Row rejected into `validation_errors` with file and line; batch continues; surfaces as its own exception class |

Each is a fixture in `demo/failure-fixtures/` and a row on the benchmark screen — the failure demo is a button, not a live edit.

---

## 11. Deliberate limitations (state these in the pitch)

- **Greedy tiered assignment, not globally optimal matching.** Traded for explainability; residue goes to review, so the cost is exception volume, never a false match. Min-cost flow is the upgrade path if precision-at-scale ever demands it.
- **Batch, not streaming.** Razorpay webhooks would arrive as events; ingest is *shaped* for them (content-hash identity, append-only runs) but the engine is invoked per batch.
- **Single currency (INR).** `currency` is validated and carried, but there is no FX logic — a multi-currency batch is rejected at validation rather than silently summed.
- **SQLite, single-tenant, no auth.** Correct for a demo. The schema is portable and the API is stateless, so multi-tenancy is an addition rather than a rewrite.
- **Synthetic data only.** No production Razorpay credentials; Test Mode webhooks are the next integration step.

---

## 12. Repository layout

```
architecture.md              this document
docs/adr/                    ADR-001 … ADR-005 (decisions, with rejected options)
recon.config.yaml            tolerance_paise, settlement_window_days, score_epsilon, model
data/
  sample_{payments,settlements,refunds,ledger}.csv
  ground_truth.csv
  failure_fixtures/
src/settlesense/
  contracts/      models.py enums.py money.py refs.py     # frozen Pydantic, Paise, RowRef
  ingest/         loader.py batch.py
  validate/       rules.py errors.py
  normalize/      amounts.py dates.py ids.py dedupe.py
  recon/          index.py candidate.py trace.py resolver.py engine.py
                  rules/r1_exact_id.py … r6_unresolved.py
  ledger/         crosscheck.py
  store/          schema.sql repository.py
  evaluate/       evaluator.py metrics.py
  ai/             client.py schemas.py explain.py cluster.py qa.py grounding.py cache.py
  api/            main.py routes/
web/              React + Vite + Tailwind (4 screens)
tests/
  unit/           money, dates, each rule in isolation
  golden/         100-record benchmark → asserted metrics (false_matches == 0)
  property/       "no settlement row is ever claimed twice"; "sum(claimed) ≤ gross"
  failure/        the six cases in §10
```

Build order follows the dependency arrows exactly: contracts → ingest/validate/normalize → rules → resolver → store → evaluate (**Day 1–2, with no AI in the repo at all**) → AI sidecar → API → web (Day 3) → failure fixtures and polish (Day 4). The AI layer is built last precisely because nothing depends on it — the same property that lets it fail on stage without consequence.

---

## 13. Decision index

| ADR | Decision | One-line rationale |
|---|---|---|
| [ADR-001](docs/adr/ADR-001-deterministic-core-ai-sidecar.md) | Deterministic core, AI as a sidecar | Makes "AI down" a cosmetic failure and keeps the metrics honest |
| [ADR-002](docs/adr/ADR-002-rules-propose-resolver-decides.md) | Rules propose, resolver decides | Makes double-claiming and forced matches structurally impossible |
| [ADR-003](docs/adr/ADR-003-storage-sqlite.md) | SQLite, results as a first-class table | Zero setup, real joins, one definition of "what matched" |
| [ADR-004](docs/adr/ADR-004-money-integer-paise.md) | Integer paise, no floats | Removes an entire class of silent correctness bugs |
| [ADR-005](docs/adr/ADR-005-grounded-structured-explanations.md) | Structured output behind a grounding gate | Turns "evidence coverage" into a measured property, not a claim |
