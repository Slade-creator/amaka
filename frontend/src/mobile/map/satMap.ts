/**
 * Satellite map plumbing for the phone app (MapLibre GL + Esri World Imagery).
 *
 * - `buildStyle()` — darkened satellite imagery, place labels, a dim mask
 *   outside Zambia and a glowing lime border (the ops-room look).
 * - `switchTo()` — the "character switch" camera move: pull up into the sky in
 *   stepped jumps, sweep across the country, then drop down in stages onto
 *   the real site. Each step fires `onBeat` so the UI can pulse blur/flash
 *   and haptics in time with the camera.
 *
 * Imagery: Esri World Imagery (Esri, Maxar, Earthstar Geographics and the GIS
 * user community). No API key is required for this tile endpoint; the
 * attribution control on the map must stay visible.
 */

import maplibregl, { type Map as MLMap, type StyleSpecification } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import { color } from "../../theme/theme";

export const ZAMBIA_CENTER: [number, number] = [27.85, -13.4];
export const ZAMBIA_BOUNDS: [[number, number], [number, number]] = [
  [21.9, -18.1],
  [33.8, -8.1],
];

/** Real site coordinates (WGS84) — the fleet payload carries the same values. */
export const SITE_COORDS: Record<string, [number, number]> = {
  arakan: [28.321, -15.435],
  kohima: [28.488, -14.406],
  makeni: [28.25, -15.47],
  mikango: [28.682, -15.329],
  peter_zuze: [28.6639, -12.9972],
  tug_argan: [28.665, -12.995],
};

export function siteLngLat(id: string, lat?: number, lon?: number): [number, number] | null {
  if (typeof lat === "number" && typeof lon === "number" && lat !== 0 && lon !== 0) return [lon, lat];
  return SITE_COORDS[id] ?? null;
}

const IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const LABELS =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";

export function buildStyle(boundary: FeatureCollection | null): StyleSpecification {
  const ring = boundaryRing(boundary);
  const style: StyleSpecification = {
    version: 8,
    sources: {
      sat: {
        type: "raster",
        tiles: [IMAGERY],
        tileSize: 256,
        maxzoom: 18,
        attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
      },
      labels: { type: "raster", tiles: [LABELS], tileSize: 256, maxzoom: 16 },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": color("bg-deep") } },
      {
        id: "sat",
        type: "raster",
        source: "sat",
        paint: {
          "raster-saturation": -0.25,
          "raster-contrast": 0.12,
          "raster-brightness-max": 0.82,
          "raster-fade-duration": 220,
        },
      },
      { id: "labels", type: "raster", source: "labels", paint: { "raster-opacity": 0.75 } },
    ],
  };
  if (ring) {
    style.sources.zambia = {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } },
    };
    // World polygon with Zambia as a hole → dims everything outside the country.
    style.sources.mask = {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [-179, -85],
              [179, -85],
              [179, 85],
              [-179, 85],
              [-179, -85],
            ],
            [...ring].reverse(),
          ],
        },
      },
    };
    style.layers.push(
      {
        id: "mask",
        type: "fill",
        source: "mask",
        paint: { "fill-color": color("bg-void"), "fill-opacity": 0.58 },
      },
      {
        id: "border-glow",
        type: "line",
        source: "zambia",
        paint: { "line-color": color("accent"), "line-width": 9, "line-opacity": 0.18, "line-blur": 6 },
      },
      {
        id: "border",
        type: "line",
        source: "zambia",
        paint: { "line-color": color("accent"), "line-width": 1.6, "line-opacity": 0.9 },
      },
    );
  }
  return style;
}

function boundaryRing(fc: FeatureCollection | null): number[][] | null {
  const g = fc?.features?.[0]?.geometry;
  if (!g) return null;
  if (g.type === "Polygon") return g.coordinates[0] as number[][];
  if (g.type === "MultiPolygon") {
    return (g.coordinates as number[][][][])
      .map((p) => p[0])
      .sort((a, b) => b.length - a.length)[0];
  }
  return null;
}

let boundaryCache: Promise<FeatureCollection | null> | null = null;

/** The Zambia outline ships with the app (public/zambia.geojson). */
export function loadBoundary(): Promise<FeatureCollection | null> {
  if (!boundaryCache) {
    boundaryCache = fetch(`${import.meta.env.BASE_URL}zambia.geojson`)
      .then((r) => (r.ok ? (r.json() as Promise<FeatureCollection>) : null))
      .catch(() => null);
  }
  return boundaryCache;
}

/** Fit the whole country with phone-sized padding. */
export function fitZambia(map: MLMap, padding = 16, duration = 0): void {
  map.fitBounds(ZAMBIA_BOUNDS, { padding, duration, pitch: 0, bearing: 0 });
}

/* ------------------------------------------------------------------ */
/* the switch                                                          */
/* ------------------------------------------------------------------ */

type EaseOpts = Parameters<MLMap["easeTo"]>[0];

function easeStep(map: MLMap, opts: EaseOpts, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("aborted", "AbortError"));
    const done = () => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    };
    const onAbort = () => {
      map.off("moveend", done);
      map.stop();
      reject(new DOMException("aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    map.once("moveend", done);
    map.easeTo({ ...opts, essential: true });
  });
}

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = window.setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(t);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true },
    );
  });

export type Beat = "up" | "sweep" | "down" | "land";

const easeIn = (t: number) => t * t * t;
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Character-switch camera move to `target` (lng, lat).
 * Up: stepped pull-backs into the sky. Sweep: a flat top-down pan high above
 * the country. Down: three hard drops, then a slow tilted settle over the site.
 */
export async function switchTo(
  map: MLMap,
  target: [number, number],
  signal: AbortSignal,
  onBeat: (beat: Beat, step: number) => void,
): Promise<void> {
  const z0 = map.getZoom();
  const skyZoom = 4.6;
  // Up: as many as three jumps, depending on how close we start.
  const ups = [z0 - 2.2, z0 - 4.4, skyZoom].filter((z, i, a) => z > skyZoom || i === a.length - 1);
  let step = 0;
  for (const z of ups) {
    onBeat("up", step++);
    await easeStep(map, { zoom: Math.max(skyZoom, z), pitch: 0, bearing: 0, duration: 340, easing: easeIn }, signal);
    await wait(90, signal);
  }
  onBeat("sweep", step++);
  await easeStep(map, { center: target, zoom: skyZoom, duration: 900, easing: (t) => t * (2 - t) }, signal);
  await wait(120, signal);
  // Down: hard drops with a beat each, then the cinematic settle.
  for (const z of [8.2, 11.6]) {
    onBeat("down", step++);
    await easeStep(map, { center: target, zoom: z, duration: 360, easing: easeIn }, signal);
    await wait(110, signal);
  }
  onBeat("land", step++);
  await easeStep(
    map,
    { center: target, zoom: 15, pitch: 52, bearing: -28, duration: 1500, easing: easeOut },
    signal,
  );
}

/** A slow orbit around the current centre (idle cinematic after landing). */
export function orbit(map: MLMap, signal: AbortSignal): void {
  let last = performance.now();
  const tick = (now: number) => {
    if (signal.aborted) return;
    const dt = now - last;
    last = now;
    if (!map.isMoving()) map.setBearing(map.getBearing() + dt * 0.0035);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export { maplibregl };
