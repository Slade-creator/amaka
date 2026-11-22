"""Build the AMAKA v2 dashboard replay from the v2 research artifacts.

Reads the trained v2 models in config/v2/ and the horizon frames from
src/v2_horizons.py, then writes:

  data/v2/replay_<site>_h<h>.csv
  data/v2/shap_<site>_h<h>.npz
  config/v2_sites.json

Each replay row is keyed by the TARGET timestamp (the hour being forecast), so
the dashboard's actual-vs-forecast chart and shared time gate stay honest for
direct 1/6/24/48-hour forecasts.

Usage: python src/build_v2_replay.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import mean_absolute_error, mean_squared_error

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

from v2_config import (  # noqa: E402
    HORIZONS, MODELS, SITES, TEST_END, TEST_START, VAL_START, VAL_END,
)
from v2_horizons import FEATURE_COLS, build_horizon, load_base  # noqa: E402

OUT = BASE_DIR / "data" / "v2"
OUT.mkdir(parents=True, exist_ok=True)
CFG_OUT = BASE_DIR / "config" / "v2_sites.json"

TEST_START_TS = pd.Timestamp(TEST_START)
TEST_END_TS = pd.Timestamp(TEST_END)

META = {
    "arakan": {"label": "Arakan Barracks", "location": "Lusaka", "type": "Admin + residential barracks",
               "base_load_kw": 1700, "pv_kwp": 400, "headcount": 2000, "floor_area_m2": 15000,
               "lat": -15.435, "lon": 28.321},
    "kohima": {"label": "Kohima Barracks", "location": "Lusaka", "type": "HQ + logistics barracks",
               "base_load_kw": 2050, "pv_kwp": 500, "headcount": 2500, "floor_area_m2": 18000,
               "lat": -14.406, "lon": 28.488},
    "makeni": {"label": "ZNS Makeni", "location": "Lusaka", "type": "ZNS camp",
               "base_load_kw": 1000, "pv_kwp": 250, "headcount": 900, "floor_area_m2": 8000,
               "lat": -15.47, "lon": 28.25},
    "mikango": {"label": "Mikango Barracks", "location": "Chongwe", "type": "Training depot",
                "base_load_kw": 1210, "pv_kwp": 350, "headcount": 1100, "floor_area_m2": 10000,
                "lat": -15.329, "lon": 28.682},
    "peter_zuze": {"label": "Peter Zuze AFB", "location": "Ndola", "type": "Air force base",
                   "base_load_kw": 2720, "pv_kwp": 800, "headcount": 1800, "floor_area_m2": 26000,
                   "lat": -12.9972, "lon": 28.6639},
    "tug_argan": {"label": "Tug Argan Barracks", "location": "Ndola", "type": "Army garrison",
                  "base_load_kw": 1470, "pv_kwp": 300, "headcount": 1400, "floor_area_m2": 12000,
                  "lat": -12.995, "lon": 28.665},
}

COST = {
    "energy_tariff_zmw_kwh": 1.78,
    "demand_charge_zmw_kw_month": 120.0,
    "diesel_price_zmw_litre": 30.0,
    "generator_litres_per_kwh": 0.28,
    "generator_share_of_energy": 0.03,
    "peak_shaving_fraction": 0.08,
    "fuel_efficiency_gain": 0.10,
    "hours_per_month": 730,
    "usd_rate_zmw": 28.5,
}

READINESS = {1: "surge", 2: "high readiness", 3: "elevated", 4: "routine"}


class ResLSTM(nn.Module):
    def __init__(self, n_features: int):
        super().__init__()
        self.lstm = nn.LSTM(n_features, 32, num_layers=2, batch_first=True, dropout=0.2)
        self.head = nn.Sequential(
            nn.Dropout(0.2), nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1)
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


def rmse(y, p) -> float:
    return float(np.sqrt(mean_squared_error(y, p)))


def load_metrics(site: str, horizon: int) -> tuple[dict, dict]:
    combined = pd.read_csv(MODELS / "metrics_horizons_combined.csv")
    rows = combined[(combined["site"] == site) & (combined["horizon"] == horizon)]
    by_model = {r["model"]: r for _, r in rows.iterrows()}
    standalone = {}
    sp = MODELS / "metrics_standalone.csv"
    if sp.exists():
        st = pd.read_csv(sp)
        st = st[(st["site"] == site) & (st["horizon"] == horizon)]
        if len(st):
            standalone = st.iloc[0].to_dict()
    return by_model, standalone


def predict(site: str, horizon: int, frame: pd.DataFrame, test_pos: np.ndarray) -> tuple[np.ndarray, np.ndarray, str, float]:
    """Return (xgb_pred, hybrid_pred, selected_model, band_sigma)."""
    x_raw = frame[FEATURE_COLS].to_numpy(np.float32)
    y = frame["target"].to_numpy(np.float32)
    xgb = joblib.load(MODELS / f"xgb_{site}_h{horizon}.pkl")
    xgb_pred = xgb.predict(x_raw[test_pos]).astype(np.float32)

    run = json.loads((MODELS / "metrics" / f"run_{site}_h{horizon}.json").read_text(encoding="utf-8"))
    selected = (run.get("selection") or {}).get("selected", "xgb")
    hybrid = xgb_pred.copy()

    if selected == "lstm":
        ckpt = torch.load(MODELS / f"lstm_{site}_h{horizon}.pt", map_location="cpu", weights_only=False)
        model = ResLSTM(len(FEATURE_COLS))
        model.load_state_dict(ckpt["state_dict"])
        model.eval()
        scaler = joblib.load(MODELS / f"feature_scaler_{site}_h{horizon}.pkl")
        r_scaler = joblib.load(MODELS / f"residual_scaler_{site}_h{horizon}.pkl")
        x_scaled = scaler.transform(x_raw).astype(np.float32)
        seq_len = int(ckpt.get("seq_len", 168))
        seqs = np.stack([x_scaled[p - seq_len:p] for p in test_pos]).astype(np.float32)
        resid = np.empty(len(seqs), dtype=np.float32)
        with torch.no_grad():
            for i in range(0, len(seqs), 512):
                resid[i:i + 512] = model(torch.from_numpy(seqs[i:i + 512])).numpy()
        resid = r_scaler.inverse_transform(resid.reshape(-1, 1)).ravel()
        alpha = float(run.get("lstm", {}).get("alpha") or 0.0)
        hybrid = xgb_pred + alpha * resid
    elif selected == "hgb":
        hgb = joblib.load(MODELS / f"resid_hgb_{site}_h{horizon}.pkl")
        alpha = float((run.get("resid_hgb") or {}).get("alpha") or 0.0)
        hybrid = xgb_pred + alpha * hgb.predict(x_raw[test_pos])

    sigma = float(np.std((hybrid - y[test_pos]).astype(float)))
    return xgb_pred, hybrid.astype(np.float32), selected, sigma


def build_site(site: str, horizon: int) -> dict:
    base = load_base(site)
    frame = build_horizon(base, site, horizon)
    tt = pd.to_datetime(frame["target_time"])
    valid = frame["target_valid"].to_numpy().astype(bool)
    in_test = (tt >= TEST_START_TS) & (tt <= TEST_END_TS)
    test_pos = np.where(in_test.to_numpy() & valid)[0]
    if len(test_pos) == 0:
        raise RuntimeError(f"no test rows for {site} h={horizon}")

    xgb_pred, hybrid, selected, sigma = predict(site, horizon, frame, test_pos)
    target_time = pd.to_datetime(frame["target_time"].iloc[test_pos]).reset_index(drop=True)
    actual = frame["target"].to_numpy(np.float32)[test_pos]

    # Target-time observed weather and readiness for the HUD (not used by the model).
    base_at = base.reindex(target_time)
    replay = pd.DataFrame({
        "timestamp": target_time,
        "actual_kw": np.round(actual, 1),
        "xgb_kw": np.round(xgb_pred, 1),
        "hybrid_kw": np.round(hybrid, 1),
        "lower_kw": np.round(hybrid - 1.96 * sigma, 1),
        "upper_kw": np.round(hybrid + 1.96 * sigma, 1),
        "selected_model": selected,
        "readiness_code": base_at["readiness_code"].fillna(4).astype(int).to_numpy(),
        "readiness_label": base_at["readiness_label"].fillna("routine").to_numpy(),
        "temperature_c": np.round(base_at["temperature_2m"].to_numpy(), 1),
        "humidity_pct": np.round(base_at["relative_humidity_2m"].to_numpy(), 1),
        "radiation_wm2": np.round(base_at["shortwave_radiation"].to_numpy(), 0),
        "cloud_cover_pct": np.round(base_at["cloud_cover"].to_numpy(), 0),
        "is_holiday": base_at["is_holiday"].fillna(0).astype(int).to_numpy(),
        "is_weekend": base_at["is_weekend"].fillna(0).astype(int).to_numpy(),
    }).sort_values("timestamp").reset_index(drop=True)
    replay.to_csv(OUT / f"replay_{site}_h{horizon}.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S")

    # TreeSHAP on the same test rows, using the XGBoost booster directly.
    import xgboost as xgb_core
    x_raw = frame[FEATURE_COLS].to_numpy(np.float32)
    dmat = xgb_core.DMatrix(x_raw[test_pos], feature_names=FEATURE_COLS)
    booster = joblib.load(MODELS / f"xgb_{site}_h{horizon}.pkl").get_booster()
    contribs = booster.predict(dmat, pred_contribs=True)
    np.savez_compressed(
        OUT / f"shap_{site}_h{horizon}.npz",
        values=contribs[:, :-1].astype("float32"),
        feature_values=x_raw[test_pos].astype("float32"),
        bias=contribs[:, -1].astype("float32"),
        features=np.array(FEATURE_COLS),
        timestamps=target_time.to_numpy(dtype="datetime64[ns]").astype("int64"),
    )

    # Threshold from the 2025 H1 validation load (never test).
    val = base.loc[(base.index >= pd.Timestamp(VAL_START)) & (base.index <= pd.Timestamp(VAL_END)), "load_kw"]
    threshold = float(np.ceil(np.quantile(val.dropna(), 0.97) / 50.0) * 50.0)
    band = 1.96 * sigma
    err = hybrid.astype(float) - actual.astype(float)
    m = {
        "xgb_rmse": round(rmse(actual, xgb_pred), 1),
        "xgb_mae": round(mean_absolute_error(actual, xgb_pred), 1),
        "hyb_rmse": round(rmse(actual, hybrid), 1),
        "hyb_mae": round(mean_absolute_error(actual, hybrid), 1),
        "hyb_mape": round(float(np.mean(np.abs(err / np.clip(np.abs(actual), 1e-6, None))) * 100), 2),
        "band_kw": round(band, 1),
        "selected_model": selected,
    }
    by_model, standalone = load_metrics(site, horizon)
    for key, model in (("persistence_mae", "persistence"), ("seasonal_naive_24_mae", "seasonal_naive_24"),
                       ("seasonal_naive_168_mae", "seasonal_naive_168")):
        if model in by_model:
            m[key] = round(float(by_model[model]["mae"]), 1)
    if standalone:
        m["standalone_lstm_mae"] = round(float(standalone.get("mae", 0)), 1)
        m["standalone_lstm_rmse"] = round(float(standalone.get("rmse", 0)), 1)

    avg_load = float(actual.mean())
    peak_load = float(actual.max())
    energy_month = avg_load * COST["hours_per_month"]
    baseline = energy_month * COST["energy_tariff_zmw_kwh"] + peak_load * COST["demand_charge_zmw_kw_month"]
    demand_saving = peak_load * COST["peak_shaving_fraction"] * COST["demand_charge_zmw_kw_month"]
    fuel_saving = (energy_month * COST["generator_share_of_energy"] * COST["fuel_efficiency_gain"]
                   * COST["generator_litres_per_kwh"] * COST["diesel_price_zmw_litre"])
    monthly_saving = demand_saving + fuel_saving

    demo_anchor = "2025-09-08T18:00:00"
    if not (replay["timestamp"] == pd.Timestamp(demo_anchor)).any():
        demo_anchor = iso(replay["timestamp"].iloc[-1])

    summary = {
        "id": site, **META[site],
        "horizon": horizon,
        "selected_model": selected,
        "test_start": iso(replay["timestamp"].min()),
        "test_end": iso(replay["timestamp"].max()),
        "rows": int(len(replay)),
        "demo_anchor": demo_anchor,
        "demo_start": iso(pd.Timestamp(demo_anchor) - pd.Timedelta(hours=72)),
        "metrics": m,
        "load": {
            "avg_kw": round(avg_load, 1),
            "peak_kw": round(peak_load, 1),
            "threshold_kw": round(threshold, 1),
            "latest_actual_kw": round(float(actual[-1]), 1),
            "latest_hybrid_kw": round(float(hybrid[-1]), 1),
        },
        "alerts": {
            "peak_hours": int((hybrid > threshold).sum()),
            "surge_hours": int((replay["readiness_code"].to_numpy() <= 2).sum()),
            "variance_hours": int((np.abs(err) > band).sum()),
        },
        "cost": {
            "energy_month_kwh": round(energy_month),
            "baseline_monthly_zmw": round(baseline),
            "monthly_saving_zmw": round(monthly_saving),
            "annual_saving_zmw": round(monthly_saving * 12),
            "demand_saving_zmw": round(demand_saving),
            "fuel_saving_zmw": round(fuel_saving),
            "saving_pct": round(monthly_saving / baseline * 100, 2),
        },
    }
    print(f"{site:11s} h={horizon:2d} n={len(replay):5d} XGB {m['xgb_rmse']:6.1f}/{m['xgb_mae']:5.1f} "
          f"HYB {m['hyb_rmse']:6.1f}/{m['hyb_mae']:5.1f} MAPE {m['hyb_mape']:4.2f}% sel={selected}")
    return summary


def choose_anchor(all_summaries: list[dict], horizon: int) -> str:
    """Pick a fleet hour with a readable mix of statuses for the map landing."""
    frames = []
    for s in all_summaries:
        p = OUT / f"replay_{s['id']}_h{horizon}.csv"
        r = pd.read_csv(p, parse_dates=["timestamp"])
        r["site"] = s["id"]
        r["threshold"] = s["load"]["threshold_kw"]
        r["critical"] = r["hybrid_kw"] > r["threshold"]
        r["warning"] = (~r["critical"]) & (r["hybrid_kw"] >= r["threshold"] * 0.97)
        frames.append(r[["timestamp", "site", "actual_kw", "critical", "warning"]])
    df = pd.concat(frames)
    g = df.groupby("timestamp").agg(critical=("critical", "sum"), warning=("warning", "sum"),
                                    load=("actual_kw", "sum")).reset_index()
    g["nominal"] = len(all_summaries) - g["critical"] - g["warning"]
    # Prefer 2 critical / 2 warning / 2 nominal, then the highest load.
    exact = g[(g["critical"] == 2) & (g["warning"] == 2) & (g["nominal"] == 2)]
    if len(exact):
        return iso(exact.sort_values("load", ascending=False).iloc[0]["timestamp"])
    return iso(g.sort_values(["critical", "load"], ascending=False).iloc[0]["timestamp"])


def main() -> None:
    all_summaries = []
    for site in SITES:
        for h in HORIZONS:
            all_summaries.append(build_site(site, h))

    # Nest per-site horizon summaries so the API can select one.
    sites = []
    for site in SITES:
        rows = [s for s in all_summaries if s["id"] == site]
        base = dict(rows[0])
        base["horizons"] = {str(s["horizon"]): s for s in rows}
        base["metrics"] = rows[0]["metrics"]
        base["load"] = rows[0]["load"]
        base["alerts"] = rows[0]["alerts"]
        base["cost"] = rows[0]["cost"]
        base["selected_model"] = rows[0]["selected_model"]
        sites.append(base)

    anchors = {str(h): choose_anchor([s for s in all_summaries if s["horizon"] == h], h) for h in HORIZONS}
    default_h = 24 if 24 in HORIZONS else HORIZONS[0]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v2",
        "default_horizon": default_h,
        "available_horizons": HORIZONS,
        "test_period": {"start": TEST_START, "end": TEST_END},
        "fleet_anchor": anchors.get(str(default_h)),
        "fleet_anchor_by_horizon": anchors,
        "model": {
            "name": "Hybrid XGBoost + validation-selected residual learner",
            "stage1": "XGBoost direct multi-horizon regressor",
            "stage2": "Residual HGB or LSTM, selected on Apr-Jun 2025 validation",
            "horizon": "Direct 1 / 6 / 24 / 48 hours ahead",
            "features": len(FEATURE_COLS),
        },
        "cost_assumptions": COST,
        "sites": sites,
    }
    CFG_OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {CFG_OUT}")
    print(f"wrote {len(all_summaries)} replay CSVs + SHAP archives to {OUT}")
    print("fleet anchors", anchors)


if __name__ == "__main__":
    main()
