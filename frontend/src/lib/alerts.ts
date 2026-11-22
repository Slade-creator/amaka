/**
 * Local alert derivation.
 *
 * The contract's alert rules are deterministic over the replay rows, so the
 * feed is computed client-side from the 24h window ending at the cursor. This
 * keeps the feed instant on every scrub/tick and immune to backend outages
 * during the demo. Rules (BUILD_CONTRACT.md §alerts):
 *   - peak:     forecast > peak threshold → critical; within 3% → warning
 *   - surge:    high readiness R1–R2 (R1 → warning, R2 → info)
 *   - variance: |actual load - forecast| > range → warning
 * De-duplicated by kind (newest kept), max 8, newest first.
 */

import { changePhrase, readinessName } from "./vocabulary";
import type { Alert, ReplayRow } from "../types";

const WINDOW_HOURS = 24;

export function deriveAlerts(
  rows: ReplayRow[],
  cursor: number,
  thresholdKw: number,
  bandKw: number,
): Alert[] {
  if (rows.length === 0 || cursor < 0) return [];
  const start = Math.max(0, cursor - (WINDOW_HOURS - 1));
  const found: Partial<Record<Alert["kind"], Alert>> = {};

  for (let i = cursor; i >= start; i--) {
    const r = rows[i];
    if (!r) continue;
    const idx = i;
    const stamp = r.timestamp;

    if (!found.peak && thresholdKw > 0) {
      if (r.hybrid_kw > thresholdKw) {
        found.peak = {
          id: `peak-${idx}`,
          severity: "critical",
          kind: "peak",
          title: "Peak threshold exceeded",
          detail: `Forecast ${Math.round(r.hybrid_kw).toLocaleString("en-US")} kW is above the ${Math.round(thresholdKw).toLocaleString("en-US")} kW peak threshold`,
          timestamp: stamp,
        };
      } else if (r.hybrid_kw > thresholdKw * 0.97) {
        found.peak = {
          id: `peak-${idx}`,
          severity: "warning",
          kind: "peak",
          title: "Approaching peak threshold",
          detail: `Forecast ${Math.round(r.hybrid_kw).toLocaleString("en-US")} kW is within 3% of the ${Math.round(thresholdKw).toLocaleString("en-US")} kW peak threshold`,
          timestamp: stamp,
        };
      }
    }

    if (!found.surge && r.readiness_code <= 2) {
      const level = readinessName(r.readiness_code);
      found.surge = {
        id: `surge-${idx}`,
        severity: r.readiness_code <= 1 ? "warning" : "info",
        kind: "surge",
        title: `${level} in effect`,
        detail: `Readiness level R${r.readiness_code} · ${level.toLowerCase()} — load is likely above a routine hour`,
        timestamp: stamp,
      };
    }

    if (!found.variance && bandKw > 0 && Math.abs(r.actual_kw - r.hybrid_kw) > bandKw) {
      const diff = r.actual_kw - r.hybrid_kw;
      found.variance = {
        id: `variance-${idx}`,
        severity: "warning",
        kind: "variance",
        title: "Actual load outside forecast range",
        detail: `Actual ${Math.round(r.actual_kw).toLocaleString("en-US")} kW vs forecast ${Math.round(r.hybrid_kw).toLocaleString("en-US")} kW (${changePhrase(diff, "forecast")}) — outside the ±${Math.round(bandKw)} kW range`,
        timestamp: stamp,
      };
    }

    if (found.peak && found.surge && found.variance) break;
  }

  return Object.values(found)
    .filter((a): a is Alert => Boolean(a))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
    .slice(0, 8);
}
