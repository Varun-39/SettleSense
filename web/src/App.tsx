import { useEffect, useState } from "react";
import { api, useAsync, type Health } from "./lib/api";
import { ControlTotals } from "./screens/ControlTotals";
import { Results } from "./screens/Results";
import { Exceptions } from "./screens/Exceptions";
import { Benchmark } from "./screens/Benchmark";

/**
 * The workspace is a stack of working papers, indexed A–D, exactly as audit
 * schedules are indexed. The left rail is a table of schedules, not
 * navigation chrome.
 */
const SCHEDULES = [
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
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null);
  const [dark, setDark] = useTheme();

  const health = useAsync<Health>(() => api.health(), []);

  async function reconcile() {
    setBusy(true);
    setFailure(null);
    try {
      const run = await api.createRun();
      setRunId(run.run_id);
      setMetrics(await api.metrics(run.run_id).catch(() => null));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void reconcile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-desk">
      <div className="mx-auto flex max-w-[1180px] gap-6 px-5 py-6">
        {/* Index of schedules */}
        <nav className="sticky top-6 hidden h-fit w-[188px] shrink-0 md:block">
          <div className="mb-6">
            <div className="font-mono text-[15px] font-medium tracking-[0.08em] text-ink">
              SETTLESENSE
            </div>
            {/* The wordmark's mark is the double rule itself: in accounting
                it means footed and verified. */}
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
                  className={`flex w-full items-baseline gap-2.5 border-l-2 py-1.5 pl-2.5 text-left text-[13px] transition-colors ${
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
              onClick={reconcile}
              disabled={busy}
              className="w-full rounded-[2px] border border-ink px-3 py-1.5 text-[12px] text-ink transition-colors hover:bg-ink hover:text-paper disabled:opacity-50"
            >
              {busy ? "Reconciling…" : "Reconcile batch"}
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
          {/* Mobile schedule switcher */}
          <div className="mb-4 flex gap-1 md:hidden">
            {SCHEDULES.map((s) => (
              <button
                key={s.key}
                onClick={() => setSchedule(s.key)}
                className={`rounded-[2px] border px-2.5 py-1 text-[12px] ${
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

          {runId ? (
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
