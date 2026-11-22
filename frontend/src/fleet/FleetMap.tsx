import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { MAP_SITES, ZAMBIA_PATH, ZAMBIA_VIEWBOX } from "./zambia";
import { type FleetSite, type FleetStatus } from "./fleetApi";
import { getRoleConfig, type Role } from "./roles";
import { fmtInt } from "../lib/format";
import { readinessName, SITE_STATUS_TERMS, siteStatusTerm } from "../lib/vocabulary";

type Props = {
  role: Role;
  /** v2 forecast horizon (hours) — shown in the map title. */
  horizon: number;
  /** Fleet payload — null while loading / after a failure. */
  sites: FleetSite[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  /** Site to zoom into; set by the map itself or by the roster. */
  zoomTarget: string | null;
  /** A card / dot / roster row was activated. */
  onRequestZoom: (id: string) => void;
  /** Zoom transition finished — parent should open the site console. */
  onZoomed: (id: string) => void;
  /** Optional persistent highlight (active site). */
  selectedId?: string | null;
};

type Offset = { dx: number; dy: number; side: "left" | "right" };

const LABEL_OFFSETS: Record<string, Offset> = {
  kohima: { dx: -146, dy: -56, side: "left" },
  arakan: { dx: -146, dy: 0, side: "left" },
  makeni: { dx: -146, dy: 56, side: "left" },
  mikango: { dx: 32, dy: 14, side: "right" },
  peter_zuze: { dx: 32, dy: -56, side: "right" },
  tug_argan: { dx: 32, dy: 56, side: "right" },
};

function spreadFor(scale: number): number {
  return scale < 0.85 ? 1.38 : 1;
}

const STATUS_COLOR: Record<FleetStatus, string> = {
  critical: "var(--crit)",
  warning: "var(--warn)",
  nominal: "var(--accent)",
};

const CITIES = [
  { name: "Lusaka", x: 524, y: 596, tx: 515, ty: 599, anchor: "end" },
  { name: "Ndola", x: 552, y: 370, tx: 543, ty: 373, anchor: "end" },
] as const;

const ZOOM_SCALE = 3.1;

/**
 * Clean, quiet Zambia fleet map:
 * - Subtle country silhouette + Lusaka–Ndola corridor
 * - Compact site cards showing Site Name, Readiness badge (R1–R4), and Load (kW)
 * - Quiet legend in the bottom-left corner without duplicating the right panel's totals
 */
export default function FleetMap({
  role,
  horizon,
  sites,
  loading,
  error,
  onRetry,
  zoomTarget,
  onRequestZoom,
  onZoomed,
  selectedId,
}: Props) {
  const worldRef = useRef<HTMLDivElement | null>(null);
  const zoomedRef = useRef(onZoomed);
  zoomedRef.current = onZoomed;

  const [box, setBox] = useState({ w: 0, h: 0 });
  const [zooming, setZooming] = useState<string | null>(null);

  useLayoutEffect(() => {
    const el = worldRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox((prev) =>
        Math.abs(prev.w - r.width) < 0.5 && Math.abs(prev.h - r.height) < 0.5
          ? prev
          : { w: r.width, h: r.height },
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!zoomTarget) {
      setZooming(null);
      return;
    }
    setZooming(zoomTarget);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      zoomedRef.current(zoomTarget);
      return;
    }
    const timer = window.setTimeout(() => zoomedRef.current(zoomTarget), 380);
    return () => window.clearTimeout(timer);
  }, [zoomTarget]);

  const cfg = getRoleConfig(role);
  const byId = new Map<string, FleetSite>();
  for (const s of sites ?? []) byId.set(s.id, s);

  const hasData = (sites?.length ?? 0) > 0;
  const measured = box.w > 0 && box.h > 0;
  const scale = measured ? Math.min(box.w / 1000, box.h / 820) : 1;
  const offX = measured ? (box.w - 1000 * scale) / 2 : 0;
  const offY = measured ? (box.h - 820 * scale) / 2 : 0;

  const worldStyle: CSSProperties = {};
  const zoomGeo = zooming ? MAP_SITES.find((m) => m.id === zooming) : undefined;
  if (zoomGeo && measured) {
    const ox = ((offX + zoomGeo.x * scale) / box.w) * 100;
    const oy = ((offY + zoomGeo.y * scale) / box.h) * 100;
    worldStyle.transform = `scale(${ZOOM_SCALE})`;
    worldStyle.transformOrigin = `${ox.toFixed(2)}% ${oy.toFixed(2)}%`;
  }

  const zoomingLabel = zooming ? (byId.get(zooming)?.label ?? zooming) : null;

  const onKeyDownActivate =
    (id: string) =>
    (e: ReactKeyboardEvent<SVGElement>): void => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onRequestZoom(id);
      }
    };

  return (
    <div className="fleet-map">
      <div className="fleet-map-world" ref={worldRef} style={worldStyle}>
        <svg
          className="fleet-svg"
          viewBox={ZAMBIA_VIEWBOX}
          preserveAspectRatio="xMidYMid meet"
          role="group"
          aria-label="Zambia fleet map with six site markers"
        >
          <defs>
            <filter id="fleet-glow" x="-15%" y="-15%" width="130%" height="130%">
              <feGaussianBlur in="SourceAlpha" stdDeviation="10" result="blur" />
              <feFlood floodColor="var(--map-glow)" floodOpacity="0.35" />
              <feComposite in2="blur" operator="in" />
              <feMerge>
                <feMergeNode />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            <clipPath id="fleet-clip-zambia">
              <path d={ZAMBIA_PATH} />
            </clipPath>

            <pattern id="fleet-hexgrid" width="17.32" height="30" patternUnits="userSpaceOnUse">
              <g fill="none" stroke="var(--line)" strokeWidth="1">
                <path d="M8.66 5 L17.32 10 L17.32 20 L8.66 25 L0 20 L0 10 Z" />
                <path d="M0 -10 L8.66 -5 L8.66 5 L0 10 L-8.66 5 L-8.66 -5 Z" />
                <path d="M17.32 -10 L25.98 -5 L25.98 5 L17.32 10 L8.66 5 L8.66 -5 Z" />
                <path d="M0 20 L8.66 25 L8.66 35 L0 40 L-8.66 35 L-8.66 25 Z" />
                <path d="M17.32 20 L25.98 25 L25.98 35 L17.32 40 L8.66 35 L8.66 25 Z" />
              </g>
            </pattern>
          </defs>

          {/* country body */}
          <path className="fleet-country" d={ZAMBIA_PATH} filter="url(#fleet-glow)" />

          {/* subtle clipped interior texture */}
          <g clipPath="url(#fleet-clip-zambia)">
            <rect
              x="0"
              y="0"
              width="1000"
              height="820"
              fill="url(#fleet-hexgrid)"
              opacity="0.22"
            />
          </g>

          {/* Lusaka–Ndola corridor */}
          <g opacity="0.2">
            <path
              d="M566 548 C 524 508 524 452 570 410"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="1"
              strokeDasharray="6 5"
            />
          </g>

          {CITIES.map((c) => (
            <g key={c.name} className="fleet-city">
              <circle cx={c.x} cy={c.y} r="1.5" fill="var(--muted-2)" opacity="0.6" />
              <text className="fleet-svg-city" x={c.tx} y={c.ty} textAnchor={c.anchor}>
                {c.name}
              </text>
            </g>
          ))}

          {/* leader lines to the HTML label cards */}
          {hasData
            ? MAP_SITES.map((m) => {
                const off = LABEL_OFFSETS[m.id];
                if (!off || !byId.has(m.id)) return null;
                return (
                  <line
                    key={`l${m.id}`}
                    className="fleet-leader"
                    x1={m.x}
                    y1={m.y}
                    x2={m.x + off.dx}
                    y2={m.y + off.dy * spreadFor(scale)}
                  />
                );
              })
            : null}

          {/* site markers */}
          {MAP_SITES.map((m) => {
            const data = byId.get(m.id);
            const color = data ? STATUS_COLOR[data.status] : "var(--line-4)";
            const isCritical = data?.status === "critical";
            const isSelected = zooming === m.id || selectedId === m.id;
            if (!data) {
              return (
                <g
                  key={m.id}
                  className="fleet-dot is-placeholder"
                  transform={`translate(${m.x} ${m.y})`}
                  aria-hidden="true"
                >
                  <circle r="6" fill="none" stroke="var(--line-4)" strokeWidth="1" />
                  <circle r="2.5" fill="var(--line-4)" />
                </g>
              );
            }
            return (
              <g
                key={m.id}
                className={`fleet-dot${isCritical ? " is-critical" : ""}`}
                transform={`translate(${m.x} ${m.y})`}
                tabIndex={0}
                role="button"
                aria-label={`${data.label}, ${fmtInt(Math.round(data.actual_kw))} kilowatts, ${siteStatusTerm(
                  data.status,
                ).name}, readiness R${data.readiness_code} ${readinessName(data.readiness_code)}`}
                onClick={() => onRequestZoom(m.id)}
                onKeyDown={onKeyDownActivate(m.id)}
              >
                <circle r="14" fill="transparent" />
                <circle className="fleet-dot-ring" r="7" stroke={color} />
                {isCritical ? (
                  <circle className="fleet-dot-pulse" r="7" stroke={color} />
                ) : null}
                {isSelected ? (
                  <circle className="fleet-dot-sel" r="9" stroke="var(--role-accent)" />
                ) : null}
                <circle className="fleet-dot-core" r="3" fill={color} />
              </g>
            );
          })}
        </svg>

        {/* Compact HTML label cards — Site Name + Readiness + Load */}
        {hasData && measured
          ? MAP_SITES.map((m) => {
              const data = byId.get(m.id);
              const off = LABEL_OFFSETS[m.id];
              if (!data || !off) return null;
              const color = STATUS_COLOR[data.status];
              const ax = offX + (m.x + off.dx) * scale;
              const ay = offY + (m.y + off.dy * spreadFor(scale)) * scale;
              const isSelected = zooming === m.id || selectedId === m.id;
              const isHighReadiness = data.readiness_code <= 2;
              return (
                <button
                  key={`c${m.id}`}
                  type="button"
                  className={`fleet-site-card side-${off.side}${isSelected ? " is-selected" : ""}`}
                  style={{ left: ax, top: ay, borderLeftColor: color }}
                  onClick={() => onRequestZoom(m.id)}
                  aria-label={`${data.label}, ${fmtInt(Math.round(data.actual_kw))} kilowatts, ${siteStatusTerm(
                    data.status,
                  ).name}. Open site.`}
                >
                  <span className="fsc-top">
                    <span className="fsc-name">{data.label}</span>
                    <span
                      className={`fsc-badge${isHighReadiness ? " is-high" : ""}`}
                      title={readinessName(data.readiness_code)}
                    >
                      R{data.readiness_code}
                    </span>
                  </span>
                  <span className="fsc-bottom">
                    <span className="fsc-load">
                      {fmtInt(Math.round(data.actual_kw))}
                      <span className="fsc-unit"> kW</span>
                    </span>
                    <span
                      className={`fsc-delta${data.headroom_kw < 0 ? " is-neg" : ""}`}
                    >
                      {data.headroom_kw < 0 ? "" : "+"}
                      {fmtInt(Math.round(data.headroom_kw))}
                    </span>
                  </span>
                </button>
              );
            })
          : null}
      </div>

      {/* Clean corner labels */}
      <div className="fleet-map-hud-top">
        <span className="fleet-map-hud-title">Zambia Fleet</span>
        <span className="fleet-map-hud-sub">Select a site to inspect its {horizon}h forecast</span>
      </div>

      <div className="fleet-map-hud-bottom" aria-label="Status legend">
        <span className="fleet-hud-item">
          <i className="fs-dot is-red" /> {SITE_STATUS_TERMS.critical.name}
        </span>
        <span className="fleet-hud-item">
          <i className="fs-dot is-amber" /> {SITE_STATUS_TERMS.warning.name}
        </span>
        <span className="fleet-hud-item">
          <i className="fs-dot is-lime" /> {SITE_STATUS_TERMS.nominal.name}
        </span>
      </div>

      {loading && !hasData ? <p className="fleet-sync-chip">Loading fleet…</p> : null}

      {error && !hasData ? (
        <div className="fleet-error" role="alert">
          <p className="fleet-error-code">Fleet data unavailable</p>
          <p className="fleet-error-msg">{error}</p>
          <button type="button" className="btn btn-lime" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : null}

      <div
        className={`fleet-zoom-veil${zooming ? " is-on" : ""}`}
        aria-hidden={zooming ? undefined : "true"}
      >
        {zoomingLabel ? (
          <span className="fleet-zoom-label" style={{ "--acc": cfg.accent } as CSSProperties}>
            Opening {zoomingLabel}…
          </span>
        ) : null}
      </div>
    </div>
  );
}
