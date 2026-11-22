"""
Combine and summarise v2 per-run metrics.

Reads config/v2/metrics/metrics_<site>_h<h>.csv and run_<site>_h<h>.json,
then prints the tables needed for the thesis:

  * RMSE / MAE by site and horizon for XGB, hybrid and naive baselines
  * mean across sites per horizon
  * readiness/weather ablations
  * peak (top-decile) bias and MAE
  * LSTM residual diagnostics (predicted vs actual residual sigma, corr)
  * OOF fold performance

Usage:
    python src/v2_report.py --dir config/v2
    python src/v2_report.py --dir config/v2_smoke2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from v2_config import MODELS


def load_metrics(directory: Path) -> pd.DataFrame:
    files = sorted((directory / "metrics").glob("metrics_*_h*.csv"))
    if not files:
        raise FileNotFoundError(f"no metrics_*_h*.csv under {directory / 'metrics'}")
    frames = [pd.read_csv(f) for f in files]
    standalone = directory / "metrics_standalone.csv"
    if standalone.exists():
        frames.append(pd.read_csv(standalone))
    for f in sorted((directory / "metrics").glob("standalone_*_h*.csv")):
        frames.append(pd.read_csv(f))
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def load_runs(directory: Path) -> pd.DataFrame:
    rows = []
    for path in sorted((directory / "metrics").glob("run_*_h*.json")):
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        lstm = r.get("lstm") or {}
        sel = r.get("selection") or {}
        rows.append({
            "site": r["site"],
            "horizon": r["horizon"],
            "selected": sel.get("selected"),
            "xgb_val_select_rmse": sel.get("xgb_val_select_rmse"),
            "lstm_val_select_rmse": sel.get("lstm_val_select_rmse"),
            "hgb_val_select_rmse": sel.get("hgb_val_select_rmse"),
            "test_rows": r["test_rows"],
            "test_rows_common": r["test_rows_common"],
            "excluded_imputed": r["test_rows_excluded_imputed"],
            "oof_mean": r.get("oof_mean"),
            "pred_resid_std": lstm.get("pred_resid_std"),
            "actual_resid_std": lstm.get("actual_resid_std"),
            "corr": lstm.get("corr"),
            "r_scaler_mean": lstm.get("r_scaler_mean"),
            "r_scaler_scale": lstm.get("r_scaler_scale"),
            "seconds": r.get("seconds"),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=MODELS)
    ap.add_argument("--write", action="store_true", help="write combined CSVs")
    args = ap.parse_args()

    df = load_metrics(args.dir)
    runs = load_runs(args.dir)

    print(f"\n=== Metrics in {args.dir} ===")
    print(f"rows={len(df)}  sites={df['site'].nunique()}  horizons={sorted(df['horizon'].unique())}")

    main_models = [
        "xgb", "hybrid_lstm", "hybrid_hgb", "hybrid", "standalone_lstm",
        "persistence", "seasonal_naive_24", "seasonal_naive_168",
    ]
    print("\n--- RMSE by site and horizon ---")
    table = (
        df[df["model"].isin(main_models)]
        .pivot_table(index=["site", "horizon"], columns="model", values="rmse")
        .round(1)
    )
    print(table.to_string())

    print("\n--- Mean RMSE by horizon (across sites) ---")
    print(
        df[df["model"].isin(main_models)]
        .groupby(["horizon", "model"])["rmse"]
        .mean()
        .unstack()
        .round(1)
        .to_string()
    )

    print("\n--- Mean MAE by horizon (across sites) ---")
    print(
        df[df["model"].isin(main_models)]
        .groupby(["horizon", "model"])["mae"]
        .mean()
        .unstack()
        .round(1)
        .to_string()
    )

    print("\n--- Ablations: mean RMSE by horizon ---")
    ab = ["xgb", "xgb_no_readiness", "xgb_no_weather", "xgb_core"]
    print(
        df[df["model"].isin(ab)]
        .groupby(["horizon", "model"])["rmse"]
        .mean()
        .unstack()
        .round(1)
        .to_string()
    )

    print("\n--- Peak (top-decile) bias / MAE, mean across sites ---")
    peak = (
        df[df["model"].isin(["xgb", "hybrid_lstm", "hybrid_hgb", "hybrid", "standalone_lstm"])]
        .groupby(["horizon", "model"])[["peak_bias", "peak_mae"]]
        .mean()
        .round(1)
    )
    print(peak.to_string())

    if not runs.empty:
        print("\n--- Validation-selected Stage 2 (Apr-Jun 2025) ---")
        cols = ["site", "horizon", "selected", "xgb_val_select_rmse",
                "lstm_val_select_rmse", "hgb_val_select_rmse"]
        print(runs[cols].to_string(index=False))

        print("\n--- LSTM residual diagnostics ---")
        print(runs.to_string(index=False))

        print("\n--- OOF fold RMSE by site/horizon ---")
        fold_rows = []
        for path in sorted((args.dir / "metrics").glob("run_*_h*.json")):
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
            for fold in r.get("oof_folds", []):
                fold_rows.append({"site": r["site"], "horizon": r["horizon"], **fold})
        if fold_rows:
            print(pd.DataFrame(fold_rows).round(2).to_string(index=False))

    midterm_path = args.dir / "metrics_midterm.csv"
    if midterm_path.exists():
        mdf = pd.read_csv(midterm_path)
        mid_models = [
            "xgb", "hybrid", "hybrid_ridge", "hybrid_hgb",
            "sarimax_harmonic", "seasonal_naive_7d", "persistence",
        ]
        for tname in ("daily_mean_kw", "daily_peak_kw"):
            sub = mdf[(mdf["target"] == tname) & (mdf["model"].isin(mid_models))]
            if sub.empty:
                continue
            print(f"\n=== Mid/Long-Term ({tname}) — Mean RMSE (kW) across sites ===")
            print(
                sub.groupby(["horizon_days", "model"])["rmse"]
                .mean()
                .unstack()[mid_models]
                .round(1)
                .to_string()
            )
            print(f"\n=== Mid/Long-Term ({tname}) — Operational Metrics (Hybrid vs XGB vs SARIMAX) ===")
            op_sub = sub[sub["model"].isin(["xgb", "hybrid", "hybrid_ridge", "sarimax_harmonic"])]
            op_cols = [
                "rmse", "mae", "mape", "peak_bias", "window_30d_mape",
                "monthly_peak_mae_kw", "monthly_peak_mae_zmw", "picp_95",
                "skill_vs_persistence_pct",
            ]
            print(
                op_sub.groupby(["horizon_days", "model"])[op_cols]
                .mean()
                .round(2)
                .to_string()
            )

    if args.write:
        args.dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.dir / "metrics_horizons_combined.csv", index=False)
        if not runs.empty:
            runs.to_csv(args.dir / "lstm_diagnostics.csv", index=False)
        print(f"\nWrote {args.dir / 'metrics_horizons_combined.csv'}")


if __name__ == "__main__":
    main()
