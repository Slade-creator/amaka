/**
 * Client for the fleet endpoint: GET /api/fleet?at=<iso>
 *
 * Same defensive posture as src/api.ts — every field is coerced, a malformed
 * payload degrades to a clean error instead of a crash, and responses are
 * cached by `at` so role switches are instant (the endpoint is role-agnostic).
 */

import { apiFetch } from "../lib/session";

export type FleetStatus = "critical" | "warning" | "nominal";

export type FleetSite = {
  id: string;
  label: string;
  location: string;
  type: string;
  lat: number;
  lon: number;
  actual_kw: number;
  hybrid_kw: number;
  threshold_kw: number;
  /** negative = over threshold */
  headroom_kw: number;
  readiness_code: number;
  readiness_label: string;
  mape: number;
  monthly_saving_zmw: number;
  status: FleetStatus;
};

export type FleetTotals = {
  load_kw: number;
  peak_kw: number;
  saving_zmw: number;
  sites_at_risk: number;
  surge_sites: number;
};

export type FleetResponse = {
  at: string;
  /** Forecast horizon (hours) the row values were sampled at. */
  horizon?: number;
  sites: FleetSite[];
  totals: FleetTotals;
};

export const FLEET_MODEL_NAME = "Hybrid XGBoost + residual learner";
/** Held-out v2 test window is 2025-07-01..2025-12-31 hourly ≈ 4,340 rows/site. */
export const TEST_ROWS_PER_SITE = 4340;

/* ------------------------------------------------------------------ */
/* defensive coercion                                                  */
/* ------------------------------------------------------------------ */

function num(v: unknown, d = 0): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return d;
}

function str(v: unknown, d = ""): string {
  return typeof v === "string" ? v : d;
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

/** Status falls back to a derivation from headroom + readiness when missing. */
function normStatus(raw: unknown, headroom: number, code: number, threshold: number): FleetStatus {
  if (raw === "critical" || raw === "warning" || raw === "nominal") return raw;
  if (code <= 1 || headroom < 0) return "critical";
  if (code === 2 || (threshold > 0 && headroom < threshold * 0.05)) return "warning";
  return "nominal";
}

function normSite(raw: unknown): FleetSite | null {
  const s = obj(raw);
  const id = str(s.id);
  if (!id) return null;
  const codeRaw = num(s.readiness_code, 4);
  const code = Math.min(4, Math.max(1, Math.round(codeRaw)));
  const threshold = num(s.threshold_kw);
  const actual = num(s.actual_kw);
  const headroomRaw = s.headroom_kw;
  const headroom =
    typeof headroomRaw === "number" && Number.isFinite(headroomRaw)
      ? headroomRaw
      : threshold > 0
        ? threshold - actual
        : 0;
  return {
    id,
    label: str(s.label, id),
    location: str(s.location, "—"),
    type: str(s.type, "—"),
    lat: num(s.lat),
    lon: num(s.lon),
    actual_kw: actual,
    hybrid_kw: num(s.hybrid_kw),
    threshold_kw: threshold,
    headroom_kw: headroom,
    readiness_code: code,
    readiness_label: str(s.readiness_label, "routine"),
    mape: num(s.mape),
    monthly_saving_zmw: num(s.monthly_saving_zmw),
    status: normStatus(s.status, headroom, code, threshold),
  };
}

/** Fleet totals — derived from the site list when the payload omits them. */
export function deriveTotals(sites: FleetSite[]): FleetTotals {
  let load = 0;
  let peak = 0;
  let saving = 0;
  let risk = 0;
  let surge = 0;
  for (const s of sites) {
    load += s.actual_kw;
    peak += s.hybrid_kw;
    saving += s.monthly_saving_zmw;
    if (s.status === "critical" || s.status === "warning") risk += 1;
    if (s.readiness_code <= 2) surge += 1;
  }
  return {
    load_kw: load,
    peak_kw: peak,
    saving_zmw: saving,
    sites_at_risk: risk,
    surge_sites: surge,
  };
}

function normalizeFleet(raw: unknown, at: string, horizon: number): FleetResponse {
  const body = obj(raw);
  const rawSites = Array.isArray(body.sites) ? body.sites : [];
  const sites = rawSites.map(normSite).filter((s): s is FleetSite => s !== null);
  const t = obj(body.totals);
  // Use the backend totals when they carry a real load; otherwise compute them
  // from the site list so a lagging/absent totals block never shows 0.0 MW.
  const totals: FleetTotals =
    num(t.load_kw, -1) > 0
      ? {
          load_kw: num(t.load_kw),
          peak_kw: num(t.peak_kw),
          saving_zmw: num(t.saving_zmw),
          sites_at_risk: Math.round(num(t.sites_at_risk)),
          surge_sites: Math.round(num(t.surge_sites)),
        }
      : deriveTotals(sites);
  const hRaw = num(body.horizon, horizon);
  const respHorizon = Number.isFinite(hRaw) && hRaw > 0 ? Math.round(hRaw) : horizon;
  return {
    at: str(body.at, at),
    horizon: respHorizon,
    sites,
    totals,
  };
}

/* ------------------------------------------------------------------ */
/* fetch + cache                                                       */
/* ------------------------------------------------------------------ */

const cache = new Map<string, FleetResponse>();

export type FleetFetchOptions = { signal?: AbortSignal; force?: boolean };

/** Cache key: the endpoint is keyed on (replay hour, forecast horizon). */
function fleetKey(at: string, horizon: number): string {
  return `${at || "latest"}|${horizon}`;
}

/**
 * Fetch fleet state for a replay cursor hour at a forecast horizon.
 * Cached by `at|horizon` unless `force` is set (retry button).
 * Throws Error with a human message; never logs.
 */
export async function fetchFleet(
  at: string,
  horizon: number,
  opts: FleetFetchOptions = {},
): Promise<FleetResponse> {
  const key = fleetKey(at, horizon);
  if (!opts.force) {
    const hit = cache.get(key);
    if (hit) return hit;
  }

  const q = new URLSearchParams({ at });
  if (Number.isFinite(horizon) && horizon > 0) q.set("horizon", String(horizon));

  let res: Response;
  try {
    res = await apiFetch(`/api/fleet?${q.toString()}`, { signal: opts.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw e instanceof Error ? e : new Error("Fleet request failed");
  }
  if (res.status === 401) throw new Error("Sign in required");
  if (!res.ok) throw new Error(`Fleet request failed (HTTP ${res.status})`);

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new Error("Malformed fleet response");
  }

  const parsed = normalizeFleet(body, at, horizon);
  if (parsed.sites.length === 0) throw new Error("Fleet response contained no site data");
  cache.set(key, parsed);
  return parsed;
}

/** True when an exception is an aborted request (ignore it). */
export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

/** Synchronous cache lookup — avoids a network round trip on role switches. */
export function peekFleet(at: string, horizon: number): FleetResponse | null {
  return cache.get(fleetKey(at, horizon)) ?? null;
}

/** Drop cached payloads (used by forced refreshes from elsewhere). */
export function clearFleetCache(): void {
  cache.clear();
}
