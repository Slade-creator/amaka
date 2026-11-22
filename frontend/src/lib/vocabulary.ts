/**
 * AMAKA vocabulary — the single source of truth for user-facing terms.
 *
 * Plain operational English: the words a commander, energy manager or analyst
 * would use on shift. The glossary and wording rules live in
 * docs/VOCABULARY.md; keep the two in step.
 *
 * API keys (`readiness_code`, `surge_sites`, `surge_hours`, `variance_hours`)
 * are deliberately not renamed. They are data-contract names, not display copy.
 */

/* ------------------------------------------------------------------ */
/* Readiness levels                                                    */
/* ------------------------------------------------------------------ */

export type ReadinessCode = 1 | 2 | 3 | 4;

export type ReadinessTerm = {
  code: ReadinessCode;
  /** Sentence-case name, e.g. "Exercise surge". */
  name: string;
  /** Uppercase name for micro-labels, e.g. "EXERCISE SURGE". */
  nameUpper: string;
  /** Compact tag used on the map and legend, e.g. "R1 EXERCISE SURGE". */
  tag: string;
  /** One-line plain-English meaning. */
  description: string;
};

export const READINESS_TERMS: Record<ReadinessCode, ReadinessTerm> = {
  1: {
    code: 1,
    name: "Exercise surge",
    nameUpper: "EXERCISE SURGE",
    tag: "R1 EXERCISE SURGE",
    description: "Major exercise; load is well above normal.",
  },
  2: {
    code: 2,
    name: "High readiness",
    nameUpper: "HIGH READINESS",
    tag: "R2 HIGH READINESS",
    description: "Heightened operations; load is above normal.",
  },
  3: {
    code: 3,
    name: "Elevated",
    nameUpper: "ELEVATED",
    tag: "R3 ELEVATED",
    description: "Increased activity; load is slightly above normal.",
  },
  4: {
    code: 4,
    name: "Routine",
    nameUpper: "ROUTINE",
    tag: "R4 ROUTINE",
    description: "Normal day-to-day activity.",
  },
};

/** Coerce any value to a valid readiness code (default: routine). */
export function readinessCode(value: unknown): ReadinessCode {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return 4;
  const code = Math.round(n);
  return code >= 1 && code <= 4 ? (code as ReadinessCode) : 4;
}

export function readinessTerm(code: unknown): ReadinessTerm {
  return READINESS_TERMS[readinessCode(code)];
}

/** "Exercise surge", "High readiness", … */
export function readinessName(code: unknown): string {
  return readinessTerm(code).name;
}

/** "R1 EXERCISE SURGE", … */
export function readinessTag(code: unknown): string {
  return readinessTerm(code).tag;
}

/** R1 and R2 are the levels that raise load above routine. */
export function isHighReadiness(code: unknown): boolean {
  return readinessCode(code) <= 2;
}

/* ------------------------------------------------------------------ */
/* Site status                                                         */
/* ------------------------------------------------------------------ */

export type SiteStatus = "critical" | "warning" | "nominal";

export type SiteStatusTerm = {
  /** Sentence-case name. */
  name: string;
  /** Uppercase name for micro-labels. */
  nameUpper: string;
  /** Three-letter code for tight HUD legends. */
  code: string;
  /** One-line plain-English meaning. */
  description: string;
};

export const SITE_STATUS_TERMS: Record<SiteStatus, SiteStatusTerm> = {
  critical: {
    name: "Critical",
    nameUpper: "CRITICAL",
    code: "CRIT",
    description: "Forecast is at or above the peak threshold.",
  },
  warning: {
    name: "Warning",
    nameUpper: "WARNING",
    code: "WARN",
    description: "Forecast is within 3% of the peak threshold.",
  },
  nominal: {
    name: "Nominal",
    nameUpper: "NOMINAL",
    code: "NOM",
    description: "Forecast is below the warning band.",
  },
};

export function isSiteStatus(value: unknown): value is SiteStatus {
  return value === "critical" || value === "warning" || value === "nominal";
}

export function siteStatusTerm(status: SiteStatus): SiteStatusTerm {
  return SITE_STATUS_TERMS[status];
}

/* ------------------------------------------------------------------ */
/* Alerts                                                              */
/* ------------------------------------------------------------------ */

export type AlertSeverity = "critical" | "warning" | "info";

export const ALERT_SEVERITY_TERMS: Record<AlertSeverity, { name: string; nameUpper: string }> = {
  critical: { name: "Critical", nameUpper: "CRITICAL" },
  warning: { name: "Warning", nameUpper: "WARNING" },
  info: { name: "Info", nameUpper: "INFO" },
};

/** Plain names for the four alert rules. */
export const ALERT_KIND_TERMS: Record<string, { name: string; nameUpper: string }> = {
  peak: { name: "Peak threshold", nameUpper: "PEAK THRESHOLD" },
  surge: { name: "Readiness", nameUpper: "READINESS" },
  variance: { name: "Forecast range", nameUpper: "FORECAST RANGE" },
  readiness: { name: "Readiness", nameUpper: "READINESS" },
  model: { name: "Model", nameUpper: "MODEL" },
};

/* ------------------------------------------------------------------ */
/* Shared wording                                                      */
/* ------------------------------------------------------------------ */

/** Repeated terms that must read the same in every panel. */
export const TERMS = {
  actualLoad: "Actual load",
  forecast: "Forecast",
  hybridForecast: "Hybrid forecast",
  peakThreshold: "Peak threshold",
  headroom: "Headroom",
  shortfall: "Shortfall",
  readiness: "Readiness",
  selectedHour: "Selected hour",
  forecastRange: "95% forecast range",
  testPeriod: "2025 H2 test period",
  replay: "2025 H2 replay",
  dataLinkOk: "Data link OK",
  dataLinkDown: "Data link down",
  dataLinkChecking: "Checking data link",
} as const;

/**
 * Plain phrasing for a signed difference between a value and a reference.
 * "+63" becomes "63 kW above forecast"; "-63" becomes "63 kW below forecast".
 */
export function changePhrase(
  value: number | null | undefined,
  reference: string,
  unit = "kW",
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return `vs ${reference} —`;
  const rounded = Math.round(value);
  if (rounded === 0) return `in line with ${reference}`;
  return `${Math.abs(rounded).toLocaleString("en-US")} ${unit} ${
    rounded > 0 ? "above" : "below"
  } ${reference}`;
}
