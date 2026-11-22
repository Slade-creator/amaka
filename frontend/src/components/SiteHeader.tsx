import { Download, FileText } from "lucide-react";
import type { Site } from "../types";
import { useState } from "react";
import { downloadReport, errMessage } from "../api";
import { fmtInt } from "../lib/format";

export type ConsoleTab = "monitor" | "drivers" | "midterm" | "specs";

type Props = {
  site: Site;
  /** first/last timestamp of the visible window (for export range) */
  from?: string;
  to?: string;
  hasRows: boolean;
  /** v2 forecast horizon (hours) — drives exports. */
  horizon: number;
  activeTab: ConsoleTab;
  onTabChange: (tab: ConsoleTab) => void;
  showDriversTab: boolean;
  alertCount: number;
};

/**
 * Clean site identity bar + focused workspace tabs + export actions.
 */
export default function SiteHeader({
  site,
  from,
  to,
  hasRows,
  horizon,
  activeTab,
  onTabChange,
  showDriversTab,
  alertCount,
}: Props) {
  const canExport = hasRows && Boolean(from && to);

  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);

  const exportAs = (kind: "csv" | "pdf") => {
    if (!canExport || !from || !to || exporting) return;
    setExporting(kind);
    downloadReport(site.id, kind, from, to, horizon)
      .catch((e) => window.alert(errMessage(e)))
      .finally(() => setExporting(null));
  };

  return (
    <section
      id="overview"
      className="flex flex-wrap items-center justify-between gap-4 pb-3 border-b border-[color:var(--border)]"
    >
      <div className="min-w-0">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.02em] text-fg">
            {site.label}
          </h1>
          <span className="text-[12px] text-dim">
            {site.location} · {site.type} · Threshold{" "}
            <span className="num text-fg">{fmtInt(site.load?.threshold_kw)} kW</span>
          </span>
        </div>
      </div>

      <div className="console-toolbar flex flex-wrap items-center gap-2.5">
        <div className="console-tabs" role="tablist" aria-label="Console view">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "monitor"}
            className={`console-tab${activeTab === "monitor" ? " is-active" : ""}`}
            onClick={() => onTabChange("monitor")}
          >
            Monitor
            {alertCount > 0 ? (
              <span className="console-tab-badge">{alertCount}</span>
            ) : null}
          </button>

          {showDriversTab ? (
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "drivers"}
              className={`console-tab${activeTab === "drivers" ? " is-active" : ""}`}
              onClick={() => onTabChange("drivers")}
            >
              Forecast Drivers
            </button>
          ) : null}

          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "midterm"}
            className={`console-tab${activeTab === "midterm" ? " is-active" : ""}`}
            onClick={() => onTabChange("midterm")}
          >
            Strategic (7D–90D)
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "specs"}
            className={`console-tab${activeTab === "specs" ? " is-active" : ""}`}
            onClick={() => onTabChange("specs")}
          >
            Model & Specs
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="btn btn-compact"
            onClick={() => exportAs("csv")}
            aria-disabled={!canExport}
            title={canExport ? "Download visible range as CSV" : "Range unavailable"}
          >
            <Download size={12} aria-hidden="true" />
            CSV
          </button>
          <button
            type="button"
            className="btn btn-compact"
            onClick={() => exportAs("pdf")}
            aria-disabled={!canExport}
            title={canExport ? "Download visible range as PDF report" : "Range unavailable"}
          >
            <FileText size={12} aria-hidden="true" />
            PDF
          </button>
        </div>
      </div>
    </section>
  );
}
