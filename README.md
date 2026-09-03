# SettleSense — Settlement Reconciliation Controller

> An evidence-first finance controller that reconciles payment and settlement
> records, explains every difference, and refuses to force uncertain matches.

**Status:** deterministic engine, HTTP API, AI sidecar and dashboard complete
and measured. **No API key is required to run
anything** — without one, explanations fall back to deterministic templates and
every figure is identical.

---

## The problem

Small and mid-sized merchants receive payment data, settlement data, refund data
and accounting exports from different systems. Finance teams spend hours matching
these records by hand, and often cannot explain why a payment is missing,
partially settled, delayed, or off by fees.

SettleSense matches the records deterministically, shows the arithmetic behind
every conclusion, and routes uncertain cases to a human instead of guessing.

## The one rule

> **AI explains and prioritizes. Deterministic code calculates and controls.**

No model output can change a rupee figure, a match verdict, or a total. This is
enforced structurally, not by prompt wording: the deterministic core imports no
HTTP client at all, verified by the import-graph test in
`tests/failure/test_failure_cases.py`.

---

## Quick start

```bash
pip install -e ".[dev]"
```

Reconcile the bundled 100-record benchmark and score it against ground truth:

```bash
python -m settlesense.cli run --evaluate
```

Regenerate the benchmark dataset (deterministic — same bytes every time):

```bash
python scripts/generate_benchmark.py
```

Run the failure fixture (8 payment rows, 6 of them malformed):

```bash
python -m settlesense.cli run --data-dir demo/failure-fixtures/malformed
```

Serve the HTTP API (interactive docs at `http://localhost:8000/docs`):

```bash
uvicorn settlesense.api.main:app --reload
```

Run the test suite:

```bash
pytest -q
```

Verify from a clean clone before shipping — an undeclared dependency is
invisible on a machine that already has it:

```bash
git clone <url> /tmp/check && cd /tmp/check && python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q
```

Run the dashboard (needs the API running):

```bash
npm --prefix web install && npm --prefix web run dev
```

---

## Architecture

```
ingest → validate → normalize → dedupe → index → rules → resolver → ledger → persist
                                                                        ↓
                                                       evaluator (ground truth)
```

The load-bearing idea is **rules propose, the resolver decides**
(ADR-002). Matching rules
are pure functions returning `Candidate` objects; one resolver arbitrates between
them, claiming settlement rows into a ledger where each row can be consumed once.
When two explanations are equally good, neither wins — the case goes to review
with both cited.

| Rule | Evidence tier | Fires when |
|---|---|---|
| R1 exact ID | 1 | One settlement carries this payment's id |
| R2 order ID | 2 | Payment id absent; order reference matches, amount and date inside tolerance |
| R3 amount+time | 3 | No identifier; amount within tolerance and inside the settlement window |
| R4 refund-adjusted | 3 | Unidentified settlement matching the *post-refund* amount |
| R5 partial | 1 | Several settlement rows share one payment id |
| R6 unresolved | — | Resolver fallback: no candidate survived |

Money is integer paise throughout
(ADR-004), storage is SQLite with
results as a first-class table
(ADR-003).

---

## Benchmark methodology

`data/` holds a 100-record synthetic batch built by
`scripts/generate_benchmark.py`, with the case mix from the build guide:

| Category | Count | Expected verdict |
|---|---:|---|
| Exact matches | 35 | matched |
| Fee differences | 15 | matched (fee explains the gap) |
| Refund-adjusted | 10 | matched |
| Partial settlements | 10 | matched (multi-row sum) |
| Delayed settlements | 10 | unresolved (outside window, no identifier) |
| Missing settlement rows | 8 | unresolved |
| Duplicate ledger rows | 5 | matched + duplicate flagged |
| Amount mismatch | 4 | review |
| Failed settlements | 3 | review |

`data/ground_truth.csv` records the expected category, status and settlement ids
per payment. The engine never reads it — `evaluate/evaluator.py` is its only
importer.

Every payment is given a distinct amount spaced far wider than the matching
tolerance, so the amount+time rule cannot succeed by coincidence. The benchmark
measures the engine, not luck in the fixture.

A **false match** is counted strictly: a result is false if it is `matched` when
truth says it should not be, **or** if it matched the right payment to the wrong
settlement set.

---

## Actual results

Measured on this machine, `python -m settlesense.cli run --evaluate`:

| Metric | Result |
|---|---:|
| Records processed | 100 |
| Correct verdicts | 100 |
| Match rate | 100.0% |
| **False matches** | **0** |
| Match precision | 100.0% |
| Exception recall | 100.0% |
| Needs review | 7 |
| Unresolved | 18 |
| Exception rate | 25.0% |
| Gross payments | Rs 167,963.50 |
| Settled net amount | Rs 118,197.66 |
| Unexplained amount | Rs 44,637.11 |
| Amount accuracy | 73.42% |
| Throughput | ~10,000 records/second |
| Test suite | 201 passing |

**Read these numbers with the following caveats — they matter more than the
numbers.**

- **The 100% match rate is on a benchmark we generated ourselves.** The engine
  and the fixture were written by the same author against the same assumptions,
  so this measures internal consistency, not real-world accuracy. It would be
  dishonest to present it as the latter. The number that would survive contact
  with real data is unknown until we have real data.
- **Amount accuracy of 73% looks low and is honest.** The 18 unresolved payments
  contribute their *entire* amount to the unexplained total, because the engine
  genuinely cannot account for that money. A tool that quietly excluded
  unresolved cases from this ratio would report ~99% and mean nothing. The
  Rs 44,637 decomposes exactly: Rs 37,400 unresolved + Rs 7,037 failed
  settlements + Rs 200 amount mismatches.
- **The 25% exception rate is by design, not a shortfall.** A first-wins cascade
  would report a higher match rate by silently mis-assigning settlements. The
  trade is explicit in ADR-002.

---

## What is built vs. designed

| Part | Status |
|---|---|
| Contracts, money, time, identity | Built, tested |
| Ingest, validation, normalization, dedupe | Built, tested |
| Rule cascade R1–R6 | Built, tested |
| Resolver + claim ledger | Built, tested |
| Ledger cross-check | Built, tested |
| SQLite persistence | Built |
| Ground-truth evaluator + metrics | Built, tested |
| CLI | Built |
| FastAPI HTTP layer | Built, tested |
| Review queue (audit trail) | Built, tested |
| CSV export | Built, tested |
| AI sidecar: explanations, grounding gate, template fallback | Built, tested |
| AI sidecar: exception clustering | Built, tested |
| Finance Q&A | Designed, not built |
| React dashboard (4 screens, light + dark) | Built |

---

## API

`uvicorn settlesense.api.main:app --reload` — OpenAPI docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/runs` | Reconcile a batch: four uploaded CSVs, or `fixture=<dir>`. Idempotent on `batch_id`. |
| `GET` | `/runs` | List runs |
| `GET` | `/runs/{id}/summary` | Control totals (screen 1) |
| `GET` | `/runs/{id}/results` | Result table, filterable by `status`, `match_type`, `reason_code`, `min_difference` (screen 2) |
| `GET` | `/runs/{id}/results/{rid}` | Evidence drawer: source rows + calculation steps (screen 3) |
| `GET` | `/runs/{id}/exceptions` | Exceptions grouped by reason |
| `GET` | `/runs/{id}/metrics` | Benchmark panel (screen 4) |
| `GET` | `/runs/{id}/validation-errors` | Quarantined rows with file and line |
| `GET` | `/runs/{id}/ledger-findings` | Duplicate / mismatched accounting rows |
| `POST` | `/runs/{id}/results/{rid}/review` | Record a human decision |
| `GET` | `/runs/{id}/export.csv` | Results + settlement ids |
| `GET` | `/health` | Version and `ai_enabled` flag |

Two conventions worth noting:

- **Every monetary field is returned twice** — `{"paise": 100000, "display": "Rs 1,000.00"}`.
  The client never guesses the unit and never does money arithmetic.
- **A review action never overwrites the engine's verdict.** It is recorded
  alongside the result; the audit trail keeps both what the engine concluded and
  what the human decided.

---

## AI sidecar

Optional in the strongest sense: **the application never needs it.** Explanations
live in their own tables behind a foreign key — truncate them and no number on
any screen changes (there is a test that asserts exactly this).

```bash
# with or without ANTHROPIC_API_KEY set — both work
python -m settlesense.cli run --evaluate --ai
```

```
POST /runs/{id}/explain    generate explanations (200 even with no key)
POST /runs/{id}/cluster    group exceptions by root cause
GET  /runs/{id}/clusters   read stored groups
```

Four gates, in order (ADR-005):

1. **Input gate** — the prompt gets the verdict, the calculation trace, and the
   already-cited rows. Nothing else. `customer_id` is stripped; the model never
   sees it.
2. **Schema gate** — structured output (`messages.parse`) against a closed
   category enum, so an off-menu answer is a parse failure rather than a new
   unhandled UI state.
3. **Grounding gate** — every cited row id must exist in the context sent, every
   money figure in the summary must appear in the trace or a cited row, and the
   category must be consistent with the engine's own reason code. Failing any
   check downgrades the case to a template.
4. **Failure gate** — 8s timeout, one retry, circuit breaker after 3 consecutive
   failures. Failures are values, not exceptions.

**Every explanation is badged `ai` or `template` in the drawer**, so a reviewer
always knows what wrote the sentence.

Money-figure checking is deliberately conservative: a figure is validated when it
is currency-marked (`Rs 50.00`), comma-grouped, or written with decimals. A bare
integer ("2 settlement rows") is prose, not an amount — checking it would reject
good explanations.

**Evidence coverage is counted, not asserted.** It is grounded explanations
divided by stored explanations, tallied from actual outcomes. It reads 100%
because ungrounded answers are downgraded rather than published — but if that
ever stopped being true, the number would say so.

**Model:** `claude-opus-5` at `effort: low` (explanation is a low-reasoning task
on a tight latency budget), with the system prompt cached across a run. Calls
scale with *exceptions*, not records — ~25 per benchmark run, cached by
`prompt_version + trace_hash + row_hashes`, so a repeated demo costs nothing.

**One deliberate deviation from ADR-005:** the ADR says a category mismatch
should be stored with `grounded = false` and routed to review. The implementation
downgrades it to a template instead. Simpler and stricter — nothing ungrounded is
ever published — at the cost of losing the "AI said something odd here" signal,
which is instead captured in `grounding_failures` on the explain response.

---

## The interface

Design direction in `direction.md` (kept local). The short version:

**Colour is reserved for money that needs a human.** A clean reconciliation
renders in ink and graphite with no colour at all; every exception introduces
audit red. The screen gets louder in exact proportion to how much money is
unexplained. There is no green for "matched" — success is the absence of
marking, as on a real working paper.

**The signature is the tick column.** Every row carries an audit tick glyph
recording *how* it was verified, mapping exactly to rules R1-R6. The legend
above the table is also the filter, because a working paper's tick legend is
how you navigate it. `Not verified` and `Contested` carry equal visual weight
to `Traced`.

Other conventions borrowed from the actual artifact: the double rule under a
footed total, brackets for negatives, an em dash for zero, decimal-aligned
tabular figures, and index references (`A-1`, `B-3/1`) that make the evidence
drawer a cross-referenced sub-schedule rather than a modal.

Type is IBM Plex Mono and IBM Plex Sans, both open-licensed. The display face
is the data face: headings are set in the same tabular mono as the figures,
because in this product the numbers are the argument.

Light-first, with a dark "light table" theme. One motion moment: totals foot
into place and the double rule draws beneath them, once, on the run that
matters. `prefers-reduced-motion` removes it.

---

## Limitations

- **Greedy tiered assignment, not globally optimal matching.** Traded for
  explainability; the cost is exception volume, never a false match.
- **Batch, not streaming.** Ingest is shaped for webhook events (content-hash
  identity, append-only runs) but the engine runs per batch.
- **Single currency (INR).** Mixed-currency batches are rejected at validation
  rather than silently summed.
- **SQLite, single-tenant, no auth.** Correct for a demo; the schema is portable.
- **Synthetic data only.** No Razorpay production credentials; Test Mode webhooks
  are the next integration step.
- **The AI layer has never run against the live API.** Every gate is tested
  against a scripted client, so the plumbing, the grounding checks and all the
  failure paths are verified — but explanation *quality* on real model output is
  unmeasured. The grounded-rate metric (`ai_grounded_rate`) exists to measure it
  the moment a key is supplied.
- **Finance Q&A is not built.** The intended design is parameterised query tools over
  the results schema, never free-form SQL.
- **The order-id column on settlements is an extension** to the spec's schema.
  Rule 2 is unimplementable without it; files omitting the column still parse and
  R2 simply never fires.

---

## Security decisions

- Source data is never mutated; runs are append-only and content-addressed.
- `customer_id` is carried for grouping but is dropped before any future AI
  prompt — it is the only PII-shaped field in the schema.
- The deterministic core imports no HTTP client at all, verified by an
  AST-based import-graph test rather than by convention.
- No secrets in the repo; the AI layer (when built) reads its key from the
  environment.

---

## What broke and how I fixed it

- **The import-guard test passed for the wrong reason, then failed for the wrong
  reason.** The first version grepped the engine source for the string
  `"anthropic"` — which appears in the docstring *explaining that anthropic must
  never be imported*. A comment could have failed the build, and an import
  written differently could have passed it. Replaced with an AST walk over every
  file in the deterministic core, checking actual `Import`/`ImportFrom` nodes.
  The lesson: a test that reads source as text tests the prose, not the code.

- **The schema assertion was whitespace-brittle.** `assert "actual_net      INTEGER" in schema`
  failed against a correct schema because the column happened to be aligned with a
  different number of spaces. Replaced with a regex capturing the declared type.
  The code was right and the test was wrong — worth stating plainly, because the
  reflex to "fix" the code in that situation is how correct code gets broken.

- **Test factories in `conftest.py` were not importable.** pytest auto-loads
  `conftest.py` but does not put it on the import path, so
  `from conftest import make_payment` failed at collection. Split the builders
  into `tests/factories.py` and left only fixtures in `conftest.py`.

- **Rule 2 was unimplementable as specified.** The build guide requires an
  order-id fallback, but its settlement schema has no `order_id` column. Rather
  than silently drop the rule or invent a join, the field was added as nullable
  and the deviation documented in the model, the README and the limitations
  section.

- **The API layer exposed a SQLite threading bug that the CLI never could.**
  `Repository` opened its connection with sqlite3's default
  `check_same_thread=True`. FastAPI runs sync endpoints in a threadpool, and the
  request-scoped dependency that opens the connection can run in a *different*
  thread from the endpoint body that uses it — so every endpoint failed with
  `SQLite objects created in a thread can only be used in that same thread`.
  Fixed with `check_same_thread=False`, which is safe here only because each
  request gets its own connection. Worth stating plainly: this bug was invisible
  to 120 passing tests and would have appeared on first deploy.

- **Unexplained money was being counted twice.** `difference_amount` and
  `pending_amount` describe different money — a discrepancy against a settlement
  that exists, versus money never settled at all — and the unexplained total adds
  them. But unresolved results set *both* to the full payment amount, and
  short-settled partials set both to the shortfall. The reported unexplained
  figure was Rs 82,037 against a true Rs 44,637, and amount accuracy read 51%
  instead of 73%.

  The tell was an API test: filtering results by `min_difference >= 1` returned
  22 rows when only 4 payments had a genuine amount discrepancy. Every one of the
  152 tests had passed with the wrong number, because none of them asserted that
  the total decomposed into its parts. Fixed at the source (unresolved money is
  `pending`, a shortfall is `pending`, only an over-settlement is a `difference`)
  and pinned by `tests/property/test_no_double_counting.py`, which now asserts
  that no result carries both, that the total equals the sum of its parts, and
  that unexplained money can never exceed gross payments.

  The general lesson: a metric that is never cross-checked against an independent
  derivation will report a wrong number confidently and indefinitely.

- **Writing the architecture doc through a shell heredoc mangled the file.**
  Quoting broke on an apostrophe inside the content. Switched to direct file
  writes. Minor, but it cost a full rewrite of a 400-line document.
