/**
 * AMAKA phone app shell.
 *
 * Bottom tabs: Fleet · Alerts · Sites · More. A site opens as a pushed screen
 * over the current tab (Android back / browser back closes it). Data is
 * loaded once per horizon and shared by every tab; pull down on any tab to
 * refresh. The signed-in account's role decides the content of each screen.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { App as CapApp } from "@capacitor/app";
import { BellRing, Building2, Map as MapIcon, UserRound, WifiOff } from "lucide-react";
import { applyHorizon, errMessage, fetchHealth, fetchOverview, fetchSiteAlerts, isAbort, isHorizon } from "../api";
import { clearFleetCache, fetchFleet, type FleetResponse } from "../fleet/fleetApi";
import { useSession } from "../auth/SessionContext";
import { POLL_MS, RESUME_REFRESH_MS, STORAGE } from "../config/app";
import { readPref, writePref } from "../lib/session";
import { isNative } from "../lib/platform";
import type { Alert, Overview } from "../types";
import type { Role } from "../fleet/roles";
import BootScreen from "../components/BootScreen";
import FleetScreen from "./FleetScreen";
import AlertsScreen from "./AlertsScreen";
import SitesScreen from "./SitesScreen";
import SiteScreen from "./SiteScreen";
import MoreScreen from "./MoreScreen";
import DataSourcesScreen from "./DataSourcesScreen";
import { Sheet, tap } from "./ui";
import "./mobile.css";

const MapExplorer = lazy(() => import("./map/MapExplorer"));

export type Tab = "fleet" | "alerts" | "sites" | "more";

export type SiteAlert = Alert & { siteId: string; siteLabel: string };

export type Loadable<T> = { data: T | null; loading: boolean; error: string | null };

const HORIZON_PREF = STORAGE.horizon;

export const HORIZON_COPY: Record<number, { label: string; desc: string }> = {
  1: { label: "H1", desc: "1 hour ahead — real-time dispatch" },
  6: { label: "H6", desc: "6 hours ahead — shift planning" },
  24: { label: "H24", desc: "24 hours ahead — day-ahead planning" },
  48: { label: "H48", desc: "48 hours ahead — two-day outlook" },
};

export default function MobileApp() {
  const { user } = useSession();
  const [tab, setTab] = useState<Tab>("fleet");
  const [siteId, setSiteId] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<number>(24);
  const [horizonSheet, setHorizonSheet] = useState(false);
  /** Full-screen satellite map: undefined = closed, else the site to switch to. */
  const [dataOpen, setDataOpen] = useState(false);
  const [mapFocus, setMapFocus] = useState<{ id: string | null } | undefined>(undefined);
  const [defaultHorizon, setDefaultHorizon] = useState<number>(24);

  const [overview, setOverview] = useState<Loadable<Overview>>({ data: null, loading: true, error: null });
  const [fleet, setFleet] = useState<Loadable<FleetResponse>>({ data: null, loading: true, error: null });
  const [alerts, setAlerts] = useState<Loadable<SiteAlert[]>>({ data: null, loading: true, error: null });
  const [linkOk, setLinkOk] = useState(true);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [reload, setReload] = useState(0);
  const prefLoaded = useRef(false);

  /* ----------------------- saved default horizon ----------------------- */
  useEffect(() => {
    readPref(HORIZON_PREF).then((v) => {
      const h = Number(v);
      if (isHorizon(h)) {
        setDefaultHorizon(h);
        setHorizon(h);
      }
      prefLoaded.current = true;
    });
  }, []);

  /* ------------------------------ overview ----------------------------- */
  useEffect(() => {
    const ctrl = new AbortController();
    setOverview((s) => ({ ...s, loading: true, error: null }));
    fetchOverview(ctrl.signal, horizon)
      .then((ov) => {
        setOverview({ data: applyHorizon(ov, horizon), loading: false, error: null });
        setLinkOk(true);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setOverview((s) => ({ ...s, loading: false, error: errMessage(e) }));
      });
    return () => ctrl.abort();
  }, [horizon, reload]);

  const at = overview.data?.fleet_anchor || overview.data?.sites[0]?.demo_anchor || "";

  /* ------------------------------- fleet ------------------------------- */
  useEffect(() => {
    if (!overview.data) return;
    const ctrl = new AbortController();
    setFleet((s) => ({ ...s, loading: true, error: null }));
    fetchFleet(at, horizon, { signal: ctrl.signal, force: reload > 0 })
      .then((data) => {
        setFleet({ data, loading: false, error: null });
        setLastSync(new Date());
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setFleet((s) => ({ ...s, loading: false, error: errMessage(e) }));
      });
    return () => ctrl.abort();
  }, [overview.data, at, horizon, reload]);

  /* ------------------------------ alerts ------------------------------- */
  useEffect(() => {
    const sites = overview.data?.sites;
    if (!sites) return;
    const ctrl = new AbortController();
    setAlerts((s) => ({ ...s, loading: true, error: null }));
    Promise.allSettled(
      sites.map((s) =>
        fetchSiteAlerts(s.id, { at, hours: 24, horizon }, ctrl.signal).then((list) =>
          list.map((a) => ({ ...a, siteId: s.id, siteLabel: s.label })),
        ),
      ),
    ).then((results) => {
      if (ctrl.signal.aborted) return;
      const ok = results.filter(
        (r): r is PromiseFulfilledResult<SiteAlert[]> => r.status === "fulfilled",
      );
      if (ok.length === 0) {
        const first = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
        setAlerts({ data: null, loading: false, error: errMessage(first?.reason) });
        return;
      }
      const rank = { critical: 0, warning: 1, info: 2 } as const;
      const list = ok
        .flatMap((r) => r.value)
        .sort((a, b) => rank[a.severity] - rank[b.severity] || b.timestamp.localeCompare(a.timestamp));
      setAlerts({ data: list, loading: false, error: null });
    });
    return () => ctrl.abort();
  }, [overview.data?.sites, at, horizon, reload]);

  /* ---------------------------- health poll ---------------------------- */
  useEffect(() => {
    let alive = true;
    const check = () =>
      fetchHealth()
        .then(() => alive && setLinkOk(true))
        .catch(() => alive && setLinkOk(false));
    const id = window.setInterval(check, POLL_MS.health);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const refresh = useCallback(async () => {
    clearFleetCache();
    setReload((n) => n + 1);
    try {
      await fetchHealth();
      setLinkOk(true);
    } catch {
      setLinkOk(false);
    }
  }, []);

  /* ----------------------------- navigation ---------------------------- */
  const siteOpenRef = useRef(false);
  siteOpenRef.current = siteId !== null;

  const openSite = useCallback((id: string) => {
    tap();
    setSiteId(id);
    if (!isNative()) window.history.pushState({ amakaSite: id }, "");
  }, []);

  const closeSite = useCallback(() => {
    if (!isNative() && window.history.state?.amakaSite) {
      window.history.back(); // popstate clears siteId
      return;
    }
    setSiteId(null);
  }, []);

  const selectTab = useCallback(
    (t: Tab) => {
      tap();
      if (siteOpenRef.current) closeSite();
      setDataOpen(false);
      setTab(t);
    },
    [closeSite],
  );

  // Browser back button closes the site screen.
  useEffect(() => {
    if (isNative()) return;
    const onPop = () => setSiteId(null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Android hardware back: sheet → site → Fleet tab → background the app.
  const backState = useRef({ horizonSheet, tab, mapOpen: false, dataOpen: false });
  backState.current = { horizonSheet, tab, mapOpen: mapFocus !== undefined, dataOpen };
  useEffect(() => {
    if (!isNative()) return;
    const handle = CapApp.addListener("backButton", () => {
      const s = backState.current;
      if (s.horizonSheet) setHorizonSheet(false);
      else if (s.mapOpen) setMapFocus(undefined);
      else if (s.dataOpen) setDataOpen(false);
      else if (siteOpenRef.current) setSiteId(null);
      else if (s.tab !== "fleet") setTab("fleet");
      else void CapApp.minimizeApp();
    });
    return () => {
      void handle.then((h) => h.remove());
    };
  }, []);

  // Refresh when the app returns to the foreground after a while.
  useEffect(() => {
    if (!isNative()) return;
    let hiddenAt = 0;
    const handle = CapApp.addListener("appStateChange", ({ isActive }) => {
      if (!isActive) hiddenAt = Date.now();
      else if (hiddenAt && Date.now() - hiddenAt > RESUME_REFRESH_MS) void refresh();
    });
    return () => {
      void handle.then((h) => h.remove());
    };
  }, [refresh]);

  const changeHorizon = useCallback((h: number) => {
    setHorizonSheet(false);
    if (isHorizon(h)) setHorizon(h);
  }, []);

  const saveDefaultHorizon = useCallback((h: number) => {
    if (!isHorizon(h)) return;
    setDefaultHorizon(h);
    setHorizon(h);
    void writePref(HORIZON_PREF, String(h));
  }, []);

  const alertBadge = useMemo(
    () => (alerts.data ?? []).filter((a) => a.severity !== "info").length,
    [alerts.data],
  );

  /* ------------------------------- render ------------------------------ */
  if (!overview.data) {
    if (overview.error) {
      return <BootScreen state="error" message={overview.error} onRetry={() => void refresh()} />;
    }
    return <BootScreen state="loading" />;
  }

  const ov = overview.data;
  const site = siteId ? ov.sites.find((s) => s.id === siteId) : undefined;
  const shared = {
    role: user.role,
    overview: ov,
    fleet,
    alerts,
    horizon,
    at,
    onOpenSite: openSite,
    onRefresh: refresh,
    onHorizonPress: () => setHorizonSheet(true),
    onOpenMap: (id: string | null) => {
      tap();
      setMapFocus({ id });
    },
  };

  return (
    <div className="m-app" data-role={user.role}>
      {!linkOk ? (
        <div className="m-offline" role="status">
          <WifiOff size={14} aria-hidden="true" />
          Data link lost — showing the last loaded data
        </div>
      ) : null}

      <div className="m-stage">
        <div className={`m-tabview${site ? " is-covered" : ""}`} aria-hidden={site ? true : undefined}>
          {tab === "fleet" ? <FleetScreen {...shared} /> : null}
          {tab === "alerts" ? <AlertsScreen {...shared} /> : null}
          {tab === "sites" ? <SitesScreen {...shared} /> : null}
          {tab === "more" ? (
            <MoreScreen
              {...shared}
              linkOk={linkOk}
              lastSync={lastSync}
              defaultHorizon={defaultHorizon}
              onDefaultHorizon={saveDefaultHorizon}
              onOpenDataSources={() => {
                tap();
                setDataOpen(true);
              }}
            />
          ) : null}
        </div>

        {dataOpen && !site ? <DataSourcesScreen role={user.role} onBack={() => setDataOpen(false)} /> : null}

        {site ? (
          <SiteScreen
            key={site.id}
            site={site}
            role={user.role}
            overview={ov}
            fleetSite={fleet.data?.sites.find((s) => s.id === site.id)}
            horizon={horizon}
            at={at}
            onBack={closeSite}
            onHorizonPress={() => setHorizonSheet(true)}
          />
        ) : null}
      </div>

      <nav className="m-tabbar" aria-label="Main">
        <TabButton icon={<MapIcon size={22} />} label="Fleet" active={tab === "fleet"} onClick={() => selectTab("fleet")} />
        <TabButton
          icon={<BellRing size={22} />}
          label="Alerts"
          badge={alertBadge}
          active={tab === "alerts"}
          onClick={() => selectTab("alerts")}
        />
        <TabButton icon={<Building2 size={22} />} label="Sites" active={tab === "sites"} onClick={() => selectTab("sites")} />
        <TabButton icon={<UserRound size={22} />} label="More" active={tab === "more"} onClick={() => selectTab("more")} />
      </nav>

      {mapFocus !== undefined ? (
        <Suspense fallback={null}>
          <MapExplorer
            sites={fleet.data?.sites ?? []}
            focusId={mapFocus.id}
            horizon={horizon}
            onClose={() => setMapFocus(undefined)}
            onOpenSite={(id) => {
              setMapFocus(undefined);
              openSite(id);
            }}
          />
        </Suspense>
      ) : null}

      <Sheet open={horizonSheet} title="Forecast horizon" onClose={() => setHorizonSheet(false)}>
        <p className="m-sheet-lede">How far ahead the forecast looks. Every screen updates.</p>
        <div className="m-choice-list" role="radiogroup" aria-label="Forecast horizon">
          {(ov.available_horizons.length ? ov.available_horizons : [1, 6, 24, 48]).map((h) => (
            <button
              key={h}
              type="button"
              role="radio"
              aria-checked={h === horizon}
              className={`m-choice${h === horizon ? " is-active" : ""}`}
              onClick={() => {
                tap();
                changeHorizon(h);
              }}
            >
              <span className="m-choice-code">{HORIZON_COPY[h]?.label ?? `H${h}`}</span>
              <span className="m-choice-desc">{HORIZON_COPY[h]?.desc ?? `${h} hours ahead`}</span>
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}

function TabButton({
  icon,
  label,
  active,
  badge,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  active: boolean;
  badge?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`m-tab${active ? " is-active" : ""}`}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
    >
      <span className="m-tab-icon" aria-hidden="true">
        {icon}
        {badge ? <span className="m-tab-badge">{badge > 9 ? "9+" : badge}</span> : null}
      </span>
      <span className="m-tab-label">{label}</span>
    </button>
  );
}

/** Props every tab screen receives. */
export type ScreenProps = {
  role: Role;
  overview: Overview;
  fleet: Loadable<FleetResponse>;
  alerts: Loadable<SiteAlert[]>;
  horizon: number;
  at: string;
  onOpenSite: (id: string) => void;
  onRefresh: () => Promise<void>;
  onHorizonPress: () => void;
  /** Open the satellite map, optionally switching straight to a site. */
  onOpenMap: (siteId: string | null) => void;
};
