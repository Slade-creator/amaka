import type { ReactNode } from "react";
import { AmakaMark } from "./ui";
import HorizonSwitcher from "./HorizonSwitcher";

type Props = {
  /** "ok" | "down" | "checking" — backend health dot. */
  apiStatus: "ok" | "down" | "checking";
  /** Replay cursor label, e.g. "09 SEP 2025 · 18:00". */
  stamp?: string;
  /** Role switcher rendered in the top-right bar. */
  roleBadge?: ReactNode;
  /** Active forecast horizon (1/6/24/48h). */
  horizon?: number;
  availableHorizons?: number[];
  onHorizonChange?: (h: number) => void;
  onBackToFleet?: () => void;
  /** Extra tool buttons (satellite, alerts, data sources). */
  tools?: ReactNode;
};

/**
 * Clean 52px top command bar:
 * Brand on the left, horizon selector + replay timestamp + role switcher on the right.
 */
export default function Header({
  apiStatus,
  stamp,
  roleBadge,
  horizon,
  availableHorizons,
  onHorizonChange,
  onBackToFleet,
  tools,
}: Props) {
  const dotClass = apiStatus === "down" ? "status-dot down" : "status-dot ok";

  return (
    <header className="app-header">
      <div className="flex min-w-0 items-center gap-2.5">
        <button
          type="button"
          onClick={onBackToFleet}
          className="flex items-center gap-2.5 bg-transparent border-0 p-0 cursor-pointer text-left"
          title="Return to Fleet Overview"
        >
          <AmakaMark size={22} />
          <span
            className="brand-label text-[13.5px] font-semibold text-fg"
            style={{ letterSpacing: "0.2em" }}
          >
            AMAKA
          </span>
        </button>
        <span className="header-divider h-[15px] w-[1px] bg-[color:var(--border)]" aria-hidden="true" />
        <span className="header-subtitle text-[12.5px] font-medium text-dim">Site Console</span>
      </div>

      <div className="header-actions flex items-center gap-3.5">
        {tools}
        {typeof horizon === "number" && onHorizonChange ? (
          <HorizonSwitcher
            horizon={horizon}
            onChange={onHorizonChange}
            available={availableHorizons}
            compact
          />
        ) : null}

        {stamp ? (
          <span className="header-stamp num text-[11.5px] text-dim" style={{ letterSpacing: "0.04em" }}>
            {stamp}
            <span className="ml-1 text-[10px] text-[color:var(--color-muted)]">CAT</span>
          </span>
        ) : null}

        {apiStatus === "down" ? (
          <span className="flex items-center gap-1.5" title="Data link offline">
            <span className={dotClass} aria-hidden="true" />
            <span className="text-[11px] text-[color:var(--color-red)]">Offline</span>
          </span>
        ) : null}

        {roleBadge}
      </div>
    </header>
  );
}
