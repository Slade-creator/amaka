import type { CSSProperties } from "react";
import { HORIZONS, isHorizon } from "../api";

type Props = {
  /** Currently selected forecast horizon (hours). */
  horizon: number;
  onChange: (h: number) => void;
  /** Offered horizons — normally `overview.available_horizons`. */
  available?: readonly number[];
  /** Tighter padding for dense bars (fleet top bar). */
  compact?: boolean;
  /** Active/accent colour — role accent on the map, lime in the console. */
  accent?: string;
  className?: string;
  /** Accessible name for the button group. */
  label?: string;
};

/**
 * v2 multi-horizon selector: `H1 H6 H24 H48`.
 * Four toggle buttons (never a dropdown), 10px mono, accent on the active
 * horizon with `aria-pressed` for screen readers. The forecast horizon is a
 * different concept from the chart's visible time window (24H/72H/7D/30D),
 * so this control always lives next to the horizon it describes.
 */
export default function HorizonSwitcher({
  horizon,
  onChange,
  available = HORIZONS,
  compact = false,
  accent = "var(--accent)",
  className = "",
  label = "Forecast horizon",
}: Props) {
  const opts = [...new Set(available.filter((h) => isHorizon(h)))];
  // v1 payloads offer no horizon choice — render nothing rather than a dead control.
  if (opts.length < 2) return null;

  const style = { "--hs-accent": accent } as CSSProperties;

  return (
    <div
      className={`hs-switch${compact ? " is-compact" : ""}${className ? ` ${className}` : ""}`}
      role="group"
      aria-label={label}
      style={style}
    >
      {opts.map((h) => {
        const active = h === horizon;
        return (
          <button
            key={h}
            type="button"
            className={`hs-btn${active ? " is-active" : ""}`}
            aria-pressed={active}
            title={`${h}-hour forecast`}
            onClick={() => onChange(h)}
          >
            H{h}
          </button>
        );
      })}
    </div>
  );
}
