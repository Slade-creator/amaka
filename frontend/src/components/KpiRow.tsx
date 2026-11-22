import type { ReactNode } from "react";
import type { ReplayRow, Site } from "../types";
import { fmtInt, fmtPct, fmtZmw } from "../lib/format";
import { changePhrase } from "../lib/vocabulary";

type Props = {
  site: Site;
  cursorRow?: ReplayRow;
  /** max hybrid_kw over the next 24 rows; null when no future rows exist */
  peak24: number | null;
  /** v2 forecast horizon (hours) — labels the forecast-error card. */
  horizon: number;
};

function Card({
  label,
  value,
  unit,
  context,
  tone,
}: {
  label: string;
  value: string;
  unit?: string;
  context: ReactNode;
  tone?: "lime" | "amber" | "red";
}) {
  return (
    <div className="kpi">
      <div className="label mb-1.5">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span
          className={`kpi-val ${
            tone === "red"
              ? "is-red"
              : tone === "amber"
                ? "is-amber"
                : tone === "lime"
                  ? "is-lime"
                  : ""
          }`}
        >
          {value}
        </span>
        {unit ? <span className="num text-[11.5px] text-dim">{unit}</span> : null}
      </div>
      <div className="num mt-1.5 text-[11px] text-dim truncate">{context}</div>
    </div>
  );
}

/**
 * Clean 4-column KPI strip with one concise context line per metric.
 */
export default function KpiRow({ site, cursorRow, peak24, horizon }: Props) {
  const actual = cursorRow?.actual_kw;
  const hybrid = cursorRow?.hybrid_kw;
  const delta =
    typeof actual === "number" && typeof hybrid === "number" ? actual - hybrid : null;

  const threshold = site.load?.threshold_kw ?? 0;
  const overThreshold = typeof peak24 === "number" && threshold > 0 && peak24 > threshold;
  const nearThreshold =
    typeof peak24 === "number" && threshold > 0 && peak24 >= threshold * 0.97;
  const peakTone = overThreshold ? "red" : nearThreshold ? "amber" : undefined;

  const m = site.metrics;
  const c = site.cost;

  return (
    <div className="kpi-grid mt-3">
      <Card
        label="Actual Load"
        value={fmtInt(Math.round(actual ?? NaN))}
        unit="kW"
        context={changePhrase(delta, "forecast")}
      />
      <Card
        label="Next 24h Peak"
        value={fmtInt(Math.round(peak24 ?? NaN))}
        unit="kW"
        tone={peakTone}
        context={
          typeof peak24 === "number" && threshold > 0
            ? peak24 > threshold
              ? `${fmtInt(Math.round(peak24 - threshold))} kW over threshold`
              : `${fmtInt(Math.round(threshold - peak24))} kW headroom`
            : `Threshold ${fmtInt(Math.round(threshold))} kW`
        }
      />
      <Card
        label={`Forecast Error (H${horizon})`}
        value={fmtPct(m?.hyb_mape, 2)}
        unit="MAPE"
        context={`MAE ${fmtInt(m?.hyb_mae, 1)} kW · RMSE ${fmtInt(m?.hyb_rmse, 1)} kW`}
      />
      <Card
        label="Est. Monthly Saving"
        value={fmtZmw(c?.monthly_saving_zmw)}
        tone="lime"
        context={`${fmtPct(c?.saving_pct, 1)} of baseline · ${fmtZmw(c?.annual_saving_zmw)}/yr`}
      />
    </div>
  );
}
