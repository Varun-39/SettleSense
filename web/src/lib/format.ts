import type { Money } from "./api";

/**
 * Accounting conventions the audience reads without thinking:
 *   zero renders as an em dash, negatives sit in brackets.
 * A minus sign is a programmer's convention; brackets are an
 * accountant's.
 */
export function amount(money: Money | undefined): string {
  if (!money || money.paise === null || money.display === null) return "—";
  if (money.paise === 0) return "—";
  const bare = money.display.replace(/^-?Rs\s*/, "");
  return money.paise < 0 ? `(${bare})` : bare;
}

/** True when a figure should carry audit colour: money needing a human. */
export function isException(status: string): boolean {
  return status !== "matched";
}

export const REASON_LABELS: Record<string, string> = {
  fee_mismatch: "fee mismatch",
  amount_mismatch: "amount mismatch",
  missing_settlement: "missing settlement",
  timing_difference: "timing difference",
  partial_settlement: "partial settlement",
  refund_adjusted: "refund adjusted",
  duplicate_record: "duplicate record",
  failed_settlement: "failed settlement",
  ambiguous_candidates: "ambiguous candidates",
  insufficient_evidence: "insufficient evidence",
};

export const ACTION_LABELS: Record<string, string> = {
  human_review: "Review by hand",
  wait_next_batch: "Wait for next batch",
  verify_refund: "Verify the refund",
  investigate_duplicate: "Investigate duplicate",
  no_action: "No action",
};

export function reason(code: string | null): string {
  if (!code) return "—";
  return REASON_LABELS[code] ?? code.replace(/_/g, " ");
}

export function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");
}
