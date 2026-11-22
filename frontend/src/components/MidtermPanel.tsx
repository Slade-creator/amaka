import { useEffect, useMemo, useRef, useState } from "react";
import {
  MIDTERM_HORIZONS_DAYS,
  errMessage,
  fetchSiteMidterm,
  isAbort,
} from "../api";
import { fmtInt, fmtPct, fmtZmw } from "../lib/format";
import type { MidtermModelMetrics, Site, SiteMidtermResponse } from "../types";
import { Panel, PanelHead } from "./ui";

type TargetKind = "daily_mean_kw" | "daily_peak_kw";

const HORIZON_NAMES: Record<number, string> = {
  7: "D7 · 1W",
  14: "D14 · 2W",
  30: "D30 · 1M",
  60: "D60 · 2M",
  90: "D90 · 3M",
};

const MODEL_ORDER: Array<{ key: string; label: string; desc: string }> = [
  {
    key: "hybrid",
    label: "Validation-Selected Hybrid",
    desc: "Served strategic model (XGBoost + gated Stage-2 residual learner)",
  },
  {
    key: "hybrid_ridge",
    label: "Hybrid · Ridge Residual",
    desc: "Stage-1 XGBoost + L2-regularized OOF seasonal/regime residual learner",
  },
  {
    key: "hybrid_hgb",
    label: "Hybrid · HGB Residual",
    desc: "Stage-1 XGBoost + HistGradientBoosting OOF residual learner",
  },
  {
    key: "xgb",
    label: "Stage-1 XGBoost",
    desc: "Direct regularized tree model with climatology-blended weather proxy",
  },
  {
    key: "sarimax_harmonic",
    label: "SARIMAX / Harmonic",
    desc: "Statistical baseline (Fourier annual harmonics + AR(1)/AR(7) lags)",
  },
  {
    key: "seasonal_naive_7d",
    label: "Seasonal Naive (7d)",
    desc: "Repeats observed daily load from the same day of week at origin",
  },
  {
    key: "persistence",
    label: "Persistence (last day)",
    desc: "Last observed daily load before forecast origin carried forward",
  },
  {
    key: "xgb_no_weather",
    label: "Ablation: No Weather",
    desc: "XGBoost without target-day climatology/weather features",
  },
  {
    key: "xgb_no_readiness",
    label: "Ablation: No Readiness",
    desc: "XGBoost without scheduled operational readiness features",
  },
];

export default function MidtermPanel({ site }: { site: Site }) {
  const [horizonDays, setHorizonDays] = useState<number>(30);
  const [target, setTarget] = useState<TargetKind>("daily_mean_kw");
  const [data, setData] = useState<SiteMidtermResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const cacheRef = useRef<Map<string, SiteMidtermResponse>>(new Map());

  useEffect(() => {
    const key = `${site.id}|${horizonDays}`;
    const cached = cacheRef.current.get(key);
    if (cached) {
      setData(cached);
      setLoading(false);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    let alive = true;
    setLoading(true);
    setError(null);
    fetchSiteMidterm(site.id, horizonDays, ctrl.signal)
      .then((res) => {
        if (!alive) return;
        cacheRef.current.set(key, res);
        setData(res);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive || isAbort(e)) return;
        setError(errMessage(e));
        setLoading(false);
      });
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [site.id, horizonDays]);

  const rows = data?.rows ?? [];
  const targetMetrics: Record<string, MidtermModelMetrics> = useMemo(() => {
    if (!data) return {};
    return target === "daily_mean_kw"
      ? data.metrics.daily_mean_kw
      : data.metrics.daily_peak_kw;
  }, [data, target]);

  const hyb = targetMetrics["hybrid"];
  const xgb = targetMetrics["xgb"];
  const sar = targetMetrics["sarimax_harmonic"];
  const stage2Name = (hyb?.selected_stage2 || "xgb").toUpperCase();

  const activeIdx =
    hoverIdx !== null && hoverIdx >= 0 && hoverIdx < rows.length
      ? hoverIdx
      : Math.max(0, rows.length - 1);
  const activeRow = rows[activeIdx];

  /* ---------------- SVG Chart Geometry ---------------- */
  const W = 920;
  const H = 260;
  const PAD = { l: 54, r: 18, t: 18, b: 28 };
  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;

  const chartGeom = useMemo(() => {
    if (rows.length === 0) return null;
    const isMean = target === "daily_mean_kw";
    const actuals = rows.map((r) => (isMean ? r.actual_mean_kw : r.actual_peak_kw));
    const hybrids = rows.map((r) => (isMean ? r.hybrid_mean_kw : r.hybrid_peak_kw));
    const xgbs = rows.map((r) => (isMean ? r.xgb_mean_kw : r.xgb_peak_kw));
    const lowers = rows.map((r) => (isMean ? r.lower_mean_kw : r.lower_peak_kw));
    const uppers = rows.map((r) => (isMean ? r.upper_mean_kw : r.upper_peak_kw));

    const allVals = [...actuals, ...lowers, ...uppers];
    const minY = Math.floor(Math.min(...allVals) * 0.94);
    const maxY = Math.ceil(Math.max(...allVals) * 1.04);
    const spanY = Math.max(1, maxY - minY);

    const xAt = (i: number) =>
      PAD.l + (rows.length > 1 ? (i / (rows.length - 1)) * plotW : plotW / 2);
    const yAt = (v: number) => PAD.t + plotH - ((v - minY) / spanY) * plotH;

    const linePath = (arr: number[]) =>
      arr
        .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`)
        .join(" ");

    const areaTop = uppers.map((v, i) => `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`);
    const areaBot = [...lowers]
      .reverse()
      .map((v, i) => `${xAt(rows.length - 1 - i).toFixed(1)},${yAt(v).toFixed(1)}`);
    const bandPolygon = `M${areaTop.join(" L")} L${areaBot.join(" L")} Z`;

    const ticksY = Array.from({ length: 5 }, (_, k) => {
      const val = minY + (spanY * k) / 4;
      return { val, y: yAt(val) };
    });

    return {
      actualPath: linePath(actuals),
      hybridPath: linePath(hybrids),
      xgbPath: linePath(xgbs),
      bandPolygon,
      ticksY,
      xAt,
      yAt,
      actuals,
      hybrids,
      xgbs,
    };
  }, [rows, target, plotW, plotH]);

  return (
    <section className="mt-3 flex flex-col gap-3">
      {/* Control bar */}
      <div className="panel flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[11px] uppercase tracking-wider text-dim font-medium">
            Strategic Horizon (1 Wk – 3 Mo)
          </span>
          <div className="hs-switch" role="group" aria-label="Mid-to-long-term horizon">
            {MIDTERM_HORIZONS_DAYS.map((d) => {
              const active = d === horizonDays;
              return (
                <button
                  key={d}
                  type="button"
                  className={`hs-btn${active ? " is-active" : ""}`}
                  aria-pressed={active}
                  onClick={() => setHorizonDays(d)}
                >
                  {HORIZON_NAMES[d] ?? `D${d}`}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-dim font-medium">
            Target
          </span>
          <div className="console-tabs" role="tablist" aria-label="Strategic target">
            <button
              type="button"
              role="tab"
              aria-selected={target === "daily_mean_kw"}
              className={`console-tab${target === "daily_mean_kw" ? " is-active" : ""}`}
              onClick={() => setTarget("daily_mean_kw")}
            >
              Daily Mean / Energy (kWh)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={target === "daily_peak_kw"}
              className={`console-tab${target === "daily_peak_kw" ? " is-active" : ""}`}
              onClick={() => setTarget("daily_peak_kw")}
            >
              Daily Peak Demand (kW)
            </button>
          </div>
        </div>
      </div>

      {/* 4 Strategic KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="panel px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wider">
            D{horizonDays} Forecast Accuracy
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="num text-[22px] font-semibold text-lime">
              {hyb ? `${fmtInt(hyb.rmse, 1)} kW` : "—"}
            </span>
            <span className="num text-[12px] text-fg">
              ({hyb ? fmtPct(hyb.mape, 2) : "—"} MAPE)
            </span>
          </div>
          <div className="mt-1 text-[11px] text-dim">
            Skill vs. Persistence:{" "}
            <span className="num text-fg">
              {hyb ? `+${hyb.skill_vs_persistence_pct.toFixed(1)}%` : "—"}
            </span>
          </div>
        </div>

        <div className="panel px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wider">
            30-Day Energy Budget Error
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="num text-[22px] font-semibold text-fg">
              {hyb ? fmtPct(hyb.window_30d_mape, 2) : "—"}
            </span>
            <span className="text-[11px] text-dim">rolling 30d MWh</span>
          </div>
          <div className="mt-1 text-[11px] text-dim">
            Net volume bias:{" "}
            <span className="num text-fg">
              {hyb
                ? `${hyb.cum_energy_bias_pct >= 0 ? "+" : ""}${hyb.cum_energy_bias_pct.toFixed(2)}%`
                : "—"}
            </span>
          </div>
        </div>

        <div className="panel px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wider">
            Monthly Peak Tariff Error
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="num text-[22px] font-semibold text-fg">
              {hyb ? fmtZmw(hyb.monthly_peak_mae_zmw) : "—"}
            </span>
            <span className="text-[11px] text-dim">/ month</span>
          </div>
          <div className="mt-1 text-[11px] text-dim">
            Billing peak MAE:{" "}
            <span className="num text-fg">
              {hyb ? `${fmtInt(hyb.monthly_peak_mae_kw, 1)} kW` : "—"}
            </span>{" "}
            (@ 120 ZMW/kW)
          </div>
        </div>

        <div className="panel px-4 py-3">
          <div className="text-[11px] text-dim uppercase tracking-wider">
            95% Interval Coverage & Stage 2
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="num text-[22px] font-semibold text-fg">
              {hyb ? `${hyb.picp_95.toFixed(1)}%` : "—"}
            </span>
            <span className="text-[11px] text-dim">
              (±{hyb ? fmtInt(hyb.interval_halfwidth_kw, 0) : "—"} kW)
            </span>
          </div>
          <div className="mt-1 text-[11px] text-dim">
            Selected learner:{" "}
            <span className="num text-lime font-medium">
              {stage2Name === "XGB" ? "Stage-1 XGBoost" : `Hybrid · ${stage2Name}`}
            </span>
          </div>
        </div>
      </div>

      {/* Daily Forecast Trace */}
      <Panel>
        <PanelHead
          title={`D${horizonDays} Strategic Forecast Trace — ${
            target === "daily_mean_kw"
              ? "Daily Mean Load (kW)"
              : "Daily Peak Demand (kW)"
          }`}
          sub={`${site.label} · 2025 H2 held-out test (${rows.length} days) · Climatology-blended weather proxy`}
          right={
            activeRow ? (
              <div className="flex items-center gap-3 text-[11.5px] num">
                <span className="text-dim">{activeRow.date}</span>
                <span>
                  Actual:{" "}
                  <b className="text-fg">
                    {fmtInt(
                      target === "daily_mean_kw"
                        ? activeRow.actual_mean_kw
                        : activeRow.actual_peak_kw,
                      1,
                    )}{" "}
                    kW
                  </b>
                </span>
                <span>
                  Hybrid:{" "}
                  <b className="text-lime">
                    {fmtInt(
                      target === "daily_mean_kw"
                        ? activeRow.hybrid_mean_kw
                        : activeRow.hybrid_peak_kw,
                      1,
                    )}{" "}
                    kW
                  </b>
                </span>
                {target === "daily_mean_kw" ? (
                  <span className="text-dim">
                    ({activeRow.hybrid_energy_mwh.toFixed(1)} MWh/d)
                  </span>
                ) : null}
              </div>
            ) : null
          }
        />
        <div className="px-4 py-3">
          {error ? (
            <div className="py-8 text-center text-[13px] text-red-400">{error}</div>
          ) : loading && !chartGeom ? (
            <div className="py-12 text-center text-[13px] text-dim">
              Loading D{horizonDays} strategic forecast…
            </div>
          ) : chartGeom ? (
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="w-full h-auto select-none overflow-visible"
              onMouseMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const relX = ((e.clientX - rect.left) / rect.width) * W - PAD.l;
                const idx = Math.round((relX / plotW) * (rows.length - 1));
                if (idx >= 0 && idx < rows.length) setHoverIdx(idx);
              }}
              onMouseLeave={() => setHoverIdx(null)}
            >
              {chartGeom.ticksY.map((t, i) => (
                <g key={i}>
                  <line
                    x1={PAD.l}
                    x2={W - PAD.r}
                    y1={t.y}
                    y2={t.y}
                    stroke="rgb(var(--white-rgb)/0.06)"
                  />
                  <text
                    x={PAD.l - 8}
                    y={t.y + 4}
                    textAnchor="end"
                    fill="rgb(var(--white-rgb)/0.45)"
                    fontSize="10"
                    fontFamily="monospace"
                  >
                    {Math.round(t.val)}
                  </text>
                </g>
              ))}

              {/* 95% interval band */}
              <path d={chartGeom.bandPolygon} fill="rgb(var(--accent-rgb)/0.11)" />

              {/* Stage-1 XGBoost dashed trace */}
              <path
                d={chartGeom.xgbPath}
                fill="none"
                stroke="rgb(var(--info-rgb)/0.65)"
                strokeWidth="1.3"
                strokeDasharray="3 3"
              />

              {/* Actual daily trace */}
              <path
                d={chartGeom.actualPath}
                fill="none"
                stroke="rgb(var(--white-rgb)/0.78)"
                strokeWidth="1.6"
              />

              {/* Selected Hybrid trace */}
              <path
                d={chartGeom.hybridPath}
                fill="none"
                stroke="var(--accent)"
                strokeWidth="2.1"
              />

              {/* Hover cursor */}
              {activeIdx >= 0 && activeIdx < rows.length ? (
                <g>
                  <line
                    x1={chartGeom.xAt(activeIdx)}
                    x2={chartGeom.xAt(activeIdx)}
                    y1={PAD.t}
                    y2={H - PAD.b}
                    stroke="rgb(var(--white-rgb)/0.25)"
                    strokeDasharray="2 2"
                  />
                  <circle
                    cx={chartGeom.xAt(activeIdx)}
                    cy={chartGeom.yAt(chartGeom.hybrids[activeIdx])}
                    r={4}
                    fill="var(--accent)"
                  />
                  <circle
                    cx={chartGeom.xAt(activeIdx)}
                    cy={chartGeom.yAt(chartGeom.actuals[activeIdx])}
                    r={3.5}
                    fill="var(--white)"
                  />
                </g>
              ) : null}

              {/* X-axis month markers */}
              {[0, 30, 61, 91, 122, 152, rows.length - 1]
                .filter((idx) => idx >= 0 && idx < rows.length)
                .map((idx) => (
                  <text
                    key={idx}
                    x={chartGeom.xAt(idx)}
                    y={H - 6}
                    textAnchor="middle"
                    fill="rgb(var(--white-rgb)/0.45)"
                    fontSize="10"
                    fontFamily="monospace"
                  >
                    {rows[idx].date.slice(5)}
                  </text>
                ))}
            </svg>
          ) : null}

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-dim border-t border-[color:var(--border)] pt-2">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <i className="inline-block w-3 h-0.5 bg-white/80" /> Actual Daily Load
              </span>
              <span className="flex items-center gap-1.5">
                <i className="inline-block w-3 h-0.5 bg-[color:var(--accent)]" /> Selected Hybrid (D
                {horizonDays})
              </span>
              <span className="flex items-center gap-1.5">
                <i className="inline-block w-3 h-0.5 bg-blue-400/80" /> Stage-1 XGBoost
              </span>
              <span className="flex items-center gap-1.5">
                <i className="inline-block w-3 h-2 bg-[rgb(var(--accent-rgb)/0.2)] border border-[rgb(var(--accent-rgb)/0.4)]" />{" "}
                95% Prediction Interval
              </span>
            </div>
            <span>
              {xgb && sar
                ? `Hybrid beats SARIMAX baseline by ${fmtInt(sar.rmse - (hyb?.rmse ?? 0), 1)} kW RMSE`
                : ""}
            </span>
          </div>
        </div>
      </Panel>

      {/* Full Mid/Long-Term Model & Baseline Comparison Table */}
      <Panel>
        <PanelHead
          title={`Mid/Long-Term Model & Ablation Evaluation (D${horizonDays} · ${
            target === "daily_mean_kw" ? "Daily Mean kW" : "Daily Peak kW"
          })`}
          sub={`${site.label} · Held-out 2025 H2 evaluation across statistical, ML, hybrid and ablation models`}
        />
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th scope="col">Model / Baseline</th>
                <th scope="col" className="r">
                  RMSE
                </th>
                <th scope="col" className="r">
                  MAE
                </th>
                <th scope="col" className="r">
                  MAPE
                </th>
                <th scope="col" className="r">
                  30d Vol Err
                </th>
                <th scope="col" className="r">
                  Monthly Peak Err
                </th>
                <th scope="col" className="r">
                  Skill vs Persist
                </th>
                <th scope="col">Notes</th>
              </tr>
            </thead>
            <tbody>
              {MODEL_ORDER.map(({ key, label, desc }) => {
                const m = targetMetrics[key];
                if (!m) return null;
                const isServed = key === "hybrid";
                return (
                  <tr key={key} className={isServed ? "is-active" : undefined}>
                    <td className={isServed ? "font-medium text-lime" : "text-fg"}>
                      {isServed
                        ? `Hybrid (${
                            stage2Name === "XGB" ? "XGB" : stage2Name
                          } selected)`
                        : label}
                    </td>
                    <td className="num r">{fmtInt(m.rmse, 1)} kW</td>
                    <td className="num r">{fmtInt(m.mae, 1)} kW</td>
                    <td className="num r">{fmtPct(m.mape, 2)}</td>
                    <td className="num r">{fmtPct(m.window_30d_mape, 2)}</td>
                    <td className="num r">{fmtZmw(m.monthly_peak_mae_zmw)}</td>
                    <td className="num r">
                      {m.skill_vs_persistence_pct >= 0 ? "+" : ""}
                      {m.skill_vs_persistence_pct.toFixed(1)}%
                    </td>
                    <td className="text-dim">{desc}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </section>
  );
}
