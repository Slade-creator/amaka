import type { Site } from "../types";
import { fmtCoords, fmtInt } from "../lib/format";
import { FactRow, Panel, PanelHead } from "./ui";

/** Clean Site Profile & Telemetry Specs card. */
export default function FacilityFacts({ site }: { site: Site }) {
  return (
    <Panel>
      <PanelHead title="Site Profile & Parameters" sub={site.location} />
      <div className="px-4 py-2">
        <FactRow label="Facility type" value={site.type} />
        <FactRow label="Coordinates" value={fmtCoords(site.lat, site.lon)} />
        <FactRow label="Base load" value={`${fmtInt(site.base_load_kw)} kW`} />
        <FactRow label="Peak threshold" value={`${fmtInt(site.load?.threshold_kw)} kW`} accent />
        <FactRow label="Rooftop PV capacity" value={`${fmtInt(site.pv_kwp)} kWp`} />
        <FactRow label="Headcount" value={fmtInt(site.headcount)} />
        <FactRow label="Conditioned floor area" value={`${fmtInt(site.floor_area_m2)} m²`} />
        <FactRow label="Test-period average" value={`${fmtInt(site.load?.avg_kw, 0)} kW`} />
        <FactRow label="Test-period peak" value={`${fmtInt(site.load?.peak_kw, 0)} kW`} />
        <FactRow label="Evaluation hours (2025 H2)" value={fmtInt(site.rows)} />
      </div>
    </Panel>
  );
}
