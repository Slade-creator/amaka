/**
 * AMAKA API client.
 * Root-relative "/api/..." paths: the Vite dev server proxies to 127.0.0.1:8000
 * and the FastAPI backend serves frontend/dist in production. Native builds
 * prefix the same paths with VITE_API_BASE_URL (see lib/apiBase.ts), so the
 * rest of the client never needs to know where the API lives. Every helper
 * normalises its payload — a missing/odd field must never crash the UI. Errors
 * are surfaced as ApiError with a human message; nothing here ever logs to the
 * console.
 */

import type {
  Alert,
  ExplainResponse,
  HealthResponse,
  MidtermModelMetrics,
  MidtermRow,
  NarrativeAnswerResponse,
  NarrativeFallbackReason,
  NarrativeFacts,
  NarrativeResponse,
  NarrativeSource,
  Overview,
  ReplayRow,
  ShapRow,
  Site,
  SiteMidtermResponse,
} from "./types";
import { normTs } from "./lib/format";
import { apiFetch, HttpError } from "./lib/session";
import { saveReport } from "./lib/files";

export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

/** Forecast horizons the v2 pipeline serves (direct 1/6/24/48-hour model). */
export const HORIZONS = [1, 6, 24, 48] as const;
const HORIZON_SET = new Set<number>(HORIZONS);

/** Runtime guard for anything coming from config/state/query strings. */
export function isHorizon(v: unknown): v is number {
  return typeof v === "number" && HORIZON_SET.has(v);
}

/** `H24` label used across chart/KPI/model/SHAP titles. */
export function horizonLabel(h: number): string {
  return `H${h}`;
}

/** Build a query string, skipping empty/undefined values. */
function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Human-readable message for any thrown value (never throws itself). */
export function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error && e.message) return e.message;
  return "Unknown error";
}

async function readJson<T>(res: Response, path: string): Promise<T> {
  if (res.status === 401) throw new ApiError("Sign in required", 401);
  if (res.status === 403) throw new ApiError("Your role does not have access to this", 403);
  if (!res.ok) throw new ApiError(`Request failed (HTTP ${res.status}) for ${path}`, res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(`Malformed response from ${path}`);
  }
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await apiFetch(path, init);
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError(e instanceof HttpError ? e.message : errMessage(e));
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return readJson<T>(await send(path, { signal }), path);
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await send(path, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readJson<T>(res, path);
}

/* ------------------------------------------------------------------ */
/* defensive coercion helpers                                          */
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

function normRow(raw: unknown): ReplayRow {
  const r = obj(raw);
  const codeRaw = num(r.readiness_code, 4);
  const code = (codeRaw >= 1 && codeRaw <= 4 ? Math.round(codeRaw) : 4) as 1 | 2 | 3 | 4;
  return {
    timestamp: str(r.timestamp),
    actual_kw: num(r.actual_kw),
    xgb_kw: num(r.xgb_kw),
    hybrid_kw: num(r.hybrid_kw),
    lower_kw: num(r.lower_kw, num(r.hybrid_kw)),
    upper_kw: num(r.upper_kw, num(r.hybrid_kw)),
    selected_model: typeof r.selected_model === "string" ? r.selected_model : undefined,
    readiness_code: code,
    readiness_label: str(r.readiness_label, "routine"),
    temperature_c: num(r.temperature_c),
    humidity_pct: num(r.humidity_pct),
    radiation_wm2: num(r.radiation_wm2),
    cloud_cover_pct: num(r.cloud_cover_pct),
  };
}

function normShap(raw: unknown): ShapRow | null {
  const r = obj(raw);
  const feature = str(r.feature);
  if (!feature) return null;
  const contribution = num(r.contribution_kw);
  return {
    feature,
    label: str(r.label, feature),
    value: num(r.value),
    contribution_kw: contribution,
    direction: (r.direction === "down" || contribution < 0 ? "down" : "up") as "up" | "down",
  };
}

function normSite(raw: unknown, depth = 0): Site | null {
  const s = obj(raw);
  const id = str(s.id);
  if (!id) return null;
  const m = obj(s.metrics);
  const l = obj(s.load);
  const a = obj(s.alerts);
  const c = obj(s.cost);
  const selected = str(s.selected_model, str(m.selected_model)) || undefined;
  const hRaw = num(s.horizon, NaN);
  const horizon =
    Number.isFinite(hRaw) && HORIZON_SET.has(Math.round(hRaw)) ? Math.round(hRaw) : undefined;
  // v1 only ships one seasonal-naive number (t-168); v2 splits 24h / 168h.
  const seasonal168 = num(m.seasonal_naive_168_mae, num(m.seasonal_naive_mae));
  // Nested v2 payload: one level only (never recurse into horizons.horizons).
  let horizons: Record<string, Site> | undefined;
  if (depth === 0) {
    const rawH = obj(s.horizons);
    const out: Record<string, Site> = {};
    for (const [k, v] of Object.entries(rawH)) {
      const nested = normSite(v, depth + 1);
      if (nested) out[k] = nested;
    }
    if (Object.keys(out).length > 0) horizons = out;
  }
  return {
    id,
    label: str(s.label, id),
    location: str(s.location, "—"),
    type: str(s.type, "—"),
    base_load_kw: num(s.base_load_kw),
    pv_kwp: num(s.pv_kwp),
    headcount: num(s.headcount),
    floor_area_m2: num(s.floor_area_m2),
    lat: num(s.lat),
    lon: num(s.lon),
    test_start: str(s.test_start),
    test_end: str(s.test_end),
    rows: num(s.rows),
    demo_anchor: str(s.demo_anchor),
    demo_start: str(s.demo_start),
    horizon,
    selected_model: selected,
    metrics: {
      xgb_rmse: num(m.xgb_rmse),
      xgb_mae: num(m.xgb_mae),
      hyb_rmse: num(m.hyb_rmse),
      hyb_mae: num(m.hyb_mae),
      hyb_mape: num(m.hyb_mape),
      persistence_mae: num(m.persistence_mae),
      seasonal_naive_mae: num(m.seasonal_naive_mae),
      seasonal_naive_24_mae: num(m.seasonal_naive_24_mae),
      seasonal_naive_168_mae: seasonal168,
      standalone_lstm_mae: num(m.standalone_lstm_mae),
      selected_model: selected,
      band_kw: num(m.band_kw),
    },
    load: {
      avg_kw: num(l.avg_kw),
      peak_kw: num(l.peak_kw, 1),
      threshold_kw: num(l.threshold_kw),
      latest_actual_kw: num(l.latest_actual_kw),
      latest_hybrid_kw: num(l.latest_hybrid_kw),
    },
    alerts: {
      peak_hours: num(a.peak_hours),
      surge_hours: num(a.surge_hours),
      variance_hours: num(a.variance_hours),
    },
    cost: {
      energy_month_kwh: num(c.energy_month_kwh),
      baseline_monthly_zmw: num(c.baseline_monthly_zmw),
      monthly_saving_zmw: num(c.monthly_saving_zmw),
      annual_saving_zmw: num(c.annual_saving_zmw),
      demand_saving_zmw: num(c.demand_saving_zmw),
      fuel_saving_zmw: num(c.fuel_saving_zmw),
      saving_pct: num(c.saving_pct),
    },
    ...(horizons ? { horizons } : {}),
  };
}

function normOverview(raw: unknown): Overview {
  const o = obj(raw);
  const model = obj(o.model);
  const period = obj(o.test_period);
  const rawSites = Array.isArray(o.sites) ? o.sites : [];
  const sites = rawSites.map((s) => normSite(s)).filter((s): s is Site => s !== null);
  const costRaw = obj(o.cost_assumptions);
  const cost: Record<string, number> = {};
  for (const [k, v] of Object.entries(costRaw)) cost[k] = num(v);
  const version = str(o.version) || undefined;
  // Horizon metadata only exists on v2 payloads — a v1 overview stays v1
  // (empty list) so the switcher never appears on the legacy pipeline.
  const rawHorizons = Array.isArray(o.available_horizons) ? o.available_horizons : [];
  const available = rawHorizons
    .map((h) => num(h))
    .filter((h) => HORIZON_SET.has(Math.round(h)))
    .map((h) => Math.round(h));
  const available_horizons =
    available.length > 0 ? available : version === "v2" ? [...HORIZONS] : [];
  const anchorRaw = obj(o.fleet_anchor_by_horizon);
  const fleet_anchor_by_horizon: Record<string, string> = {};
  for (const [k, v] of Object.entries(anchorRaw)) {
    if (typeof v === "string" && v) fleet_anchor_by_horizon[k] = v;
  }
  return {
    generated_at: str(o.generated_at),
    test_period: { start: str(period.start), end: str(period.end) },
    version,
    default_horizon: HORIZON_SET.has(Math.round(num(o.default_horizon, 24)))
      ? Math.round(num(o.default_horizon, 24))
      : 24,
    available_horizons,
    fleet_anchor: typeof o.fleet_anchor === "string" ? o.fleet_anchor : undefined,
    fleet_anchor_by_horizon:
      Object.keys(fleet_anchor_by_horizon).length > 0 ? fleet_anchor_by_horizon : undefined,
    model: {
      name: str(model.name, "Hybrid forecast model"),
      stage1: str(model.stage1),
      stage2: str(model.stage2),
      horizon: str(model.horizon),
      features: num(model.features),
    },
    cost_assumptions: cost,
    sites,
    served_at: typeof o.served_at === "string" ? o.served_at : undefined,
  };
}

/**
 * Swap an overview onto a specific forecast horizon using the nested
 * `site.horizons[str(h)]` payload (instant, no network). Falls back to just
 * re-anchoring the fleet when the payload carries no nested data — the caller
 * still refreshes from `/api/overview?horizon=h` for authoritative numbers.
 */
export function applyHorizon(ov: Overview, h: number): Overview {
  const key = String(h);
  const anchor = ov.fleet_anchor_by_horizon?.[key] ?? ov.fleet_anchor;
  const hasNested = ov.sites.some((s) => s.horizons?.[key]);
  if (!hasNested) {
    return anchor && anchor !== ov.fleet_anchor ? { ...ov, fleet_anchor: anchor } : ov;
  }
  const sites = ov.sites.map((s) => {
    const n = s.horizons?.[key];
    if (!n) return s;
    return {
      ...s,
      ...n,
      id: s.id, // identity stays with the base record (defensive)
      label: n.label || s.label,
      location: n.location || s.location,
      lat: n.lat || s.lat,
      lon: n.lon || s.lon,
      demo_anchor: n.demo_anchor || s.demo_anchor,
      selected_model: n.selected_model || s.selected_model,
      horizon: h,
      horizons: s.horizons,
    };
  });
  return { ...ov, sites, ...(anchor ? { fleet_anchor: anchor } : {}) };
}

/* ------------------------------------------------------------------ */
/* public calls                                                        */
/* ------------------------------------------------------------------ */

export async function fetchOverview(
  signal?: AbortSignal,
  horizon?: number,
): Promise<Overview> {
  const path = `/api/overview${qs({ horizon: isHorizon(horizon) ? horizon : undefined })}`;
  const raw = await getJson<unknown>(path, signal);
  const ov = normOverview(raw);
  if (ov.sites.length === 0) throw new ApiError("Overview returned no sites");
  return ov;
}

/**
 * Full replay series for a site at a given forecast horizon.
 * Callers cache by `${site}|${horizon}` so a horizon switch never refetches
 * an hour block it already holds.
 */
export async function fetchSeries(
  site: string,
  signal?: AbortSignal,
  horizon?: number,
): Promise<ReplayRow[]> {
  const path = `/api/sites/${encodeURIComponent(site)}/series${qs({
    horizon: isHorizon(horizon) ? horizon : undefined,
  })}`;
  const raw = await getJson<unknown>(path, signal);
  const body = obj(raw);
  const rows = Array.isArray(body.rows) ? body.rows : [];
  if (rows.length === 0) throw new ApiError(`No load data for site "${site}"`);
  return rows.map((r) => normRow(r));
}

export async function fetchExplain(
  site: string,
  at: string,
  signal?: AbortSignal,
  horizon?: number,
): Promise<ExplainResponse> {
  const q = qs({
    at,
    horizon: isHorizon(horizon) ? horizon : undefined,
  });
  const raw = await getJson<unknown>(
    `/api/sites/${encodeURIComponent(site)}/explain${q}`,
    signal,
  );
  const body = obj(raw);
  const rawTop = Array.isArray(body.top) ? body.top : [];
  const rawAll = Array.isArray(body.all) ? body.all : [];
  let top = rawTop.map(normShap).filter((s): s is ShapRow => s !== null);
  if (top.length === 0) {
    // some backends only fill `all` — derive the top slice ourselves
    top = rawAll
      .map(normShap)
      .filter((s): s is ShapRow => s !== null)
      .sort((a, b) => Math.abs(b.contribution_kw) - Math.abs(a.contribution_kw))
      .slice(0, 10);
  }
  return {
    site: str(body.site, site),
    at: str(body.at, at),
    base_kw: num(body.base_kw),
    top,
    all: rawAll.map(normShap).filter((s): s is ShapRow => s !== null),
  };
}

function normSource(v: unknown): NarrativeSource {
  return v === "model" ? "model" : "rules";
}

function normFallback(v: unknown): NarrativeFallbackReason {
  return v === "not_configured" || v === "breaker" || v === "provider" || v === "grounding"
    ? v
    : null;
}

/**
 * Grounded explanation of the visible window + selected hour.
 * `mode: "fast"` returns the deterministic rules text immediately and never
 * calls the language model; `"auto"` lets the backend refine it.
 */
export async function fetchNarrative(
  site: string,
  params: {
    at?: string;
    from?: string;
    to?: string;
    role?: string;
    horizon?: number;
    mode?: "auto" | "fast";
  },
  signal?: AbortSignal,
): Promise<NarrativeResponse> {
  const path = `/api/sites/${encodeURIComponent(site)}/narrative${qs({
    at: params.at,
    from: params.from,
    to: params.to,
    role: params.role,
    horizon: isHorizon(params.horizon) ? params.horizon : undefined,
    mode: params.mode,
  })}`;
  const raw = await getJson<unknown>(path, signal);
  const body = obj(raw);
  const win = obj(body.window);
  return {
    site: str(body.site, site),
    horizon: num(body.horizon),
    role: str(body.role, "operator"),
    at: str(body.at, params.at ?? ""),
    window: { from: str(win.from), to: str(win.to) },
    text: str(body.text),
    source: normSource(body.source),
    model: typeof body.model === "string" ? body.model : null,
    cached: body.cached === true,
    notice: typeof body.notice === "string" && body.notice ? body.notice : null,
    fallback_reason: normFallback(body.fallback_reason),
    facts: obj(body.facts) as NarrativeFacts,
  };
}

/** Ask a free-text question about the same chart window. */
export async function askNarrative(
  site: string,
  params: {
    question: string;
    at?: string;
    from?: string;
    to?: string;
    role?: string;
    horizon?: number;
  },
  signal?: AbortSignal,
): Promise<NarrativeAnswerResponse> {
  const raw = await postJson<unknown>(
    `/api/sites/${encodeURIComponent(site)}/narrative/ask`,
    {
      question: params.question,
      at: params.at,
      from: params.from,
      to: params.to,
      role: params.role,
      horizon: isHorizon(params.horizon) ? params.horizon : undefined,
    },
    signal,
  );
  const body = obj(raw);
  return {
    site: str(body.site, site),
    horizon: num(body.horizon),
    role: str(body.role, params.role ?? "operator"),
    question: str(body.question, params.question),
    answer: str(body.answer),
    source: normSource(body.source),
    model: typeof body.model === "string" ? body.model : null,
    cached: body.cached === true,
    notice: typeof body.notice === "string" && body.notice ? body.notice : null,
    fallback_reason: normFallback(body.fallback_reason),
  };
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const raw = await getJson<unknown>("/api/health", signal);
  const h = obj(raw);
  const rawH = Array.isArray(h.horizons) ? h.horizons : [];
  const horizons = rawH
    .map((x) => num(x))
    .filter((x) => HORIZON_SET.has(Math.round(x)))
    .map((x) => Math.round(x));
  return {
    status: str(h.status, "ok"),
    sites: num(h.sites),
    generated_at: str(h.generated_at),
    version: str(h.version) || undefined,
    horizons: horizons.length > 0 ? horizons : undefined,
  };
}

/* ------------------------------------------------------------------ */
/* downloads                                                           */
/* ------------------------------------------------------------------ */

/** report.csv / report.pdf API path for the visible window (inclusive ISO range). */
export function reportPath(
  site: string,
  kind: "csv" | "pdf",
  from: string,
  to: string,
  horizon?: number,
): string {
  const q = qs({
    from: normTs(from),
    to: normTs(to),
    horizon: isHorizon(horizon) ? horizon : undefined,
  });
  return `/api/sites/${encodeURIComponent(site)}/report.${kind}${q}`;
}

/**
 * Download a report with the session token attached. Browsers get a normal
 * file download; the Android app saves it to the app's documents folder and
 * opens the share sheet. Resolves to the saved file name.
 */
export async function downloadReport(
  site: string,
  kind: "csv" | "pdf",
  from: string,
  to: string,
  horizon?: number,
): Promise<string> {
  const path = reportPath(site, kind, from, to, horizon);
  const res = await send(path, { headers: { Accept: kind === "pdf" ? "application/pdf" : "text/csv" } });
  if (!res.ok) {
    let msg = `Export failed (HTTP ${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(msg, res.status);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const name = match?.[1] ?? `amaka_${site}_h${horizon ?? 24}_report.${kind}`;
  await saveReport(await res.blob(), name);
  return name;
}

export const MIDTERM_HORIZONS_DAYS = [7, 14, 30, 60, 90] as const;

export async function fetchSiteMidterm(
  site: string,
  horizonDays: number = 30,
  signal?: AbortSignal,
): Promise<SiteMidtermResponse> {
  const path = `/api/sites/${encodeURIComponent(site)}/midterm${qs({
    horizon_days: horizonDays,
  })}`;
  const raw = await getJson<unknown>(path, signal);
  const b = obj(raw);
  const rawMetrics = obj(b.metrics);
  const parseTargetMap = (tRaw: unknown): Record<string, MidtermModelMetrics> => {
    const out: Record<string, MidtermModelMetrics> = {};
    for (const [k, v] of Object.entries(obj(tRaw))) {
      const m = obj(v);
      out[k] = {
        rmse: num(m.rmse),
        mae: num(m.mae),
        mape: num(m.mape),
        wape: num(m.wape),
        bias: num(m.bias),
        peak_bias: num(m.peak_bias),
        peak_mae: num(m.peak_mae),
        cum_energy_bias_pct: num(m.cum_energy_bias_pct),
        window_30d_mape: num(m.window_30d_mape),
        monthly_peak_mae_kw: num(m.monthly_peak_mae_kw),
        monthly_peak_mae_zmw: num(m.monthly_peak_mae_zmw),
        picp_95: num(m.picp_95),
        interval_halfwidth_kw: num(m.interval_halfwidth_kw),
        skill_vs_persistence_pct: num(m.skill_vs_persistence_pct),
        skill_vs_seasonal_pct: num(m.skill_vs_seasonal_pct),
        selected_stage2: str(m.selected_stage2, k),
      };
    }
    return out;
  };
  const rawRows = Array.isArray(b.rows) ? b.rows : [];
  const rows: MidtermRow[] = rawRows.map((rr) => {
    const r = obj(rr);
    return {
      date: str(r.date),
      actual_mean_kw: num(r.actual_mean_kw),
      xgb_mean_kw: num(r.xgb_mean_kw),
      hybrid_mean_kw: num(r.hybrid_mean_kw),
      lower_mean_kw: num(r.lower_mean_kw),
      upper_mean_kw: num(r.upper_mean_kw),
      selected_mean_model: str(r.selected_mean_model, "xgb"),
      actual_energy_mwh: num(r.actual_energy_mwh),
      hybrid_energy_mwh: num(r.hybrid_energy_mwh),
      actual_peak_kw: num(r.actual_peak_kw),
      xgb_peak_kw: num(r.xgb_peak_kw),
      hybrid_peak_kw: num(r.hybrid_peak_kw),
      lower_peak_kw: num(r.lower_peak_kw),
      upper_peak_kw: num(r.upper_peak_kw),
      selected_peak_model: str(r.selected_peak_model, "xgb"),
      temp_mean_c: num(r.temp_mean_c),
      temp_max_c: num(r.temp_max_c),
      humidity_pct: num(r.humidity_pct),
      readiness_mult_max: num(r.readiness_mult_max, 1),
      is_holiday: num(r.is_holiday),
      is_weekend: num(r.is_weekend),
    };
  });

  return {
    site: str(b.site, site),
    label: str(b.label, site),
    location: str(b.location),
    type: str(b.type),
    horizon_days: num(b.horizon_days, horizonDays),
    available_horizons_days: Array.isArray(b.available_horizons_days)
      ? b.available_horizons_days.map((d) => num(d))
      : [...MIDTERM_HORIZONS_DAYS],
    threshold_kw: num(b.threshold_kw),
    metrics: {
      daily_mean_kw: parseTargetMap(rawMetrics.daily_mean_kw),
      daily_peak_kw: parseTargetMap(rawMetrics.daily_peak_kw),
    },
    rows,
  };
}

/* ------------------------------------------------------------------ */
/* alerts                                                              */
/* ------------------------------------------------------------------ */

function normAlert(raw: unknown): Alert | null {
  const a = obj(raw);
  const id = str(a.id);
  const sev = a.severity;
  const kind = a.kind;
  if (!id || (sev !== "critical" && sev !== "warning" && sev !== "info")) return null;
  return {
    id,
    severity: sev,
    kind:
      kind === "peak" || kind === "surge" || kind === "variance" || kind === "readiness" || kind === "model"
        ? kind
        : "peak",
    title: str(a.title, "Alert"),
    detail: str(a.detail),
    timestamp: str(a.timestamp),
  };
}

/** Server-evaluated alerts for one site over the `hours` ending at `at`. */
export async function fetchSiteAlerts(
  site: string,
  params: { at?: string; hours?: number; horizon?: number },
  signal?: AbortSignal,
): Promise<Alert[]> {
  const path = `/api/sites/${encodeURIComponent(site)}/alerts${qs({
    at: params.at ? normTs(params.at) : undefined,
    hours: params.hours ?? 24,
    horizon: isHorizon(params.horizon) ? params.horizon : undefined,
  })}`;
  const body = obj(await getJson<unknown>(path, signal));
  const list = Array.isArray(body.alerts) ? body.alerts : [];
  return list.map(normAlert).filter((a): a is Alert => a !== null);
}
