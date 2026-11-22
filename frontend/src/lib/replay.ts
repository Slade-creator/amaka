/**
 * Replay-window maths — pure helpers shared by App and the load trace.
 * The visible window ends at the cursor (clamped) so the trace always shows
 * "history up to now". While replay runs, the window is frozen so the cursor
 * sweeps across it and loops within it.
 */

import { parseTs } from "./format";
import { readinessName } from "./vocabulary";
import type { ReadinessRun, ReplayRow, Site } from "../types";

export type Bounds = { ws: number; we: number };

/** Index nearest to a site's demo_anchor so the boot view shows a surge. */
export function anchorIndex(rows: ReplayRow[], anchor: string | undefined): number {
  if (rows.length === 0) return 0;
  if (!anchor) return Math.floor(rows.length / 2);
  const target = parseTs(anchor);
  if (!target) return Math.floor(rows.length / 2);
  let best = 0;
  let bestDiff = Infinity;
  for (let i = 0; i < rows.length; i++) {
    const d = Math.abs(parseTs(rows[i].timestamp) - target);
    if (d < bestDiff) {
      bestDiff = d;
      best = i;
      if (d === 0) break;
    }
  }
  return best;
}

/**
 * Window of `rangeHours` rows anchored so the cursor sits at ~85% of the
 * window — full history behind it plus a little forward context (so a surge
 * at the cursor is never clipped at the right edge). Clamped to the series.
 */
export function deriveBounds(cursor: number, len: number, rangeHours: number): Bounds {
  if (len <= 0) return { ws: 0, we: 0 };
  const rl = Math.min(Math.max(rangeHours, 2), len);
  const tail = Math.max(1, Math.round(rl * 0.15));
  let we = cursor + 1 + tail;
  let ws = we - rl;
  if (ws < 0) {
    ws = 0;
    we = Math.min(len, rl);
  }
  if (we > len) {
    we = len;
    ws = Math.max(0, len - rl);
  }
  return { ws, we };
}

/** Point data for the Recharts composed chart (band pre-split for stacking). */
export type TracePoint = {
  t: number; // epoch ms — the x axis
  ts: string; // original timestamp, for the tooltip
  actual_kw: number;
  hybrid_kw: number;
  lower_kw: number;
  band: number; // upper - lower (stacked on top of lower → the 95% interval)
  readiness_code: number;
  readiness_label: string;
  temperature_c: number;
  humidity_pct: number;
  radiation_wm2: number;
  cloud_cover_pct: number;
};

export function buildTrace(rows: ReplayRow[], b: Bounds): TracePoint[] {
  const out: TracePoint[] = [];
  for (let i = b.ws; i < b.we; i++) {
    const r = rows[i];
    if (!r) continue;
    const lower = Math.min(r.lower_kw, r.upper_kw);
    const upper = Math.max(r.lower_kw, r.upper_kw);
    out.push({
      t: parseTs(r.timestamp) || i * 3_600_000,
      ts: r.timestamp,
      actual_kw: r.actual_kw,
      hybrid_kw: r.hybrid_kw,
      lower_kw: lower,
      band: Math.max(0, upper - lower),
      readiness_code: r.readiness_code,
      readiness_label: r.readiness_label,
      temperature_c: r.temperature_c,
      humidity_pct: r.humidity_pct,
      radiation_wm2: r.radiation_wm2,
      cloud_cover_pct: r.cloud_cover_pct,
    });
  }
  return out;
}

/** Contiguous high-readiness runs (R1–R2) inside the window (chart shading). */
export function highReadinessRuns(rows: ReplayRow[], b: Bounds): Array<{ x1: number; x2: number; count: number }> {
  const runs: Array<{ x1: number; x2: number; count: number }> = [];
  let open: { x1: number; x2: number; count: number } | null = null;
  for (let i = b.ws; i < b.we; i++) {
    const r = rows[i];
    if (!r) continue;
    const t = parseTs(r.timestamp) || i * 3_600_000;
    if (r.readiness_code <= 2) {
      if (open) {
        open.x2 = t;
        open.count += 1;
      } else {
        open = { x1: t, x2: t, count: 1 };
      }
    } else if (open) {
      runs.push(open);
      open = null;
    }
  }
  if (open) runs.push(open);
  // widen single-point runs so a 1h surge is still visible on the axis
  return runs.map((r) => (r.count === 1 ? { ...r, x1: r.x1 - 1_800_000, x2: r.x2 + 1_800_000 } : r));
}

/** Compressed readiness segments for the strip below the chart. */
export function readinessRuns(rows: ReplayRow[], b: Bounds): ReadinessRun[] {
  const runs: ReadinessRun[] = [];
  for (let i = b.ws; i < b.we; i++) {
    const r = rows[i];
    if (!r) continue;
    const last = runs[runs.length - 1];
    if (last && last.code === r.readiness_code) {
      last.endIdx = i;
    } else {
      runs.push({
        startIdx: i,
        endIdx: i,
        code: r.readiness_code,
        label: readinessName(r.readiness_code),
      });
    }
  }
  return runs;
}

/** Max hybrid in the next `ahead` rows (the 24h projected-peak KPI). */
export function projectedPeak(rows: ReplayRow[], cursor: number, ahead = 24): number | null {
  if (rows.length === 0) return null;
  const end = Math.min(rows.length, cursor + ahead);
  let peak = -Infinity;
  for (let i = cursor; i < end; i++) {
    const v = rows[i]?.hybrid_kw;
    if (typeof v === "number" && v > peak) peak = v;
  }
  return Number.isFinite(peak) ? peak : null;
}

function niceStep(range: number): number {
  if (!(range > 0)) return 1;
  const raw = range / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

/** Padded, rounded [min,max] for the Y axis over the visible trace. */
export function niceDomain(
  rows: ReplayRow[],
  b: Bounds,
  threshold: number,
): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (let i = b.ws; i < b.we; i++) {
    const r = rows[i];
    if (!r) continue;
    min = Math.min(min, r.lower_kw, r.actual_kw, r.hybrid_kw);
    max = Math.max(max, r.upper_kw, r.actual_kw, r.hybrid_kw);
  }
  if (threshold > 0) {
    min = Math.min(min, threshold);
    max = Math.max(max, threshold);
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) return [min - 1, max + 1];
  const pad = (max - min) * 0.06;
  const step = niceStep(max - min + 2 * pad);
  const rawLo = Math.floor((min - pad) / step) * step;
  const lo = rawLo < 0 ? 0 : rawLo;
  const hi = Math.ceil((max + pad) / step) * step;
  return [lo, hi > lo ? hi : lo + step];
}

/** 0..1 normalised load for the background intensity layer. */
export function normalizedLoad(site: Site | undefined, row: ReplayRow | undefined): number {
  const peak = site?.load?.peak_kw || 0;
  const v = row?.actual_kw;
  if (!peak || typeof v !== "number") return 0.4;
  return Math.max(0, Math.min(1, v / peak));
}
