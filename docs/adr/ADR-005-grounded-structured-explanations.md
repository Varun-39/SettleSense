# ADR-005: AI explanations use structured output behind a grounding gate

**Status:** Accepted
**Date:** 2026-09-02
**Deciders:** Project owner (solo build)

## Context

ADR-001 places the AI layer downstream of the engine, so no model output can change a number. That removes the arithmetic risk but not the *narrative* risk, which for this product is the more dangerous one.

The failure that would actually damage the demo looks like this: the engine correctly computes a ₹30 difference explained by a recorded fee, and the explanation reads "the ₹30 difference is a partial refund on `rfnd_88`" — where `rfnd_88` does not exist, or exists but is unrelated. Every number on screen is correct. The sentence a human will act on is wrong, and it is wrong in the most convincing possible register.

The brief also asks for **evidence coverage** as a displayed metric: explanations containing valid source-row references, divided by all explanations. A metric like that is only meaningful if something actually checks the references. Otherwise it reports 100% by construction and measures nothing.

## Decision

Explanations are produced through a four-gate pipeline, and an explanation that fails any gate never reaches the database as an AI explanation.

**1. Input gate.** The prompt contains only the deterministic verdict, the `CalcTrace`, and the specific source rows already cited as evidence by the engine. No full batch, no browsing, no tool access. `customer_id` is stripped before rendering — it is the only PII-shaped field in the schema and no explanation needs it.

**2. Schema gate.** Structured output with a closed enum:

```python
class Explanation(BaseModel):
    category: Literal["fee_mismatch", "timing_difference", "missing_settlement",
                      "partial_settlement", "refund_adjusted", "duplicate_record",
                      "amount_mismatch", "failed_settlement", "insufficient_evidence"]
    summary: str
    evidence_refs: list[str]
    recommended_action: Literal["human_review", "wait_next_batch", "verify_refund",
                                "investigate_duplicate", "no_action"]
    needs_human_review: bool

resp = client.messages.parse(model="claude-opus-5", max_tokens=2000,
                             output_format=Explanation, ...)
```

An off-menu category is a parse failure rather than a new, unhandled state in the UI.

**3. Grounding gate.** Before persisting:

- every id in `evidence_refs` must appear in the context that was sent → else reject;
- every money token parsed out of `summary` must appear in `calc_steps` or in a cited row → else reject;
- `category` must belong to the same family as the deterministic `reason_code` → else persist with `grounded = false` and route the case to review.

A rejected explanation falls back to a deterministic **template** rendered from the trace, persisted with `source = 'template'`. The UI shows the source as a badge. `Evidence coverage` is computed from this gate's outcomes — which is what makes it a measurement rather than an assertion.

**4. Failure gate.** 8s timeout, one retry, circuit-breaker after three consecutive failures in a run → "explanation unavailable — deterministic result stands". Explanations are cached on `sha256(prompt_version + trace_hash + sorted(row_hashes))`, so a repeated demo run costs nothing and cannot be delayed by the network.

**Model:** `claude-opus-5` with adaptive thinking, ~10–40 calls per run, all cached.

## Options Considered

### Option A: Free-text explanations

| Dimension | Assessment |
|---|---|
| Complexity | Lowest |
| Cost | Low |
| Verifiability | None |
| Team familiarity | High |

**Pros:** trivial; reads well.
**Cons:** nothing is checkable, so evidence coverage cannot be measured and the honest value to report is "unknown"; category and next action have to be re-extracted by string parsing; a fabricated row id looks identical to a real one.

### Option B: Structured output, no validation

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | Low |
| Verifiability | Partial — shape only |
| Team familiarity | High |

**Pros:** parseable, enumerable, renders cleanly.
**Cons:** guarantees the *shape* of `evidence_refs`, not that the ids exist. A well-formed hallucinated reference passes. Coverage still measures nothing.

### Option C: Structured output + grounding validation (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium — one validator plus a template fallback renderer |
| Cost | Low |
| Verifiability | High — every claim traced to a row or the trace |
| Team familiarity | Medium |

**Pros:** hallucinated references cannot be displayed; evidence coverage becomes a real metric; the template fallback means an ungrounded output degrades to a plainer explanation rather than to nothing; the `ai | template` badge is itself a credibility signal on screen.
**Cons:** the validator is code to write and test; over-strict money-token matching can reject good explanations, so the tokeniser needs care (and its rejections are logged so the rate is visible).

### Option D: Second model pass to critique the first

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | 2× calls |
| Verifiability | Probabilistic |
| Team familiarity | Medium |

**Pros:** catches semantic errors a string check misses.
**Cons:** verifies a stochastic output with another stochastic output. Option C's checks are deterministic and answer the exact question that matters ("does this row exist and does this number come from the trace?"). Rejected as strictly weaker for this purpose at twice the cost.

## Trade-off Analysis

The pivotal choice is between B and C, and it turns on what "evidence coverage: 100%" is allowed to mean.

Under B, that number is generated by the same process it claims to audit and is worth nothing. Under C, it is produced by a deterministic checker with no model in the loop, and it is defensible under questioning — which is the situation this metric exists for.

The cost is roughly a half-day: a validator, a template renderer, and tests. In exchange, the single most likely credibility failure — a fluent explanation citing a row that does not exist — becomes structurally impossible to display, and the pitch gains a concrete answer to "how do you know the AI isn't making this up?"

The template fallback is what makes strictness affordable. Without it, a strict validator would leave blank cells and create pressure to relax the checks; with it, the worst case is a plainer sentence assembled from the same trace the drawer already shows.

## Consequences

**Easier**
- Evidence coverage is a genuine, defensible metric.
- Categories and recommended actions are enum values, so they can be filtered, grouped and counted without NLP.
- Ungrounded output degrades to a template rather than to an empty cell or a wrong claim.
- Caching makes repeat demo runs instant and network-independent.

**Harder**
- Validator complexity, especially money-token extraction from prose (`₹1,000`, `1000.00`, `Rs 1,000`, `1,000 paise`).
- An over-strict validator can reject correct explanations; the rejection rate is logged and treated as a tuning signal.
- Two explanation renderers (AI and template) to keep consistent.

**To revisit**
- If the grounded rate is high and stable, consider allowing the model a *scoped* retrieval tool over the run's rows — but only through parameterised queries, never free SQL, and the grounding gate stays in place regardless.

## Action Items

1. [ ] `ai/schemas.py` — `Explanation`, `ClusterLabel`, `QAAnswer` Pydantic models.
2. [ ] `ai/grounding.py` — ref existence check, money-token check, category-family check; unit tests including a deliberately hallucinated-ref fixture.
3. [ ] `ai/fallback.py` — template renderer over `CalcTrace`; must be able to explain every `reason_code`.
4. [ ] Content-hash cache keyed on `prompt_version + trace_hash + row_hashes`.
5. [ ] Timeout / retry / circuit-breaker, plus the `--no-ai` path shared with the failure demo.
6. [ ] Surface `evidence coverage` and `ai vs template` counts on the benchmark screen.
