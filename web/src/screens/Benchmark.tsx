import { DoubleRule, Sheet } from "../components/Sheet";

/**
 * Screen D — measured performance against ground truth.
 *
 * False matches sit first and are shown even at zero. A reconciliation tool
 * that reports only its wins is the thing finance teams already distrust.
 */
const PERCENT = new Set([
  "ai_grounded_rate",
  "match_rate",
  "match_precision",
  "exception_recall",
  "exception_rate",
  "amount_accuracy",
  "evidence_coverage",
]);

const LABELS: Record<string, string> = {
  false_matches: "False matches",
  records_processed: "Records processed",
  correct_verdicts: "Correct verdicts",
  match_rate: "Match rate",
  match_precision: "Precision of accepted matches",
  exception_recall: "Exception recall",
  review_count: "Needs review",
  unresolved_count: "Unresolved",
  exception_rate: "Exception rate",
  amount_accuracy: "Amount accuracy",
  unexplained_paise: "Unexplained amount",
  throughput_records_per_second: "Throughput",
  validation_errors: "Validation errors",
  duplicates_collapsed: "Duplicates collapsed",
  ai_explanations: "AI explanations",
  template_explanations: "Template explanations",
  grounding_rejections: "Rejected by grounding gate",
  ai_grounded_rate: "Model answers that were grounded",
};

const ORDER = [
  "false_matches",
  "records_processed",
  "correct_verdicts",
  "match_rate",
  "match_precision",
  "exception_recall",
  "exception_rate",
  "amount_accuracy",
  "unexplained_paise",
  "throughput_records_per_second",
  "validation_errors",
  "duplicates_collapsed",
  "ai_explanations",
  "template_explanations",
  "grounding_rejections",
  "ai_grounded_rate",
  "evidence_coverage",
];

function render(name: string, value: number): string {
  if (PERCENT.has(name)) return `${(value * 100).toFixed(1)}%`;
  if (name === "unexplained_paise")
    return (value / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
  if (name === "throughput_records_per_second")
    return `${Math.round(value).toLocaleString("en-IN")} rec/s`;
  return String(Math.round(value));
}

export function Benchmark({ metrics }: { metrics: Record<string, number> | null }) {
  if (!metrics) {
    return (
      <Sheet index="D-1" title="Benchmark">
        <p className="px-6 py-8 text-[13px] text-ink-muted">
          No ground truth was supplied with this batch, so accuracy cannot be
          measured. The reconciliation itself is unaffected.
        </p>
      </Sheet>
    );
  }

  const known = ORDER.filter((k) => k in metrics);
  const falseMatches = metrics.false_matches ?? 0;

  return (
    <Sheet
      index="D-1"
      title="Benchmark"
      meta="Measured against a held-out ground-truth file the engine never reads"
    >
      <div className="px-6 py-6">
        <div className="foot-in">
          <div
            className={`fig text-[40px] leading-none font-medium ${
              falseMatches > 0 ? "text-audit" : "text-ink"
            }`}
          >
            {falseMatches}
          </div>
          <div className="label mt-2">False matches</div>
          <p className="mt-2 max-w-md text-[12px] text-ink-muted">
            Records reported as reconciled that were not, or matched to the wrong
            settlement. This is the number that matters most, and it is shown even
            when it is zero.
          </p>
        </div>

        <div className="mt-6">
          <DoubleRule animate />
        </div>

        <dl className="mt-4">
          {known
            .filter((k) => k !== "false_matches")
            .map((name) => (
              <div
                key={name}
                className="flex items-baseline justify-between border-b border-rule-soft py-1.5 last:border-b-0"
              >
                <dt className="text-[13px] text-ink-muted">
                  {LABELS[name] ?? name.replace(/_/g, " ")}
                </dt>
                <dd className="fig text-[13px] text-ink">
                  {render(name, metrics[name])}
                </dd>
              </div>
            ))}
        </dl>
      </div>
    </Sheet>
  );
}
