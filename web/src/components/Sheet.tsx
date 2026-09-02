import type { ReactNode } from "react";

/**
 * A sheet of working paper. Every screen is one.
 *
 * The index reference in the top-right corner is where auditors put it, and
 * it is what makes the evidence drawer read as a cross-referenced
 * sub-schedule rather than a modal that appeared from nowhere.
 */
export function Sheet({
  index,
  title,
  meta,
  actions,
  children,
}: {
  index: string;
  title: string;
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="sheet">
      <header className="flex items-start justify-between gap-4 border-b border-rule px-6 py-4">
        <div className="min-w-0">
          <h2 className="font-mono text-[15px] font-medium tracking-tight text-ink">
            {title}
          </h2>
          {meta ? <div className="mt-1 text-[12px] text-ink-muted">{meta}</div> : null}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {actions}
          <span className="index-ref">{index}</span>
        </div>
      </header>
      {children}
    </section>
  );
}

/** In accounting a double underline means "footed and verified". */
export function DoubleRule({ animate = false }: { animate?: boolean }) {
  return <div className={`double-rule ${animate ? "rule-draw" : ""}`} />;
}

export function Empty({ headline, body }: { headline: string; body: string }) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="font-mono text-[14px] text-ink">{headline}</p>
      <p className="mx-auto mt-2 max-w-sm text-[13px] text-ink-muted">{body}</p>
    </div>
  );
}
