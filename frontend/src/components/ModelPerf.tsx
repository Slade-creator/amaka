import type { Site } from "../types";
import { fmtInt, fmtPct } from "../lib/format";
import { Panel, PanelHead } from "./ui";

type Row = {
  name: string;
  mae: string;
  rmse: string;
  mape: string;
  note: string;
  active?: boolean;
  show: boolean;
};

/** Clean model comparison against naive baselines. */
export default function ModelPerf({ site, horizon }: { site: Site; horizon: number }) {
  const m = site.metrics;
  const hLabel = `H${horizon}`;

  const learner = (site.selected_model || m?.selected_model || "").toLowerCase();
  const learnerLabel = learner.includes("lstm") ? "LSTM" : learner.includes("hgb") ? "HGB" : "";
  const hybridName = learnerLabel
    ? `Hybrid · ${learnerLabel}`
    : site.horizon
      ? "Hybrid (XGB selected)"
      : "Hybrid forecast";

  const persistence = m?.persistence_mae ?? 0;
  const seasonal24 = m?.seasonal_naive_24_mae ?? 0;
  const seasonal168 = m?.seasonal_naive_168_mae ?? 0;
  const standaloneLstm = m?.standalone_lstm_mae ?? 0;

  const rows: Row[] = [
    {
      name: hybridName,
      mae: `${fmtInt(m?.hyb_mae, 1)} kW`,
      rmse: `${fmtInt(m?.hyb_rmse, 1)} kW`,
      mape: fmtPct(m?.hyb_mape, 2),
      note: "Served model (XGBoost + validation-selected residual)",
      active: true,
      show: true,
    },
    {
      name: "Stage-1 XGBoost",
      mae: `${fmtInt(m?.xgb_mae, 1)} kW`,
      rmse: `${fmtInt(m?.xgb_rmse, 1)} kW`,
      mape: "—",
      note: "Direct multi-horizon tree model without residual stage",
      show: true,
    },
    {
      name: "Persistence (last hour)",
      mae: `${fmtInt(persistence, 1)} kW`,
      rmse: "—",
      mape: "—",
      note: "Last observed load carried forward",
      show: persistence > 0,
    },
    {
      name: "Seasonal naive (24h)",
      mae: `${fmtInt(seasonal24, 1)} kW`,
      rmse: "—",
      mape: "—",
      note: "Repeats load from the same hour yesterday",
      show: seasonal24 > 0,
    },
    {
      name: "Seasonal naive (7d)",
      mae: `${fmtInt(seasonal168, 1)} kW`,
      rmse: "—",
      mape: "—",
      note: "Repeats load from the same hour last week",
      show: seasonal168 > 0,
    },
    {
      name: "Standalone LSTM",
      mae: `${fmtInt(standaloneLstm, 1)} kW`,
      rmse: "—",
      mape: "—",
      note: "Sequence model without XGBoost stage",
      show: standaloneLstm > 0,
    },
  ].filter((r) => r.show);

  return (
    <Panel>
      <PanelHead
        title={`Model Accuracy (${hLabel})`}
        sub={`${site.label} · 2025 H2 evaluation`}
        right={
          <span className="num text-[11px] text-dim">
            95% range ±{fmtInt(m?.band_kw, 0)} kW
          </span>
        }
      />
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col" className="r">
                MAE
              </th>
              <th scope="col" className="r">
                RMSE
              </th>
              <th scope="col" className="r">
                MAPE
              </th>
              <th scope="col">Description</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className={r.active ? "is-active" : undefined}>
                <td className={r.active ? "font-medium text-lime" : "text-fg"}>{r.name}</td>
                <td className="num r">{r.mae}</td>
                <td className="num r">{r.rmse}</td>
                <td className="num r">{r.mape}</td>
                <td className="text-dim">{r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-[color:var(--border)] px-4 py-2.5 text-[11.5px] text-dim">
        {learnerLabel
          ? `Stage-2 ${learnerLabel} residual learner selected on Apr–Jun 2025 validation for H${horizon}.`
          : `Plain Stage-1 XGBoost served for H${horizon} (residual candidate did not exceed the 0.5% validation gate).`}
      </p>
    </Panel>
  );
}
