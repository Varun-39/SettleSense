import { useEffect, useState } from "react";
import { api, useAsync, type ResultDetail } from "../lib/api";
import { ACTION_LABELS, amount, asNote, reason } from "../lib/format";
import { RULE_NAMES, Tick, tickFor } from "./Tick";
import { SignOff, type Recorded } from "./SignOff";

/**
 * The evidence drawer — a cross-referenced sub-schedule, indexed B-3/1.
 *
 * The calculation renders as a worked derivation, indented and ruled the way
 * a schedule is, because that is what calc_steps already is. Nothing here is
 * recomputed: every figure was written by the engine at reconciliation time.
 */
export function EvidenceDrawer({
  runId,
  reconciliationId,
  onClose,
}: {
  runId: string;
  reconciliationId: string;
  onClose: () => void;
}) {
  const { data, error, loading } = useAsync<ResultDetail>(
    () => api.detail(runId, reconciliationId),
    [runId, reconciliationId],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button
        aria-label="Close evidence"
        onClick={onClose}
        className="absolute inset-0 bg-scrim"
      />
      <aside className="relative flex h-full w-full max-w-[560px] flex-col overflow-y-auto border-l border-rule bg-paper shadow-[-8px_0_24px_rgb(0_0_0/0.12)]">
        {loading ? (
          <p className="px-6 py-8 text-[13px] text-ink-muted">Reading evidence…</p>
        ) : error || !data ? (
          <p className="px-6 py-8 text-[13px] text-audit">{error}</p>
        ) : (
          <Body data={data} onClose={onClose} runId={runId} />
        )}
      </aside>
    </div>
  );
}

/** Show a derivation's inputs in the order the expression names them, not in
 *  whatever order the JSON arrived. A reader follows the formula top to
 *  bottom; alphabetical ordering breaks that. */
function orderedInputs(step: { expression: string; inputs: Record<string, number> }) {
  return Object.entries(step.inputs).sort(([a], [b]) => {
    const ia = step.expression.indexOf(a);
    const ib = step.expression.indexOf(b);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}

function Body({
  data,
  onClose,
  runId,
}: {
  data: ResultDetail;
  onClose: () => void;
  runId: string;
}) {
  const { result } = data;
  const exception = result.status !== "matched";
  const [copied, setCopied] = useState(false);
  const [signOffs, setSignOffs] = useState<Recorded[]>(
    data.review_actions.map((a) => ({
      actor: a.actor,
      action: a.action,
      note: a.note,
    })),
  );

  return (
    <>
      <header className="sticky top-0 border-b border-rule bg-paper px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <Tick kind={tickFor(result)} />
            <h2 className="fig text-[17px] font-medium text-ink">
              {result.payment_id}
            </h2>
            <span
              className={`text-[12px] ${exception ? "text-audit" : "text-ink-muted"}`}
            >
              {result.status}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="index-ref">B-3/1</span>
            {/* Analysts spend the day explaining these cases to other people.
                Retyping figures into an email is where transcription errors
                come from. */}
            <button
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(asNote(result));
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1600);
                } catch {
                  setCopied(false);
                }
              }}
              className="text-[12px] text-trace underline underline-offset-2"
            >
              {copied ? "Copied" : "Copy as note"}
            </button>
            <button
              onClick={onClose}
              className="text-[12px] text-trace underline underline-offset-2"
            >
              Close
            </button>
          </div>
        </div>
        <p className="mt-1 text-[12px] text-ink-muted">
          {RULE_NAMES[tickFor(result)]}
          {result.reason_code ? <> · {reason(result.reason_code)}</> : null}
        </p>
      </header>

      <section className="px-6 py-5">
        <h3 className="label mb-3">Working</h3>
        <div className="font-mono text-[13px]">
          {data.calc_steps.map((step) => (
            <div key={step.seq} className="mb-3">
              <div className="mb-1 text-[11px] text-ink-faint">{step.label}</div>
              {orderedInputs(step).map(([name, value]) => (
                <div
                  key={name}
                  className="flex justify-between border-b border-rule-soft py-0.5 pl-4"
                >
                  <span className="text-ink-muted">{name.replace(/_/g, " ")}</span>
                  <span className="fig text-ink">
                    {(value / 100).toLocaleString("en-IN", {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </span>
                </div>
              ))}
              <div className="mt-1 flex justify-between border-t border-ink py-0.5">
                <span className="text-ink">{step.expression}</span>
                <span
                  className={`fig font-medium ${
                    (step.result.paise ?? 0) < 0 ? "text-audit" : "text-ink"
                  }`}
                >
                  {amount(step.result)}
                </span>
              </div>
            </div>
          ))}
          {data.calc_steps.length === 0 ? (
            <p className="text-[13px] text-ink-muted">
              No arithmetic exists for this case. Nothing was matched, so there is
              nothing to derive.
            </p>
          ) : null}
        </div>
      </section>

      {data.settlements.length > 0 ? (
        <section className="border-t border-rule px-6 py-5">
          <h3 className="label mb-3">Claimed settlements</h3>
          {data.settlements.map((s) => (
            <div
              key={s.settlement_id}
              className="flex justify-between border-b border-rule-soft py-1 last:border-b-0"
            >
              <span className="fig text-[13px] text-ink">{s.settlement_id}</span>
              <span className="fig text-[13px] text-ink">{amount(s.claimed)}</span>
            </div>
          ))}
        </section>
      ) : null}

      <section className="border-t border-rule px-6 py-5">
        <h3 className="label mb-3">Traced to</h3>
        {data.evidence.map((item) => (
          <details
            key={`${item.table}-${item.natural_id}`}
            className="border-b border-rule-soft py-1.5 last:border-b-0"
          >
            <summary className="flex cursor-pointer items-center gap-2 text-[13px]">
              <span className="label">[{item.table}]</span>
              <span className="fig text-trace">{item.natural_id}</span>
            </summary>
            {item.row ? (
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 pl-4">
                {Object.entries(item.row)
                  .filter(([k]) => k !== "row_hash")
                  .map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="text-[12px] text-ink-muted">
                        {k.replace(/_/g, " ")}
                      </dt>
                      <dd className="fig text-[12px] text-ink">{String(v)}</dd>
                    </div>
                  ))}
              </dl>
            ) : null}
          </details>
        ))}
      </section>

      {data.explanation ? (
        <section className="border-t border-rule px-6 py-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="label">Explanation</h3>
            <span className="index-ref">
              {data.explanation.source}
              {data.explanation.grounded ? " · grounded" : " · ungrounded"}
            </span>
          </div>
          <p className="text-[13px] leading-relaxed text-ink">
            {data.explanation.summary}
          </p>
          <p className="mt-3 text-[12px] text-ink-muted">
            Recommended:{" "}
            {ACTION_LABELS[data.explanation.recommended_action] ??
              data.explanation.recommended_action}
          </p>
        </section>
      ) : null}

      <SignOff
        runId={runId}
        reconciliationId={result.reconciliation_id}
        existing={signOffs}
        onRecorded={(entry) => setSignOffs((prev) => [...prev, entry])}
      />
    </>
  );
}
