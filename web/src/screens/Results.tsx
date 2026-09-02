import { useMemo, useState } from "react";
import { api, useAsync, type ResultPage, type ResultRow } from "../lib/api";
import { amount, reason } from "../lib/format";
import { Empty, Sheet } from "../components/Sheet";
import { Tick, tickFor, type TickKind } from "../components/Tick";
import { TickLegend } from "../components/TickLegend";
import { EvidenceDrawer } from "../components/EvidenceDrawer";

/**
 * Screen B — the results schedule.
 *
 * The left margin channel carries the tick. The variance column is decimal
 * aligned with brackets for negatives. Zero is an em dash. Only exception
 * rows carry colour; matched rows are silent.
 */
export function Results({ runId }: { runId: string }) {
  const [tick, setTick] = useState<TickKind | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const { data, error, loading } = useAsync<ResultPage>(
    () => api.results(runId, { limit: 1000 }),
    [runId],
  );

  const rows = data?.results ?? [];
  const counts = useMemo(() => {
    const out: Partial<Record<TickKind, number>> = {};
    for (const row of rows) {
      const kind = tickFor(row);
      out[kind] = (out[kind] ?? 0) + 1;
    }
    return out;
  }, [rows]);

  const visible = tick ? rows.filter((r) => tickFor(r) === tick) : rows;

  return (
    <>
      <Sheet
        index="B-1"
        title="Results schedule"
        meta={
          loading
            ? "Reading…"
            : `${visible.length} of ${rows.length} rows${tick ? " · filtered" : ""}`
        }
      >
        <TickLegend active={tick} counts={counts} onToggle={setTick} />

        {error ? (
          <p className="px-6 py-8 text-[13px] text-audit">{error}</p>
        ) : visible.length === 0 && !loading ? (
          <Empty
            headline="No rows carry this tick."
            body="Clear the filter to see the full schedule."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-rule">
                  <th className="w-9 px-3 py-2" />
                  <th className="label px-2 py-2 font-medium">Payment</th>
                  <th className="label px-2 py-2 text-right font-medium">
                    Expected net
                  </th>
                  <th className="label px-2 py-2 text-right font-medium">Settled</th>
                  <th className="label px-2 py-2 text-right font-medium">Variance</th>
                  <th className="label px-2 py-2 text-right font-medium">Pending</th>
                  <th className="label px-2 py-2 font-medium">Status</th>
                  <th className="label px-2 py-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <Row
                    key={row.reconciliation_id}
                    row={row}
                    onOpen={() => setOpen(row.reconciliation_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Sheet>

      {open ? (
        <EvidenceDrawer
          runId={runId}
          reconciliationId={open}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </>
  );
}

function Row({ row, onOpen }: { row: ResultRow; onOpen: () => void }) {
  const kind = tickFor(row);
  const exception = row.status !== "matched";
  const variance = amount(row.difference);
  const pending = amount(row.pending_amount);

  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className="cursor-pointer border-b border-rule-soft last:border-b-0 hover:bg-desk"
    >
      <td className="px-3 py-1.5 align-middle">
        <Tick kind={kind} title={kind.replace("-", " ")} />
      </td>
      <td className="fig px-2 py-1.5 text-[13px] text-ink">{row.payment_id}</td>
      <td className="fig px-2 py-1.5 text-right text-[13px] text-ink">
        {amount(row.expected_net)}
      </td>
      <td className="fig px-2 py-1.5 text-right text-[13px] text-ink">
        {amount(row.settled_amount)}
      </td>
      <td
        className={`fig px-2 py-1.5 text-right text-[13px] ${
          (row.difference.paise ?? 0) !== 0 ? "text-audit" : "text-ink-faint"
        }`}
      >
        {variance}
      </td>
      <td
        className={`fig px-2 py-1.5 text-right text-[13px] ${
          (row.pending_amount.paise ?? 0) !== 0 ? "text-audit" : "text-ink-faint"
        }`}
      >
        {pending}
      </td>
      <td
        className={`px-2 py-1.5 text-[12px] ${
          exception ? "text-audit" : "text-ink-muted"
        }`}
      >
        {row.status}
      </td>
      <td className="px-2 py-1.5 text-[12px] text-ink-muted">
        {reason(row.reason_code)}
      </td>
    </tr>
  );
}
