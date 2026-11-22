import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from "lucide-react";
import type { ReplayRow, Site } from "../types";
import { fmtAxisTick, fmtInt, fmtStamp, readinessColor } from "../lib/format";
import { readinessName } from "../lib/vocabulary";
import { buildTrace, highReadinessRuns, niceDomain, type Bounds } from "../lib/replay";
import { Segmented, tap } from "./ui";

type Props = {
  site: Site;
  rows: ReplayRow[];
  bounds: Bounds;
  cursor: number;
  rangeHours: number;
  playing: boolean;
  onRange: (h: number) => void;
  onScrub: (idx: number) => void;
  onStep: (delta: number) => void;
  onTogglePlay: () => void;
  onReset: () => void;
};

const RANGES = [
  { value: 24, label: "24H" },
  { value: 72, label: "72H" },
  { value: 168, label: "7D" },
];

/**
 * Phone load trace: actual load, forecast, 95% forecast range, peak threshold
 * and high-readiness shading. Tap the chart or drag the slider to move the
 * selected hour; the readout above the chart replaces hover tooltips.
 */
export default function MobileTrace({
  site,
  rows,
  bounds,
  cursor,
  rangeHours,
  playing,
  onRange,
  onScrub,
  onStep,
  onTogglePlay,
  onReset,
}: Props) {
  const threshold = site.load?.threshold_kw ?? 0;
  const data = useMemo(() => buildTrace(rows, bounds), [rows, bounds]);
  const domain = useMemo(() => niceDomain(rows, bounds, threshold), [rows, bounds, threshold]);
  const runs = useMemo(() => highReadinessRuns(rows, bounds), [rows, bounds]);
  const row = rows[cursor];
  const cursorT = data[cursor - bounds.ws]?.t;
  const diff = row ? row.actual_kw - row.hybrid_kw : 0;
  const over = row ? row.hybrid_kw > threshold && threshold > 0 : false;

  return (
    <div className="m-trace">
      <div className="m-trace-readout">
        <div className="m-trace-stamp num">{row ? fmtStamp(row.timestamp) : "—"}</div>
        <div className="m-trace-vals">
          <span>
            <i className="m-key is-actual" /> Actual <b className="num">{fmtInt(row?.actual_kw)} kW</b>
          </span>
          <span>
            <i className="m-key is-forecast" /> Forecast{" "}
            <b className={`num${over ? " is-critical" : ""}`}>{fmtInt(row?.hybrid_kw)} kW</b>
          </span>
        </div>
        {row ? (
          <div className="m-trace-meta">
            <span style={{ color: readinessColor(row.readiness_code) }}>
              R{row.readiness_code} {readinessName(row.readiness_code)}
            </span>
            <span className="num">
              {diff >= 0 ? "+" : "−"}
              {fmtInt(Math.abs(diff))} kW vs forecast
            </span>
            <span className="num">
              {fmtInt(row.temperature_c, 1)}°C · {fmtInt(row.humidity_pct)}% RH
            </span>
          </div>
        ) : null}
      </div>

      <div className="m-trace-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: -8 }}
            onClick={(e) => {
              const i = (e as { activeTooltipIndex?: number } | null)?.activeTooltipIndex;
              if (typeof i === "number") {
                tap();
                onScrub(bounds.ws + i);
              }
            }}
          >
            <CartesianGrid stroke="rgb(var(--white-rgb)/0.06)" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => fmtAxisTick(t, rangeHours)}
              tick={{ fill: "var(--dim)", fontSize: 10, fontFamily: "JetBrains Mono" }}
              tickLine={false}
              axisLine={{ stroke: "rgb(var(--white-rgb)/0.12)" }}
              minTickGap={36}
            />
            <YAxis
              domain={domain}
              tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v))}
              tick={{ fill: "var(--dim)", fontSize: 10, fontFamily: "JetBrains Mono" }}
              tickLine={false}
              axisLine={false}
              width={40}
            />
            {runs.map((r, i) => (
              <ReferenceArea key={i} x1={r.x1} x2={r.x2} fill="var(--warn)" fillOpacity={0.08} strokeOpacity={0} />
            ))}
            <Area dataKey="lower_kw" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
            <Area
              dataKey="band"
              stackId="band"
              stroke="none"
              fill="rgb(var(--accent-rgb)/0.16)"
              isAnimationActive={false}
            />
            {threshold > 0 ? (
              <ReferenceLine y={threshold} stroke="var(--warn)" strokeDasharray="5 4" strokeWidth={1.2} />
            ) : null}
            <Line
              dataKey="hybrid_kw"
              stroke="var(--accent)"
              strokeWidth={1.6}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line dataKey="actual_kw" stroke="var(--fg)" strokeWidth={1.8} dot={false} isAnimationActive={false} />
            {cursorT ? <ReferenceLine x={cursorT} stroke="var(--teal)" strokeWidth={1.4} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="m-trace-legend">
        <span>
          <i className="m-key is-actual" /> Actual load
        </span>
        <span>
          <i className="m-key is-forecast" /> Forecast
        </span>
        <span>
          <i className="m-key is-band" /> 95% range
        </span>
        <span>
          <i className="m-key is-threshold" /> Peak threshold
        </span>
      </div>

      <input
        className="m-slider"
        type="range"
        min={bounds.ws}
        max={Math.max(bounds.ws, bounds.we - 1)}
        step={1}
        value={Math.min(Math.max(cursor, bounds.ws), Math.max(bounds.ws, bounds.we - 1))}
        onChange={(e) => onScrub(Number(e.target.value))}
        aria-label="Selected hour"
      />

      <div className="m-trace-controls">
        <button type="button" className="m-icon-btn is-boxed" onClick={() => onStep(-1)} aria-label="Previous hour">
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`m-btn${playing ? " is-active" : ""}`}
          onClick={() => {
            tap();
            onTogglePlay();
          }}
        >
          {playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
          {playing ? "Pause" : "Replay"}
        </button>
        <button type="button" className="m-icon-btn is-boxed" onClick={() => onStep(1)} aria-label="Next hour">
          <ChevronRight size={20} aria-hidden="true" />
        </button>
        <button type="button" className="m-icon-btn is-boxed" onClick={onReset} aria-label="Back to the selected fleet hour">
          <RotateCcw size={17} aria-hidden="true" />
        </button>
        <div className="m-trace-range">
          <Segmented<number> label="Window" value={rangeHours} onChange={onRange} options={RANGES} />
        </div>
      </div>
    </div>
  );
}
