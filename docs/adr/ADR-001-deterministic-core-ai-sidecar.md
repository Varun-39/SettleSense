# ADR-001: Deterministic core with AI as a downstream sidecar

**Status:** Accepted
**Date:** 2026-09-02
**Deciders:** Project owner (solo build)

## Context

The product reconciles money. Two failure modes are unacceptable in a finance tool: a wrong number presented confidently, and a total that changes because an external service was slow. A third is specific to this build — the demo runs live, on venue wifi, in front of judges who are told to look for failure recovery.

The AI capability is genuinely useful, but only for ambiguity, language, ranking and grouping. The Razorpay brief also asks for a *measured* match rate. Any architecture where a model participates in computing that number makes the measurement unfalsifiable.

Forces at play:

- Every rupee figure must be reproducible from source rows, forever, with no network call.
- The AI layer should still be visible and valuable enough to be worth demoing.
- The build has four days; the design cannot require an orchestration platform.
- "AI unavailable" must be a *demonstrable* graceful degradation, not a claim.

## Decision

The reconciliation engine is a pure, deterministic, offline pipeline. The AI layer is a **sidecar that runs after the engine has finished and persisted its results**, and it writes to separate tables joined by foreign key. No AI output is ever an input to a calculation, a match verdict, a status, or a metric.

Concretely:

- `recon/` has no HTTP client in its dependency graph, enforced by an import-lint rule.
- `reconciliation_results`, `calc_steps`, `evidence_refs` and `metrics` are written before the first token is generated.
- `explanations` and `exception_clusters` are additive. Truncating them changes no number on any screen.
- The engine exposes a `--no-ai` flag; the API exposes the same as a runtime toggle for the failure demo.

## Options Considered

### Option A: AI-in-the-loop matcher (LLM proposes or confirms matches)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — prompt per candidate pair, retries, parsing |
| Cost | Highest — one or more calls per record, not per exception |
| Scalability | Poor — latency scales with record count |
| Team familiarity | High |

**Pros:** handles fuzzy cases no rule anticipated; demos as "real AI".
**Cons:** match rate becomes non-reproducible run to run; a network failure halts reconciliation; the false-match metric loses meaning because the thing being measured is stochastic; impossible to unit test; and an incorrect match is invisible — it looks exactly like a correct one.

### Option B: Deterministic engine, AI sidecar (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low — one directional dependency, no coordination |
| Cost | Low — calls scale with *exceptions*, not records; fully cacheable |
| Scalability | Engine is O(n) and offline; sidecar is optional and parallel |
| Team familiarity | High |

**Pros:** reproducible metrics; the outage demo is free; the engine is unit-testable end to end; the AI still owns the parts it is genuinely better at (explanation, category, clustering, next action, Q&A).
**Cons:** AI cannot rescue a case the rules could not classify — such cases surface as exceptions rather than as matches. We consider that the correct behaviour, not a shortfall.

### Option C: AI as a reviewer of deterministic output (post-hoc "is this right?")

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Medium — one call per matched record |
| Scalability | Moderate |
| Team familiarity | High |

**Pros:** could catch rule blind spots.
**Cons:** creates a second, softer authority on the same question. When the reviewer and the engine disagree, there is no principled tiebreak, and whichever wins, the audit story collapses. Deferred: the same value is available more honestly by widening the *review* routing rules.

## Trade-off Analysis

The real trade is **reach vs. trustworthiness**. Option A resolves more cases; Option B resolves fewer but can defend every one it resolves and honestly flags the rest.

For a finance controller — and for a track that explicitly scores an honest exception list and a measured match rate — trustworthiness dominates. A 91% match rate with 0 false matches and 9 flagged exceptions is a stronger result than 97% with an unknown number of confident mistakes, because the second number cannot be verified by anyone, including us.

The secondary trade is demo risk. Option B converts the single most likely live-demo failure (API timeout on conference wifi) from a catastrophe into a talking point.

## Consequences

**Easier**
- Metrics are reproducible; the golden benchmark test can assert exact values.
- The AI outage demo is a flag flip, not a special code path.
- The engine can be developed and fully tested on Day 1–2 with no API key present.
- Cost stays negligible: calls scale with exceptions (~10–40/run) and are cached by content hash.

**Harder**
- Genuinely fuzzy cases (semantic ledger descriptions, unusual naming) land in the review queue rather than being auto-resolved. Accepted.
- Two storage paths for a single result view; the API composes them, and the UI must render an explanation-missing state.

**To revisit**
- If exception volume in review grows past what a human can triage, add an AI *ranking* layer (ordering the queue is safe — it changes no verdict), never an AI matcher.

## Action Items

1. [ ] Add import-lint rule: `src/settlesense/recon/**` may not import `ai/`, `anthropic`, or any HTTP client.
2. [ ] Persist results and metrics before invoking the sidecar; assert ordering in an integration test.
3. [ ] Implement `--no-ai` (CLI) and the runtime toggle (API) with an identical code path to a real outage.
4. [ ] Golden test: run the benchmark twice with AI disabled and enabled; assert byte-identical `reconciliation_results` and `metrics`.
