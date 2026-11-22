import type { Alert, SiteAlertCounts } from "../types";
import { fmtStampIso } from "../lib/format";
import { ALERT_KIND_TERMS, ALERT_SEVERITY_TERMS } from "../lib/vocabulary";
import { Panel, PanelHead } from "./ui";

type Props = {
  alerts: Alert[];
  periodCounts?: SiteAlertCounts;
};

const SEV_TEXT: Record<Alert["severity"], string> = {
  critical: "var(--crit)",
  warning: "var(--warn)",
  info: "var(--accent)",
};

/**
 * Clean 24h Alert Feed panel.
 */
export default function AlertFeed({ alerts, periodCounts }: Props) {
  const critical = alerts.filter((a) => a.severity === "critical").length;
  const warning = alerts.filter((a) => a.severity === "warning").length;

  return (
    <Panel>
      <PanelHead
        title="Active Alerts"
        sub="Last 24h"
        right={
          <span className="num text-[11px]">
            {critical > 0 ? <span style={{ color: "var(--crit)" }}>{critical} crit</span> : null}
            {critical > 0 && warning > 0 ? <span className="text-dim"> · </span> : null}
            {warning > 0 ? <span style={{ color: "var(--warn)" }}>{warning} warn</span> : null}
            {alerts.length === 0 ? <span className="text-dim">0 active</span> : null}
          </span>
        }
      />

      <div className="px-3.5 py-3">
        {alerts.length === 0 ? (
          <div className="rounded border border-[color:var(--border)] bg-[rgb(var(--white-rgb)/0.015)] px-3 py-5 text-center">
            <div className="text-[12px] font-medium text-lime">All clear</div>
            <div className="mt-1 text-[11px] text-dim">
              No peak, readiness, or range alerts in this 24h window.
            </div>
          </div>
        ) : (
          <div className="max-h-[260px] overflow-y-auto pr-0.5">
            {alerts.map((a) => (
              <article key={a.id} className={`alert-item sev-${a.severity}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span
                    className="num text-[10px] font-medium"
                    style={{ color: SEV_TEXT[a.severity] }}
                  >
                    {ALERT_SEVERITY_TERMS[a.severity].name} ·{" "}
                    {(ALERT_KIND_TERMS[a.kind] ?? ALERT_KIND_TERMS.model).name}
                  </span>
                  <span className="num text-[10px] text-dim">{fmtStampIso(a.timestamp)}</span>
                </div>
                <h3 className="mt-0.5 text-[12px] font-medium leading-snug text-fg">
                  {a.title || "Alert"}
                </h3>
                <p className="num mt-0.5 text-[10.5px] leading-relaxed text-dim">{a.detail}</p>
              </article>
            ))}
          </div>
        )}

        {periodCounts ? (
          <div className="mt-3 border-t border-[color:var(--border)] pt-2 flex items-center justify-between text-[10.5px] text-dim">
            <span>2025 H2 totals</span>
            <span className="num">
              {periodCounts.peak_hours}p · {periodCounts.surge_hours}r · {periodCounts.variance_hours}v
            </span>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
