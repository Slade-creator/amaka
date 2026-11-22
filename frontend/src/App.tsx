import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import GridBackground from "./components/GridBackground";
import Header from "./components/Header";
import Rail from "./components/Rail";
import SiteHeader, { type ConsoleTab } from "./components/SiteHeader";
import KpiRow from "./components/KpiRow";
import LoadTrace from "./components/LoadTrace";
import ChartNarrative from "./components/ChartNarrative";
import AlertFeed from "./components/AlertFeed";
import FacilityFacts from "./components/FacilityFacts";
import ExplainPanel from "./components/ExplainPanel";
import ModelPerf from "./components/ModelPerf";
import MidtermPanel from "./components/MidtermPanel";
import FleetTable from "./components/FleetTable";
import BootScreen from "./components/BootScreen";
import DispatchCard from "./components/DispatchCard";
import SceneWipe from "./components/SceneWipe";
import { FactRow, Panel, PanelHead } from "./components/ui";
import FleetView from "./fleet/FleetView";
import RoleSwitcher from "./fleet/RoleSwitcher";
import { getRoleConfig, type Role } from "./fleet/roles";
import { useSession } from "./auth/SessionContext";
import { POLL_MS, REPLAY_TICK_MS } from "./config/app";
import { DesktopPanels, DesktopToolbar, useFleetAlerts, type DesktopPanel } from "./desktop/DesktopTools";
import {
  applyHorizon,
  errMessage,
  fetchExplain,
  fetchHealth,
  fetchOverview,
  fetchSeries,
  isAbort,
  isHorizon,
} from "./api";
import { deriveAlerts } from "./lib/alerts";
import { fmtInt, fmtStamp, normTs } from "./lib/format";
import { anchorIndex, deriveBounds, normalizedLoad, projectedPeak, type Bounds } from "./lib/replay";
import type { ExplainResponse, Overview, ReplayRow } from "./types";

type ExplainUi = {
  data: ExplainResponse | null;
  status: "idle" | "loading" | "ok" | "error";
  error: string | null;
  siteId: string;
};

type View = "fleet" | "site";

type WipeState = {
  label: string;
  accent: string;
  mode: "enter" | "fleet";
  x?: number;
  y?: number;
} | null;

function AppShell({
  children,
  intensity,
  risk,
  wipe,
}: {
  children: ReactNode;
  intensity: number;
  /** 0..1 share of the fleet at risk; tints the background glow warm. */
  risk: number;
  wipe: WipeState;
}) {
  return (
    <div>
      <GridBackground intensity={intensity} risk={risk} className="pointer-events-none" />
      <div className="relative z-10">{children}</div>
      <SceneWipe
        active={wipe !== null}
        label={wipe?.label ?? ""}
        accent={wipe?.accent}
        mode={wipe?.mode}
        x={wipe?.x}
        y={wipe?.y}
      />
    </div>
  );
}

export default function App() {
  /* ------------------------------ data ------------------------------ */
  const [overview, setOverview] = useState<Overview | null>(null);
  const [boot, setBoot] = useState<{ status: "loading" | "error"; error: string | null }>({
    status: "loading",
    error: null,
  });
  const [bootAttempt, setBootAttempt] = useState(0);

  // The signed-in account decides the role; there is no role picker.
  const { user } = useSession();
  const [role, setRole] = useState<Role>(user.role);
  const [panel, setPanel] = useState<DesktopPanel>(null);
  const [mapFocus, setMapFocus] = useState<string | null>(null);
  const [view, setView] = useState<View>("fleet");
  const [activeTab, setActiveTab] = useState<ConsoleTab>("monitor");
  const [at, setAt] = useState<string>("");
  const [horizon, setHorizon] = useState<number>(24);
  const horizonRef = useRef<number>(24);
  const horizonTouchedRef = useRef(false);
  const horizonFetchRef = useRef<AbortController | null>(null);

  const [wipe, setWipe] = useState<WipeState>(null);
  const [bgBoost, setBgBoost] = useState(false);
  const [consoleEnter, setConsoleEnter] = useState(false);

  const [siteId, setSiteId] = useState("");
  const [rows, setRows] = useState<ReplayRow[]>([]);
  const [series, setSeries] = useState<{ syncing: boolean; error: string | null }>({
    syncing: false,
    error: null,
  });
  const [seriesAttempt, setSeriesAttempt] = useState(0);

  /* --------------------------- replay state -------------------------- */
  const [rangeHours, setRangeHours] = useState(72);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [frozen, setFrozen] = useState<Bounds | null>(null);

  /* --------------------------- explain state ------------------------- */
  const [explain, setExplain] = useState<ExplainUi>({
    data: null,
    status: "idle",
    error: null,
    siteId: "",
  });

  const [apiStatus, setApiStatus] = useState<"ok" | "down" | "checking">("checking");

  /* ------------------------------ refs ------------------------------- */
  const seriesCacheRef = useRef<Map<string, ReplayRow[]>>(new Map());
  const explainCacheRef = useRef<Map<string, ExplainResponse>>(new Map());
  const boundsRef = useRef<Bounds>({ ws: 0, we: 0 });
  const playingRef = useRef(false);
  const rangeRef = useRef(rangeHours);
  const lenRef = useRef(0);
  const explainTickRef = useRef(0);
  const lastExplainFetchRef = useRef(0);
  rangeRef.current = rangeHours;
  horizonRef.current = horizon;

  const site = useMemo(() => {
    if (!overview) return undefined;
    return overview.sites.find((s) => s.id === siteId) ?? overview.sites[0];
  }, [overview, siteId]);

  const len = rows.length;
  lenRef.current = len;
  const cursorRow = cursor >= 0 && cursor < len ? rows[cursor] : undefined;

  const bounds: Bounds = useMemo(() => {
    if (len <= 0) return { ws: 0, we: 0 };
    if (frozen && frozen.we > frozen.ws && frozen.we <= len && frozen.ws >= 0) return frozen;
    return deriveBounds(cursor, len, rangeHours);
  }, [frozen, cursor, len, rangeHours]);
  boundsRef.current = bounds;

  playingRef.current = playing;

  /* --------------------------- boot: overview ------------------------ */
  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;
    setBoot({ status: "loading", error: null });
    (async () => {
      try {
        const ov = await fetchOverview(ctrl.signal);
        if (!alive) return;
        if (!horizonTouchedRef.current && isHorizon(ov.default_horizon)) {
          horizonRef.current = ov.default_horizon;
          setHorizon(ov.default_horizon);
        }
        const prepared = applyHorizon(ov, horizonRef.current);
        setOverview(prepared);
        setSiteId((prev) => prev || prepared.sites[0]?.id || "");
        setAt(
          (prev) =>
            prev || prepared.fleet_anchor || prepared.sites[0]?.demo_anchor || "",
        );
        setApiStatus("ok");
      } catch (e) {
        if (!alive || isAbort(e)) return;
        setBoot({ status: "error", error: errMessage(e) });
        setApiStatus("down");
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [bootAttempt]);

  const overviewLoaded = overview !== null;
  const bootFailed = !overviewLoaded && boot.status === "error";

  /* ------------------- prefetch every site's series ------------------ */
  useEffect(() => {
    if (!overview) return;
    let cancelled = false;
    (async () => {
      for (const s of overview.sites) {
        if (cancelled) return;
        const key = `${s.id}|${horizon}`;
        if (seriesCacheRef.current.has(key)) continue;
        try {
          const data = await fetchSeries(s.id, undefined, horizon);
          if (!cancelled) seriesCacheRef.current.set(key, data);
        } catch {
          /* fallback to on-demand fetch */
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [overview, horizon]);

  /* --------------------------- series per site ----------------------- */
  useEffect(() => {
    if (!overviewLoaded || !siteId) return;
    const key = `${siteId}|${horizon}`;
    const cached = seriesCacheRef.current.get(key);
    if (cached && cached.length > 0) {
      const idx = anchorIndex(cached, at || site?.demo_anchor);
      setRows(cached);
      setCursor(idx);
      setSeries({ syncing: false, error: null });
      setFrozen(deriveBounds(idx, cached.length, rangeRef.current));
      return;
    }
    const ctrl = new AbortController();
    let alive = true;
    setSeries({ syncing: true, error: null });
    setRows([]);
    (async () => {
      try {
        const data = await fetchSeries(siteId, ctrl.signal, horizon);
        if (!alive) return;
        seriesCacheRef.current.set(key, data);
        const idx = anchorIndex(data, at || site?.demo_anchor);
        setRows(data);
        setCursor(idx);
        setSeries({ syncing: false, error: null });
        setFrozen(deriveBounds(idx, data.length, rangeRef.current));
      } catch (e) {
        if (!alive || isAbort(e)) return;
        setRows([]);
        setSeries({ syncing: false, error: errMessage(e) });
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overviewLoaded, siteId, seriesAttempt, at, horizon]);

  /* --------------------------- API health poll ----------------------- */
  useEffect(() => {
    const ctrl = new AbortController();
    let alive = true;
    const check = async () => {
      try {
        await fetchHealth(ctrl.signal);
        if (alive) setApiStatus("ok");
      } catch {
        if (alive) setApiStatus("down");
      }
    };
    void check();
    const id = window.setInterval(() => void check(), POLL_MS.health);
    return () => {
      alive = false;
      ctrl.abort();
      window.clearInterval(id);
    };
  }, [bootAttempt]);

  /* --------------------------- replay ticker ------------------------- */
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const b = boundsRef.current;
      if (b.we <= b.ws) return;
      setCursor((prev) => {
        const next = prev + 1;
        if (next > b.we - 1) return b.ws;
        if (next >= b.we) return b.ws;
        return next;
      });
    }, REPLAY_TICK_MS.desktop);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    if (playing && len === 0) setPlaying(false);
  }, [playing, len]);

  /* --------------------------- explain fetch ------------------------- */
  const cursorTs = cursorRow ? normTs(cursorRow.timestamp) : "";

  useEffect(() => {
    if (!siteId || !cursorTs) return;
    const key = `${siteId}|${cursorTs}|${horizon}`;
    const cached = explainCacheRef.current.get(key);
    if (cached) {
      setExplain({ data: cached, status: "ok", error: null, siteId });
      return;
    }
    if (playingRef.current) {
      explainTickRef.current += 1;
      if (explainTickRef.current % 5 !== 0) return;
    }
    const elapsed = Date.now() - lastExplainFetchRef.current;
    const delay = playingRef.current ? 0 : Math.max(400, 800 - elapsed);
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      lastExplainFetchRef.current = Date.now();
      setExplain((prev) => ({ ...prev, status: "loading", error: null, siteId }));
      fetchExplain(siteId, cursorTs, ctrl.signal, horizon)
        .then((data) => {
          const cache = explainCacheRef.current;
          cache.set(key, data);
          if (cache.size > 240) {
            const oldest = cache.keys().next().value;
            if (oldest !== undefined) cache.delete(oldest);
          }
          setExplain({ data, status: "ok", error: null, siteId });
        })
        .catch((e) => {
          if (isAbort(e)) return;
          setExplain((prev) => ({
            ...prev,
            status: prev.data ? "ok" : "error",
            error: errMessage(e),
            siteId,
          }));
        });
    }, delay);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [siteId, cursorTs, playing, horizon]);

  /* --------------------------- actions ------------------------------- */
  const selectSite = useCallback(
    (id: string) => {
      if (!id) return;
      if (cursorRow) setAt(normTs(cursorRow.timestamp));
      setSiteId((prev) => (prev === id ? prev : id));
    },
    [cursorRow],
  );

  const openSite = useCallback(
    (id: string) => {
      if (!id) return;
      const target = overview?.sites.find((s) => s.id === id);
      const accent = role ? getRoleConfig(role).accent : "var(--accent)";
      const marker = document.querySelector(".fleet-site-card.is-selected") as HTMLElement | null;
      const rect = marker?.getBoundingClientRect();
      const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2;
      const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2;
      setPlaying(false);
      setWipe({ label: `Entering ${target?.label ?? id}`, accent, mode: "enter", x, y });
      setBgBoost(true);
      window.setTimeout(() => {
        setSiteId(id);
        setView("site");
        setActiveTab("monitor");
        setConsoleEnter(true);
      }, 220);
      window.setTimeout(() => {
        setWipe(null);
        setBgBoost(false);
      }, 680);
      window.setTimeout(() => setConsoleEnter(false), 1100);
    },
    [overview, role],
  );

  const backToFleet = useCallback(() => {
    const accent = role ? getRoleConfig(role).accent : "var(--accent)";
    setWipe({ label: "Returning to fleet overview", accent, mode: "fleet" });
    setBgBoost(true);
    const ts = cursorRow ? normTs(cursorRow.timestamp) : at;
    window.setTimeout(() => {
      if (ts) setAt(ts);
      setPlaying(false);
      setView("fleet");
    }, 220);
    window.setTimeout(() => {
      setWipe(null);
      setBgBoost(false);
    }, 680);
  }, [cursorRow, at, role]);

  const changeRole = useCallback((r: Role) => {
    setRole(r);
    if (r === "commander") {
      setActiveTab((prev) => (prev === "drivers" ? "monitor" : prev));
    }
  }, []);

  const changeHorizon = useCallback(
    (h: number) => {
      if (!isHorizon(h) || h === horizonRef.current) return;
      horizonTouchedRef.current = true;
      horizonRef.current = h;
      setHorizon(h);

      const key = String(h);
      const keptTs = cursorRow ? normTs(cursorRow.timestamp) : at;
      const anchorFor = (ov: Overview): string => {
        const target = ov.sites.find((s) => s.id === siteId) ?? ov.sites[0];
        return (
          target?.horizons?.[key]?.demo_anchor ||
          ov.fleet_anchor_by_horizon?.[key] ||
          target?.demo_anchor ||
          ov.fleet_anchor ||
          ""
        );
      };
      const commit = (ov: Overview) => {
        const next = applyHorizon(ov, h);
        setOverview(next);
        const nextAt = keptTs || anchorFor(next);
        if (nextAt && nextAt !== at) setAt(nextAt);
      };

      if (overview) commit(overview);

      horizonFetchRef.current?.abort();
      const ctrl = new AbortController();
      horizonFetchRef.current = ctrl;
      fetchOverview(ctrl.signal, h)
        .then((ov) => {
          if (horizonRef.current !== h) return;
          commit(ov);
        })
        .catch(() => {});
    },
    [cursorRow, at, overview, siteId],
  );

  useEffect(
    () => () => {
      horizonFetchRef.current?.abort();
    },
    [],
  );

  const changeRange = useCallback(
    (h: number) => {
      setRangeHours(h);
      setFrozen(deriveBounds(cursor, lenRef.current, h));
    },
    [cursor],
  );

  const scrub = useCallback((idx: number) => {
    const v = Math.max(0, Math.min(idx, lenRef.current - 1));
    setCursor(v);
    const b = boundsRef.current;
    if (!(v >= b.ws && v < b.we)) {
      setFrozen(deriveBounds(v, lenRef.current, rangeRef.current));
    }
  }, []);

  const togglePlay = useCallback(() => {
    setPlaying((prev) => !prev);
  }, []);

  const retrySeries = useCallback(() => setSeriesAttempt((n) => n + 1), []);
  const retryBoot = useCallback(() => setBootAttempt((n) => n + 1), []);

  /* --------------------------- keyboard shortcuts -------------------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || el?.isContentEditable)
        return;
      if (tag === "button" || tag === "a") return;

      if (e.key.toLowerCase() === "f") {
        if (view === "site") backToFleet();
        return;
      }
      if (view !== "site") return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setPlaying(false);
        scrub(cursor - 1);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setPlaying(false);
        scrub(cursor + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, cursor, backToFleet, togglePlay, scrub]);

  /* ------------------- desktop tools (map / alerts / data) ----------- */
  const fleetAt = at || overview?.fleet_anchor || "";
  const fleetTools = useFleetAlerts(overview, fleetAt, horizon);
  const toolAlertCount = (fleetTools.alerts.data ?? []).filter((a) => a.severity !== "info").length;
  const tools = (
    <DesktopToolbar
      alertCount={toolAlertCount}
      onOpen={(p) => {
        setMapFocus(null);
        setPanel(p);
      }}
    />
  );
  // Share of sites at risk (critical or warning) -> background glow turns warm.
  const fleetRisk = fleetTools.fleet.data
    ? Math.min(1, (fleetTools.fleet.data.totals.sites_at_risk || 0) / Math.max(1, fleetTools.fleet.data.sites.length))
    : 0;
  const closePanel = useCallback(() => setPanel(null), []);
  const panels =
    overview && panel ? (
      <DesktopPanels
        panel={panel}
        mapFocus={mapFocus}
        onClose={closePanel}
        role={role}
        overview={overview}
        at={fleetAt}
        horizon={horizon}
        fleet={fleetTools.fleet}
        alerts={fleetTools.alerts}
        onRefresh={fleetTools.refresh}
        onOpenSite={(id) => openSite(id)}
        onOpenMap={(id) => {
          setMapFocus(id);
          setPanel("map");
        }}
      />
    ) : null;

  /* --------------------------- derived ------------------------------- */
  const peak24 = useMemo(
    () => (len > 0 ? projectedPeak(rows, cursor, 24) : null),
    [rows, cursor, len],
  );

  const alerts = useMemo(() => {
    if (!site || len === 0) return [];
    return deriveAlerts(
      rows,
      cursor,
      site.load?.threshold_kw ?? 0,
      site.metrics?.band_kw ?? 0,
    );
  }, [rows, cursor, site, len]);

  const intensity = useMemo(
    () => Math.min(0.45, 0.14 + normalizedLoad(site, cursorRow) * 0.25),
    [site, cursorRow],
  );
  const bgIntensity = bgBoost ? 0.75 : intensity;

  const from = rows[bounds.ws]?.timestamp;
  const to = rows[Math.max(0, bounds.we - 1)]?.timestamp;

  /* --------------------------- render -------------------------------- */
  if (bootFailed) {
    return <BootScreen state="error" message={boot.error} onRetry={retryBoot} />;
  }
  if (!overview) {
    return <BootScreen state="loading" />;
  }
  if (view === "fleet") {
    return (
      <AppShell intensity={bgIntensity} risk={fleetRisk} wipe={wipe}>
        <FleetView
          role={role}
          at={at || overview.fleet_anchor || ""}
          horizon={horizon}
          availableHorizons={overview.available_horizons}
          onHorizonChange={changeHorizon}
          onRoleChange={changeRole}
          onSelectSite={openSite}
          withBackground={false}
          tools={tools}
        />
        {panels}
      </AppShell>
    );
  }
  if (!site) {
    return <BootScreen state="loading" />;
  }

  const showDriversTab = role !== "commander";
  const syncing = series.syncing;
  const seriesFailed = series.error !== null && len === 0;

  return (
    <AppShell intensity={bgIntensity} risk={fleetRisk} wipe={wipe}>
      <div className={consoleEnter ? "scene-enter" : undefined}>
        <Header
          apiStatus={apiStatus}
          roleBadge={<RoleSwitcher role={role} onChange={changeRole} compact />}
          stamp={cursorRow ? fmtStamp(cursorRow.timestamp) : undefined}
          horizon={horizon}
          availableHorizons={overview.available_horizons}
          onHorizonChange={changeHorizon}
          onBackToFleet={backToFleet}
          tools={tools}
        />
        {panels}
        <Rail
          sites={overview.sites}
          activeSiteId={site.id}
          activeLoadKw={cursorRow?.actual_kw}
          onSelectSite={selectSite}
          onBackToFleet={backToFleet}
          apiStatus={apiStatus}
          model={overview.model}
        />

        <main className="main-shell">
          <div className="mx-auto w-full max-w-[1520px] px-6 py-4">
            <SiteHeader
              site={site}
              from={from}
              to={to}
              hasRows={len > 0}
              horizon={horizon}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              showDriversTab={showDriversTab}
              alertCount={alerts.length}
            />

            <KpiRow site={site} cursorRow={cursorRow} peak24={peak24} horizon={horizon} />

            {/* ---------------- TAB 1: MONITOR ---------------- */}
            {activeTab === "monitor" ? (
              <section id="forecast" className="forecast-grid mt-3">
                <div className="left-col">
                  <LoadTrace
                    site={site}
                    rows={rows}
                    bounds={bounds}
                    cursor={cursor}
                    rangeHours={rangeHours}
                    horizon={horizon}
                    playing={playing}
                    onRange={changeRange}
                    onScrub={scrub}
                    onTogglePlay={togglePlay}
                    error={series.error}
                    onRetry={seriesFailed ? retrySeries : undefined}
                  />
                  <ChartNarrative
                    site={site}
                    role={role}
                    horizon={horizon}
                    at={cursorRow ? normTs(cursorRow.timestamp) : ""}
                    from={from}
                    to={to}
                    playing={playing}
                    hasRows={len > 0}
                  />
                </div>
                <div className="right-col">
                  {role === "operator" ? (
                    <DispatchCard site={site} rows={rows} cursor={cursor} peak24={peak24} />
                  ) : null}
                  <AlertFeed alerts={alerts} periodCounts={site.alerts} />
                  {role !== "operator" ? (
                    <Panel>
                      <PanelHead
                        title="Site Limits"
                        right={
                          <button
                            type="button"
                            className="text-[11px] text-lime bg-transparent border-0 p-0 cursor-pointer hover:underline"
                            onClick={() => setActiveTab("specs")}
                          >
                            All specs →
                          </button>
                        }
                      />
                      <div className="px-3.5 py-1.5">
                        <FactRow
                          label="Peak threshold"
                          value={`${fmtInt(site.load?.threshold_kw)} kW`}
                          accent
                        />
                        <FactRow label="Base load" value={`${fmtInt(site.base_load_kw)} kW`} />
                        <FactRow label="Rooftop PV" value={`${fmtInt(site.pv_kwp)} kWp`} />
                        <FactRow
                          label="Test-period peak"
                          value={`${fmtInt(site.load?.peak_kw, 0)} kW`}
                        />
                      </div>
                    </Panel>
                  ) : null}
                </div>
              </section>
            ) : null}

            {/* ---------------- TAB 2: FORECAST DRIVERS (SHAP) ---------------- */}
            {activeTab === "drivers" ? (
              <section className="mt-3 flex flex-col gap-3">
                <div className="panel flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
                  <div className="flex items-center gap-3">
                    <span className="text-[12px] text-dim">Selected Hour</span>
                    <span className="num text-[13px] font-medium text-fg">
                      {cursorRow ? fmtStamp(cursorRow.timestamp) : "—"}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        className="btn btn-compact"
                        onClick={() => {
                          setPlaying(false);
                          scrub(cursor - 1);
                        }}
                        title="Previous hour (←)"
                      >
                        <ChevronLeft size={13} aria-hidden="true" />
                        -1h
                      </button>
                      <button
                        type="button"
                        className="btn btn-compact"
                        onClick={() => {
                          setPlaying(false);
                          scrub(cursor + 1);
                        }}
                        title="Next hour (→)"
                      >
                        +1h
                        <ChevronRight size={13} aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-1 max-w-[420px] items-center gap-2.5">
                    <input
                      className="scrub flex-1"
                      type="range"
                      min={bounds.ws}
                      max={Math.max(bounds.ws, bounds.we - 1)}
                      step={1}
                      value={Math.min(
                        Math.max(cursor, bounds.ws),
                        Math.max(bounds.ws, bounds.we - 1),
                      )}
                      onChange={(e) => scrub(Number(e.target.value))}
                      aria-label="Scrub hour for SHAP drivers"
                    />
                  </div>
                </div>

                <ExplainPanel
                  site={site}
                  stamp={cursorRow ? fmtStamp(cursorRow.timestamp) : "—"}
                  forecastKw={cursorRow?.hybrid_kw ?? null}
                  xgbKw={cursorRow?.xgb_kw ?? null}
                  horizon={horizon}
                  data={explain.siteId === site.id ? explain.data : null}
                  status={explain.siteId === site.id ? explain.status : "idle"}
                  error={explain.siteId === site.id ? explain.error : null}
                />
              </section>
            ) : null}

            {/* ---------------- TAB 2.5: STRATEGIC MID/LONG-TERM (7D-90D) ---------------- */}
            {activeTab === "midterm" ? <MidtermPanel site={site} /> : null}

            {/* ---------------- TAB 3: MODEL & SPECS ---------------- */}
            {activeTab === "specs" ? (
              <section className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_340px] items-start">
                <div className="flex flex-col gap-3 min-w-0">
                  <ModelPerf site={site} horizon={horizon} />
                  <FleetTable
                    sites={overview.sites}
                    activeId={site.id}
                    onSelect={selectSite}
                    horizon={horizon}
                  />
                </div>
                <div className="flex flex-col gap-3">
                  <FacilityFacts site={site} />
                  <Panel>
                    <PanelHead title="Data & Model Provenance" />
                    <div className="px-4 py-2.5 text-[11.5px] leading-relaxed text-dim flex flex-col gap-2">
                      <div>
                        <span className="text-fg font-medium">Architecture: </span>
                        {overview.model?.name ?? "Hybrid XGBoost + Residual Learner"}
                      </div>
                      <div>
                        <span className="text-fg font-medium">Evaluation Window: </span>
                        <span className="num">
                          {String(overview.test_period?.start ?? "2025-07-01").slice(0, 10)} →{" "}
                          {String(overview.test_period?.end ?? "2025-12-31").slice(0, 10)}
                        </span>{" "}
                        (held-out test period)
                      </div>
                      <div>
                        <span className="text-fg font-medium">Source: </span>
                        <span className="num text-[11px]">
                          config/v2_sites.json · data/v2/replay_{site.id}_h{horizon}.csv
                        </span>
                      </div>
                    </div>
                  </Panel>
                </div>
              </section>
            ) : null}
          </div>
        </main>

        {syncing ? (
          <div className="sync-overlay" role="status" aria-live="polite">
            <span className="sync-badge">Loading {site.label}…</span>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
