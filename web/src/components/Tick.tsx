/**
 * Audit tick marks — the signature element.
 *
 * Auditors mark each figure on a working paper with a glyph recording *how*
 * it was verified, and define those glyphs in a legend on the same sheet.
 * These map exactly to the engine's rules R1–R6, so the visual system is the
 * engine's own structure rather than a metaphor laid over it.
 *
 * Drawn as SVG rather than unicode: circled-digit characters are missing from
 * most monospace fonts and would fall back inconsistently.
 */
import type { ReactElement } from "react";
import type { ResultRow } from "../lib/api";

export type TickKind =
  | "traced-id"
  | "traced-ref"
  | "agreed"
  | "refund"
  | "footed"
  | "unresolved"
  | "ambiguous";

export const TICKS: { kind: TickKind; name: string; meaning: string }[] = [
  { kind: "traced-id", name: "Traced", meaning: "matched on payment id" },
  { kind: "traced-ref", name: "Referenced", meaning: "matched on order reference" },
  { kind: "agreed", name: "Agreed", meaning: "amount and date within tolerance" },
  { kind: "refund", name: "Adjusted", meaning: "refund accounted for separately" },
  { kind: "footed", name: "Footed", meaning: "summed across settlement rows" },
  { kind: "unresolved", name: "Not verified", meaning: "evidence insufficient" },
  { kind: "ambiguous", name: "Contested", meaning: "two equal matches; none taken" },
];

/** The tick is derived from the engine's verdict, never chosen by the UI. */
export function tickFor(row: Pick<ResultRow, "status" | "match_type" | "reason_code">): TickKind {
  if (row.reason_code === "ambiguous_candidates") return "ambiguous";
  if (row.status === "unresolved") return "unresolved";
  switch (row.match_type) {
    case "partial":
      return "footed";
    case "refund_adjusted":
      return "refund";
    case "amount_time":
      return "agreed";
    case "unresolved":
      return "unresolved";
    default:
      return "traced-id";
  }
}

const PATHS: Record<TickKind, ReactElement> = {
  // A clean audit check.
  "traced-id": <path d="M2.5 7.5 L5.5 11 L11.5 3" />,
  // Check with a reference dot: traced by a secondary identifier.
  "traced-ref": (
    <>
      <path d="M2.5 7.5 L5.5 11 L11.5 3" />
      <circle cx="12.2" cy="11.2" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  // Double caret: agreed within tolerance, not identical.
  agreed: (
    <>
      <path d="M2.5 6 L5.5 3 L8.5 6" />
      <path d="M5.5 11.5 L8.5 8.5 L11.5 11.5" />
    </>
  ),
  // Check struck through: an adjustment was applied.
  refund: (
    <>
      <path d="M2.5 7.5 L5.5 11 L11.5 3" />
      <path d="M2 12.5 L12.5 12.5" />
    </>
  ),
  // Footing bracket over stacked rows: summed and totalled.
  footed: (
    <>
      <path d="M3 2.5 L11 2.5" />
      <path d="M3 6 L11 6" />
      <path d="M2 9.5 L12 9.5" />
      <path d="M2 9.5 L2 12 M12 9.5 L12 12" />
    </>
  ),
  // Open circle, struck: nothing was verified here.
  unresolved: (
    <>
      <circle cx="7" cy="7" r="5" />
      <path d="M3.6 10.4 L10.4 3.6" />
    </>
  ),
  // Fork: the evidence pointed two ways.
  ambiguous: (
    <>
      <path d="M7 12.5 L7 7.5" />
      <path d="M7 7.5 L3.5 3" />
      <path d="M7 7.5 L10.5 3" />
    </>
  ),
};

/** The rule behind a tick, named for a reader who has not learned the glyphs. */
export const RULE_NAMES: Record<TickKind, string> = {
  "traced-id": "R1 · traced by payment id",
  "traced-ref": "R2 · traced by order reference",
  agreed: "R3 · agreed on amount and date",
  refund: "R4 · refund accounted for separately",
  footed: "R5 · footed across settlement rows",
  unresolved: "R6 · no candidate survived",
  ambiguous: "contested · two equal matches, neither taken",
};

export function Tick({
  kind,
  tone,
  title,
}: {
  kind: TickKind;
  /** Overrides the default colour. Passed explicitly rather than as a class,
   *  because two same-specificity utilities are resolved by CSS source order,
   *  not by the order they appear in the attribute. */
  tone?: "inherit";
  title?: string;
}) {
  const exception = kind === "unresolved" || kind === "ambiguous";
  const colour =
    tone === "inherit"
      ? "text-current"
      : exception
        ? "text-audit"
        : "text-ink-muted";
  return (
    <svg
      viewBox="0 0 14 14"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={title}
      className={colour}
    >
      {title ? <title>{title}</title> : null}
      {PATHS[kind]}
    </svg>
  );
}
