import { api, useAsync, type Proof } from "../lib/api";
import { amount } from "../lib/format";
import { DoubleRule } from "./Sheet";

/**
 * The control-total proof: does every rupee collected have somewhere to go?
 *
 * A controller's first instinct with any schedule is "does it foot?". This is
 * the answer, laid out so it can be added up by hand — which is the point. A
 * figure nobody can check is a figure nobody trusts.
 *
 * It is also a live self-audit. Both money bugs this project has had would
 * have shown up here as a non-zero difference before anyone noticed them on
 * another screen.
 */
export function ControlTotalProof({ runId }: { runId: string }) {
  const { data, error, loading } = useAsync<Proof>(() => api.proof(runId), [runId]);

  if (loading || error || !data) return null;

  const parts = [
    ["Settled cash", data.settled],
    ["Provider fees", data.fees],
    ["Tax on fees", data.tax],
    ["Refunds", data.refunds],
    ["Unexplained", data.unexplained],
  ] as const;

  return (
    <div className="border-t border-rule px-6 py-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="label">Where the money went</h3>
        <span className="index-ref">A-2</span>
      </div>

      <dl>
        <div className="flex items-baseline justify-between border-b border-rule-soft py-1.5">
          <dt className="text-[13px] text-ink">Gross collections</dt>
          <dd className="fig text-[14px] font-medium text-ink">
            {amount(data.gross)}
          </dd>
        </div>

        {parts.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between border-b border-rule-soft py-1.5"
          >
            <dt className="pl-4 text-[13px] text-ink-muted">{label}</dt>
            <dd
              className={`fig text-[13px] ${
                label === "Unexplained" && (value.paise ?? 0) > 0
                  ? "text-audit"
                  : "text-ink"
              }`}
            >
              {amount(value)}
            </dd>
          </div>
        ))}

        <div className="flex items-baseline justify-between py-1.5">
          <dt className="text-[13px] text-ink">Accounted for</dt>
          <dd className="fig text-[14px] font-medium text-ink">
            {amount(data.accounted)}
          </dd>
        </div>
      </dl>

      {/* Footed and verified — only drawn when it actually balances. */}
      {data.balances ? <DoubleRule /> : null}

      <p
        className={`mt-3 text-[12px] ${
          data.balances ? "text-ink-muted" : "text-audit"
        }`}
      >
        {data.balances ? (
          <>
            Difference <span className="fig">0.00</span>. Every rupee collected is
            either settled, taken as a fee, refunded, or reported as unexplained.
          </>
        ) : (
          <>
            Difference <span className="fig">{amount(data.difference)}</span>. The
            run does not balance, so a figure on this screen is wrong. Treat every
            total here as unverified until it is resolved.
          </>
        )}
      </p>
    </div>
  );
}
