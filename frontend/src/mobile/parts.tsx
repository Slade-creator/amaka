/** Small AMAKA-specific pieces shared by the phone screens. */

import { ChevronDown, ChevronRight } from "lucide-react";
import type { FleetSite } from "../fleet/fleetApi";
import { fmtInt } from "../lib/format";
import { readinessName } from "../lib/vocabulary";
import { StatusDot } from "./ui";

export function HorizonChip({ horizon, onPress }: { horizon: number; onPress: () => void }) {
  return (
    <button type="button" className="m-hchip" onClick={onPress} aria-label={`Forecast horizon H${horizon}. Change`}>
      <span className="m-hchip-k">Horizon</span>
      <span className="m-hchip-v num">H{horizon}</span>
      <ChevronDown size={16} aria-hidden="true" />
    </button>
  );
}

export function SiteRow({ site, onPress }: { site: FleetSite; onPress: () => void }) {
  const over = site.headroom_kw < 0;
  return (
    <li>
      <button type="button" className={`m-row is-${site.status}`} onClick={onPress}>
        <StatusDot status={site.status} />
        <span className="m-row-main">
          <span className="m-row-title">{site.label}</span>
          <span className="m-row-sub">
            {site.location} · R{site.readiness_code} {readinessName(site.readiness_code)}
          </span>
        </span>
        <span className="m-row-figs">
          <span className="num m-row-load">
            {fmtInt(site.actual_kw)}
            <small> kW</small>
          </span>
          <span className={`num m-row-head${over ? " is-critical" : " is-good"}`}>
            {over ? "−" : "+"}
            {fmtInt(Math.abs(site.headroom_kw))} kW
          </span>
        </span>
        <ChevronRight size={18} className="m-row-chev" aria-hidden="true" />
      </button>
    </li>
  );
}
