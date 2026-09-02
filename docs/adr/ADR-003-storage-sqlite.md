# ADR-003: SQLite, with reconciliation results as a first-class table

**Status:** Accepted
**Date:** 2026-09-02
**Deciders:** Project owner (solo build)

## Context

Four inputs arrive as CSVs. The outputs are results, calculation traces, evidence references, explanations, review actions and metrics — and those outputs are consumed by four different readers: the evaluator (joins to ground truth), the API/UI, the Q&A layer, and the CSV export.

The tempting shortcut is to keep everything in pandas DataFrames and render the screen from memory. That works until the first of these questions is asked, and all of them will be asked:

- What exactly did run #3 conclude, and how does it differ from run #4 after I changed the tolerance?
- Show me the source rows behind this conclusion, with proof they are the rows that were used.
- What is the total unexplained amount across all `review` cases over ₹500?
- A reviewer accepted this exception — where is that recorded?

Constraints: a judge clones the repo and runs one command; no container, no service to provision; the dataset is 100–1000 rows and will never be 10 million.

## Decision

**SQLite**, one file (`settlesense.db`), schema created on first run from `store/schema.sql`. Reconciliation output is persisted as a normalised set of tables — `reconciliation_results`, `result_settlements`, `calc_steps`, `evidence_refs`, `explanations`, `exception_clusters`, `review_actions`, `metrics` — not as a screen payload or a serialised blob.

Runs are **append-only**: each run gets a `run_id` stamped with `engine_version`, `rules_version` and the config used. Nothing is updated in place, so two runs over the same batch can be diffed.

Schema stays portable: plain SQL types, no SQLite-only constructs, so the migration to Postgres is a connection-string change.

## Options Considered

### Option A: In-memory pandas / CSV output

| Dimension | Assessment |
|---|---|
| Complexity | Lowest |
| Cost | Free |
| Scalability | Fine at this size |
| Team familiarity | High |

**Pros:** fastest to a first table on screen; no schema to design.
**Cons:** no foreign keys, so evidence links are convention rather than constraint; no durability across runs, so no before/after comparison and no review actions; the evidence drawer must re-derive or serialise into pickles; and the evaluator, API and export each end up with their own slightly different notion of "what matched" — the exact defect that makes a finance tool untrustworthy.

### Option B: SQLite with a real schema (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low–Medium — one `schema.sql` and a thin repository layer |
| Cost | Free |
| Scalability | Comfortable to ~10⁵–10⁶ rows |
| Team familiarity | High |

**Pros:** zero provisioning and a single file a judge can open with any tool; in-process, so no pool, port or container; real joins and constraints; durable append-only runs enable regression diffs; one canonical results table for every reader; the Q&A layer gets exact SQL instead of approximate retrieval.
**Cons:** a schema to design up front and keep in step with the Pydantic contracts; single-writer concurrency (irrelevant for a batch tool, a real limit for multi-tenant).

### Option C: PostgreSQL (Docker Compose)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — compose file, migrations, connection config |
| Cost | Free locally |
| Scalability | Excellent |
| Team familiarity | High |

**Pros:** the production answer; concurrent writers; richer types.
**Cons:** it adds a runtime dependency to the one step that must not fail — the judge's fresh clone. Ports, daemons and container startup are the most common cause of "it doesn't run on my machine" in a hackathon, and it buys nothing at 100 records. Nothing in the design is Postgres-shaped; adopting it later costs a connection string.

## Trade-off Analysis

Option A is cheaper for the first hour and more expensive for every hour after, because the evidence drawer, the evaluator, the review queue and the export all quietly need a database and would each grow half of one.

Option C is the right choice for a product and the wrong choice for a four-day demo: it moves risk to the moment of judging in exchange for scale we do not need.

Option B sits exactly on the requirement — it is the smallest thing that provides foreign keys, durability and joins. The decisive point is not the engine but the *shape*: making results a first-class table is what guarantees a single definition of "what matched" shared by every reader, and that guarantee is the same one whether the file is SQLite or Postgres.

## Consequences

**Easier**
- One canonical results table for the evaluator, API, Q&A and export.
- Evidence drawer is a join, not a re-computation.
- Re-running a batch after a rule change and diffing runs becomes the Day-4 regression test.
- Q&A returns exact numbers via parameterised SQL — no vector store, no embedding drift.
- Judges can inspect `settlesense.db` directly, which is itself a credibility argument.

**Harder**
- The schema and the Pydantic contracts must be kept in step; drift is caught by a round-trip test.
- Single-writer concurrency rules out multi-tenant use without migrating.
- Migrations are manual (drop-and-recreate during the build window; acceptable because runs are re-derivable from source files).

**To revisit**
- Multi-tenant, concurrent, or >10⁶ rows → Postgres, using the same schema.
- If run history grows large, add a retention policy; raw row storage is the bulk of it.

## Action Items

1. [ ] Write `store/schema.sql` with foreign keys enabled (`PRAGMA foreign_keys = ON`).
2. [ ] Thin repository layer; no ORM — the query set is small, fixed and worth reading.
3. [ ] Round-trip test: Pydantic contract → row → contract, per table.
4. [ ] `settlesense run --batch data/ --compare-to <run_id>` for run diffs.
5. [ ] Confirm fresh-clone path: clone → `pip install -e .` → `settlesense run` → DB created, metrics printed.
