import { TICKS, Tick, type TickKind } from "./Tick";

/**
 * The legend and the filter are the same object.
 *
 * A working paper's tick legend is how you navigate it, so making the legend
 * the control is the honest interaction — not a decorative key sitting beside
 * a separate filter bar.
 */
export function TickLegend({
  active,
  counts,
  onToggle,
}: {
  active: TickKind | null;
  counts: Partial<Record<TickKind, number>>;
  onToggle: (kind: TickKind | null) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 border-b border-rule px-4 py-2.5">
      <span className="label mr-2 py-1">Tick legend</span>
      {TICKS.map(({ kind, name, meaning }) => {
        const count = counts[kind] ?? 0;
        const isActive = active === kind;
        return (
          <button
            key={kind}
            type="button"
            disabled={count === 0}
            onClick={() => onToggle(isActive ? null : kind)}
            title={meaning}
            aria-pressed={isActive}
            className={`flex items-center gap-1.5 rounded-[2px] border px-2 py-1 text-[12px] transition-colors disabled:opacity-35 ${
              isActive
                ? "border-ink bg-ink text-paper"
                : "border-transparent text-ink-muted hover:border-rule hover:bg-desk"
            }`}
          >
            <Tick kind={kind} tone={isActive ? "inherit" : undefined} />
            <span>{name}</span>
            <span
              className={`fig text-[11px] ${
                isActive ? "opacity-70" : "text-ink-faint"
              }`}
            >
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
