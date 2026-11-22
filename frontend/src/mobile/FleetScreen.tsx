import { lazy, Suspense, useMemo } from "react";
import { ChevronRight, Fuel, Gauge, ShieldAlert } from "lucide-react";
import type { FleetSite, FleetStatus } from "../fleet/fleetApi";
import { MAP_SITES, ZAMBIA_PATH, ZAMBIA_VIEWBOX } from "../fleet/zambia";
import { getRoleConfig } from "../fleet/roles";
import { fmtInt, fmtPct, fmtStamp, fmtZmw } from "../lib/format";
import type { ScreenProps } from "./MobileApp";
import { HorizonChip, SiteRow } from "./parts";
import { Card, ErrorState, ScrollView, Skeleton, Stat } from "./ui";

const SatMapCard = lazy(() => import("./map/SatMapCard"));

const STATUS_RANK: Record<FleetStatus, number> = { critical: 0, warning: 1, nominal: 2 };

export function sortByRisk(sites: FleetSite[]): FleetSite[] {
  return [...sites].sort(
    (a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || a.headroom_kw - b.headroom_kw,
  );
}

/** Generator size to pre-start for a shortfall (same rule as the desktop dispatch card). */
export function generatorFor(shortfallKw: number): number {
  return Math.max(500, Math.ceil(shortfallKw / 500) * 500);
}

export default function FleetScreen(props: ScreenProps) {
  const { role, fleet, horizon, at, onOpenSite, onOpenMap, onRefresh, onHorizonPress, overview } = props;
  const sites = useMemo(() => sortByRisk(fleet.data?.sites ?? []), [fleet.data]);
  const totals = fleet.data?.totals;
  const cfg = getRoleConfig(role);

  return (
    <div className="m-screen">
      <header className="m-hero">
        <div className="m-hero-row">
          <div>
            <p className="m-eyebrow" style={{ color: cfg.accent }}>
              {cfg.purpose}
            </p>
            <h1 className="m-hero-title">Fleet</h1>
          </div>
          <HorizonChip horizon={horizon} onPress={onHorizonPress} />
        </div>
        <p className="m-hero-sub num">Selected hour {at ? fmtStamp(at) : "—"} · replay</p>
      </header>

      <ScrollView onRefresh={onRefresh}>
        {fleet.error && !fleet.data ? (
          <ErrorState message={fleet.error} onRetry={() => void onRefresh()} />
        ) : !fleet.data ? (
          <div className="m-stack">
            <Skeleton h={180} />
            <Skeleton h={120} />
            <Skeleton h={220} />
          </div>
        ) : (
          <div className="m-stack">
            <div className="m-kpis">
              <Stat label="Fleet load" value={((totals?.load_kw ?? 0) / 1000).toFixed(1)} unit="MW" />
              <Stat
                label="Sites at risk"
                value={totals?.sites_at_risk ?? 0}
                unit={`/ ${sites.length}`}
                tone={(totals?.sites_at_risk ?? 0) > 0 ? "critical" : "good"}
              />
              <Stat
                label="High readiness"
                value={totals?.surge_sites ?? 0}
                unit="sites"
                tone={(totals?.surge_sites ?? 0) > 0 ? "warning" : undefined}
              />
            </div>

            {role === "commander" ? <CommanderCard sites={sites} saving={totals?.saving_zmw ?? 0} /> : null}
            {role === "operator" ? <DispatchList sites={sites} onOpenSite={onOpenSite} /> : null}
            {role === "analyst" ? (
              <AccuracyCard sites={sites} horizon={horizon} onOpenSite={onOpenSite} model={overview.model.name} />
            ) : null}

            <Card title="Satellite map" right={<Legend />} flush>
              <Suspense fallback={<MiniMap sites={sites} onOpenSite={onOpenSite} />}>
                <SatMapCard
                  sites={sites}
                  onOpenMap={onOpenMap}
                  fallback={<MiniMap sites={sites} onOpenSite={onOpenSite} />}
                />
              </Suspense>
            </Card>

            <Card title={`Sites (${sites.length})`} flush>
              <ul className="m-list">
                {sites.map((s) => (
                  <SiteRow key={s.id} site={s} onPress={() => onOpenSite(s.id)} />
                ))}
              </ul>
            </Card>
          </div>
        )}
      </ScrollView>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* role cards                                                          */
/* ------------------------------------------------------------------ */

function CommanderCard({ sites, saving }: { sites: FleetSite[]; saving: number }) {
  const over = sites.filter((s) => s.headroom_kw < 0);
  const shortfall = over.reduce((sum, s) => sum + Math.abs(s.headroom_kw), 0);
  const headline =
    over.length === 0
      ? "All sites are within their peak thresholds."
      : `${over.length} of ${sites.length} sites are over their peak threshold.`;
  return (
    <Card className="m-role-card" title={<><ShieldAlert size={16} aria-hidden="true" /> Fleet risk</>}>
      <p className={`m-headline${over.length ? " is-critical" : ""}`}>{headline}</p>
      <div className="m-kpis is-two">
        <Stat
          label="Peak shortfall"
          value={fmtInt(shortfall)}
          unit="kW"
          tone={shortfall > 0 ? "critical" : "good"}
        />
        <Stat label="Monthly saving" value={fmtZmw(saving)} tone="good" note="forecast-led dispatch" />
      </div>
    </Card>
  );
}

function DispatchList({ sites, onOpenSite }: { sites: FleetSite[]; onOpenSite: (id: string) => void }) {
  const actions = sites.filter((s) => s.headroom_kw < 0);
  return (
    <Card className="m-role-card" title={<><Fuel size={16} aria-hidden="true" /> Generator dispatch</>}>
      {actions.length === 0 ? (
        <p className="m-headline is-good">Hold generators — every site is within its peak threshold.</p>
      ) : (
        <ul className="m-actions">
          {actions.map((s) => (
            <li key={s.id}>
              <button type="button" className="m-action" onClick={() => onOpenSite(s.id)}>
                <span className="m-action-main">
                  <strong>Pre-start {fmtInt(generatorFor(Math.abs(s.headroom_kw)))} kW generator</strong>
                  <span>
                    {s.label} · {fmtInt(Math.abs(s.headroom_kw))} kW over threshold
                  </span>
                </span>
                <ChevronRight size={18} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AccuracyCard({
  sites,
  horizon,
  model,
  onOpenSite,
}: {
  sites: FleetSite[];
  horizon: number;
  model: string;
  onOpenSite: (id: string) => void;
}) {
  const withMape = sites.filter((s) => s.mape > 0);
  const avg = withMape.reduce((sum, s) => sum + s.mape, 0) / Math.max(1, withMape.length);
  const sorted = [...withMape].sort((a, b) => a.mape - b.mape);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];
  return (
    <Card className="m-role-card" title={<><Gauge size={16} aria-hidden="true" /> Forecast accuracy · H{horizon}</>}>
      <div className="m-kpis is-two">
        <Stat label="Fleet MAPE" value={fmtPct(avg)} note="mean absolute % error" tone={avg < 5 ? "good" : "warning"} />
        <Stat label="Sites scored" value={withMape.length} note="test period Jul–Dec 2025" />
      </div>
      {best && worst ? (
        <div className="m-split">
          <button type="button" className="m-split-item" onClick={() => onOpenSite(best.id)}>
            <span>Most accurate</span>
            <strong>{best.label}</strong>
            <span className="num is-good">{fmtPct(best.mape)}</span>
          </button>
          <button type="button" className="m-split-item" onClick={() => onOpenSite(worst.id)}>
            <span>Least accurate</span>
            <strong>{worst.label}</strong>
            <span className="num is-warning">{fmtPct(worst.mape)}</span>
          </button>
        </div>
      ) : null}
      <p className="m-fine">{model}</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* map                                                                 */
/* ------------------------------------------------------------------ */

function Legend() {
  return (
    <span className="m-legend">
      <span>
        <i className="m-dot is-critical" /> Critical
      </span>
      <span>
        <i className="m-dot is-warning" /> Warning
      </span>
      <span>
        <i className="m-dot is-nominal" /> Nominal
      </span>
    </span>
  );
}

/** Spread co-located sites (same base / same city) around their centre. */
function layout(sites: FleetSite[]) {
  const pts = sites
    .map((s) => {
      const p = MAP_SITES.find((m) => m.id === s.id);
      return p ? { site: s, x: p.x, y: p.y } : null;
    })
    .filter((p): p is { site: FleetSite; x: number; y: number } => p !== null);
  const groups: Array<typeof pts> = [];
  for (const p of pts) {
    const g = groups.find((grp) => Math.hypot(grp[0].x - p.x, grp[0].y - p.y) < 40);
    if (g) g.push(p);
    else groups.push([p]);
  }
  return groups.flatMap((g) => {
    if (g.length === 1) return g;
    const cx = g.reduce((s, p) => s + p.x, 0) / g.length;
    const cy = g.reduce((s, p) => s + p.y, 0) / g.length;
    return g.map((p, i) => {
      const a = (i / g.length) * Math.PI * 2 - Math.PI / 2;
      return { ...p, x: cx + Math.cos(a) * 30, y: cy + Math.sin(a) * 30 };
    });
  });
}

function MiniMap({ sites, onOpenSite }: { sites: FleetSite[]; onOpenSite: (id: string) => void }) {
  const pts = useMemo(() => layout(sites), [sites]);
  return (
    <div className="m-map">
      <svg viewBox={ZAMBIA_VIEWBOX} role="img" aria-label="Map of Zambia with site status">
        <path d={ZAMBIA_PATH} className="m-map-country" />
        <text x="600" y="360" className="m-map-city">
          NDOLA
        </text>
        <text x="610" y="640" className="m-map-city">
          LUSAKA
        </text>
        {pts.map(({ site, x, y }) => (
          <g
            key={site.id}
            className={`m-map-site is-${site.status}`}
            role="button"
            tabIndex={0}
            aria-label={`${site.label}: ${site.status}`}
            onClick={() => onOpenSite(site.id)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpenSite(site.id)}
          >
            <circle cx={x} cy={y} r="34" className="m-map-hit" />
            {site.status === "critical" ? <circle cx={x} cy={y} r="14" className="m-map-pulse" /> : null}
            <circle cx={x} cy={y} r="13" className="m-map-dot" />
          </g>
        ))}
      </svg>
    </div>
  );
}
