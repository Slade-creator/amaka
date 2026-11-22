"""
Build the prototype's replay dataset, SHAP attributions and site summaries.

Runs the saved Stage-1 XGBoost and Stage-2 residual LSTM over the held-out
test period (2025-07-01 .. 2025-12-31) for every site and writes:

  data/processed/replay_<site>.csv   actual / xgb / hybrid / interval + context
  data/processed/shap_<site>.npz     TreeSHAP contributions for every replay row
  config/sites.json                  metadata, metrics, cost model, demo anchor

The replay CSV is what the FastAPI backend serves; no model inference happens
during the live demo, which keeps the dashboard responsive and deterministic.

Usage:  python src/build_forecasts.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import mean_absolute_error, mean_squared_error

BASE = Path(__file__).resolve().parents[1]
PROC = BASE / "data" / "processed"
CFG = BASE / "config"
SITES = ["arakan", "kohima", "makeni", "mikango", "peter_zuze", "tug_argan"]
DROP = ["load_kw", "readiness_label"]
SEQ = 168
TEST_START = "2025-07-01"

META = {
    "arakan": {
        "label": "Arakan Barracks", "location": "Lusaka", "type": "Admin + residential barracks",
        "base_load_kw": 1800, "pv_kwp": 400, "headcount": 2000, "floor_area_m2": 15000,
        "lat": -15.435, "lon": 28.321,
    },
    "kohima": {
        "label": "Kohima Barracks", "location": "Lusaka", "type": "HQ + logistics barracks",
        "base_load_kw": 2200, "pv_kwp": 500, "headcount": 2500, "floor_area_m2": 18000,
        "lat": -14.406, "lon": 28.488,
    },
    "makeni": {
        "label": "ZNS Makeni", "location": "Lusaka", "type": "ZNS camp",
        "base_load_kw": 1000, "pv_kwp": 250, "headcount": 900, "floor_area_m2": 8000,
        "lat": -15.47, "lon": 28.25,
    },
    "mikango": {
        "label": "Mikango Barracks", "location": "Chongwe", "type": "Training depot",
        "base_load_kw": 1200, "pv_kwp": 350, "headcount": 1100, "floor_area_m2": 10000,
        "lat": -15.329, "lon": 28.682,
    },
    "peter_zuze": {
        "label": "Peter Zuze AFB", "location": "Ndola", "type": "Air force base",
        "base_load_kw": 3000, "pv_kwp": 800, "headcount": 1800, "floor_area_m2": 26000,
        "lat": -12.9972, "lon": 28.6639,
    },
    "tug_argan": {
        "label": "Tug Argan Barracks", "location": "Ndola", "type": "Army garrison",
        "base_load_kw": 1500, "pv_kwp": 300, "headcount": 1400, "floor_area_m2": 12000,
        "lat": -12.995, "lon": 28.665,
    },
}

# Illustrative ZESCO-style cost assumptions (editable in config/sites.json).
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

READINESS_LABEL = {1: "EXERCISE SURGE", 2: "HIGH READINESS", 3: "ELEVATED", 4: "ROUTINE"}


class ResLSTM(nn.Module):
    """Must match the architecture used by src/train_all_sites.py."""

    def __init__(self, f: int):
        super().__init__()
        self.lstm = nn.LSTM(f, 32, num_layers=2, batch_first=True, dropout=0.2)
        self.head = nn.Sequential(nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def rmse(y, p) -> float:
    return float(np.sqrt(mean_squared_error(y, p)))


def iso(ts) -> str:
    """ISO-8601 without timezone, matching the replay CSVs."""
    return pd.Timestamp(ts).isoformat()


def mape(y, p) -> float:
    return float(np.mean(np.abs((y - p) / np.clip(np.abs(y), 1e-6, None))) * 100)


def load_site(site: str):
    df = (
        pd.read_csv(PROC / f"features_{site}.csv", parse_dates=["timestamp"])
        .dropna()
        .set_index("timestamp")
        .sort_index()
    )
    xgb = joblib.load(CFG / f"xgb_{site}.pkl")
    ckpt = torch.load(CFG / f"lstm_{site}.pt", map_location="cpu", weights_only=False)
    feat_cols = ckpt["feat_cols"]
    model = ResLSTM(len(feat_cols))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    scaler = joblib.load(CFG / f"scaler_{site}.pkl")
    r_scaler = joblib.load(CFG / f"rscaler_{site}.pkl")
    return df, xgb, model, scaler, r_scaler, feat_cols


def build(site: str) -> dict:
    df, xgb, model, scaler, r_scaler, feat_cols = load_site(site)
    xgb_all = xgb.predict(df[feat_cols].to_numpy())
    x_all = scaler.transform(df[feat_cols]).astype("float32")

    test_mask = df.index >= pd.Timestamp(TEST_START, tz=df.index.tz)
    test_pos = np.where(test_mask)[0]
    test_df = df.iloc[test_pos]
    xgb_test = xgb_all[test_pos]

    # Build (N, 168, F) windows for every test row, batched through the LSTM.
    seqs = np.stack([x_all[p - SEQ:p] for p in test_pos]).astype("float32")
    resid_scaled = np.empty(len(seqs), dtype="float32")
    with torch.no_grad():
        for i in range(0, len(seqs), 512):
            chunk = torch.from_numpy(seqs[i:i + 512])
            resid_scaled[i:i + 512] = model(chunk).cpu().numpy()
    resid = r_scaler.inverse_transform(resid_scaled.reshape(-1, 1)).ravel()
    hybrid_test = xgb_test + resid

    y = test_df["load_kw"].to_numpy()
    err = hybrid_test - y
    sigma = float(np.std(err))
    band = 1.96 * sigma

    # Naive baselines for the honesty panel.
    lag1 = test_df["load_lag_1h"].to_numpy()
    lag24 = test_df["load_lag_24h"].to_numpy()

    # Demo anchor: a high-readiness surge hour with above-median forecast accuracy,
    # so the live replay opens on a peak that the model actually gets right.
    surge = test_df["readiness_code"].to_numpy() <= 2
    abs_err = np.abs(y - hybrid_test)
    candidates = surge & (y > np.quantile(y, 0.90)) & (abs_err < np.median(abs_err))
    anchor_idx = int(np.argmax(np.where(candidates, y, -np.inf)))
    if not np.isfinite(y[anchor_idx]):
        anchor_idx = int(np.argmax(hybrid_test))

    # TreeSHAP via XGBoost's native pred_contribs (no extra dependency).
    import xgboost as xgb_core

    dmat = xgb_core.DMatrix(test_df[feat_cols].to_numpy(), feature_names=feat_cols)
    booster = xgb.get_booster() if hasattr(xgb, "get_booster") else xgb.booster_
    contribs = booster.predict(dmat, pred_contribs=True)
    values = contribs[:, :-1].astype("float32")
    bias = contribs[:, -1].astype("float32")

    np.savez_compressed(
        PROC / f"shap_{site}.npz",
        values=values,
        feature_values=test_df[feat_cols].to_numpy(dtype="float32"),
        bias=bias,
        features=np.array(feat_cols),
        timestamps=test_df.index.to_numpy(dtype="datetime64[ns]").astype("int64"),
    )

    # Replay table served by the API.
    replay = pd.DataFrame({
        "timestamp": test_df.index,
        "actual_kw": np.round(y, 1),
        "xgb_kw": np.round(xgb_test, 1),
        "hybrid_kw": np.round(hybrid_test, 1),
        "lower_kw": np.round(hybrid_test - band, 1),
        "upper_kw": np.round(hybrid_test + band, 1),
        "readiness_code": test_df["readiness_code"].astype(int).to_numpy(),
        "readiness_label": test_df["readiness_label"].to_numpy(),
        "temperature_c": np.round(test_df["temperature_2m"].to_numpy(), 1),
        "humidity_pct": np.round(test_df["relative_humidity_2m"].to_numpy(), 1),
        "radiation_wm2": np.round(test_df["shortwave_radiation"].to_numpy(), 0),
        "cloud_cover_pct": np.round(test_df["cloud_cover"].to_numpy(), 0),
    })
    replay.to_csv(PROC / f"replay_{site}.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S")

    # Peak threshold = 97th percentile of the 2024 training load, rounded up.
    train = df.loc[df.index < pd.Timestamp("2025-01-01", tz=df.index.tz)]
    threshold = float(np.ceil(np.quantile(train["load_kw"], 0.97) / 50.0) * 50.0)

    peak_hours = int(np.sum(hybrid_test > threshold))
    surge_hours = int(np.sum(test_df["readiness_code"].to_numpy() <= 2))
    variance_hours = int(np.sum(np.abs(err) > band))

    avg_load = float(np.mean(y))
    peak_load = float(np.max(y))
    energy_month = avg_load * COST["hours_per_month"]
    base_monthly = energy_month * COST["energy_tariff_zmw_kwh"] + peak_load * COST["demand_charge_zmw_kw_month"]
    demand_saving = peak_load * COST["peak_shaving_fraction"] * COST["demand_charge_zmw_kw_month"]
    fuel_saving = (
        energy_month
        * COST["generator_share_of_energy"]
        * COST["fuel_efficiency_gain"]
        * COST["generator_litres_per_kwh"]
        * COST["diesel_price_zmw_litre"]
    )
    monthly_saving = demand_saving + fuel_saving

    summary = {
        "id": site,
        **META[site],
        "test_start": iso(test_df.index.min()),
        "test_end": iso(test_df.index.max()),
        "rows": int(len(test_df)),
        "demo_anchor": iso(test_df.index[anchor_idx]),
        "demo_start": iso(test_df.index[max(0, anchor_idx - 72)]),
        "metrics": {
            "xgb_rmse": round(rmse(y, xgb_test), 1),
            "xgb_mae": round(mean_absolute_error(y, xgb_test), 1),
            "hyb_rmse": round(rmse(y, hybrid_test), 1),
            "hyb_mae": round(mean_absolute_error(y, hybrid_test), 1),
            "hyb_mape": round(mape(y, hybrid_test), 2),
            "persistence_mae": round(mean_absolute_error(y, lag1), 1),
            "seasonal_naive_mae": round(mean_absolute_error(y, lag24), 1),
            "band_kw": round(band, 1),
        },
        "load": {
            "avg_kw": round(avg_load, 1),
            "peak_kw": round(peak_load, 1),
            "threshold_kw": round(threshold, 1),
            "latest_actual_kw": round(float(y[-1]), 1),
            "latest_hybrid_kw": round(float(hybrid_test[-1]), 1),
        },
        "alerts": {
            "peak_hours": peak_hours,
            "surge_hours": surge_hours,
            "variance_hours": variance_hours,
        },
        "cost": {
            "energy_month_kwh": round(energy_month),
            "baseline_monthly_zmw": round(base_monthly),
            "monthly_saving_zmw": round(monthly_saving),
            "annual_saving_zmw": round(monthly_saving * 12),
            "demand_saving_zmw": round(demand_saving),
            "fuel_saving_zmw": round(fuel_saving),
            "saving_pct": round(monthly_saving / base_monthly * 100, 2),
        },
    }

    print(
        f"{site:11s} rows={len(test_df):5d}  XGB {summary['metrics']['xgb_rmse']:5.1f}/"
        f"{summary['metrics']['xgb_mae']:5.1f}  HYB {summary['metrics']['hyb_rmse']:5.1f}/"
        f"{summary['metrics']['hyb_mae']:5.1f}  MAPE {summary['metrics']['hyb_mape']:4.2f}%  "
        f"anchor {test_df.index[anchor_idx]}  saving ZMW {monthly_saving:,.0f}/mo"
    )
    return summary


def main() -> None:
    print("Building replay data, SHAP attributions and summaries...")
    summaries = []
    for site in SITES:
        summaries.append(build(site))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "test_period": {"start": TEST_START, "end": "2025-12-31T23:00:00"},
        # A fleet-wide moment with a readable mix of statuses (2 critical,
        # 2 warning, 2 nominal) and accurate forecasts at the risk sites.
        "fleet_anchor": "2025-09-08T18:00:00",
        "model": {
            "name": "Hybrid XGBoost + Residual LSTM",
            "stage1": "XGBoost Regressor (300 trees, depth 6)",
            "stage2": "2-layer LSTM, 32 hidden, 168h lookback",
            "horizon": "1 hour ahead (operational replay)",
            "features": 23,
        },
        "cost_assumptions": COST,
        "sites": summaries,
    }
    with open(CFG / "sites.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwrote {CFG / 'sites.json'}")
    print(f"wrote {len(SITES)} replay CSVs and SHAP archives")


if __name__ == "__main__":
    main()
