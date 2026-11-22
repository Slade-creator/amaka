/** Shared small presentational primitives for AMAKA. */
import type { ReactNode } from "react";

/** Panel wrapper — clean hairline border, dark surface. */
export function Panel({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`panel ${className}`}>
      {children}
    </section>
  );
}

/** Panel header row: clean title + optional subtitle on the left, slot on the right. */
export function PanelHead({
  title,
  sub,
  right,
}: {
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[color:var(--border)] px-4 py-2.5">
      <div className="flex min-w-0 items-baseline gap-2.5">
        <h2 className="text-[12.5px] font-semibold tracking-[-0.01em] text-fg whitespace-nowrap">
          {title}
        </h2>
        {sub ? <span className="text-[11.5px] text-dim truncate">{sub}</span> : null}
      </div>
      {right ? <div className="flex items-center gap-2">{right}</div> : null}
    </div>
  );
}

/** Small "label / value" stat used in facility facts. */
export function FactRow({
  label,
  value,
  accent,
}: {
  label: string;
  value: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[color:var(--border)] py-2 last:border-b-0">
      <span className="text-[12px] text-dim">{label}</span>
      <span
        className={`num text-[12.5px] ${accent ? "text-lime font-medium" : "text-fg"}`}
        style={{ whiteSpace: "nowrap" }}
      >
        {value}
      </span>
    </div>
  );
}

/** AMAKA mark: AMAKA hexagon with a load spike crossing a dashed peak threshold. */
export function AmakaMark({ size = 48 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="14 9 68 78" aria-hidden="true" focusable="false" style={{ display: "block" }}>
      <polygon
        points="48,14 77,31 77,65 48,82 19,65 19,31"
        fill="rgb(var(--accent-rgb)/0.06)"
        stroke="var(--accent)"
        strokeWidth="3.2"
        strokeLinejoin="round"
      />
      <line x1="27" y1="40" x2="69" y2="40" stroke="var(--warn)" strokeWidth="1.6" strokeDasharray="3 2.5" opacity="0.85" />
      <polyline
        points="27,58 37,52 43,56 49,32 54,62 60,46 69,46"
        fill="none"
        stroke="var(--accent)"
        strokeWidth="3.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
