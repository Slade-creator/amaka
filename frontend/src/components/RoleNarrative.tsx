import type { CSSProperties } from "react";
import type { ReplayRow, Site } from "../types";
import { getRoleConfig, type Role } from "../fleet/roles";
import { fmtInt, fmtPct } from "../lib/format";

type Props = {
  role: Role;
  site: Site;
  cursorRow?: ReplayRow;
  peak24: number | null;
  alertCount: number;
};

/**
 * The 5-second message. One sentence per role, directly under the site header.
 * This is the "no narrative" fix from the dashboard review: the first thing the
 * eye reads is the current state and the next action, not another metric.
 */
export default function RoleNarrative({ role, site, peak24, alertCount }: Props) {
  const cfg = getRoleConfig(role);
  const threshold = site.load?.threshold_kw ?? 0;
  const m = site.metrics;
  const peak = typeof peak24 === "number" ? peak24 : null;
  const headroom = peak !== null ? threshold - peak : null;
  const over = headroom !== null && headroom < 0;

  let purpose = "STRATEGIC VIEW";
  let message: string;

  if (role === "commander") {
    purpose = "STRATEGIC VIEW";
    message =
      peak !== null && headroom !== null
        ? `${alertCount} active alert${alertCount === 1 ? "" : "s"} · next 24 h peak ${fmtInt(peak)} kW · ${
            over ? `${fmtInt(Math.abs(headroom))} kW over threshold` : `${fmtInt(headroom)} kW headroom`
          }`
        : "Waiting for forecast data for this site.";
  } else if (role === "operator") {
    purpose = "OPERATIONS VIEW";
    message =
      peak !== null && headroom !== null
        ? `${over ? "Pre-start the generator" : "Hold generators"} · next 24 h peak ${fmtInt(peak)} kW · ${
            over ? `${fmtInt(Math.abs(headroom))} kW over threshold` : `${fmtInt(headroom)} kW headroom`
          }`
        : "Waiting for forecast data for this site.";
  } else {
    purpose = "ANALYSIS VIEW";
    message = `Forecast error (MAPE) ${fmtPct(m?.hyb_mape, 2)} · RMSE ${fmtInt(
      m?.hyb_rmse,
      1,
    )} kW · ${fmtInt(site.alerts?.variance_hours)} hours outside the forecast range in the test period`;
  }

  return (
    <div
      className="role-narrative"
      style={{ "--role": cfg.accent, "--role-dim": cfg.accentDim } as CSSProperties}
      role="status"
      aria-live="polite"
    >
      <span className="rn-role">{purpose}</span>
      <span className="rn-sep" aria-hidden="true" />
      <span className="rn-message">{message}</span>
    </div>
  );
}
