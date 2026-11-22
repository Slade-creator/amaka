/**
 * Client for live meter-kit ingestion (backend/ingest_api.py,
 * docs/DATA_INGESTION.md). Reads need any signed-in user; writes are
 * analyst-only (403 otherwise). Measured load only — no live forecast yet.
 */

import { apiFetch } from "./session";

export type KitStatus = "waiting" | "online" | "stale" | "offline" | "revoked" | "manual";

export type LiveSite = {
  id: string;
  label: string;
  location: string;
  type: string;
  lat: number;
  lon: number;
  threshold_kw: number;
  headcount?: number;
  floor_area_m2?: number;
  pv_kwp?: number;
  source: "fleet" | "field";
};

export type Device = {
  id: string;
  site_id: string;
  site_label: string;
  label: string;
  hardware?: string;
  interval_s?: number;
  status: KitStatus;
  enrolled_at?: string;
  last_seen?: string | null;
  last_seen_age_s?: number | null;
  last_kw?: number | null;
  readings_total: number;
  readings_24h: number;
  coverage_24h_pct: number;
};

export type Enrolment = {
  code: string;
  site_id: string;
  label: string;
  expires_at: string;
  qr_payload: string;
};

export type FlagKind = "gap" | "low_coverage" | "flatline" | "zero" | "spike";

export type HourlyRow = {
  hour: string;
  mean_kw: number | null;
  peak_kw: number | null;
  samples: number;
  expected: number;
  over_threshold: boolean;
  flags: FlagKind[];
};

export type Hourly = {
  site: { id: string; label: string; threshold_kw: number };
  from: string;
  to: string;
  hours: number;
  completeness_pct: number;
  flag_counts: Record<FlagKind, number>;
  rows: HourlyRow[];
};

export type LivePoint = {
  t: string;
  k: number;
  model_h: number;
  exact: boolean;
  kw: number;
  lower: number;
  upper: number;
  over_threshold: boolean;
};

export type LiveForecast = {
  site: { id: string; label: string; threshold_kw: number; source: string };
  model: { site: string; proxy: boolean; name: string; stage2_by_horizon: Record<string, string>; note: string | null };
  generated_at: string;
  origin: string;
  last_reading_hour: string;
  readiness_code: number;
  weather_source: string;
  history_hours: number;
  notes: string[];
  points: LivePoint[];
  recent: Array<{ t: string; kw: number }>;
  peak_24h: { kw: number; at: string; over_by_kw: number | null };
  backtest_h1: { n: number; mae_kw: number | null; mape_pct: number | null; rows: Array<{ t: string; actual: number; forecast: number }> };
};

/** 409 from the forecast route: not enough measured history yet. */
export class NotEnoughHistory extends Error {}

export type UploadResult = {
  received: number;
  accepted: number;
  duplicates: number;
  rejected: number;
  errors: Array<{ index: number; error: string }>;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let msg = `Request failed (HTTP ${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d) => d?.msg ?? "").join("; ") || msg;
    } catch {
      /* not JSON */
    }
    if (res.status === 403) msg = "Only analysts can change data sources.";
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const liveApi = {
  sites: () => call<{ sites: LiveSite[] }>("/api/live/sites").then((r) => r.sites ?? []),
  addSite: (s: Omit<LiveSite, "source">) => call<LiveSite>("/api/live/sites", json(s)),
  devices: (site?: string) =>
    call<{ devices: Device[] }>(`/api/devices${site ? `?site=${encodeURIComponent(site)}` : ""}`).then(
      (r) => r.devices ?? [],
    ),
  enrol: (site_id: string, label?: string) =>
    call<Enrolment>("/api/devices/enrolment", json({ site_id, label: label || undefined })),
  revoke: (id: string) => call<unknown>(`/api/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  hourly: (site: string, hours = 168) =>
    call<Hourly>(`/api/live/sites/${encodeURIComponent(site)}/hourly?hours=${hours}`),
  forecast: async (site: string, readiness = 4): Promise<LiveForecast> => {
    const res = await apiFetch(`/api/live/sites/${encodeURIComponent(site)}/forecast?readiness=${readiness}`);
    if (res.status === 409) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      throw new NotEnoughHistory(body.detail ?? "Not enough readings to forecast yet.");
    }
    if (!res.ok) throw new Error(`Forecast failed (HTTP ${res.status})`);
    return (await res.json()) as LiveForecast;
  },
  upload: (site: string, csv: string) =>
    call<UploadResult>(`/api/live/sites/${encodeURIComponent(site)}/upload`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: csv,
    }),
};

/** "just now" / "4 min ago" / "3 h ago" / "2 d ago". */
export function ago(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "never";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}
