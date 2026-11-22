import { useMemo, useState } from "react";
import { BellOff, ChevronRight } from "lucide-react";
import { fmtStamp } from "../lib/format";
import type { ScreenProps, SiteAlert } from "./MobileApp";
import { HorizonChip } from "./parts";
import { EmptyState, ErrorState, ScrollView, Segmented, Skeleton } from "./ui";

type Filter = "all" | SiteAlert["severity"];

const KIND_LABEL: Record<SiteAlert["kind"], string> = {
  peak: "Peak threshold",
  surge: "Readiness",
  variance: "Forecast range",
  readiness: "Readiness",
  model: "Model",
};

/**
 * Fleet-wide alert inbox: every site's alerts for the 24 hours up to the
 * selected hour, evaluated by the server, most severe first.
 */
export default function AlertsScreen({ alerts, horizon, at, onOpenSite, onRefresh, onHorizonPress }: ScreenProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const list = alerts.data ?? [];
  const counts = useMemo(
    () => ({
      critical: list.filter((a) => a.severity === "critical").length,
      warning: list.filter((a) => a.severity === "warning").length,
      info: list.filter((a) => a.severity === "info").length,
    }),
    [list],
  );
  const shown = filter === "all" ? list : list.filter((a) => a.severity === filter);

  return (
    <div className="m-screen">
      <header className="m-hero">
        <div className="m-hero-row">
          <div>
            <p className="m-eyebrow">LAST 24 HOURS</p>
            <h1 className="m-hero-title">Alerts</h1>
          </div>
          <HorizonChip horizon={horizon} onPress={onHorizonPress} />
        </div>
        <p className="m-hero-sub num">Up to {at ? fmtStamp(at) : "—"}</p>
        <div className="m-hero-tools">
          <Segmented<Filter>
            label="Severity"
            stretch
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All", badge: list.length },
              { value: "critical", label: "Critical", badge: counts.critical },
              { value: "warning", label: "Warning", badge: counts.warning },
              { value: "info", label: "Info", badge: counts.info },
            ]}
          />
        </div>
      </header>

      <ScrollView onRefresh={onRefresh}>
        {alerts.error && !alerts.data ? (
          <ErrorState message={alerts.error} onRetry={() => void onRefresh()} />
        ) : !alerts.data ? (
          <div className="m-stack">
            <Skeleton h={96} />
            <Skeleton h={96} />
            <Skeleton h={96} />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon={<BellOff size={28} aria-hidden="true" />}
            title={filter === "all" ? "No alerts" : `No ${filter} alerts`}
            body="Every site is inside its peak threshold and forecast range for this window."
          />
        ) : (
          <ul className="m-alerts">
            {shown.map((a) => (
              <li key={`${a.siteId}-${a.id}`}>
                <button type="button" className={`m-alert is-${a.severity}`} onClick={() => onOpenSite(a.siteId)}>
                  <span className="m-alert-top">
                    <span className="m-alert-sev">{a.severity}</span>
                    <span className="m-alert-kind">{KIND_LABEL[a.kind]}</span>
                    <span className="m-alert-time num">{fmtStamp(a.timestamp).slice(0, 6)} {fmtStamp(a.timestamp).slice(-5)}</span>
                  </span>
                  <span className="m-alert-title">{a.title}</span>
                  <span className="m-alert-site">{a.siteLabel}</span>
                  <span className="m-alert-detail">{a.detail}</span>
                  <ChevronRight size={18} className="m-alert-chev" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScrollView>
    </div>
  );
}
