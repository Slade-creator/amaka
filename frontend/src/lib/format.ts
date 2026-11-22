/**
 * Formatting helpers for AMAKA.
 * All date parsing goes through normTs/parseTs so overview payloads that use a
 * space instead of "T" ("2025-10-06 18:00:00") never produce Invalid Date.
 * Formatting reads local getters from the parsed epoch, so the displayed clock
 * always matches the stored wall-clock value regardless of browser timezone.
 */

import { readinessName } from "./vocabulary";

const DASH = "-";
const EM = "\u2014"; // em dash for missing values

/** "2025-10-06 18:00:00" → "2025-10-06T18:00:00" (leaves T / offsets alone). */
export function normTs(s: unknown): string {
  if (typeof s !== "string") return "";
  const t = s.trim();
  return t.replace(/^(\d{4}-\d{2}-\d{2})[ ]+/, "$1T");
}

/** Epoch ms for an ISO-ish string; 0 when unparseable. */
export function parseTs(s: unknown): number {
  const t = Date.parse(normTs(s));
  return Number.isFinite(t) ? t : 0;
}

function isNum(n: unknown): n is number {
  return typeof n === "number" && Number.isFinite(n);
}

/** Thousands-separated number, fixed decimals. "—" for non-finite input. */
export function fmtInt(n: unknown, digits = 0): string {
  if (!isNum(n)) return EM;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

/** ZMW compact: "ZMW 68k", "ZMW 1.2M". */
export function fmtZmw(n: unknown): string {
  if (!isNum(n)) return EM;
  const a = Math.abs(n);
  if (a >= 1_000_000) return `ZMW ${(n / 1_000_000).toFixed(1)}M`;
  if (a >= 100_000) return `ZMW ${Math.round(n / 1_000)}k`;
  if (a >= 1_000) return `ZMW ${(n / 1_000).toFixed(1)}k`;
  return `ZMW ${fmtInt(n)}`;
}

/** Percent with fixed decimals: "2.78%". */
export function fmtPct(n: unknown, digits = 2): string {
  if (!isNum(n)) return EM;
  return `${n.toFixed(digits)}%`;
}

/** Signed number: "+63" / "-12". */
export function fmtSigned(n: unknown, digits = 0): string {
  if (!isNum(n)) return EM;
  return `${n >= 0 ? "+" : "-"}${fmtInt(Math.abs(n), digits)}`;
}

const MONTHS_SHORT = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const MONTHS_TINY = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(epoch: number) {
  const d = new Date(epoch);
  return {
    dd: String(d.getDate()).padStart(2, "0"),
    mm: String(d.getMonth() + 1).padStart(2, "0"),
    yyyy: d.getFullYear(),
    hh: String(d.getHours()).padStart(2, "0"),
    mi: String(d.getMinutes()).padStart(2, "0"),
    mon: MONTHS_SHORT[d.getMonth()],
    monTiny: MONTHS_TINY[d.getMonth()],
  };
}

/** "06 OCT 2025 · 18:00" — cursor / replay timestamp. */
export function fmtStamp(s: unknown): string {
  const epoch = parseTs(s);
  if (!epoch) return typeof s === "string" && s ? s : EM;
  const p = parts(epoch);
  return `${p.dd} ${p.mon} ${p.yyyy} \u00B7 ${p.hh}:${p.mi}`;
}

/** "2025-10-06 18:00" — machine-ish stamp for tooltips. */
export function fmtStampIso(s: unknown): string {
  const epoch = parseTs(s);
  if (!epoch) return typeof s === "string" && s ? s : EM;
  const p = parts(epoch);
  return `${p.yyyy}-${p.mm}-${p.dd} ${p.hh}:${p.mi}`;
}

/** X-axis tick: dense ranges show hour, long ranges show date only. */
export function fmtAxisTick(epoch: number, rangeHours: number): string {
  if (!Number.isFinite(epoch)) return "";
  const p = parts(epoch);
  return rangeHours <= 168 ? `${p.dd} ${p.hh}:00` : `${p.dd} ${p.monTiny}`;
}

/** UTC wall clock for the header: "17:26:04". */
export function fmtUtcClock(d: Date): string {
  return d.toISOString().slice(11, 19);
}

/** Footer timestamp: ISO string → "2026-11-01 17:26:23 UTC". */
export function fmtIsoUtc(s: unknown): string {
  if (typeof s !== "string" || !s) return EM;
  const epoch = Date.parse(s);
  if (!Number.isFinite(epoch)) return s;
  return `${new Date(epoch).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** "-15.435, 28.321" coordinates line. */
export function fmtCoords(lat: unknown, lon: unknown): string {
  if (!isNum(lat) || !isNum(lon)) return EM;
  return `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
}

/** Feature-value annotation for SHAP rows (scales decimals to magnitude). */
export function fmtFeatureValue(n: unknown): string {
  if (!isNum(n)) return EM;
  const a = Math.abs(n);
  if (a >= 1000) return fmtInt(n, 0);
  if (a >= 100) return fmtInt(n, 1);
  if (a >= 1) return n.toFixed(2);
  return n.toFixed(3);
}

/** readiness_code → strip/bar colour. 4 routine … 1 exercise surge. */
export function readinessColor(code: number): string {
  switch (code) {
    case 1:
      return "var(--crit-hot)";
    case 2:
      return "var(--warn-hot)";
    case 3:
      return "var(--accent)";
    default:
      return "rgb(var(--accent-rgb)/0.4)";
  }
}

/**
 * Canonical readiness label, shared by map, strip, tooltip and alerts.
 * Always derived from the code, never from the CSV's `readiness_label`, so
 * old and new data files read the same.
 */
export function readinessLabel(code: number, _label?: string): string {
  return readinessName(code);
}

export function titleCase(s: unknown): string {
  if (typeof s !== "string" || !s) return "";
  return s
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export { EM as EM_DASH, DASH as DASH_CHAR };
