import { useEffect, useRef, useState, type ReactNode } from "react";
import { Maximize2 } from "lucide-react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FleetSite } from "../../fleet/fleetApi";
import { buildStyle, fitZambia, loadBoundary, maplibregl, siteLngLat } from "./satMap";
import "./map.css";

type Props = {
  sites: FleetSite[];
  /** Open the full-screen explorer, optionally switching to a site. */
  onOpenMap: (siteId: string | null) => void;
  /** Shown when satellite imagery cannot load (offline). */
  fallback: ReactNode;
};

/** Static satellite overview of Zambia for the Fleet tab; tap to explore. */
export default function SatMapCard({ sites, onOpenMap, fallback }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const openRef = useRef(onOpenMap);
  openRef.current = onOpenMap;

  useEffect(() => {
    let cancelled = false;
    let map: maplibregl.Map | null = null;
    let errors = 0;
    loadBoundary().then((boundary) => {
      if (cancelled || !holder.current) return;
      map = new maplibregl.Map({
        container: holder.current,
        style: buildStyle(boundary),
        center: [27.85, -13.4],
        zoom: 4.4,
        interactive: false,
        attributionControl: { compact: true },
        fadeDuration: 0,
      });
      mapRef.current = map;
      fitZambia(map, 14);
      map.on("error", (e) => {
        if ((e as { sourceId?: string }).sourceId === "sat" && !map?.loaded() && ++errors >= 4) setFailed(true);
      });
      map.once("load", () => {
        if (cancelled || !map) return;
        map.resize();
        fitZambia(map, 14);
        // Start with the compact attribution collapsed (the "i" button).
        holder.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
        setReady(true);
      });
      const onResize = () => map && fitZambia(map, 14);
      window.addEventListener("resize", onResize);
      map.once("remove", () => window.removeEventListener("resize", onResize));
    });
    return () => {
      cancelled = true;
      markers.current.forEach((m) => m.remove());
      markers.current.clear();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const s of sites) {
      const ll = siteLngLat(s.id, s.lat, s.lon);
      if (!ll) continue;
      let m = markers.current.get(s.id);
      if (!m) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "mx-pin is-small";
        el.innerHTML = `<span class="mx-pin-pulse"></span><span class="mx-pin-dot"></span>`;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          openRef.current(s.id);
        });
        m = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(ll).addTo(map);
        markers.current.set(s.id, m);
      }
      const el = m.getElement();
      el.classList.remove("is-critical", "is-warning", "is-nominal");
      el.classList.add(`is-${s.status}`);
      m.getElement().setAttribute("aria-label", `${s.label}, ${s.status}. Open on map`);
    }
  }, [sites, ready]);

  if (failed) return <>{fallback}</>;

  return (
    <div className="mx-card-map">
      <div ref={holder} className="mx-card-canvas" onClick={() => onOpenMap(null)} />
      {!ready ? <div className="mx-card-loading skeleton" aria-hidden="true" /> : null}
      <button type="button" className="mx-expand" onClick={() => onOpenMap(null)}>
        <Maximize2 size={14} aria-hidden="true" /> Explore
      </button>
    </div>
  );
}
