import { useMemo, useState } from "react";
import { BellOff, ChevronLeft, ChevronRight, FileSpreadsheet, FileText, Share2 } from "lucide-react";
import ChartNarrative from "../components/ChartNarrative";
import ExplainPanel from "../components/ExplainPanel";
import MidtermPanel from "../components/MidtermPanel";
import ModelPerf from "../components/ModelPerf";
import FacilityFacts from "../components/FacilityFacts";
import { downloadReport, errMessage } from "../api";
import { deriveAlerts } from "../lib/alerts";
import { fmtInt, fmtPct, fmtStamp, fmtZmw, normTs } from "../lib/format";
import { readinessName } from "../lib/vocabulary";
import type { FleetSite } from "../fleet/fleetApi";
import type { Role } from "../fleet/roles";
import type { Overview, ReplayRow, Site } from "../types";
import MobileTrace from "./MobileTrace";
import { generatorFor } from "./FleetScreen";
import { HorizonChip } from "./parts";
import { useExplain, useSiteReplay } from "./useSiteReplay";
import { Card, ErrorState, ScrollView, Segmented, Sheet, Skeleton, Spinner, Stat, StatusPill, TopBar, tap } from "./ui";

type Section = "monitor" | "drivers" | "outlook" | "details";

type Props = {
  site: Site;
  role: Role;
  overview: Overview;
  fleetSite?: FleetSite;
  horizon: number;
  at: string;
  onBack: () => void;
  onHorizonPress: () => void;
};

export default function SiteScreen({ site, role, overview, fleetSite, horizon, at, onBack, onHorizonPress }: Props) {
  const [section, setSection] = useState<Section>("monitor");
  const [shareOpen, setShareOpen] = useState(false);
  const replay = useSiteReplay(site.id, horizon, at);
  const { rows, cursor, cursorRow, bounds, peak24 } = replay;
  const cursorTs = cursorRow ? normTs(cursorRow.timestamp) : "";
  const explain = useExplain(site.id, horizon, cursorTs, section === "drivers");
  const threshold = site.load?.threshold_kw ?? 0;
  const from = rows[bounds.ws]?.timestamp;
  const to = rows[Math.max(0, bounds.we - 1)]?.timestamp;

  const alerts = useMemo(
    () => (rows.length ? deriveAlerts(rows, cursor, threshold, site.metrics?.band_kw ?? 0) : []),
    [rows, cursor, threshold, site.metrics?.band_kw],
  );

  const sections: Array<{ value: Section; label: string; badge?: number }> = [
    { value: "monitor", label: "Monitor", badge: alerts.filter((a) => a.severity !== "info").length },
    ...(role !== "commander" ? [{ value: "drivers" as const, label: "Drivers" }] : []),
    { value: "outlook", label: "Outlook" },
    { value: "details", label: "Details" },
  ];

  return (
    <div className="m-push" role="region" aria-label={site.label}>
      <TopBar
        title={site.label}
        subtitle={`${site.location} · ${site.type}`}
        onBack={onBack}
        right={
          <button
            type="button"
            className="m-icon-btn"
            onClick={() => setShareOpen(true)}
            aria-label="Export report"
            disabled={!rows.length}
          >
            <Share2 size={20} aria-hidden="true" />
          </button>
        }
      />

      <div className="m-site-strip">
        {fleetSite ? <StatusPill status={fleetSite.status} /> : null}
        <span className="m-site-strip-t">
          Threshold <b className="num">{fmtInt(threshold)} kW</b>
        </span>
        <HorizonChip horizon={horizon} onPress={onHorizonPress} />
      </div>

      <div className="m-site-tabs">
        <Segmented<Section> label="Site view" stretch value={section} onChange={setSection} options={sections} />
      </div>

      <ScrollView className="m-site-scroll" resetKey={section}>
        {replay.error && !rows.length ? (
          <ErrorState message={replay.error} onRetry={replay.retry} />
        ) : replay.loading && !rows.length ? (
          <div className="m-stack">
            <Skeleton h={150} />
            <Skeleton h={340} />
          </div>
        ) : (
          <div className="m-stack">
            {section === "monitor" ? (
              <>
                <div className="m-kpis is-grid">
                  <Stat
                    label="Actual load"
                    value={fmtInt(cursorRow?.actual_kw)}
                    unit="kW"
                    note={
                      cursorRow
                        ? `${fmtInt(Math.abs(cursorRow.actual_kw - cursorRow.hybrid_kw))} kW ${cursorRow.actual_kw >= cursorRow.hybrid_kw ? "above" : "below"} forecast`
                        : undefined
                    }
                  />
                  <Stat
                    label="Next 24h peak"
                    value={fmtInt(peak24)}
                    unit="kW"
                    tone={peak24 !== null && peak24 > threshold ? "critical" : "good"}
                    note={
                      peak24 !== null
                        ? peak24 > threshold
                          ? `${fmtInt(peak24 - threshold)} kW over threshold`
                          : `${fmtInt(threshold - peak24)} kW headroom`
                        : undefined
                    }
                  />
                  <Stat
                    label={`Forecast error · H${horizon}`}
                    value={fmtPct(site.metrics?.hyb_mape)}
                    note={`MAE ${fmtInt(site.metrics?.hyb_mae, 1)} kW`}
                  />
                  <Stat
                    label="Monthly saving"
                    value={fmtZmw(site.cost?.monthly_saving_zmw)}
                    tone="good"
                    note={`${fmtPct(site.cost?.saving_pct, 1)} of baseline`}
                  />
                </div>

                <Card title="Load trace" flush>
                  <MobileTrace
                    site={site}
                    rows={rows}
                    bounds={bounds}
                    cursor={cursor}
                    rangeHours={replay.rangeHours}
                    playing={replay.playing}
                    onRange={replay.changeRange}
                    onScrub={(i) => {
                      replay.pause();
                      replay.scrub(i);
                    }}
                    onStep={replay.step}
                    onTogglePlay={replay.togglePlay}
                    onReset={replay.resetToAnchor}
                  />
                </Card>

                {role === "operator" ? (
                  <DispatchCard peak={peak24} threshold={threshold} rows={rows} cursor={cursor} />
                ) : null}

                <Card title="Alerts · 24 h to selected hour" flush>
                  {alerts.length === 0 ? (
                    <div className="m-inline-empty">
                      <BellOff size={18} aria-hidden="true" /> No alerts in this window
                    </div>
                  ) : (
                    <ul className="m-mini-alerts">
                      {alerts.map((a) => (
                        <li key={a.id} className={`is-${a.severity}`}>
                          <span className="m-alert-sev">{a.severity}</span>
                          <strong>{a.title}</strong>
                          <span>{a.detail}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                <div className="m-embed">
                  <ChartNarrative
                    site={site}
                    role={role}
                    horizon={horizon}
                    at={cursorTs}
                    from={from}
                    to={to}
                    playing={replay.playing}
                    hasRows={rows.length > 0}
                  />
                </div>
              </>
            ) : null}

            {section === "drivers" ? (
              <>
                <Card>
                  <div className="m-stepper">
                    <button type="button" className="m-icon-btn is-boxed" onClick={() => replay.step(-1)} aria-label="Previous hour">
                      <ChevronLeft size={20} aria-hidden="true" />
                    </button>
                    <div className="m-stepper-mid">
                      <span className="m-stat-label">Selected hour</span>
                      <span className="num">{cursorRow ? fmtStamp(cursorRow.timestamp) : "—"}</span>
                    </div>
                    <button type="button" className="m-icon-btn is-boxed" onClick={() => replay.step(1)} aria-label="Next hour">
                      <ChevronRight size={20} aria-hidden="true" />
                    </button>
                  </div>
                  <input
                    className="m-slider"
                    type="range"
                    min={bounds.ws}
                    max={Math.max(bounds.ws, bounds.we - 1)}
                    value={Math.min(Math.max(cursor, bounds.ws), Math.max(bounds.ws, bounds.we - 1))}
                    onChange={(e) => replay.scrub(Number(e.target.value))}
                    aria-label="Selected hour"
                  />
                  <p className="m-fine">
                    Shows which inputs pushed the H{horizon} forecast up or down at this hour (SHAP contributions in
                    kW).
                  </p>
                </Card>
                <div className="m-embed">
                  <ExplainPanel
                    site={site}
                    stamp={cursorRow ? fmtStamp(cursorRow.timestamp) : "—"}
                    forecastKw={cursorRow?.hybrid_kw ?? null}
                    xgbKw={cursorRow?.xgb_kw ?? null}
                    horizon={horizon}
                    data={explain.data}
                    status={explain.status}
                    error={explain.error}
                  />
                </div>
              </>
            ) : null}

            {section === "outlook" ? (
              <div className="m-embed">
                <MidtermPanel site={site} />
              </div>
            ) : null}

            {section === "details" ? (
              <>
                <div className="m-embed">
                  <FacilityFacts site={site} />
                </div>
                <div className="m-embed">
                  <ModelPerf site={site} horizon={horizon} />
                </div>
                <Card title="Data and model">
                  <dl className="m-dl">
                    <dt>Model</dt>
                    <dd>{overview.model?.name}</dd>
                    <dt>Test period</dt>
                    <dd className="num">
                      {String(overview.test_period?.start).slice(0, 10)} → {String(overview.test_period?.end).slice(0, 10)}
                    </dd>
                    <dt>Readiness now</dt>
                    <dd>{cursorRow ? `R${cursorRow.readiness_code} ${readinessName(cursorRow.readiness_code)}` : "—"}</dd>
                    <dt>Data</dt>
                    <dd>Synthetic load driven by real Open-Meteo weather</dd>
                  </dl>
                </Card>
              </>
            ) : null}
          </div>
        )}
      </ScrollView>

      <ExportSheet
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        site={site}
        horizon={horizon}
        from={from}
        to={to}
      />
    </div>
  );
}

function DispatchCard({
  peak,
  threshold,
  rows,
  cursor,
}: {
  peak: number | null;
  threshold: number;
  rows: ReplayRow[];
  cursor: number;
}) {
  const window = rows.slice(cursor, Math.min(rows.length, cursor + 24));
  const peakRow = window.reduce<ReplayRow | undefined>(
    (best, r) => (!best || r.hybrid_kw > best.hybrid_kw ? r : best),
    undefined,
  );
  const over = peak !== null && peak > threshold;
  return (
    <Card className={`m-dispatch${over ? " is-action" : ""}`} title="Generator dispatch">
      <p className="m-dispatch-action">
        {over ? `Pre-start ${fmtInt(generatorFor(peak! - threshold))} kW generator` : "Hold generators"}
      </p>
      <div className="m-kpis is-three">
        <Stat label="24h peak" value={fmtInt(peak)} unit="kW" />
        <Stat label="Peak time" value={peakRow ? fmtStamp(peakRow.timestamp).slice(-5) : "—"} />
        <Stat
          label={over ? "Shortfall" : "Headroom"}
          value={peak !== null ? fmtInt(Math.abs(threshold - peak)) : "—"}
          unit="kW"
          tone={over ? "critical" : "good"}
        />
      </div>
    </Card>
  );
}

function ExportSheet({
  open,
  onClose,
  site,
  horizon,
  from,
  to,
}: {
  open: boolean;
  onClose: () => void;
  site: Site;
  horizon: number;
  from?: string;
  to?: string;
}) {
  const [busy, setBusy] = useState<"csv" | "pdf" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const run = (kind: "csv" | "pdf") => {
    if (!from || !to || busy) return;
    tap();
    setBusy(kind);
    setMsg(null);
    downloadReport(site.id, kind, from, to, horizon)
      .then((name) => setMsg({ ok: true, text: `Saved ${name}` }))
      .catch((e) => setMsg({ ok: false, text: errMessage(e) }))
      .finally(() => setBusy(null));
  };

  return (
    <Sheet open={open} title="Export report" onClose={onClose}>
      <p className="m-sheet-lede">
        {site.label} · H{horizon} · {from ? fmtStamp(from) : "—"} → {to ? fmtStamp(to) : "—"}
      </p>
      <div className="m-choice-list">
        <button type="button" className="m-choice" onClick={() => run("pdf")} disabled={!!busy}>
          <FileText size={22} aria-hidden="true" />
          <span className="m-choice-desc">
            <strong>PDF briefing</strong>
            <span>Chart, KPIs and alerts for the visible window</span>
          </span>
          {busy === "pdf" ? <Spinner /> : null}
        </button>
        <button type="button" className="m-choice" onClick={() => run("csv")} disabled={!!busy}>
          <FileSpreadsheet size={22} aria-hidden="true" />
          <span className="m-choice-desc">
            <strong>CSV data</strong>
            <span>Hourly actual load, forecast and 95% range</span>
          </span>
          {busy === "csv" ? <Spinner /> : null}
        </button>
      </div>
      {msg ? <p className={`m-sheet-msg${msg.ok ? " is-ok" : " is-error"}`}>{msg.text}</p> : null}
    </Sheet>
  );
}
