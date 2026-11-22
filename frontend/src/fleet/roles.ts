/**
 * Operating roles for the AMAKA fleet map.
 *
 * Three entry roles, each with its own accent and its own set of right-column
 * panel sections. Kept as plain data so every fleet component reads from one
 * source of truth (accent colours, copy, panel wiring).
 *
 * Display copy follows docs/VOCABULARY.md: role names are nouns (Commander,
 * Energy Manager, Analyst) and the purpose is a plain view name.
 */

export type Role = "commander" | "operator" | "analyst";

/** Panel sections the right column can render (one panel per role). */
export type PanelSection =
  | "fleet_readiness"
  | "cost_exposure"
  | "dispatch"
  | "peak_shaving"
  | "weather"
  | "model_health"
  | "data_quality"
  | "exports";

export type RoleConfig = {
  key: Role;
  /** Full display label. */
  label: string;
  /** View name: strategic, operations or analysis. */
  purpose: "STRATEGIC VIEW" | "OPERATIONS VIEW" | "ANALYSIS VIEW";
  /** 3-letter code for compact controls. */
  code: string;
  /** Signal accent hex. */
  accent: string;
  /** Dim/tint version of the accent (backgrounds, washes). */
  accentDim: string;
  /** One-line description on the role gate. */
  description: string;
  /** Which right-column panels this role sees. */
  sections: PanelSection[];
};

/** Stable ordering for the gate cards and the switcher menu. */
export const ROLE_ORDER: Role[] = ["commander", "operator", "analyst"];

export const ROLE_CONFIG: Record<Role, RoleConfig> = {
  commander: {
    key: "commander",
    label: "COMMANDER",
    purpose: "STRATEGIC VIEW",
    code: "CMD",
    accent: "var(--violet)",
    accentDim: "rgb(var(--violet-rgb)/0.14)",
    description: "Fleet status, peak risk and cost exposure.",
    sections: ["fleet_readiness", "cost_exposure"],
  },
  operator: {
    key: "operator",
    label: "ENERGY MANAGER",
    purpose: "OPERATIONS VIEW",
    code: "OPS",
    accent: "var(--teal)",
    accentDim: "rgb(var(--teal-rgb)/0.12)",
    description: "Generator dispatch, peak shaving and site weather.",
    sections: ["dispatch", "peak_shaving", "weather"],
  },
  analyst: {
    key: "analyst",
    label: "ANALYST",
    purpose: "ANALYSIS VIEW",
    code: "ANL",
    accent: "var(--info)",
    accentDim: "rgb(var(--info-rgb)/0.12)",
    description: "Model accuracy, data quality and fleet comparison.",
    sections: ["model_health", "data_quality", "exports"],
  },
};

/** Role the gate opens on. */
export const DEFAULT_ROLE: Role = "commander";

/** Runtime guard — URL params / storage / API values may be anything. */
export function isRole(v: unknown): v is Role {
  return v === "commander" || v === "operator" || v === "analyst";
}

/** Config lookup that never throws on a bad value. */
export function getRoleConfig(role: Role): RoleConfig {
  return ROLE_CONFIG[role] ?? ROLE_CONFIG[DEFAULT_ROLE];
}
