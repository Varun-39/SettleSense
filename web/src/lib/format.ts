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


/**
 * Days since the payment was captured. How long money has been outstanding is
 * what a controller escalates on, and it is the difference between "wait for
 * the next batch" and "call the provider".
 */
export function ageInDays(capturedAt: string | null): number | null {
  if (!capturedAt) return null;
  const then = new Date(capturedAt).getTime();
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((Date.now() - then) / 86_400_000));
}

export function ageLabel(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "today";
  return `${days}d`;
}

/**
 * A case as plain text, ready to paste into a chase email or a ticket.
 * Analysts spend their day explaining these to other people; retyping the
 * figures is where transcription errors come from.
 */
export function asNote(row: {
  payment_id: string;
  status: string;
  reason_code: string | null;
  expected_net: Money;
  settled_amount: Money;
  difference: Money;
  pending_amount: Money;
  captured_at: string | null;
}): string {
  const lines = [
    `${row.payment_id} — ${row.status}${
      row.reason_code ? ` (${reason(row.reason_code)})` : ""
    }`,
  ];
  if (row.captured_at) {
    lines.push(`captured      ${row.captured_at.slice(0, 10)}`);
  }
  lines.push(`expected net  ${amount(row.expected_net)}`);
  lines.push(`settled       ${amount(row.settled_amount)}`);
  if ((row.difference.paise ?? 0) !== 0) {
    lines.push(`variance      ${amount(row.difference)}`);
  }
  if ((row.pending_amount.paise ?? 0) !== 0) {
    lines.push(`outstanding   ${amount(row.pending_amount)}`);
  }
  return lines.join("\n");
}
