import { api, useAsync, type Summary } from "../lib/api";
import { amount } from "../lib/format";
import { DoubleRule, Sheet } from "../components/Sheet";
import { ControlTotalProof } from "../components/ControlTotalProof";

/**
 * Screen A — the six numbers a controller checks first.
 *
 * The hero is not a KPI row. It is the honest triple (matched / review /
 * unresolved) sitting above the two figures that decide whether this tool can
 * be trusted: unexplained money, and false matches.
 */
function Count({
  value,
  label,
  tone = "ink",
  delay,
}: {
  value: number;
  label: string;
  tone?: "ink" | "audit";
  delay: number;
}) {
  return (
    <div className="foot-in" style={{ animationDelay: `${delay}ms` }}>
      <div
        className={`fig text-[40px] leading-none font-medium tracking-[-0.02em] ${
          tone === "audit" ? "text-audit" : "text-ink"
        }`}
      >
        {value}
      </div>
      <div className="label mt-2">{label}</div>
    </div>
  );
}

export function ControlTotals({
  runId,
  metrics,
}: {
  runId: string;
  metrics: Record<string, number> | null;
}) {
  const { data, error, loading } = useAsync<Summary>(
    () => api.summary(runId),
    [runId],
  );

  if (loading) return <Sheet index="A-1" title="Control totals">{null}</Sheet>;
  if (error || !data)
    return (
      <Sheet index="A-1" title="Control totals">
        <p className="px-6 py-8 text-[13px] text-audit">{error}</p>
      </Sheet>
    );

  const falseMatches = metrics?.false_matches;
  const reconciled = data.records_processed > 0;

  return (
    <Sheet
      index="A-1"
      title="Control totals"
      meta={
        <>
          Batch <span className="fig">{data.batch_id.slice(0, 12)}</span> · engine{" "}
          <span className="fig">{data.engine_version}</span> · rules{" "}
          <span className="fig">{data.rules_version}</span>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-y-8 px-6 py-7 sm:grid-cols-4">
        <Count value={data.records_processed} label="Processed" delay={0} />
        <Count value={data.matched} label="Matched" delay={60} />
        <Count
          value={data.needs_review}
          label="Needs review"
          tone={data.needs_review > 0 ? "audit" : "ink"}
          delay={120}
        />
        <Count
          value={data.unresolved}
          label="Unresolved"
          tone={data.unresolved > 0 ? "audit" : "ink"}
          delay={180}
        />
      </div>

      <div className="px-6 pb-6">
        <dl className="space-y-0">
          <Line label="Gross payments" value={amount(data.gross_payments)} />
          <Line label="Settled net" value={amount(data.settled_net)} />
          <Line
            label="Unexplained"
            value={amount(data.unexplained)}
            tone={(data.unexplained.paise ?? 0) > 0 ? "audit" : "ink"}
            emphasis
          />
          {falseMatches !== undefined ? (
            <Line
              label="False matches"
              value={String(falseMatches)}
              tone={falseMatches > 0 ? "audit" : "ink"}
              emphasis
            />
          ) : null}
        </dl>
        {reconciled ? <DoubleRule animate /> : null}
        <p className="mt-3 text-[12px] text-ink-muted">
          Unexplained money is the sum of every variance and every unsettled
          amount. Nothing is excluded to make the figure smaller.
        </p>
      </div>

      <ControlTotalProof runId={runId} />
    </Sheet>
  );
}

function Line({
  label,
  value,
  tone = "ink",
  emphasis = false,
}: {
  label: string;
  value: string;
  tone?: "ink" | "audit";
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between border-b border-rule-soft py-2 last:border-b-0">
      <dt className={`text-[13px] ${emphasis ? "text-ink" : "text-ink-muted"}`}>
        {label}
      </dt>
      <dd
        className={`fig ${emphasis ? "text-[17px] font-medium" : "text-[15px]"} ${
          tone === "audit" ? "text-audit" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
