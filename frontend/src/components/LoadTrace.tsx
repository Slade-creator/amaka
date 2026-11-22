import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Pause, Play } from "lucide-react";
import type { ReplayRow, Site } from "../types";
import { Panel, PanelHead } from "./ui";
import { fmtAxisTick, fmtInt, fmtStamp, fmtStampIso, readinessColor } from "../lib/format";
import { readinessName } from "../lib/vocabulary";
import { buildTrace, highReadinessRuns, niceDomain, readinessRuns, type Bounds } from "../lib/replay";

type Props = {
  site: Site;
  rows: ReplayRow[];
  bounds: Bounds;
  cursor: number;
  rangeHours: number;
  horizon: number;
  playing: boolean;
  onRange: (hours: number) => void;
  onScrub: (index: number) => void;
  onTogglePlay: () => void;
  error?: string | null;
  onRetry?: () => void;
};

const RANGES: Array<{ hours: number; label: string }> = [
  { hours: 24, label: "24H" },
  { hours: 72, label: "72H" },
  { hours: 168, label: "7D" },
  { hours: 720, label: "30D" },
];

function TraceTooltip({ active, payload, threshold }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  const rows: Array<{ k: string; v: string; c?: string }> = [
    { k: "Actual load", v: `${fmtInt(p.actual_kw, 1)} kW`, c: "var(--fg)" },
    { k: "Forecast", v: `${fmtInt(p.hybrid_kw, 1)} kW`, c: "var(--accent)" },
    {
      k: "95% range",
      v: `${fmtInt(p.lower_kw, 0)} – ${fmtInt(p.lower_kw + p.band, 0)} kW`,
      c: "rgb(var(--accent-rgb)/0.75)",
    },
    { k: "Peak threshold", v: `${fmtInt(threshold, 0)} kW`, c: "var(--warn)" },
    {
      k: "Readiness",
      v: `R${p.readiness_code} ${readinessName(p.readiness_code)}`,
      c: readinessColor(p.readiness_code),
    },
    {
      k: "Weather",
      v: `${fmtInt(p.temperature_c, 1)}°C · ${fmtInt(p.humidity_pct, 0)}% RH · ${fmtInt(p.radiation_wm2, 0)} W/m²`,
    },
  ];
  return (
    <div
      style={{
        background: "rgb(var(--panel-rgb)/0.96)",
        border: "1px solid rgb(var(--white-rgb)/0.14)",
        borderRadius: 6,
        padding: "9px 12px",
        minWidth: 224,
        boxShadow: "0 10px 28px rgb(var(--black-rgb)/0.55)",
      }}
    >
      <div
        className="num"
        style={{
          fontSize: 11,
          color: "var(--accent)",
          borderBottom: "1px solid rgb(var(--white-rgb)/0.08)",
          paddingBottom: 5,
          marginBottom: 5,
        }}
      >
        {fmtStampIso(p.ts)}
      </div>
      {rows.map((r) => (
        <div
          key={r.k}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 14,
            fontSize: 11,
            lineHeight: "17px",
          }}
        >
          <span style={{ color: "var(--dim)" }}>{r.k}</span>
          <span
            className="num"
            style={{ color: r.c ?? "var(--fg)", fontVariantNumeric: "tabular-nums" }}
          >
            {r.v}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Streamlined Hero Load Trace:
 * - Inline legend in header + range tabs
 * - Unified replay & environment bar (scrubber + readiness + compact weather)
 * - Clean chart + slim readiness timeline bar at the bottom
 */
export default function LoadTrace({
  site,
  rows,
  bounds,
  cursor,
  rangeHours,
  horizon,
  playing,
  onRange,
  onScrub,
  onTogglePlay,
  error,
  onRetry,
}: Props) {
  const trace = useMemo(() => buildTrace(rows, bounds), [rows, bounds]);
  const domain = useMemo(
    () => niceDomain(rows, bounds, site.load?.threshold_kw ?? 0),
    [rows, bounds, site.load?.threshold_kw],
  );
  const runs = useMemo(() => highReadinessRuns(rows, bounds), [rows, bounds]);
  const stripRuns = useMemo(() => readinessRuns(rows, bounds), [rows, bounds]);
  const threshold = site.load?.threshold_kw ?? 0;
  const cursorRow = rows[cursor];
  const hasRows = trace.length > 0;
  const cursorOffset = Math.min(trace.length - 1, Math.max(0, cursor - bounds.ws));
  const cursorT = hasRows ? trace[cursorOffset]?.t : undefined;

  return (
    <Panel className="min-w-0">
      <PanelHead
        title={`Load Trace (${horizon}h Forecast)`}
        sub={
          <span className="hidden sm:inline-flex items-center gap-3.5 ml-2 text-[11px] text-dim">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-[2px] bg-[color:var(--fg)]" /> Actual
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-[2px] border-t-2 border-dashed border-[color:var(--accent)]" />{" "}
              Forecast
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2 bg-[rgb(var(--accent-rgb)/0.25)] rounded-[1px]" />{" "}
              95% Range
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-[2px] border-t border-dashed border-[color:var(--warn)]" />{" "}
              Threshold
            </span>
          </span>
        }
        right={
          <div className="range-tabs" role="group" aria-label="Visible range">
            {RANGES.map((r) => (
              <button
                key={r.hours}
                type="button"
                className={rangeHours === r.hours ? "is-active" : undefined}
                aria-pressed={rangeHours === r.hours}
                onClick={() => onRange(r.hours)}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />

      {/* Unified replay controls + selected hour telemetry */}
      <div className="flex flex-wrap items-center gap-3 border-b border-[color:var(--border)] px-4 py-2">
        <button
          type="button"
          className={playing ? "btn btn-lime btn-compact" : "btn btn-compact"}
          onClick={onTogglePlay}
          aria-pressed={playing}
          aria-label={playing ? "Pause replay" : "Play replay"}
        >
          {playing ? <Pause size={11} aria-hidden="true" /> : <Play size={11} aria-hidden="true" />}
          {playing ? "Pause" : "Replay"}
        </button>

        <div className="flex items-center gap-2">
          {playing ? <span className="live-dot" aria-hidden="true" /> : null}
          <span
            className="num text-[12px]"
            style={{ color: playing ? "var(--accent)" : "var(--fg)" }}
            aria-live="off"
          >
            {cursorRow ? fmtStamp(cursorRow.timestamp) : "—"}
          </span>
        </div>

        <div className="flex min-w-[180px] flex-1 items-center gap-2.5">
          <input
            className="scrub flex-1"
            type="range"
            min={bounds.ws}
            max={Math.max(bounds.ws, bounds.we - 1)}
            step={1}
            value={Math.min(Math.max(cursor, bounds.ws), Math.max(bounds.ws, bounds.we - 1))}
            onChange={(e) => onScrub(Number(e.target.value))}
            aria-label="Replay hour slider"
            aria-valuetext={cursorRow ? fmtStamp(cursorRow.timestamp) : "no data"}
          />
        </div>

        {cursorRow ? (
          <div className="hidden md:flex items-center gap-3 text-[11px] text-dim num">
            <span
              className="px-1.5 py-0.5 rounded text-[10px]"
              style={{
                color: readinessColor(cursorRow.readiness_code),
                background: "rgb(var(--white-rgb)/0.04)",
              }}
            >
              R{cursorRow.readiness_code} {readinessName(cursorRow.readiness_code)}
            </span>
            <span>{fmtInt(cursorRow.temperature_c, 1)}°C</span>
            <span>{fmtInt(cursorRow.humidity_pct, 0)}% RH</span>
            <span>{fmtInt(cursorRow.radiation_wm2, 0)} W/m²</span>
          </div>
        ) : null}
      </div>

      {/* Chart plot */}
      <div className="px-2 pb-1 pt-2">
        {hasRows ? (
          <div className="load-plot" style={{ width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={trace} margin={{ top: 8, right: 36, bottom: 2, left: 0 }}>
                <CartesianGrid stroke="rgb(var(--white-rgb)/0.045)" vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(v: number) => fmtAxisTick(v, rangeHours)}
                  tick={{ fill: "var(--muted-2)", fontSize: 10.5, fontFamily: "var(--font-mono)" }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={64}
                  tickMargin={6}
                />
                <YAxis
                  domain={domain}
                  tickFormatter={(v: number) => fmtInt(v, 0)}
                  tick={{ fill: "var(--muted-2)", fontSize: 10.5, fontFamily: "var(--font-mono)" }}
                  tickLine={false}
                  axisLine={false}
                  width={52}
                />
                {runs.map((r) => (
                  <ReferenceArea
                    key={`s-${r.x1}`}
                    x1={r.x1}
                    x2={r.x2}
                    fill="var(--warn)"
                    fillOpacity={0.05}
                    ifOverflow="hidden"
                  />
                ))}
                <Tooltip
                  content={<TraceTooltip threshold={threshold} />}
                  cursor={{ stroke: "rgb(var(--accent-rgb)/0.35)", strokeWidth: 1 }}
                  wrapperStyle={{ outline: "none", zIndex: 5 }}
                />
                <ReferenceLine
                  y={threshold}
                  stroke="var(--warn)"
                  strokeDasharray="4 4"
                  strokeWidth={1}
                  strokeOpacity={0.65}
                  label={
                    {
                      value: `${fmtInt(threshold, 0)} kW`,
                      position: "insideTopRight",
                      fill: "var(--warn)",
                      fontSize: 10,
                      fontFamily: "var(--font-mono)",
                    } as any
                  }
                />
                <Area
                  dataKey="lower_kw"
                  stackId="band"
                  stroke="none"
                  fill="transparent"
                  isAnimationActive={false}
                  dot={false}
                />
                <Area
                  dataKey="band"
                  stackId="band"
                  stroke="none"
                  fill="var(--accent)"
                  fillOpacity={0.09}
                  isAnimationActive={false}
                  dot={false}
                />
                <Line
                  dataKey="actual_kw"
                  stroke="var(--fg)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 3, fill: "var(--fg)", stroke: "var(--bg)" }}
                  isAnimationActive={false}
                />
                <Line
                  dataKey="hybrid_kw"
                  stroke="var(--accent)"
                  strokeWidth={1.75}
                  strokeDasharray="6 4"
                  dot={false}
                  activeDot={{ r: 3, fill: "var(--accent)", stroke: "var(--bg)" }}
                  isAnimationActive={false}
                />
                {cursorT !== undefined && cursorRow ? (
                  <>
                    <ReferenceLine
                      x={cursorT}
                      stroke="rgb(var(--accent-rgb)/0.65)"
                      strokeWidth={1}
                      ifOverflow="hidden"
                    />
                    <ReferenceDot
                      x={cursorT}
                      y={cursorRow.actual_kw}
                      r={3.5}
                      fill="var(--fg)"
                      stroke="var(--bg)"
                      strokeWidth={1.5}
                      ifOverflow="hidden"
                    />
                    <ReferenceDot
                      x={cursorT}
                      y={cursorRow.hybrid_kw}
                      r={3.5}
                      fill="var(--accent)"
                      stroke="var(--bg)"
                      strokeWidth={1.5}
                      ifOverflow="hidden"
                    />
                  </>
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-[320px] flex-col items-center justify-center gap-2 px-4 text-center">
            <p className="text-[12px] font-medium text-fg">
              {error ? "Site data unavailable" : "Loading site series…"}
            </p>
            {error ? <p className="text-[11.5px] text-dim max-w-[380px]">{error}</p> : null}
            {error && onRetry ? (
              <button type="button" className="btn btn-compact mt-1" onClick={onRetry}>
                Retry
              </button>
            ) : null}
          </div>
        )}
      </div>

      {/* Slim readiness timeline bar at the bottom of the plot */}
      <div className="px-4 pb-3 pt-1">
        <div
          className="strip"
          role="img"
          aria-label={
            cursorRow
              ? `Readiness timeline; selected hour is ${readinessName(cursorRow.readiness_code)}`
              : "Readiness timeline"
          }
        >
          {stripRuns.map((r) => (
            <span
              key={r.startIdx}
              style={{
                flexGrow: r.endIdx - r.startIdx + 1,
                flexBasis: 0,
                background: readinessColor(r.code),
              }}
              title={`${rows[r.startIdx] ? fmtStampIso(rows[r.startIdx].timestamp) : ""} · ${r.label} (R${r.code})`}
            />
          ))}
        </div>
      </div>
    </Panel>
  );
}
