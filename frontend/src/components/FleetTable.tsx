import type { Site } from "../types";
import { fmtInt, fmtPct, fmtZmw } from "../lib/format";
import { Panel, PanelHead } from "./ui";

type Props = {
  sites: Site[];
  activeId: string;
  onSelect: (id: string) => void;
  horizon: number;
};

/** Clean fleet comparison table in the Model & Specs tab. */
export default function FleetTable({ sites, activeId, onSelect, horizon }: Props) {
  const maxMape = sites.reduce((acc, s) => Math.max(acc, s.metrics?.hyb_mape ?? 0), 0) || 1;

  return (
    <Panel id="fleet" className="section-anchor">
      <PanelHead
        title={`Fleet Benchmark (H${horizon})`}
        sub="Click any site to switch console context"
      />
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th scope="col">Site</th>
              <th scope="col">Region</th>
              <th scope="col" className="r">
                Latest Load
              </th>
              <th scope="col" className="r">
                MAPE
              </th>
              <th scope="col" className="r">
                Test Peak
              </th>
              <th scope="col" className="r">
                Monthly Saving
              </th>
            </tr>
          </thead>
          <tbody>
            {sites.map((s) => {
              const active = s.id === activeId;
              const mape = s.metrics?.hyb_mape ?? 0;
              return (
                <tr
                  key={s.id}
                  className={`clickable ${active ? "is-active" : ""}`}
                  onClick={() => onSelect(s.id)}
                >
                  <td>
                    <button
                      type="button"
                      className={`bg-transparent p-0 text-left ${active ? "text-lime font-medium" : "text-fg"}`}
                      style={{ font: "inherit", cursor: "pointer" }}
                      aria-pressed={active}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelect(s.id);
                      }}
                    >
                      {s.label}
                    </button>
                  </td>
                  <td className="text-[11.5px] text-dim">{s.location}</td>
                  <td className="num r">{fmtInt(Math.round(s.load?.latest_actual_kw ?? 0))} kW</td>
                  <td className="r">
                    <span className="flex items-center justify-end gap-2">
                      <span
                        className="mape-bar"
                        style={{ width: `${Math.max(6, (mape / maxMape) * 54)}px` }}
                        aria-hidden="true"
                      />
                      <span className="num">{fmtPct(mape, 2)}</span>
                    </span>
                  </td>
                  <td className="num r">{fmtInt(Math.round(s.load?.peak_kw ?? 0))} kW</td>
                  <td className="num r text-lime">{fmtZmw(s.cost?.monthly_saving_zmw)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
