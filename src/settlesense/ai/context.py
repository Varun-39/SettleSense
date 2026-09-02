"""The input gate (ADR-005).

The prompt receives exactly three things: the deterministic verdict, the
calculation trace, and the source rows already cited as evidence by the engine.
No full batch, no browsing, no tool access.

`customer_id` is stripped before rendering. It is the only PII-shaped field in
the schema and no explanation needs it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from settlesense.contracts.money import format_inr

PII_FIELDS = {"customer_id"}

SYSTEM_PROMPT = """\
You explain settlement reconciliation results to a finance reviewer.

A deterministic engine has already decided the outcome and computed every
figure. Your job is to explain what it found, not to recompute it.

Hard rules:
- Never state a rupee figure that is not in the calculation trace or in a cited
  source row. Do not add, subtract, or derive new amounts.
- Never invent a row id. Cite only ids present in the case below.
- Never claim a case is resolved when the engine marked it review or unresolved.
- A refund is not a fee. Keep them distinct.
- If the evidence is insufficient to explain the case, say so plainly and
  recommend human review. That is a correct answer, not a failure.

Write two or three sentences a finance reviewer can act on.\
"""


@dataclass(frozen=True)
class CaseContext:
    """Everything the model is shown, plus the allow-lists the grounding gate
    checks its answer against."""

    prompt: str
    allowed_ids: frozenset[str]
    allowed_amounts_paise: frozenset[int]
    trace_hash: str
    row_hashes: tuple[str, ...]


def _scrub(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in PII_FIELDS}


def _amounts_in(row: dict) -> set[int]:
    """Monetary fields of a source row, used to validate figures the model
    quotes back."""
    fields = (
        "amount",
        "gross_amount",
        "fee",
        "tax",
        "net_amount",
        "refund_amount",
        "debit",
        "credit",
    )
    out: set[int] = set()
    for field in fields:
        value = row.get(field)
        if isinstance(value, int):
            out.add(value)
            out.add(abs(value))
    return out


def build_case(result: dict, calc_steps: list[dict], evidence: list[dict]) -> CaseContext:
    """Render one reconciliation case for explanation.

    `result`, `calc_steps` and `evidence` come straight from the repository's
    `result_detail` — the same rows the evidence drawer shows a human.
    """
    allowed_ids: set[str] = {result["payment_id"]}
    allowed_amounts: set[int] = set()

    for key in (
        "expected_net",
        "actual_net",
        "difference_amount",
        "settled_amount",
        "pending_amount",
    ):
        value = result.get(key)
        if isinstance(value, int):
            allowed_amounts.add(value)
            allowed_amounts.add(abs(value))

    lines: list[str] = []
    lines.append("## Engine verdict")
    lines.append(f"payment_id: {result['payment_id']}")
    lines.append(f"status: {result['status']}")
    lines.append(f"reason_code: {result.get('reason_code') or 'none'}")
    lines.append(f"match_type: {result['match_type']}")
    lines.append(f"expected_net: {format_inr(result['expected_net'])}")
    if result.get("actual_net") is not None:
        lines.append(f"actual_net: {format_inr(result['actual_net'])}")
    lines.append(f"difference: {format_inr(result['difference_amount'])}")
    lines.append(f"settled: {format_inr(result['settled_amount'])}")
    lines.append(f"pending: {format_inr(result['pending_amount'])}")

    lines.append("")
    lines.append("## Calculation trace (the only arithmetic that exists)")
    trace_parts: list[str] = []
    for step in calc_steps:
        allowed_amounts.add(step["result_paise"])
        allowed_amounts.add(abs(step["result_paise"]))
        for value in step["inputs"].values():
            if isinstance(value, int):
                allowed_amounts.add(value)
                allowed_amounts.add(abs(value))
        rendered = (
            f"{step['seq']}. {step['label']}: {step['expression']} = "
            f"{format_inr(step['result_paise'])}   inputs={step['inputs']}"
        )
        lines.append(rendered)
        trace_parts.append(rendered)
    if not calc_steps:
        lines.append("(no arithmetic — nothing was matched)")

    lines.append("")
    lines.append("## Source rows (cite these ids only)")
    row_hashes: list[str] = []
    for item in evidence:
        allowed_ids.add(item["natural_id"])
        row_hashes.append(item["row_hash"])
        row = item.get("row")
        if row:
            allowed_amounts |= _amounts_in(row)
            body = json.dumps(_scrub(row), sort_keys=True, default=str)
        else:
            body = "(row not available)"
        lines.append(f"- [{item['table']}] {item['natural_id']}: {body}")

    import hashlib

    trace_hash = hashlib.sha256("\n".join(trace_parts).encode("utf-8")).hexdigest()

    return CaseContext(
        prompt="\n".join(lines),
        allowed_ids=frozenset(allowed_ids),
        allowed_amounts_paise=frozenset(allowed_amounts),
        trace_hash=trace_hash,
        row_hashes=tuple(sorted(row_hashes)),
    )
