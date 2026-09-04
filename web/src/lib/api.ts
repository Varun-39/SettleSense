/**
 * Typed access to the reconciliation API.
 *
 * The client performs no money arithmetic. Every amount arrives as both
 * exact paise and a preformatted display string; this layer only carries
 * them.
 */
import { useCallback, useEffect, useState } from "react";

// Same origin once built, because the API serves the bundle. Only the dev
// server needs an absolute URL, since Vite and uvicorn run on separate ports.
const BASE =
  import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

export type Money = { paise: number | null; display: string | null };

export type RunCreated = {
  run_id: string;
  batch_id: string;
  records_processed: number;
  already_existed: boolean;
  elapsed_seconds: number;
};

export type Summary = {
  run_id: string;
  batch_id: string;
  engine_version: string;
  rules_version: string;
  records_processed: number;
  matched: number;
  needs_review: number;
  unresolved: number;
  validation_errors: number;
  gross_payments: Money;
  settled_net: Money;
  unexplained: Money;
};

export type ResultRow = {
  reconciliation_id: string;
  payment_id: string;
  review_count: number;
  last_action: string | null;
  captured_at: string | null;
  match_type: string;
  match_score: number;
  status: "matched" | "review" | "unresolved";
  reason_code: string | null;
  expected_net: Money;
  actual_net: Money;
  difference: Money;
  settled_amount: Money;
  pending_amount: Money;
};

export type ResultPage = {
  total: number;
  limit: number;
  offset: number;
  results: ResultRow[];
};

export type CalcStep = {
  seq: number;
  label: string;
  expression: string;
  inputs: Record<string, number>;
  result: Money;
};

export type Evidence = {
  table: string;
  natural_id: string;
  row_hash: string;
  role: string | null;
  row: Record<string, unknown> | null;
};

export type Explanation = {
  source: "ai" | "template";
  category: string;
  summary: string;
  recommended_action: string;
  needs_human_review: boolean;
  evidence_refs: string[];
  grounded: boolean;
  model: string | null;
};

export type ResultDetail = {
  result: ResultRow;
  calc_steps: CalcStep[];
  settlements: { settlement_id: string; claimed: Money }[];
  evidence: Evidence[];
  review_actions: { actor: string; action: string; note: string | null }[];
  explanation: Explanation | null;
};

export type ExceptionGroup = {
  reason_code: string;
  status: string;
  count: number;
  unexplained: Money;
};

export type Proof = {
  run_id: string;
  balances: boolean;
  gross: Money;
  settled: Money;
  fees: Money;
  tax: Money;
  refunds: Money;
  unexplained: Money;
  accounted: Money;
  difference: Money;
};

export type Health = {
  status: string;
  version: string;
  engine_version: string;
  rules_version: string;
  ai_enabled: boolean;
  ai_unavailable_reason: string | null;
};

export type FixtureInfo = {
  name: string;
  label: string;
  description: string;
  available: boolean;
};

export type ValidationError = {
  source_file: string;
  source_line: number;
  field: string | null;
  reason: string;
  raw_row: string;
};

export type ExplainReport = {
  explained: number;
  from_ai: number;
  from_template: number;
  from_cache: number;
  rejected_by_grounding: number;
  grounding_failures: string[];
  evidence_coverage: number;
  ai_available: boolean;
  unavailable_reason: string | null;
};

export type LedgerFinding = {
  order_id: string;
  payment_id: string | null;
  reason: string;
  detail: string;
  amount: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`${response.status} ${path}${body ? ` — ${body}` : ""}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  fixtures: () => request<FixtureInfo[]>("/fixtures"),

  /** Reconcile a registered fixture by name. Never a path. */
  runFixture: (name?: string) => {
    const body = new FormData();
    if (name) body.set("fixture", name);
    return request<RunCreated>("/runs", { method: "POST", body });
  },

  /** Reconcile four uploaded CSVs. All four are required together. */
  uploadRun: (files: {
    payments: File;
    settlements: File;
    refunds: File;
    ledger: File;
  }) => {
    const body = new FormData();
    body.set("payments", files.payments);
    body.set("settlements", files.settlements);
    body.set("refunds", files.refunds);
    body.set("ledger", files.ledger);
    return request<RunCreated>("/runs", { method: "POST", body });
  },
  listRuns: () => request<{ run_id: string; batch_id: string }[]>("/runs"),
  summary: (runId: string) => request<Summary>(`/runs/${runId}/summary`),
  metrics: (runId: string) => request<Record<string, number>>(`/runs/${runId}/metrics`),
  proof: (runId: string) => request<Proof>(`/runs/${runId}/proof`),
  exceptions: (runId: string) =>
    request<ExceptionGroup[]>(`/runs/${runId}/exceptions`),
  ledgerFindings: (runId: string) =>
    request<LedgerFinding[]>(`/runs/${runId}/ledger-findings`),
  results: (runId: string, params: Record<string, string | number | undefined>) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") query.set(key, String(value));
    }
    return request<ResultPage>(`/runs/${runId}/results?${query}`);
  },
  detail: (runId: string, reconciliationId: string) =>
    request<ResultDetail>(
      `/runs/${runId}/results/${encodeURIComponent(reconciliationId)}`,
    ),
  validationErrors: (runId: string) =>
    request<ValidationError[]>(`/runs/${runId}/validation-errors`),
  explain: (runId: string) =>
    request<ExplainReport>(`/runs/${runId}/explain`, { method: "POST" }),
  review: (
    runId: string,
    reconciliationId: string,
    body: { action: string; note?: string; actor?: string },
  ) =>
    request<Record<string, unknown>>(
      `/runs/${runId}/results/${encodeURIComponent(reconciliationId)}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  reviewBatch: (
    runId: string,
    body: {
      reconciliation_ids: string[];
      action: string;
      note?: string;
      actor?: string;
    },
  ) =>
    request<{ requested: number; recorded: number }>(
      `/runs/${runId}/results/review-batch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  exportUrl: (runId: string) => `${BASE}/runs/${runId}/export.csv`,
};

/** Minimal fetch hook. No cache library — the data set is one batch. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    run()
      .then((value) => alive && setData(value))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [run]);

  return { data, error, loading };
}
