import { useMemo, useState } from "react";
import { api, useAsync, type ResultPage, type ResultRow } from "../lib/api";
import { ageInDays, ageLabel, amount, reason } from "../lib/format";
import { Empty, Sheet } from "../components/Sheet";
import { Tick, tickFor, type TickKind } from "../components/Tick";
import { TickLegend } from "../components/TickLegend";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { BulkSignOff } from "../components/BulkSignOff";

/**
 * Screen B — the results schedule.
 *
 * The left margin channel carries the tick. The variance column is decimal
 * aligned with brackets for negatives. Zero is an em dash. Only exception
 * rows carry colour; matched rows are silent.
 *
 * Everything added here serves working through the queue rather than looking
 * at it: sort by what is worst, find one payment, age an exception, sign off
 * a whole group, and see what is left.
 */
type SortKey = "payment" | "variance" | "outstanding" | "age";

const OUTSTANDING = (r: ResultRow) =>
  Math.abs(r.difference.paise ?? 0) + (r.pending_amount.paise ?? 0);

export function Results({ runId }: { runId: string }) {
  const [tick, setTick] = useState<TickKind | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("payment");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reloadKey, setReloadKey] = useState(0);

  const { data, error, loading } = useAsync<ResultPage>(
    () => api.results(runId, { limit: 1000 }),
    [runId, reloadKey],
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

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let out = rows;
    if (tick) out = out.filter((r) => tickFor(r) === tick);
    if (needle) out = out.filter((r) => r.payment_id.toLowerCase().includes(needle));
    const sorted = [...out];
    switch (sort) {
      // Worst first: the money a controller has to account for.
      case "variance":
        sorted.sort(
          (a, b) => Math.abs(b.difference.paise ?? 0) - Math.abs(a.difference.paise ?? 0),
        );
        break;
      case "outstanding":
        sorted.sort((a, b) => OUTSTANDING(b) - OUTSTANDING(a));
        break;
      case "age":
        sorted.sort(
          (a, b) => (ageInDays(b.captured_at) ?? 0) - (ageInDays(a.captured_at) ?? 0),
        );
        break;
      default:
        sorted.sort((a, b) => a.payment_id.localeCompare(b.payment_id));
    }
    return sorted;
  }, [rows, tick, query, sort]);

  const exceptions = rows.filter((r) => r.status !== "matched");
  const untriaged = exceptions.filter((r) => r.review_count === 0).length;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const allVisibleSelected =
    visible.length > 0 && visible.every((r) => selected.has(r.reconciliation_id));

  return (
    <>
      <Sheet
        index="B-1"
        title="Results schedule"
        meta={
          loading ? (
            "Reading…"
          ) : (
            <>
              {visible.length} of {rows.length} rows
              {exceptions.length > 0 ? (
                <>
                  {" · "}
                  <span className={untriaged > 0 ? "text-audit" : undefined}>
                    {untriaged} of {exceptions.length} exceptions untriaged
                  </span>
                </>
              ) : null}
            </>
          )
        }
        actions={
          <a
            href={api.exportUrl(runId)}
            className="text-[12px] text-trace underline underline-offset-2"
          >
            Export CSV
          </a>
        }
      >
        <TickLegend active={tick} counts={counts} onToggle={setTick} />

        <div className="flex flex-wrap items-center gap-3 border-b border-rule px-4 py-2.5">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a payment"
            aria-label="Find a payment by id"
            className="fig w-44 rounded-[2px] border border-rule bg-paper px-2 py-1 text-[12px] text-ink placeholder:text-ink-faint"
          />
          <div className="flex items-center gap-1">
            <span className="label mr-1">Worst first</span>
            {(
              [
                ["payment", "Id"],
                ["outstanding", "Outstanding"],
                ["variance", "Variance"],
                ["age", "Age"],
              ] as [SortKey, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setSort(key)}
                aria-pressed={sort === key}
                className={`rounded-[2px] border px-2 py-1 text-[12px] transition-colors ${
                  sort === key
                    ? "border-ink bg-ink text-paper"
                    : "border-transparent text-ink-muted hover:border-rule hover:bg-desk"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {query || tick || sort !== "payment" ? (
            <button
              onClick={() => {
                setQuery("");
                setTick(null);
                setSort("payment");
              }}
              className="text-[12px] text-trace underline underline-offset-2"
            >
              Clear
            </button>
          ) : null}
        </div>

        {selected.size > 0 ? (
          <BulkSignOff
            runId={runId}
            ids={[...selected]}
            onDone={() => {
              setSelected(new Set());
              setReloadKey((n) => n + 1);
            }}
            onCancel={() => setSelected(new Set())}
          />
        ) : null}

        {error ? (
          <p className="px-6 py-8 text-[13px] text-audit">{error}</p>
        ) : visible.length === 0 && !loading ? (
          <Empty
            headline="Nothing matches."
            body="Clear the filter or the search to see the full schedule."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead className="sticky top-0 z-10 bg-paper">
                <tr className="border-b border-rule">
                  <th className="w-8 px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      aria-label="Select every visible row"
                      onChange={() =>
                        setSelected(
                          allVisibleSelected
                            ? new Set()
                            : new Set(visible.map((r) => r.reconciliation_id)),
                        )
                      }
                    />
                  </th>
                  <th className="w-8 px-1 py-2" />
                  <th className="label px-2 py-2 font-medium">Payment</th>
                  <th className="label px-2 py-2 text-right font-medium">Age</th>
                  <th className="label px-2 py-2 text-right font-medium">
                    Expected net
                  </th>
                  <th className="label px-2 py-2 text-right font-medium">Settled</th>
                  <th className="label px-2 py-2 text-right font-medium">Variance</th>
                  <th className="label px-2 py-2 text-right font-medium">Pending</th>
                  <th className="label px-2 py-2 font-medium">Status</th>
                  <th className="label px-2 py-2 font-medium">Reason</th>
                  <th className="label px-2 py-2 font-medium">Sign-off</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <Row
                    key={row.reconciliation_id}
                    row={row}
                    selected={selected.has(row.reconciliation_id)}
                    onSelect={() => toggle(row.reconciliation_id)}
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
          onClose={() => {
            setOpen(null);
            setReloadKey((n) => n + 1);
          }}
        />
      ) : null}
    </>
  );
}

function Row({
  row,
  selected,
  onSelect,
  onOpen,
}: {
  row: ResultRow;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  const kind = tickFor(row);
  const exception = row.status !== "matched";
  const age = ageInDays(row.captured_at);
  // Aging only means something for money still outstanding.
  const stale = exception && age !== null && age >= 14;

  return (
    <tr
      className={`border-b border-rule-soft last:border-b-0 hover:bg-desk ${
        selected ? "bg-desk" : ""
      }`}
    >
      <td className="px-3 py-1.5">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          aria-label={`Select ${row.payment_id}`}
        />
      </td>
      <td
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
        className="cursor-pointer px-1 py-1.5 align-middle"
      >
        <Tick kind={kind} title={kind.replace("-", " ")} />
      </td>
      <td
        onClick={onOpen}
        className="fig cursor-pointer px-2 py-1.5 text-[13px] text-ink"
      >
        {row.payment_id}
      </td>
      <td
        className={`fig px-2 py-1.5 text-right text-[12px] ${
          stale ? "text-audit" : "text-ink-faint"
        }`}
        title={stale ? "Outstanding for two weeks or more" : undefined}
      >
        {ageLabel(age)}
      </td>
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
        {amount(row.difference)}
      </td>
      <td
        className={`fig px-2 py-1.5 text-right text-[13px] ${
          (row.pending_amount.paise ?? 0) !== 0 ? "text-audit" : "text-ink-faint"
        }`}
      >
        {amount(row.pending_amount)}
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
      <td className="px-2 py-1.5 text-[12px] text-ink-muted">
        {row.last_action ?? (exception ? "—" : "")}
      </td>
    </tr>
  );
}
