import {
  api,
  useAsync,
  type ExceptionGroup,
  type LedgerFinding,
  type ValidationError,
} from "../lib/api";
import { amount, reason } from "../lib/format";
import { Empty, Sheet } from "../components/Sheet";

/**
 * Screen C — exceptions grouped by cause.
 *
 * The queue is a designed output, not what fell through. Each group states
 * the money it accounts for, so the sum is auditable against screen A.
 */
export function Exceptions({ runId }: { runId: string }) {
  const groups = useAsync<ExceptionGroup[]>(() => api.exceptions(runId), [runId]);
  const findings = useAsync<LedgerFinding[]>(
    () => api.ledgerFindings(runId),
    [runId],
  );
  const rejected = useAsync<ValidationError[]>(
    () => api.validationErrors(runId),
    [runId],
  );

  const total = (groups.data ?? []).reduce((n, g) => n + g.count, 0);

  return (
    <div className="space-y-6">
      <Sheet
        index="C-1"
        title="Exceptions by cause"
        meta={groups.loading ? "Reading…" : `${total} cases needing a human`}
      >
        {groups.error ? (
          <p className="px-6 py-8 text-[13px] text-audit">{groups.error}</p>
        ) : (groups.data ?? []).length === 0 && !groups.loading ? (
          <Empty
            headline="No exceptions in this batch."
            body="Every payment reconciled with zero residual. Nothing needs review."
          />
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-rule">
                <th className="label px-6 py-2 font-medium">Cause</th>
                <th className="label px-2 py-2 font-medium">Routed to</th>
                <th className="label px-2 py-2 text-right font-medium">Cases</th>
                <th className="label px-6 py-2 text-right font-medium">
                  Unexplained
                </th>
              </tr>
            </thead>
            <tbody>
              {(groups.data ?? []).map((g) => (
                <tr
                  key={`${g.reason_code}-${g.status}`}
                  className="border-b border-rule-soft last:border-b-0"
                >
                  <td className="px-6 py-2 text-[13px] text-ink">
                    {reason(g.reason_code)}
                  </td>
                  <td className="px-2 py-2 text-[12px] text-audit">{g.status}</td>
                  <td className="fig px-2 py-2 text-right text-[13px] text-ink">
                    {g.count}
                  </td>
                  <td className="fig px-6 py-2 text-right text-[13px] text-audit">
                    {amount(g.unexplained)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Sheet>

      <Sheet
        index="C-2"
        title="Ledger cross-check"
        meta="The third leg: the merchant's accounting view against the payments"
      >
        {(findings.data ?? []).length === 0 ? (
          <Empty
            headline="The ledger agrees."
            body="No duplicate or mismatched accounting rows were found."
          />
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-rule">
                <th className="label px-6 py-2 font-medium">Finding</th>
                <th className="label px-2 py-2 font-medium">Order</th>
                <th className="label px-6 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {(findings.data ?? []).map((f, i) => (
                <tr key={i} className="border-b border-rule-soft last:border-b-0">
                  <td className="px-6 py-2 text-[13px] text-audit">
                    {reason(f.reason)}
                  </td>
                  <td className="fig px-2 py-2 text-[13px] text-ink">{f.order_id}</td>
                  <td className="fig px-6 py-2 text-[12px] text-ink-muted">
                    {f.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Sheet>

      <Sheet
        index="C-3"
        title="Rejected rows"
        meta="Rows set aside at validation; the rest of the batch still reconciled"
      >
        {(rejected.data ?? []).length === 0 ? (
          <Empty
            headline="Every row parsed."
            body="No source row was rejected, so nothing was set aside."
          />
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-rule">
                <th className="label px-6 py-2 font-medium">File</th>
                <th className="label px-2 py-2 text-right font-medium">Line</th>
                <th className="label px-2 py-2 font-medium">Field</th>
                <th className="label px-6 py-2 font-medium">Why it was rejected</th>
              </tr>
            </thead>
            <tbody>
              {(rejected.data ?? []).map((e, i) => (
                <tr key={i} className="border-b border-rule-soft last:border-b-0">
                  <td className="fig px-6 py-2 text-[12px] text-ink">
                    {e.source_file}
                  </td>
                  <td className="fig px-2 py-2 text-right text-[13px] text-ink">
                    {e.source_line}
                  </td>
                  <td className="fig px-2 py-2 text-[12px] text-audit">{e.field}</td>
                  <td className="px-6 py-2 text-[12px] text-ink-muted">{e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Sheet>
    </div>
  );
}
