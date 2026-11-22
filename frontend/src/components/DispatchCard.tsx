import type { ReplayRow, Site } from "../types";
import { fmtInt, fmtStamp } from "../lib/format";

type Props = {
  site: Site;
  rows: ReplayRow[];
  cursor: number;
  peak24: number | null;
};

/**
 * Operator dispatch guidance: one clear action, peak time, and headroom/shortfall.
 */
export default function DispatchCard({ site, rows, cursor, peak24 }: Props) {
  const threshold = site.load?.threshold_kw ?? 0;
  const window = rows.slice(cursor, Math.min(rows.length, cursor + 24));
  const peakRow = window.reduce<ReplayRow | undefined>(
    (best, row) => (!best || row.hybrid_kw > best.hybrid_kw ? row : best),
    undefined,
  );
  const peak = peak24 ?? peakRow?.hybrid_kw ?? null;
  const headroom = peak !== null ? threshold - peak : null;
  const over = headroom !== null && headroom < 0;
  const startKw =
    peak !== null && over ? Math.max(500, Math.ceil((peak - threshold) / 500) * 500) : 0;

  return (
    <section className="panel dispatch-card">
      <header className="dispatch-head">
        <span className="text-[12px] font-semibold text-fg">Generator Dispatch</span>
        <span className={`dispatch-tag ${over ? "is-action" : "is-hold"}`}>
          {over ? "Action Required" : "Standby"}
        </span>
      </header>

      <p className={`dispatch-action ${over ? "is-action" : "is-hold"}`}>
        {over ? `Pre-start ${startKw} kW Generator` : "Hold Generators"}
      </p>

      <div className="dispatch-rows">
        <div>
          <span className="label">24h Peak</span>
          <span className="num">
            {peak !== null ? `${fmtInt(Math.round(peak))} kW` : "—"}
          </span>
        </div>
        <div>
          <span className="label">Peak Time</span>
          <span className="num">{peakRow ? fmtStamp(peakRow.timestamp).slice(-5) : "—"}</span>
        </div>
        <div>
          <span className="label">{over ? "Shortfall" : "Headroom"}</span>
          <span className={`num ${over ? "is-amber" : ""}`}>
            {headroom !== null ? `${fmtInt(Math.round(Math.abs(headroom)))} kW` : "—"}
          </span>
        </div>
      </div>
    </section>
  );
}
