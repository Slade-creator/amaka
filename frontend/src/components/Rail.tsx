import { useEffect, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import type { ModelInfo, Site } from "../types";
import { fmtInt } from "../lib/format";

type Props = {
  sites: Site[];
  activeSiteId: string;
  activeLoadKw?: number;
  onSelectSite: (id: string) => void;
  onBackToFleet: () => void;
  apiStatus: "ok" | "down" | "checking";
  model?: ModelInfo;
};

/** Region grouping — Chongwe rolls up into the Lusaka group per the contract. */
function regionOf(site: Site): string {
  return site.location === "Ndola" ? "Ndola" : "Lusaka";
}

export default function Rail({
  sites,
  activeSiteId,
  activeLoadKw,
  onSelectSite,
  onBackToFleet,
  apiStatus,
  model,
}: Props) {
  const groups: Array<{ name: string; sites: Site[] }> = [];
  for (const s of sites) {
    const name = regionOf(s);
    let g = groups.find((x) => x.name === name);
    if (!g) {
      g = { name, sites: [] };
      groups.push(g);
    }
    g.sites.push(s);
  }
  groups.sort((a, b) =>
    a.name === "Lusaka" ? -1 : b.name === "Lusaka" ? 1 : a.name === "Ndola" ? 1 : -1,
  );

  const dotClass = apiStatus === "down" ? "status-dot down" : "status-dot ok";
  const activeRef = useRef<HTMLButtonElement | null>(null);

  // On phones the rail is a horizontal strip; keep the selected site visible.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [activeSiteId]);

  return (
    <aside className="rail" aria-label="Site navigation">
      <div className="rail-top-action">
        <button type="button" className="rail-back-btn" onClick={onBackToFleet}>
          <ArrowLeft size={14} aria-hidden="true" />
          <span>Fleet Map</span>
          <span className="ml-auto num text-[10px] text-[color:var(--color-muted)]">F</span>
        </button>
      </div>

      <div className="rail-sites">
        <div className="rail-sites-head">
          <span>Sites</span>
          <span>Load</span>
        </div>
        {groups.map((g) => (
          <div className="rail-group" key={g.name}>
            <div className="rail-group-label">{g.name}</div>
            <div className="rail-group-items">
              {g.sites.map((s) => {
                const active = s.id === activeSiteId;
                return (
                  <button
                    key={s.id}
                    ref={active ? activeRef : undefined}
                    type="button"
                    className={`rail-site ${active ? "is-active" : ""}`}
                    aria-current={active ? "true" : undefined}
                    onClick={() => onSelectSite(s.id)}
                    title={`${s.label} (${s.location})`}
                  >
                    <span
                      className={`status-dot ${active ? "ok" : ""}`}
                      style={
                        active
                          ? undefined
                          : { opacity: 0.35, background: "var(--dim)", boxShadow: "none" }
                      }
                      aria-hidden="true"
                    />
                    <span className="rs-name">{s.label}</span>
                    <span className="rs-load">
                      {fmtInt(
                        Math.round(
                          active && typeof activeLoadKw === "number"
                            ? activeLoadKw
                            : (s.load?.latest_actual_kw ?? 0),
                        ),
                      )}
                      <span className="ml-0.5 text-[9.5px] opacity-65">kW</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="rail-foot">
        <div className="flex items-center gap-2">
          <span className={dotClass} aria-hidden="true" />
          <span className="truncate" title={model?.name}>
            XGBoost + Residual
          </span>
        </div>
      </div>
    </aside>
  );
}
