/**
 * Desktop access to the features first built for the phone: satellite map
 * with the switch, fleet-wide alerts inbox, and Data sources (meter kits,
 * SCADA connectors, CSV upload, live forecast). The phone screens are reused
 * inside a right-hand drawer so both layouts behave identically.
 */

import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { BellRing, Globe2, RadioTower, X } from "lucide-react";
import { errMessage, fetchSiteAlerts, isAbort } from "../api";
import { fetchFleet, type FleetResponse } from "../fleet/fleetApi";
import type { Role } from "../fleet/roles";
import type { Overview } from "../types";
import type { Loadable, SiteAlert } from "../mobile/MobileApp";
import AlertsScreen from "../mobile/AlertsScreen";
import DataSourcesScreen from "../mobile/DataSourcesScreen";
import "../mobile/mobile.css";
import "./desktop-tools.css";

const MapExplorer = lazy(() => import("../mobile/map/MapExplorer"));

export type DesktopPanel = null | "map" | "alerts" | "data";

/** Fleet snapshot + every site's server alerts for the selected hour. */
export function useFleetAlerts(overview: Overview | null, at: string, horizon: number) {
  const [fleet, setFleet] = useState<Loadable<FleetResponse>>({ data: null, loading: true, error: null });
  const [alerts, setAlerts] = useState<Loadable<SiteAlert[]>>({ data: null, loading: true, error: null });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!overview || !at) return;
    const ctrl = new AbortController();
    fetchFleet(at, horizon, { signal: ctrl.signal, force: reload > 0 })
      .then((data) => setFleet({ data, loading: false, error: null }))
      .catch((e) => !isAbort(e) && setFleet((s) => ({ ...s, loading: false, error: errMessage(e) })));
    Promise.allSettled(
      overview.sites.map((s) =>
        fetchSiteAlerts(s.id, { at, hours: 24, horizon }, ctrl.signal).then((list) =>
          list.map((a) => ({ ...a, siteId: s.id, siteLabel: s.label })),
        ),
      ),
    ).then((results) => {
      if (ctrl.signal.aborted) return;
      const ok = results.filter((r): r is PromiseFulfilledResult<SiteAlert[]> => r.status === "fulfilled");
      if (!ok.length) {
        setAlerts({ data: null, loading: false, error: "Could not load alerts" });
        return;
      }
      const rank = { critical: 0, warning: 1, info: 2 } as const;
      setAlerts({
        data: ok
          .flatMap((r) => r.value)
          .sort((a, b) => rank[a.severity] - rank[b.severity] || b.timestamp.localeCompare(a.timestamp)),
        loading: false,
        error: null,
      });
    });
    return () => ctrl.abort();
  }, [overview, at, horizon, reload]);

  const refresh = useCallback(async () => setReload((n) => n + 1), []);
  return { fleet, alerts, refresh };
}

/** Buttons for the desktop top bars. */
export function DesktopToolbar({
  onOpen,
  alertCount,
}: {
  onOpen: (p: Exclude<DesktopPanel, null>) => void;
  alertCount: number;
}) {
  return (
    <div className="dk-toolbar" role="toolbar" aria-label="Tools">
      <button type="button" className="dk-tool" onClick={() => onOpen("map")}>
        <Globe2 size={14} aria-hidden="true" /> Satellite
      </button>
      <button type="button" className="dk-tool" onClick={() => onOpen("alerts")}>
        <BellRing size={14} aria-hidden="true" /> Alerts
        {alertCount > 0 ? <span className="dk-badge">{alertCount > 99 ? "99+" : alertCount}</span> : null}
      </button>
      <button type="button" className="dk-tool" onClick={() => onOpen("data")}>
        <RadioTower size={14} aria-hidden="true" /> Data sources
      </button>
    </div>
  );
}

/** The open panel: full-screen satellite map, or a right-hand drawer. */
export function DesktopPanels({
  panel,
  mapFocus,
  onClose,
  role,
  overview,
  at,
  horizon,
  fleet,
  alerts,
  onRefresh,
  onOpenSite,
  onOpenMap,
}: {
  panel: DesktopPanel;
  mapFocus: string | null;
  onClose: () => void;
  role: Role;
  overview: Overview;
  at: string;
  horizon: number;
  fleet: Loadable<FleetResponse>;
  alerts: Loadable<SiteAlert[]>;
  onRefresh: () => Promise<void>;
  onOpenSite: (id: string) => void;
  onOpenMap: (id: string | null) => void;
}) {
  useEffect(() => {
    if (!panel) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector(".m-sheet-root")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel, onClose]);

  if (!panel) return null;

  if (panel === "map") {
    return (
      <Suspense fallback={null}>
        <div className="dk-map">
          <MapExplorer
            sites={fleet.data?.sites ?? []}
            focusId={mapFocus}
            horizon={horizon}
            onClose={onClose}
            onOpenSite={(id) => {
              onClose();
              onOpenSite(id);
            }}
          />
        </div>
      </Suspense>
    );
  }

  return (
    <div className="dk-drawer-root">
      <button type="button" className="dk-scrim" aria-label="Close panel" onClick={onClose} />
      <aside className="dk-drawer" aria-label={panel === "alerts" ? "Alerts" : "Data sources"}>
        <button type="button" className="dk-close" onClick={onClose} aria-label="Close">
          <X size={18} aria-hidden="true" />
        </button>
        {panel === "alerts" ? (
          <AlertsScreen
            role={role}
            overview={overview}
            fleet={fleet}
            alerts={alerts}
            horizon={horizon}
            at={at}
            onOpenSite={(id) => {
              onClose();
              onOpenSite(id);
            }}
            onRefresh={onRefresh}
            onHorizonPress={() => {}}
            onOpenMap={onOpenMap}
          />
        ) : (
          <DataSourcesScreen role={role} onBack={onClose} />
        )}
      </aside>
    </div>
  );
}
