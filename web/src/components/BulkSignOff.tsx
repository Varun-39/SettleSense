import { useState } from "react";
import { api } from "../lib/api";

/**
 * Sign off a whole selection at once.
 *
 * Eighteen payments waiting on the same provider batch is one decision. Doing
 * it eighteen times is the kind of work software is supposed to remove.
 */
export function BulkSignOff({
  runId,
  ids,
  onDone,
  onCancel,
}: {
  runId: string;
  ids: string[];
  onDone: () => void;
  onCancel: () => void;
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
      await api.reviewBatch(runId, {
        reconciliation_ids: ids,
        action,
        note: note.trim() || undefined,
        actor: actor.trim(),
      });
      onDone();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-rule bg-desk px-4 py-2.5">
      <span className="text-[13px] text-ink">
        <span className="fig">{ids.length}</span> selected
      </span>
      <input
        value={actor}
        onChange={(e) => setActor(e.target.value)}
        placeholder="Initials"
        aria-label="Your initials"
        className="fig w-20 rounded-[2px] border border-rule bg-paper px-2 py-1 text-[12px] text-ink placeholder:text-ink-faint"
      />
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note for all selected"
        aria-label="Note applied to every selected case"
        className="min-w-0 flex-1 rounded-[2px] border border-rule bg-paper px-2 py-1 text-[12px] text-ink placeholder:text-ink-faint"
      />
      {["accept", "reject", "annotate", "escalate"].map((action) => (
        <button
          key={action}
          disabled={busy}
          onClick={() => record(action)}
          className="rounded-[2px] border border-rule bg-paper px-2.5 py-1 text-[12px] text-ink transition-colors hover:border-ink disabled:opacity-40"
        >
          {action.charAt(0).toUpperCase() + action.slice(1)}
        </button>
      ))}
      <button
        onClick={onCancel}
        className="text-[12px] text-trace underline underline-offset-2"
      >
        Cancel
      </button>
      {failure ? (
        <p className="w-full text-[12px] text-audit">{failure}</p>
      ) : null}
    </div>
  );
}
