import { useMemo } from "react";
import type { ExplainResponse, Site } from "../types";
import { fmtFeatureValue, fmtInt, fmtSigned } from "../lib/format";
import { Panel, PanelHead } from "./ui";

type Props = {
  site: Site;
  /** display stamp of the selected hour this SHAP snapshot explains */
  stamp: string;
  /** served hybrid forecast at the selected hour (from the replay series) */
  forecastKw: number | null;
  /** Stage-1 XGBoost prediction at the selected hour. */
  xgbKw?: number | null;
  /** v2 forecast horizon (hours). */
  horizon: number;
  data?: ExplainResponse | null;
  status: "idle" | "loading" | "ok" | "error";
  error?: string | null;
};

const MAX_BARS = 8;

/**
 * Clean SHAP Attribution Panel (Forecast Drivers tab).
 * Removed the 8 duplicate driver pill buttons that repeated the bar labels.
 */
export default function ExplainPanel({
  site,
  stamp,
  forecastKw,
  xgbKw,
  horizon,
  data,
  status,
  error,
}: Props) {
  const top = useMemo(() => (data?.top ?? []).slice(0, MAX_BARS), [data]);
  const maxAbs = useMemo(() => {
    const m = top.reduce((acc, t) => Math.max(acc, Math.abs(t.contribution_kw)), 0);
    return m > 0 ? m : 1;
  }, [top]);

  const base = data?.base_kw;
  const forecast = forecastKw ?? null;
  const xgb = xgbKw ?? null;
  const residual =
    typeof xgb === "number" && typeof forecast === "number" ? forecast - xgb : null;

  const busy = status === "loading";

  return (
    <Panel id="explainability" className="section-anchor">
      <PanelHead
        title={`Forecast Drivers (${horizon}h Ahead)`}
        sub={`SHAP attribution for ${site.label} at ${stamp}`}
        right={
          busy ? (
            <span className="text-[11px] text-[color:var(--color-amber)]">Updating…</span>
          ) : null
        }
      />

      <div className="grid gap-6 p-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Left: Two-stage model breakdown */}
        <div className="flex flex-col justify-between gap-4 border-b lg:border-b-0 lg:border-r border-[color:var(--border)] pb-4 lg:pb-0 lg:pr-5">
          <div className="flex flex-col gap-2.5">
            <div className="text-[11.5px] font-medium text-dim">Two-Stage Decomposition</div>

            <div className="rounded border border-[color:var(--border)] bg-[rgb(var(--white-rgb)/0.02)] p-3">
              <div className="flex items-baseline justify-between">
                <span className="text-[11.5px] text-dim">SHAP Base Load</span>
                <span className="num text-[13px] text-fg">{fmtInt(base, 0)} kW</span>
              </div>
              <div className="mt-2 flex items-baseline justify-between border-t border-[color:var(--border)] pt-2">
                <span className="text-[11.5px] text-dim">Stage-1 XGBoost</span>
                <span className="num text-[14px] font-medium text-fg">
                  {fmtInt(xgb ?? base, 0)} kW
                </span>
              </div>
              {typeof residual === "number" ? (
                <div className="mt-2 flex items-baseline justify-between border-t border-[color:var(--border)] pt-2">
                  <span className="text-[11.5px] text-dim">Stage-2 Residual</span>
                  <span
                    className="num text-[13px]"
                    style={{ color: residual >= 0 ? "var(--accent)" : "var(--warn)" }}
                  >
                    {fmtSigned(residual, 0)} kW
                  </span>
                </div>
              ) : null}
              <div className="mt-2 flex items-baseline justify-between border-t border-[color:var(--border)] pt-2">
                <span className="text-[12px] font-medium text-lime">Served Forecast</span>
                <span className="num text-[16px] font-semibold text-lime">
                  {fmtInt(forecast, 0)} kW
                </span>
              </div>
            </div>
          </div>

          <p className="text-[11.5px] leading-relaxed text-dim">
            Bars on the right show the top {MAX_BARS} inputs pushing the Stage-1 XGBoost
            forecast above or below the site's base load ({fmtInt(base, 0)} kW).
            {status === "error" && error ? (
              <span className="block mt-1 text-[color:var(--color-red)]">{error}</span>
            ) : null}
          </p>
        </div>

        {/* Right: Diverging SHAP bars */}
        <div
          className="min-w-0"
          style={{ opacity: busy && data ? 0.55 : 1, transition: "opacity .2s ease" }}
        >
          {top.length === 0 ? (
            <div className="flex h-full min-h-[180px] items-center justify-center rounded border border-dashed border-[color:var(--border)]">
              <span className="text-[12px] text-dim">
                {status === "loading" ? "Computing SHAP drivers…" : "No SHAP data for this hour"}
              </span>
            </div>
          ) : (
            <div>
              <div className="shap-row mb-1.5 px-1.5 py-0 text-[11px] text-dim">
                <span>Input Feature</span>
                <div className="flex justify-between">
                  <span>← Lowers load</span>
                  <span>Raises load →</span>
                </div>
                <span className="text-right">Effect (kW)</span>
              </div>
              {top.map((t) => {
                const c = t.contribution_kw;
                const up = c >= 0;
                const width = (Math.abs(c) / maxAbs) * 50;
                return (
                  <div key={t.feature} className="shap-row">
                    <div className="min-w-0 flex items-baseline justify-between gap-2 pr-2">
                      <span
                        className="truncate text-[12.5px] text-fg"
                        title={`${t.label} (${t.feature})`}
                      >
                        {t.label}
                      </span>
                      <span className="num text-[10.5px] text-dim shrink-0">
                        {fmtFeatureValue(t.value)}
                      </span>
                    </div>
                    <div className="shap-track">
                      <div className="shap-zero" />
                      <div
                        className={`shap-bar ${up ? "up" : "down"}`}
                        style={{ width: `${Math.max(1.5, width)}%` }}
                        role="img"
                        aria-label={`${t.label}: ${fmtSigned(c, 1)} kilowatts`}
                      />
                    </div>
                    <span
                      className="num text-right text-[12px] font-medium"
                      style={{ color: up ? "var(--accent)" : "var(--warn)" }}
                    >
                      {fmtSigned(c, 1)} kW
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
