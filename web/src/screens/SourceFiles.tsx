import { useRef, useState } from "react";
import { api, useAsync, type FixtureInfo, type RunCreated } from "../lib/api";
import { Sheet } from "../components/Sheet";

/**
 * The cover sheet — which batch this workbook covers.
 *
 * Schedules A-D are outputs; choosing sources happens before them, so this is
 * indexed 0-1 rather than joining the schedule index.
 */
const SLOTS = [
  { key: "payments", label: "Payments", file: "sample_payments.csv" },
  { key: "settlements", label: "Settlements", file: "sample_settlements.csv" },
  { key: "refunds", label: "Refunds", file: "sample_refunds.csv" },
  { key: "ledger", label: "Merchant ledger", file: "sample_ledger.csv" },
] as const;

type SlotKey = (typeof SLOTS)[number]["key"];
type Picked = Partial<Record<SlotKey, File>>;

export function SourceFiles({
  busy,
  onRun,
}: {
  busy: boolean;
  onRun: (fn: () => Promise<RunCreated>) => void;
}) {
  const [picked, setPicked] = useState<Picked>({});
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const fixtures = useAsync<FixtureInfo[]>(() => api.fixtures(), []);

  const chosen = SLOTS.filter((s) => picked[s.key]).length;
  const complete = chosen === SLOTS.length;

  function pick(key: SlotKey, file: File | undefined) {
    setPicked((prev) => {
      const next = { ...prev };
      if (file) next[key] = file;
      else delete next[key];
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <Sheet
        index="0-1"
        title="Source files"
        meta="Four exports, reconciled as one batch"
      >
        <div className="px-6 py-5">
          {SLOTS.map((slot) => {
            const file = picked[slot.key];
            return (
              <div
                key={slot.key}
                className="flex items-center justify-between gap-4 border-b border-rule-soft py-2.5 last:border-b-0"
              >
                <div className="min-w-0">
                  <div className="text-[13px] text-ink">{slot.label}</div>
                  <div className="fig text-[11px] text-ink-faint">
                    {file ? file.name : slot.file}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {file ? (
                    <>
                      <span className="fig text-[11px] text-ink-muted">
                        {(file.size / 1024).toFixed(1)} kB
                      </span>
                      <button
                        onClick={() => {
                          pick(slot.key, undefined);
                          const el = inputs.current[slot.key];
                          if (el) el.value = "";
                        }}
                        className="text-[12px] text-trace underline underline-offset-2"
                      >
                        Remove
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => inputs.current[slot.key]?.click()}
                      className="rounded-[2px] border border-rule px-2.5 py-1 text-[12px] text-ink hover:bg-desk"
                    >
                      Choose file
                    </button>
                  )}
                  <input
                    ref={(el) => {
                      inputs.current[slot.key] = el;
                    }}
                    type="file"
                    accept=".csv,text/csv"
                    className="sr-only"
                    aria-label={`${slot.label} CSV`}
                    onChange={(e) => pick(slot.key, e.target.files?.[0])}
                  />
                </div>
              </div>
            );
          })}

          <div className="mt-5 flex items-center gap-3">
            <button
              disabled={!complete || busy}
              onClick={() =>
                onRun(() =>
                  api.uploadRun({
                    payments: picked.payments!,
                    settlements: picked.settlements!,
                    refunds: picked.refunds!,
                    ledger: picked.ledger!,
                  }),
                )
              }
              className="rounded-[2px] border border-ink bg-ink px-3 py-1.5 text-[12px] text-paper transition-opacity hover:opacity-85 disabled:opacity-35"
            >
              {busy ? "Reconciling…" : "Reconcile these files"}
            </button>
            <span className="text-[12px] text-ink-muted">
              {complete
                ? "All four supplied."
                : `${chosen} of 4 chosen. All four are needed to reconcile a batch.`}
            </span>
          </div>

          <p className="mt-4 text-[12px] leading-relaxed text-ink-muted">
            Rows that fail validation are set aside with their file and line
            number, and the rest of the batch still reconciles. Re-uploading the
            same four files returns the existing run instead of counting it
            twice.
          </p>
        </div>
      </Sheet>

      <Sheet
        index="0-2"
        title="Prepared batches"
        meta="Known inputs, including the ones built to fail"
      >
        <div className="px-6 py-5">
          {(fixtures.data ?? []).map((f) => (
            <div
              key={f.name}
              className="flex items-start justify-between gap-6 border-b border-rule-soft py-3 last:border-b-0"
            >
              <div className="min-w-0">
                <div className="text-[13px] text-ink">{f.label}</div>
                <p className="mt-0.5 max-w-xl text-[12px] leading-relaxed text-ink-muted">
                  {f.description}
                </p>
              </div>
              <button
                disabled={!f.available || busy}
                onClick={() => onRun(() => api.runFixture(f.name))}
                className="shrink-0 rounded-[2px] border border-ink px-3 py-1.5 text-[12px] text-ink transition-colors hover:bg-ink hover:text-paper disabled:opacity-35"
              >
                Reconcile
              </button>
            </div>
          ))}
          {fixtures.error ? (
            <p className="text-[13px] text-audit">{fixtures.error}</p>
          ) : null}
        </div>
      </Sheet>
    </div>
  );
}
