import { useEffect, useState } from "react";
import {
  api,
  useAsync,
  type ExplainReport,
  type Health,
  type RunCreated,
} from "./lib/api";
import { SourceFiles } from "./screens/SourceFiles";
import { ControlTotals } from "./screens/ControlTotals";
import { Results } from "./screens/Results";
import { Exceptions } from "./screens/Exceptions";
import { Benchmark } from "./screens/Benchmark";

/**
 * The workspace is a stack of working papers, indexed A–D, exactly as audit
 * schedules are indexed. Choosing sources happens before the schedules, so the
 * cover sheet is indexed 0 rather than joining them.
 */
const SCHEDULES = [
  { key: "0", title: "Source files" },
  { key: "A", title: "Control totals" },
  { key: "B", title: "Results" },
  { key: "C", title: "Exceptions" },
  { key: "D", title: "Benchmark" },
] as const;

type ScheduleKey = (typeof SCHEDULES)[number]["key"];

function useTheme() {
  const [dark, setDark] = useState(
    () => document.documentElement.dataset.theme === "dark",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("settlesense-theme", dark ? "dark" : "light");
    } catch {
      /* private mode: the toggle still works for this session */
    }
  }, [dark]);
  return [dark, setDark] as const;
}

export default function App() {
  const [schedule, setSchedule] = useState<ScheduleKey>("A");
  const [run, setRun] = useState<RunCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null);
  const [explained, setExplained] = useState<ExplainReport | null>(null);
  const [dark, setDark] = useTheme();

  const health = useAsync<Health>(() => api.health(), []);

  async function reconcile(fn: () => Promise<RunCreated>) {
    setBusy(true);
    setFailure(null);
    setExplained(null);
    try {
      const created = await fn();
      setRun(created);
      setMetrics(await api.metrics(created.run_id).catch(() => null));
      setSchedule("A");
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function explain() {
    if (!run) return;
    setBusy(true);
    try {
      setExplained(await api.explain(run.run_id));
      setMetrics(await api.metrics(run.run_id).catch(() => metrics));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void reconcile(() => api.runFixture());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runId = run?.run_id ?? null;

  return (
    <div className="min-h-screen bg-desk">
      <div className="mx-auto flex max-w-[1180px] gap-6 px-5 py-6">
        <nav className="sticky top-6 hidden h-fit w-[196px] shrink-0 md:block">
          <div className="mb-6">
            <div className="font-mono text-[15px] font-medium tracking-[0.08em] text-ink">
              SETTLESENSE
            </div>
            {/* The mark is the double rule: in accounting it means footed
                and verified. */}
            <div className="double-rule mt-1 w-[142px]" />
            <p className="mt-2 text-[11px] leading-snug text-ink-faint">
              Evidence for every conclusion
            </p>
          </div>

          <div className="label mb-2">Schedules</div>
          <ul>
            {SCHEDULES.map((s) => (
              <li key={s.key}>
                <button
                  onClick={() => setSchedule(s.key)}
                  disabled={!runId && s.key !== "0"}
                  className={`flex w-full items-baseline gap-2.5 border-l-2 py-1.5 pl-2.5 text-left text-[13px] transition-colors disabled:opacity-40 ${
                    schedule === s.key
                      ? "border-ink text-ink"
                      : "border-transparent text-ink-muted hover:text-ink"
                  }`}
                >
                  <span className="index-ref">{s.key}</span>
                  <span>{s.title}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className="mt-6 border-t border-rule pt-4">
            <button
              onClick={() => reconcile(() => api.runFixture())}
              disabled={busy}
              className="w-full rounded-[2px] border border-ink px-3 py-1.5 text-[12px] text-ink transition-colors hover:bg-ink hover:text-paper disabled:opacity-50"
            >
              {busy ? "Working…" : "Reconcile benchmark"}
            </button>
            <button
              onClick={explain}
              disabled={busy || !runId}
              className="mt-2 w-full rounded-[2px] border border-rule px-3 py-1.5 text-[12px] text-ink-muted transition-colors hover:border-ink hover:text-ink disabled:opacity-40"
            >
              Explain exceptions
            </button>
            <button
              onClick={() => setDark(!dark)}
              className="mt-2 w-full px-3 py-1 text-left text-[11px] text-ink-faint hover:text-ink"
            >
              {dark ? "View on paper" : "View on light table"}
            </button>
          </div>

          {health.data ? (
            <p className="mt-4 text-[11px] leading-snug text-ink-faint">
              Engine <span className="fig">{health.data.engine_version}</span>
              <br />
              Explanations {health.data.ai_enabled ? "live" : "from templates"}
            </p>
          ) : null}
        </nav>

        <main className="min-w-0 flex-1">
          <div className="mb-4 flex gap-1 md:hidden">
            {SCHEDULES.map((s) => (
              <button
                key={s.key}
                onClick={() => setSchedule(s.key)}
                disabled={!runId && s.key !== "0"}
                className={`rounded-[2px] border px-2.5 py-1 text-[12px] disabled:opacity-40 ${
                  schedule === s.key
                    ? "border-ink bg-ink text-paper"
                    : "border-rule text-ink-muted"
                }`}
              >
                {s.key}
              </button>
            ))}
          </div>

          {failure ? (
            <div className="sheet mb-4 px-6 py-4">
              <p className="text-[13px] text-audit">
                The API did not respond. Start it with{" "}
                <span className="fig">uvicorn settlesense.api.main:app</span>, then
                reconcile again.
              </p>
              <p className="mt-1 font-mono text-[11px] text-ink-faint">{failure}</p>
            </div>
          ) : null}

          {/* The duplicate-batch case, stated rather than silently handled. */}
          {run?.already_existed && schedule !== "0" ? (
            <div className="sheet mb-4 px-6 py-3">
              <p className="text-[13px] text-ink">
                These four files were already reconciled. Showing the existing run
                rather than counting the batch twice.
              </p>
            </div>
          ) : null}

          {explained && schedule !== "0" ? (
            <div className="sheet mb-4 px-6 py-3">
              <p className="text-[13px] text-ink">
                Explained {explained.explained} exceptions ·{" "}
                <span className="fig">{explained.from_ai}</span> from the model,{" "}
                <span className="fig">{explained.from_template}</span> from
                templates
                {explained.rejected_by_grounding > 0 ? (
                  <>
                    {" "}
                    ·{" "}
                    <span className="fig text-audit">
                      {explained.rejected_by_grounding}
                    </span>{" "}
                    rejected by the grounding gate
                  </>
                ) : null}
              </p>
              {!explained.ai_available ? (
                <p className="mt-1 text-[12px] text-ink-muted">
                  {explained.unavailable_reason}. Figures are unchanged.
                </p>
              ) : null}
            </div>
          ) : null}

          {schedule === "0" ? (
            <SourceFiles busy={busy} onRun={reconcile} />
          ) : runId ? (
            <>
              {schedule === "A" ? (
                <ControlTotals runId={runId} metrics={metrics} />
              ) : null}
              {schedule === "B" ? <Results runId={runId} /> : null}
              {schedule === "C" ? <Exceptions runId={runId} /> : null}
              {schedule === "D" ? <Benchmark metrics={metrics} /> : null}
            </>
          ) : !failure ? (
            <div className="sheet px-6 py-12 text-center">
              <p className="font-mono text-[14px] text-ink">Reconciling the batch…</p>
            </div>
          ) : null}
        </main>
      </div>
    </div>
  );
}
