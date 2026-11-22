/**
 * AMAKA API types — mirrors docs/BUILD_CONTRACT.md.
 * Every shape is defensive: components must tolerate missing/odd fields
 * (normalisation happens in api.ts, optional chaining in components).
 */

export type ReplayRow = {
  /** Target hour — the hour being forecast (v2 compares at the same time). */
  timestamp: string;
  actual_kw: number;
  xgb_kw: number;
  hybrid_kw: number;
  lower_kw: number;
  upper_kw: number;
  /** v2 only: residual learner selected for this site/horizon ("hgb" | "lstm"). */
  selected_model?: string;
  readiness_code: 1 | 2 | 3 | 4;
  readiness_label: string;
  temperature_c: number;
  humidity_pct: number;
  radiation_wm2: number;
  cloud_cover_pct: number;
};

export type ShapRow = {
  feature: string;
  label: string;
  value: number;
  contribution_kw: number;
  direction: "up" | "down";
};

export type Alert = {
  id: string;
  severity: "critical" | "warning" | "info";
  kind: "peak" | "surge" | "variance" | "readiness" | "model";
  title: string;
  detail: string;
  timestamp: string;
};

export type SiteMetrics = {
  xgb_rmse: number;
  xgb_mae: number;
  hyb_rmse: number;
  hyb_mae: number;
  hyb_mape: number;
  persistence_mae: number;
  /** v1 legacy seasonal naive (t-168). Kept for backwards compatibility. */
  seasonal_naive_mae: number;
  /** v2 baseline rows (0 when the backend is still on v1). */
  seasonal_naive_24_mae: number;
  seasonal_naive_168_mae: number;
  standalone_lstm_mae: number;
  /** v2 residual learner for this site/horizon: "hgb" | "lstm". */
  selected_model?: string;
  band_kw: number;
};

export type SiteLoad = {
  avg_kw: number;
  peak_kw: number;
  threshold_kw: number;
  latest_actual_kw: number;
  latest_hybrid_kw: number;
};

export type SiteAlertCounts = {
  peak_hours: number;
  surge_hours: number;
  variance_hours: number;
};

export type SiteCost = {
  energy_month_kwh: number;
  baseline_monthly_zmw: number;
  monthly_saving_zmw: number;
  annual_saving_zmw: number;
  demand_saving_zmw: number;
  fuel_saving_zmw: number;
  saving_pct: number;
};

export type Site = {
  id: string;
  label: string;
  location: string;
  type: string;
  base_load_kw: number;
  pv_kwp: number;
  headcount: number;
  floor_area_m2: number;
  lat: number;
  lon: number;
  test_start: string;
  test_end: string;
  rows: number;
  demo_anchor: string;
  demo_start: string;
  /** v2 forecast horizon (hours) these metrics describe; 1/undefined on v1. */
  horizon?: number;
  /** v2 residual learner selected for this site/horizon: "hgb" | "lstm". */
  selected_model?: string;
  metrics: SiteMetrics;
  load: SiteLoad;
  alerts: SiteAlertCounts;
  cost: SiteCost;
  /** v2 nested per-horizon payloads keyed "1" | "6" | "24" | "48". */
  horizons?: Record<string, Site>;
};

export type ModelInfo = {
  name: string;
  stage1: string;
  stage2: string;
  horizon: string;
  features: number;
};

export type Overview = {
  generated_at: string;
  test_period: { start: string; end: string };
  /** Payload version — "v2" for the multi-horizon pipeline, absent on v1. */
  version?: string;
  /** Config default forecast horizon (24 on v2, unused on v1). */
  default_horizon: number;
  /** Horizons the backend can serve (empty on a v1 payload). */
  available_horizons: number[];
  /** Fleet-wide demo moment used by the map landing. */
  fleet_anchor?: string;
  /** Per-horizon fleet anchors, keyed "1" | "6" | "24" | "48". */
  fleet_anchor_by_horizon?: Record<string, string>;
  model: ModelInfo;
  cost_assumptions: Record<string, number>;
  sites: Site[];
  /** added by /api/overview */
  served_at?: string;
};

export type SeriesResponse = {
  site: string;
  rows: ReplayRow[];
};

export type ExplainResponse = {
  site: string;
  at: string;
  base_kw: number;
  top: ShapRow[];
  all?: ShapRow[];
};

/** "model" = grounded LLM prose; "rules" = deterministic fallback. */
export type NarrativeSource = "model" | "rules";

/** Why the rule-based fallback was used (null on a model answer). */
export type NarrativeFallbackReason =
  | "not_configured"
  | "breaker"
  | "provider"
  | "grounding"
  | null;

/** Subset of the server-side fact pack shown in the evidence line. */
export type NarrativeFacts = {
  peak_threshold_kw?: number;
  selected_hour?: {
    readiness?: string;
    headroom_kw?: number;
    status?: string;
    model_inputs?: Array<{ label?: string; contribution_kw?: number }>;
  };
  window?: {
    hours?: number;
    actual_max_kw?: number;
    actual_max_at?: string;
    hours_over_threshold?: number;
    mape_pct?: number | null;
    high_readiness_hours?: number;
  };
};

export type NarrativeResponse = {
  site: string;
  horizon: number;
  role: string;
  at: string;
  window: { from: string; to: string };
  text: string;
  source: NarrativeSource;
  model?: string | null;
  cached: boolean;
  /** Why the rule-based fallback was used, when applicable. */
  notice?: string | null;
  fallback_reason?: NarrativeFallbackReason;
  /** The computed fact pack the text is grounded in. */
  facts?: NarrativeFacts;
};

export type NarrativeAnswerResponse = {
  site: string;
  horizon: number;
  role: string;
  question: string;
  answer: string;
  source: NarrativeSource;
  model?: string | null;
  cached: boolean;
  notice?: string | null;
  fallback_reason?: NarrativeFallbackReason;
};

export type HealthResponse = {
  status: string;
  sites?: number;
  generated_at?: string;
  /** "v2" once the multi-horizon backend is live; absent on v1. */
  version?: string;
  horizons?: number[];
};

/** One contiguous readiness segment (used by the strip + chart shading). */
export type ReadinessRun = {
  startIdx: number;
  endIdx: number;
  code: number;
  label: string;
};

export type MidtermModelMetrics = {
  rmse: number;
  mae: number;
  mape: number;
  wape: number;
  bias: number;
  peak_bias: number;
  peak_mae: number;
  cum_energy_bias_pct: number;
  window_30d_mape: number;
  monthly_peak_mae_kw: number;
  monthly_peak_mae_zmw: number;
  picp_95: number;
  interval_halfwidth_kw: number;
  skill_vs_persistence_pct: number;
  skill_vs_seasonal_pct: number;
  selected_stage2: string;
};

export type MidtermRow = {
  date: string;
  actual_mean_kw: number;
  xgb_mean_kw: number;
  hybrid_mean_kw: number;
  lower_mean_kw: number;
  upper_mean_kw: number;
  selected_mean_model: string;
  actual_energy_mwh: number;
  hybrid_energy_mwh: number;
  actual_peak_kw: number;
  xgb_peak_kw: number;
  hybrid_peak_kw: number;
  lower_peak_kw: number;
  upper_peak_kw: number;
  selected_peak_model: string;
  temp_mean_c: number;
  temp_max_c: number;
  humidity_pct: number;
  readiness_mult_max: number;
  is_holiday: number;
  is_weekend: number;
};

export type SiteMidtermResponse = {
  site: string;
  label: string;
  location: string;
  type: string;
  horizon_days: number;
  available_horizons_days: number[];
  threshold_kw: number;
  metrics: {
    daily_mean_kw: Record<string, MidtermModelMetrics>;
    daily_peak_kw: Record<string, MidtermModelMetrics>;
  };
  rows: MidtermRow[];
};
