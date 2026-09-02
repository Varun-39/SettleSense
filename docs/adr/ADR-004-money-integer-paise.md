# ADR-004: All monetary values are integer paise; floats are banned

**Status:** Accepted
**Date:** 2026-09-02
**Deciders:** Project owner (solo build)

## Context

The engine's central operation is deciding whether two monetary quantities are equal, and reporting the difference when they are not:

```
expected_net = payment_amount − refund_amount − fee − tax
matched      = (settlement.net_amount == expected_net)
```

If the representation of those quantities admits rounding error, the comparison is unsound and every number downstream — difference amount, unexplained total, amount accuracy — inherits the unsoundness. `0.1 + 0.2 != 0.3` is a curiosity in a tutorial and a defect in a settlement variance report.

Real-world aggravators specific to this domain: fee and tax are frequently fractions of a rupee; partial settlements sum many rows, so error accumulates in the direction of the row count; and CSV input arrives as strings such as `"1000.00"`, `"1,000.00"` and `"1000"`.

Tolerance handling makes it sharper still. The design uses a tolerance (default ₹1) for inferred matches. A tolerance expressed in a different unit or type from the values it compares is a bug waiting for a specific dataset.

## Decision

Every monetary value is an **integer number of paise**, from the moment of parsing to the moment of display.

```python
Paise = NewType("Paise", int)          # ₹1,000.00 == 100_000

def parse_amount(raw: str) -> Paise:
    # strip separators → Decimal(str) → quantize(Decimal("0.01"), ROUND_HALF_UP) → int
    # a value with sub-paise precision is a validation error, not a rounding opportunity
```

Supporting rules:

- `float` is prohibited inside `src/settlesense/` for monetary paths, enforced by a `no-float-money` lint check in pre-commit and CI. `Decimal` appears only inside `parse_amount`, never in a stored field or a function signature.
- Tolerances are paise: `tolerance_paise: 100` (₹1). Value and comparison share a unit.
- Formatting to `₹1,000.00` happens once, in a display helper, at the API/UI boundary.
- `match_score` is the only float in the system, and it is explicitly not money — it never participates in an equality test against an amount.

## Options Considered

### Option A: `float` rupees

| Dimension | Assessment |
|---|---|
| Complexity | Lowest |
| Cost | Free |
| Correctness | Unsound |
| Team familiarity | High |

**Pros:** parses with `float(x)`; no conversion layer.
**Cons:** equality on money is undefined; errors accumulate over multi-row partials; every comparison needs an epsilon, and that epsilon becomes indistinguishable from the *business* tolerance — meaning the system can no longer tell "these differ by a fee" from "these differ by floating-point noise". Disqualifying for a finance tool.

### Option B: `Decimal` rupees everywhere

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Free |
| Correctness | Sound if used correctly |
| Team familiarity | Medium |

**Pros:** exact; reads naturally as rupees.
**Cons:** correctness depends on discipline that is easy to lose under time pressure — one `Decimal(0.1)` from a float, or one un-quantized division, reintroduces the problem silently. Serialisation to JSON and SQLite needs custom handling in both directions. Comparison semantics carry the precision trap (`Decimal("1.0") != Decimal("1.00")` under `compare_total`).

### Option C: Integer paise (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Low — one parse function and one format function |
| Cost | Free |
| Correctness | Exact by construction |
| Team familiarity | High |

**Pros:** equality is exact and total; sums cannot drift; serialises to JSON, SQLite and CSV with no adapter; matches how payment systems (including Razorpay) represent amounts, so test fixtures and any future API integration line up; tolerance and value are the same type and unit.
**Cons:** a unit-confusion class of bug (paise treated as rupees) that shows up as a 100× error — loud, immediately visible in tests, and mitigated by the `Paise` NewType plus a display helper as the single conversion point.

## Trade-off Analysis

Option C's failure mode is the reason to prefer it. Option A and Option B both fail *quietly* — the number is slightly wrong and looks right. Option C fails *loudly* — the number is 100× wrong and is caught by the first assertion or the first glance at the screen.

For a tool whose entire value proposition is that its numbers can be trusted, choosing the representation whose errors are impossible to miss is worth the small ergonomic cost of reading `100_000` in test fixtures.

The alignment with payment-provider conventions is a bonus rather than the reason: it means fixtures, any future Razorpay Test Mode payload, and the internal representation need no translation layer.

## Consequences

**Easier**
- `==` on money is correct and needs no epsilon.
- Sums over partial settlements are exact regardless of row count.
- Business tolerance is unambiguous and configurable in the same unit as the data.
- Storage and transport are trivial; no custom JSON encoder.

**Harder**
- Test fixtures read in paise; mitigated by a `rupees(1000)` helper in test utilities.
- Every display site must go through the formatter; enforced by keeping raw `Paise` out of templates and returning a formatted field from the API alongside the integer.
- Input parsing must reject sub-paise precision explicitly rather than rounding it away — deliberately a validation error so the row appears in `validation_errors` rather than being silently altered.

**To revisit**
- Multi-currency support: the exponent stops being fixed at 2 (e.g. JPY, KWD). `Paise` would become `Minor(currency, amount)`. Out of scope while INR-only, and validation rejects mixed-currency batches today.

## Action Items

1. [ ] `contracts/money.py`: `Paise` NewType, `parse_amount`, `format_inr`; 100% branch coverage.
2. [ ] Pre-commit + CI `no-float-money` check over `src/settlesense/`.
3. [ ] Parser tests: `"1000"`, `"1000.00"`, `"1,000.00"`, `"1000.005"` (→ validation error), `""`, `"-500"`, `"1e3"`.
4. [ ] `tolerance_paise` and `settlement_window_days` live in `recon.config.yaml`; no numeric literals in rule code.
5. [ ] Property test: for any partition of a payment into partial settlements, Σ claimed == expected_net exactly.
