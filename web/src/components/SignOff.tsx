import { useState } from "react";
import { api } from "../lib/api";

/**
 * A reviewer's decision on an exception.
 *
 * In working-paper terms this is a sign-off: initials, a date, and a note in
 * the corner. It is recorded alongside the engine's verdict and never
 * replaces it, so the audit trail keeps both what the engine concluded and
 * what the human decided.
 */
const ACTIONS = [
  { value: "accept", label: "Accept", hint: "Agree with the engine and close" },
  { value: "reject", label: "Reject", hint: "Disagree; the case stays open" },
  { value: "annotate", label: "Annotate", hint: "Record a note only" },
  {
    value: "escalate",
    label: "Escalate",
    hint: "Hand to someone else; the case stays open",
  },
] as const;

export type Recorded = { actor: string; action: string; note: string | null };

export function SignOff({
  runId,
  reconciliationId,
  existing,
  onRecorded,
}: {
  runId: string;
  reconciliationId: string;
  existing: Recorded[];
  onRecorded: (entry: Recorded) => void;
}) {
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function record(action: string) {
    if (!actor.trim()) {
      setFailure("Add your initials before signing off.");
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      await api.review(runId, reconciliationId, {
        action,
        note: note.trim() || undefined,
        actor: actor.trim(),
      });
      onRecorded({ actor: actor.trim(), action, note: note.trim() || null });
      setNote("");
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border-t border-rule px-6 py-5">
      <h3 className="label mb-3">Sign-off</h3>

      {existing.length > 0 ? (
        <ul className="mb-4">
          {existing.map((entry, i) => (
            <li
              key={i}
              className="flex items-baseline justify-between border-b border-rule-soft py-1.5 last:border-b-0"
            >
              <span className="text-[13px] text-ink">
                <span className="fig">{entry.actor}</span> · {entry.action}
              </span>
              {entry.note ? (
                <span className="ml-4 text-[12px] text-ink-muted">{entry.note}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex gap-2">
        <input
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="Initials"
          aria-label="Your initials"
          className="fig w-24 rounded-[2px] border border-rule bg-paper px-2 py-1.5 text-[13px] text-ink placeholder:text-ink-faint"
        />
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note (optional)"
          aria-label="Note"
          className="min-w-0 flex-1 rounded-[2px] border border-rule bg-paper px-2 py-1.5 text-[13px] text-ink placeholder:text-ink-faint"
        />
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        {ACTIONS.map((a) => (
          <button
            key={a.value}
            disabled={busy}
            title={a.hint}
            onClick={() => record(a.value)}
            className="rounded-[2px] border border-rule px-2.5 py-1 text-[12px] text-ink transition-colors hover:border-ink hover:bg-desk disabled:opacity-40"
          >
            {a.label}
          </button>
        ))}
      </div>

      {failure ? (
        <p className="mt-2 text-[12px] text-audit">{failure}</p>
      ) : (
        <p className="mt-2 text-[12px] text-ink-muted">
          Recorded beside the engine's verdict. It does not change the figures.
        </p>
      )}
    </section>
  );
}
