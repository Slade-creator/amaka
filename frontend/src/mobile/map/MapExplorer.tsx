import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, Crosshair, Globe2, ImageOff } from "lucide-react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FleetSite } from "../../fleet/fleetApi";
import { fmtInt } from "../../lib/format";
import { readinessName } from "../../lib/vocabulary";
import { StatusDot, StatusPill, tap } from "../ui";
import {
  buildStyle,
  fitZambia,
  loadBoundary,
  maplibregl,
  orbit,
  siteLngLat,
  switchTo,
  type Beat,
} from "./satMap";
import "./map.css";

type Props = {
  sites: FleetSite[];
  /** Site to switch to as soon as the map is ready (null = country view). */
  focusId: string | null;
  horizon: number;
  onClose: () => void;
  onOpenSite: (id: string) => void;
};

type Phase = "loading" | "country" | "switching" | "landed" | "failed";

/**
 * Full-screen satellite explorer. Choosing a site runs the switch: the camera
 * pulls up into the sky in stepped jumps, sweeps across Zambia, then drops in
 * stages onto the real base and slowly orbits it.
 */
export default function MapExplorer({ sites, focusId, horizon, onClose, onOpenSite }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const flight = useRef<AbortController | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [selected, setSelected] = useState<string | null>(null);
  const [beat, setBeat] = useState<{ kind: Beat; n: number } | null>(null);
  const sitesRef = useRef(sites);
  sitesRef.current = sites;

  const site = sites.find((s) => s.id === selected) ?? null;

  /* ------------------------------ create map ------------------------------ */
  useEffect(() => {
    let cancelled = false;
    let map: maplibregl.Map | null = null;
    let tileErrors = 0;
    loadBoundary().then((boundary) => {
      if (cancelled || !holder.current) return;
      map = new maplibregl.Map({
        container: holder.current,
        style: buildStyle(boundary),
        center: [27.85, -13.4],
        zoom: 4.6,
        attributionControl: { compact: true },
        maxPitch: 70,
        fadeDuration: 150,
      });
      mapRef.current = map;
      fitZambia(map, 24);
      map.on("error", (e) => {
        const src = (e as { sourceId?: string }).sourceId;
        if (src === "sat" && !map?.loaded()) {
          tileErrors += 1;
          if (tileErrors >= 4) setPhase("failed");
        }
      });
      // Pin labels only once zoomed in (they overlap at country scale).
      const syncZoom = () => holder.current?.classList.toggle("is-far", (map?.getZoom() ?? 0) < 8);
      map.on("zoom", syncZoom);
      syncZoom();
      map.once("load", () => {
        if (cancelled) return;
        setPhase((p) => (p === "failed" ? p : "country"));
      });
    });
    return () => {
      cancelled = true;
      flight.current?.abort();
      markers.current.forEach((m) => m.remove());
      markers.current.clear();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  /* ------------------------------- markers -------------------------------- */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || phase === "loading" || phase === "failed") return;
    for (const s of sites) {
      const ll = siteLngLat(s.id, s.lat, s.lon);
      if (!ll) continue;
      let m = markers.current.get(s.id);
      if (!m) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "mx-pin";
        el.innerHTML = `<span class="mx-pin-pulse"></span><span class="mx-pin-dot"></span><span class="mx-pin-label"></span>`;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          go(s.id);
        });
        m = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(ll).addTo(map);
        markers.current.set(s.id, m);
      }
      const el = m.getElement();
      // Toggle classes only: MapLibre's own marker classes position the element.
      el.classList.remove("is-critical", "is-warning", "is-nominal");
      el.classList.add(`is-${s.status}`);
      el.classList.toggle("is-selected", s.id === selected);
      el.setAttribute("aria-label", `${s.label}, ${s.status}`);
      const label = el.querySelector(".mx-pin-label");
      if (label) label.textContent = s.label;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sites, phase, selected]);

  /* -------------------------------- switch -------------------------------- */
  const go = useCallback((id: string) => {
    const map = mapRef.current;
    const s = sitesRef.current.find((x) => x.id === id);
    const ll = s ? siteLngLat(s.id, s.lat, s.lon) : null;
    if (!map || !ll) return;
    flight.current?.abort();
    const ctrl = new AbortController();
    flight.current = ctrl;
    setSelected(id);
    setPhase("switching");
    tap("medium");
    switchTo(map, ll, ctrl.signal, (kind, n) => {
      setBeat({ kind, n });
      tap(kind === "land" ? "medium" : "light");
    })
      .then(() => {
        setBeat(null);
        setPhase("landed");
        orbit(map, ctrl.signal);
      })
      .catch(() => {
        /* aborted by a newer switch or close */
      });
  }, []);

  const backToCountry = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    flight.current?.abort();
    tap();
    setSelected(null);
    setPhase("country");
    setBeat({ kind: "up", n: 99 });
    map.easeTo({ pitch: 0, bearing: 0, duration: 400 });
    window.setTimeout(() => {
      fitZambia(map, 24, 1100);
      window.setTimeout(() => setBeat(null), 500);
    }, 380);
  }, []);

  // Initial focus from the caller (a tapped pin on the Fleet card).
  const focusedOnce = useRef(false);
  useEffect(() => {
    if (phase !== "country" || focusedOnce.current || !focusId) return;
    focusedOnce.current = true;
    const t = window.setTimeout(() => go(focusId), 350);
    return () => window.clearTimeout(t);
  }, [phase, focusId, go]);

  const switching = phase === "switching";

  return (
    <div
      className={`mx-root${switching ? " is-switching" : ""}${beat ? ` beat-${beat.kind}` : ""}`}
      role="dialog"
      aria-modal="true"
      aria-label="Fleet satellite map"
    >
      <div ref={holder} className="mx-map" key="map" />
      {beat ? <div key={`${beat.kind}-${beat.n}`} className="mx-flash" aria-hidden="true" /> : null}
      <div className="mx-bars" aria-hidden="true" />

      <header className="mx-top">
        <button type="button" className="mx-round" onClick={onClose} aria-label="Close map">
          <ChevronLeft size={22} aria-hidden="true" />
        </button>
        <div className="mx-title">
          <strong>{site && phase !== "country" ? site.label : "Zambia fleet"}</strong>
          <span className="num">
            {site && phase !== "country"
              ? `${site.location} · ${Math.abs(siteLngLat(site.id, site.lat, site.lon)?.[1] ?? 0).toFixed(3)}°S ${(
                  siteLngLat(site.id, site.lat, site.lon)?.[0] ?? 0
                ).toFixed(3)}°E`
              : `${sites.length} sites · H${horizon} forecast`}
          </span>
        </div>
        {phase === "landed" || switching ? (
          <button type="button" className="mx-round" onClick={backToCountry} aria-label="Back to country view">
            <Globe2 size={20} aria-hidden="true" />
          </button>
        ) : null}
      </header>

      {switching && site ? (
        <div className="mx-hud" aria-live="polite">
          <span className="mx-hud-k">SWITCHING TO</span>
          <span className="mx-hud-v">{site.label}</span>
        </div>
      ) : null}

      {phase === "loading" ? (
        <div className="mx-center">
          <Crosshair size={26} className="mx-spin-slow" aria-hidden="true" />
          <span>Acquiring satellite imagery…</span>
        </div>
      ) : null}

      {phase === "failed" ? (
        <div className="mx-center is-error" role="alert">
          <ImageOff size={26} aria-hidden="true" />
          <span>Satellite imagery needs an internet connection.</span>
          <button type="button" className="m-btn" onClick={onClose}>
            Back to fleet
          </button>
        </div>
      ) : null}

      <footer className="mx-bottom">
        {phase === "landed" && site ? (
          <div className={`mx-card is-${site.status}`}>
            <div className="mx-card-top">
              <div>
                <strong>{site.label}</strong>
                <span>
                  {site.type} · R{site.readiness_code} {readinessName(site.readiness_code)}
                </span>
              </div>
              <StatusPill status={site.status} />
            </div>
            <div className="mx-card-figs">
              <span>
                <small>Load</small>
                <b className="num">{fmtInt(site.actual_kw)} kW</b>
              </span>
              <span>
                <small>Forecast</small>
                <b className="num">{fmtInt(site.hybrid_kw)} kW</b>
              </span>
              <span>
                <small>{site.headroom_kw < 0 ? "Over threshold" : "Headroom"}</small>
                <b className={`num ${site.headroom_kw < 0 ? "is-critical" : "is-good"}`}>
                  {fmtInt(Math.abs(site.headroom_kw))} kW
                </b>
              </span>
            </div>
            <button type="button" className="mx-open" onClick={() => onOpenSite(site.id)}>
              Open site console
            </button>
          </div>
        ) : null}

        {phase !== "loading" && phase !== "failed" ? (
          <div className="mx-chips" role="list" aria-label="Switch to site">
            {sites.map((s) => (
              <button
                key={s.id}
                type="button"
                role="listitem"
                className={`mx-chip${s.id === selected ? " is-active" : ""}`}
                onClick={() => go(s.id)}
                disabled={switching && s.id === selected}
              >
                <StatusDot status={s.status} />
                <span>{s.label}</span>
              </button>
            ))}
          </div>
        ) : null}
      </footer>
    </div>
  );
}
