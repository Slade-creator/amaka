import type { Overview } from "../types";
import { fmtIsoUtc } from "../lib/format";

/** Section 8 — provenance, model version, timestamps, attribution. */
export default function SiteFooter({ overview }: { overview: Overview }) {
  const period = overview.test_period ?? { start: "—", end: "—" };
  const model = overview.model;

  return (
    <footer className="mt-4 border-t border-[rgb(var(--dim-rgb)/0.2)] pt-4 pb-2">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
        <div className="min-w-0">
          <div className="label mb-1">Data source</div>
          <p className="num text-[10.5px] leading-relaxed text-dim">
            config/v2_sites.json + data/v2/replay_&lt;site&gt;_h&lt;h&gt;.csv · synthetic hourly data ·{" "}
            {String(period.start).slice(0, 10)} → {String(period.end).slice(0, 10)} (test period)
          </p>
        </div>
        <div className="min-w-0">
          <div className="label mb-1">Model</div>
          <p className="num text-[10.5px] leading-relaxed text-dim">
            {model?.name ?? "—"}
            <br />
            {model?.stage1 ?? ""}
            {model?.stage2 ? ` + ${model.stage2}` : ""}
          </p>
        </div>
        <div className="min-w-0">
          <div className="label mb-1">Generated</div>
          <p className="num text-[10.5px] leading-relaxed text-dim">
            {fmtIsoUtc(overview.generated_at)}
            {overview.served_at ? (
              <>
                <br />
                data served {fmtIsoUtc(overview.served_at)}
              </>
            ) : null}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[rgb(var(--dim-rgb)/0.12)] pt-3">
        <span className="label text-[10px]">
          AMAKA v0.1 · UNCLASSIFIED // SYNTHETIC DEMO DATA · NOT FOR OPERATIONAL USE
        </span>
        <span className="label text-[10px] text-[rgb(var(--accent-rgb)/0.75)]">
          Built for ICT431 · Mulungushi University
        </span>
      </div>
    </footer>
  );
}
