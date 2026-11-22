import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import "./fleet.css";
import GridBackground from "../components/GridBackground";
import { AmakaMark } from "../components/ui";
import { fmtInt, fmtStamp, fmtZmw } from "../lib/format";
import { siteStatusTerm } from "../lib/vocabulary";
import { getRoleConfig, type Role } from "./roles";
import RoleSwitcher from "./RoleSwitcher";
import FleetMap from "./FleetMap";
import HorizonSwitcher from "../components/HorizonSwitcher";
import {
  TEST_ROWS_PER_SITE,
  deriveTotals,
  fetchFleet,
  isAbort,
  peekFleet,
  type FleetResponse,
  type FleetSite,
  type FleetStatus,
} from "./fleetApi";

type Props = {
  role: Role;
  /** Replay cursor hour (ISO local) — the fleet endpoint is keyed on this. */
  at: string;
  /** v2 forecast horizon (hours) — the second key of the fleet endpoint. */
  horizon: number;
  /** Horizons the backend offers (empty/1-item hides the switcher). */
  availableHorizons?: number[];
  onHorizonChange: (h: number) => void;
  onRoleChange: (r: Role) => void;
  onSelectSite: (id: string) => void;
  /** Optional: opens the site console (back navigation from the map). */
  onBackToConsole?: () => void;
  /** Render the WebGPU hex field here (false when the shell already does). */
  withBackground?: boolean;
  /** Extra tool buttons (satellite, alerts, data sources). */
  tools?: ReactNode;
};

type ApiState = "sync" | "ok" | "stale" | "down";

const RANK: Record<FleetStatus, number> = { critical: 0, warning: 1, nominal: 2 };

const STATUS_COLOR: Record<FleetStatus, string> = {
  critical: "var(--crit)",
  warning: "var(--warn)",
  nominal: "var(--accent)",
};

/** Sorted worst-first risk slice. */
function topRisk(sites: FleetSite[], n: number): FleetSite[] {
  return [...sites]
    .sort((a, b) => RANK[a.status] - RANK[b.status] || a.headroom_kw - b.headroom_kw)
    .slice(0, n);
}

/**
 * Minimal, intentional Fleet Command view:
 * - Clean top bar with horizon selector, replay timestamp, and role switcher
 * - Zambia map canvas on the left with clean markers
 * - Single consolidated right panel combining role summary, 3 key metrics, and the 6-site roster
 */
export default function FleetView({
  role,
  at,
  horizon,
  availableHorizons,
  onHorizonChange,
  onRoleChange,
  onSelectSite,
  onBackToConsole,
  withBackground = true,
  tools,
}: Props) {
  const cfg = getRoleConfig(role);

  const [data, setData] = useState<FleetResponse | null>(null);
  const [status, setStatus] = useState<ApiState>("sync");
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [zoomTarget, setZoomTarget] = useState<string | null>(null);
  const dataRef = useRef<FleetResponse | null>(null);
  const forceRef = useRef(false);

  const retry = useCallback(() => {
    forceRef.current = true;
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    const force = forceRef.current;
    forceRef.current = false;

    const hit = !force ? peekFleet(at, horizon) : null;
    if (hit) {
      dataRef.current = hit;
      setData(hit);
      setError(null);
      setStatus("ok");
      return;
    }

    const ac = new AbortController();
    let alive = true;
    setStatus("sync");
    fetchFleet(at, horizon, { signal: ac.signal, force })
      .then((res) => {
        if (!alive) return;
        dataRef.current = res;
        setData(res);
        setError(null);
        setStatus("ok");
      })
      .catch((e: unknown) => {
        if (!alive || isAbort(e)) return;
        setError(e instanceof Error && e.message ? e.message : "Unknown error");
        setStatus(dataRef.current ? "stale" : "down");
      });
    return () => {
      alive = false;
      ac.abort();
    };
  }, [at, horizon, role, nonce]);

  const sites = data?.sites ?? null;
  const loading = status === "sync";

  const roster = useMemo(() => {
    if (!sites) return null;
    if (role === "analyst") {
      return [...sites].sort((a, b) => (b.mape ?? 0) - (a.mape ?? 0));
    }
    return [...sites].sort(
      (a, b) => RANK[a.status] - RANK[b.status] || a.headroom_kw - b.headroom_kw,
    );
  }, [sites, role]);

  const handleRequestZoom = useCallback((id: string) => setZoomTarget(id), []);
  const handleZoomed = useCallback(
    (id: string) => {
      setZoomTarget(null);
      onSelectSite(id);
    },
    [onSelectSite],
  );

  const rootStyle = {
    "--role-accent": cfg.accent,
    "--role-accent-dim": cfg.accentDim,
  } as CSSProperties;

  const totals = sites && sites.length > 0 ? deriveTotals(sites) : null;
  const worstRisk = sites ? topRisk(sites, 1)[0] : null;
  const worstMape =
    sites && sites.length > 0
      ? [...sites].sort((a, b) => (b.mape ?? 0) - (a.mape ?? 0))[0]
      : null;
  const avgMape =
    sites && sites.length > 0
      ? sites.reduce((sum, s) => sum + (s.mape ?? 0), 0) / sites.length
      : null;

  return (
    <div className="fleet-root" style={rootStyle}>
      {withBackground ? <GridBackground intensity={0.18} /> : null}

      {/* ---------------- top bar ---------------- */}
      <header className="fleet-topbar">
        <div className="fleet-brand">
          <AmakaMark size={22} />
          <span className="fleet-wordmark">AMAKA</span>
          <span className="fleet-brand-divider" aria-hidden="true" />
          <span className="fleet-viewname">Fleet Overview</span>
        </div>

        <div className="fleet-topbar-right">
          {tools}
          <HorizonSwitcher
            horizon={horizon}
            onChange={onHorizonChange}
            available={availableHorizons}
            compact
            accent={cfg.accent}
            label="Forecast horizon"
          />

          <span className="fleet-time" aria-label="Replay hour">
            {fmtStamp(at)} <b>CAT</b>
          </span>

          {status === "stale" || status === "down" ? (
            <span className={`fleet-api is-${status}`}>
              <span className="fleet-api-dot" aria-hidden="true" />
              <span className="fleet-api-text">
                {status === "stale" ? "Data stale" : "Offline"}
              </span>
              <button type="button" className="fleet-retry" onClick={retry}>
                Retry
              </button>
            </span>
          ) : null}

          <RoleSwitcher role={role} onChange={onRoleChange} compact />

          {onBackToConsole ? (
            <button type="button" className="btn fleet-console-btn" onClick={onBackToConsole}>
              Site View
            </button>
          ) : null}
        </div>

        <span
          className={`fleet-progress${loading ? " is-on" : ""}`}
          aria-hidden="true"
        >
          <i />
        </span>
      </header>

      {/* ---------------- body ---------------- */}
      <div className="fleet-body">
        <FleetMap
          role={role}
          horizon={horizon}
          sites={sites}
          loading={loading}
          error={error}
          onRetry={retry}
          zoomTarget={zoomTarget}
          onRequestZoom={handleRequestZoom}
          onZoomed={handleZoomed}
        />

        <aside className="fleet-col" aria-label="Fleet summary and sites">
          <section className="fleet-panel fleet-unified-panel">
            {/* 1. Role summary takeaway */}
            <div className="fleet-summary-box">
              <div className="fleet-summary-kicker">
                <span>{cfg.purpose}</span>
                <span className="num text-[10px] text-dim">H{horizon} Forecast</span>
              </div>

              {role === "commander" ? (
                <>
                  <p className="fleet-summary-headline">
                    {totals && worstRisk
                      ? totals.sites_at_risk > 0
                        ? `${totals.sites_at_risk} sites at peak risk. ${worstRisk.label} has the largest shortfall (${fmtInt(Math.round(Math.abs(worstRisk.headroom_kw)))} kW).`
                        : "All 6 sites are operating within peak thresholds."
                      : "Loading fleet status…"}
                  </p>
                  <div className="fleet-stat-strip">
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">At Risk</span>
                      <span
                        className={`fleet-stat-value${
                          totals && totals.sites_at_risk > 0 ? " is-amber" : ""
                        }`}
                      >
                        {totals ? `${totals.sites_at_risk} / 6` : "—"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Total Load</span>
                      <span className="fleet-stat-value">
                        {totals ? `${(totals.load_kw / 1000).toFixed(1)} MW` : "—"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Monthly Saving</span>
                      <span className="fleet-stat-value is-lime">
                        {totals ? fmtZmw(totals.saving_zmw) : "—"}
                      </span>
                    </div>
                  </div>
                </>
              ) : role === "operator" ? (
                <>
                  <p className="fleet-summary-headline">
                    {worstRisk
                      ? worstRisk.headroom_kw < 0
                        ? `Pre-start ${Math.ceil(-worstRisk.headroom_kw / 100) * 100} kW generator at ${worstRisk.label} (${fmtInt(Math.round(-worstRisk.headroom_kw))} kW over threshold).`
                        : "All sites within peak thresholds. Hold backup generators on standby."
                      : "Loading dispatch status…"}
                  </p>
                  <div className="fleet-stat-strip">
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Dispatch Alerts</span>
                      <span
                        className={`fleet-stat-value${
                          totals && totals.sites_at_risk > 0 ? " is-amber" : ""
                        }`}
                      >
                        {totals ? `${totals.sites_at_risk}` : "—"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Peak Shortfall</span>
                      <span
                        className={`fleet-stat-value${
                          worstRisk && worstRisk.headroom_kw < 0 ? " is-red" : ""
                        }`}
                      >
                        {worstRisk && worstRisk.headroom_kw < 0
                          ? `${fmtInt(Math.round(-worstRisk.headroom_kw))} kW`
                          : "0 kW"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">High Readiness</span>
                      <span className="fleet-stat-value">
                        {totals ? `${totals.surge_sites} sites` : "—"}
                      </span>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <p className="fleet-summary-headline">
                    {avgMape !== null && worstMape
                      ? `Mean fleet error is ${avgMape.toFixed(2)}% MAPE across 6 sites (${worstMape.label} highest at ${worstMape.mape.toFixed(2)}%).`
                      : "Loading model metrics…"}
                  </p>
                  <div className="fleet-stat-strip">
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Fleet MAPE</span>
                      <span className="fleet-stat-value is-lime">
                        {avgMape !== null ? `${avgMape.toFixed(2)}%` : "—"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Max Error</span>
                      <span className="fleet-stat-value">
                        {worstMape ? `${worstMape.mape.toFixed(2)}%` : "—"}
                      </span>
                    </div>
                    <div className="fleet-stat-cell">
                      <span className="fleet-stat-label">Test Window</span>
                      <span className="fleet-stat-value">
                        {sites ? `${fmtInt(sites.length * TEST_ROWS_PER_SITE)} h` : "—"}
                      </span>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* 2. Unified Site Roster */}
            <header className="fleet-roster-head">
              <span>Sites ({sites ? sites.length : 6})</span>
              <span>Load</span>
              <span>{role === "analyst" ? "MAPE" : "Headroom"}</span>
            </header>

            <div className="fleet-roster-list">
              {roster
                ? roster.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`fleet-roster-row${zoomTarget === s.id ? " is-selected" : ""}`}
                      onClick={() => setZoomTarget(s.id)}
                      aria-label={`${s.label}, ${siteStatusTerm(s.status).name}, ${fmtInt(
                        Math.round(s.actual_kw),
                      )} kilowatts. Open site console.`}
                    >
                      <span
                        className="frr-bar"
                        style={{ background: STATUS_COLOR[s.status] }}
                        aria-hidden="true"
                      />
                      <span className="frr-main">
                        <span className="frr-name">{s.label}</span>
                        <span className="frr-loc">
                          {s.location} · R{s.readiness_code}
                        </span>
                      </span>
                      <span className="frr-load">
                        {fmtInt(Math.round(s.actual_kw))}
                        <i>kW</i>
                      </span>
                      {role === "analyst" ? (
                        <span className="frr-head">
                          {s.mape.toFixed(2)}%
                        </span>
                      ) : (
                        <span
                          className={`frr-head${s.headroom_kw < 0 ? " is-neg" : ""}`}
                        >
                          {s.headroom_kw < 0 ? "" : "+"}
                          {fmtInt(Math.round(s.headroom_kw))} kW
                        </span>
                      )}
                      <span className="frr-go" aria-hidden="true">
                        ›
                      </span>
                    </button>
                  ))
                : Array.from({ length: 6 }, (_, i) => (
                    <div key={i} className="fleet-roster-skel" aria-hidden="true">
                      <span className="skeleton" />
                    </div>
                  ))}
              {roster && roster.length === 0 ? (
                <p className="fleet-empty">No site data</p>
              ) : null}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
