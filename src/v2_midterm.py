"""
Train and evaluate direct mid- to long-term (1 week to 3 months) forecasting models.

Horizons: D in {7, 14, 30, 60, 90} days ahead (1 week, 2 weeks, 1 month, 2 months, 3 months).
Targets:
  1. daily_mean_kw   (daily average power in kW; x24 = daily energy in kWh/day)
  2. daily_peak_kw   (daily maximum hourly demand in kW; drives monthly ZESCO peak demand tariff)

Methodology:
  * Gap-aware daily aggregation from data/synthetic_v2/features_<site>.csv.
    A day is valid for training/evaluation only if <= 6 hours were missing/imputed.
  * Horizon-decaying weather proxy: blends target weather anomaly with 2024-fitted
    Fourier seasonal climatology using exp(-D / 7.0) so 30-90 day forecasts rely on
    seasonal climate expectations + realistic noise rather than future observed weather.
  * Chronological splits on TARGET date (identical to short-term v2):
      - Train:            2024-01-01 .. 2024-12-31 (with 3 expanding OOF folds)
      - Val calibration:  2025-01-01 .. 2025-03-31 (fit shrinkage alpha in [0, 1])
      - Val selection:    2025-04-01 .. 2025-06-30 (select Stage 2 with 0.5% margin + corr gate)
      - Test:             2025-07-01 .. 2025-12-31 (held-out evaluation, untouched)
  * Models compared:
      - Baselines: persistence, rolling_persistence_7d, seasonal_naive_7d, sarimax_harmonic
      - Stage 1:   xgb (regularized XGBoost)
      - Stage 2:   hybrid_hgb (XGB + OOF HistGradientBoosting), hybrid_ridge (XGB + OOF Ridge),
                   hybrid (validation-selected with 0.5% RMSE margin and non-degenerate corr gate)
      - Ablations: xgb_no_readiness, xgb_no_weather, xgb_core

Outputs:
  config/v2/metrics_midterm.csv
  config/v2/metrics_midterm_summary.csv
  config/v2/midterm_manifest.json
  config/v2/midterm_<target>_<site>_d<D>.pkl
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from v2_config import (
    MODELS, OOF_FOLDS, PROCESSED, READINESS, SITES, stable_site_seed,
)

MIDTERM_HORIZONS = [7, 14, 30, 60, 90]  # days ahead (1 wk, 2 wk, 1 mo, 2 mo, 3 mo)
TARGETS = ["daily_mean_kw", "daily_peak_kw"]
DEMAND_CHARGE_ZMW_KW_MONTH = 120.0
SELECTION_MARGIN = 0.005  # >= 0.5% validation RMSE improvement required
MIN_VAL_CORR = 0.05       # non-degenerate residual correlation gate

ORIGIN_COLS_MEAN = [
    "lag_1d", "lag_7d", "lag_14d", "lag_28d",
    "roll_mean_7d", "roll_std_7d", "roll_mean_28d",
    "origin_peak_roll_7d", "origin_temp_roll_7d",
]
ORIGIN_COLS_PEAK = [
    "peak_lag_1d", "peak_lag_7d", "peak_lag_14d", "peak_lag_28d",
    "peak_roll_mean_7d", "peak_roll_std_7d", "peak_roll_mean_28d",
    "origin_mean_roll_7d", "origin_temp_roll_7d",
]
TARGET_CALENDAR_COLS = [
    "dow_sin", "dow_cos", "month_sin", "month_cos",
    "doy_sin1", "doy_cos1", "doy_sin2", "doy_cos2",
    "is_weekend", "is_holiday",
]
TARGET_WEATHER_COLS = [
    "temp_mean", "temp_max", "humidity_mean", "cloud_mean",
    "shortwave_mean", "precip_sum", "wind_mean", "cdd_24",
]
TARGET_OP_COLS = [
    "readiness_mult_mean", "readiness_mult_max", "maintenance_share",
]


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y - p) ** 2)))


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(y - p)))


def mape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs((y - p) / np.clip(np.abs(y), 1e-6, None))) * 100.0)


def eval_midterm_metrics(
    y: np.ndarray,
    p: np.ndarray,
    target_dates: pd.DatetimeIndex,
    sigma_val: float,
    persist_rmse: float,
    seasonal_rmse: float,
) -> dict:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    err = y - p  # positive = under-prediction

    cur_rmse = rmse(y, p)
    cur_mae = mae(y, p)
    cur_mape = mape(y, p)
    cur_bias = float(np.mean(err))

    # Top-decile peak-day metrics
    peak_mask = y >= np.quantile(y, 0.90) if len(y) else np.zeros(0, dtype=bool)
    peak_bias = float(np.mean(err[peak_mask])) if peak_mask.any() else 0.0
    peak_mae = float(np.mean(np.abs(err[peak_mask]))) if peak_mask.any() else 0.0

    # Cumulative energy / volume bias (%) across the test window
    # (positive = model under-forecasts total MWh volume; negative = over-forecasts)
    cum_vol_bias_pct = float(np.sum(err) / np.clip(np.sum(y), 1e-6, None) * 100.0)
    wape_pct = float(np.sum(np.abs(err)) / np.clip(np.sum(y), 1e-6, None) * 100.0)

    # Rolling 30-day energy volume MAPE (%) — measures monthly billing/fuel budget accuracy
    if len(y) >= 30:
        s_y = pd.Series(y).rolling(30).sum().dropna().to_numpy()
        s_p = pd.Series(p).rolling(30).sum().dropna().to_numpy()
        window_30d_mape = float(np.mean(np.abs((s_y - s_p) / np.clip(s_y, 1e-6, None))) * 100.0)
    else:
        window_30d_mape = abs(cum_vol_bias_pct)

    # Monthly billing maximum peak error (kW and ZMW at 120 ZMW/kW/month)
    df_m = pd.DataFrame({"y": y, "p": p}, index=pd.to_datetime(target_dates))
    monthly_y_max = df_m.groupby(df_m.index.to_period("M"))["y"].max()
    monthly_p_max = df_m.groupby(df_m.index.to_period("M"))["p"].max()
    monthly_max_err = (monthly_y_max - monthly_p_max).to_numpy()
    monthly_peak_mae_kw = float(np.mean(np.abs(monthly_max_err))) if len(monthly_max_err) else 0.0
    monthly_peak_bias_kw = float(np.mean(monthly_max_err)) if len(monthly_max_err) else 0.0
    monthly_peak_mae_zmw = monthly_peak_mae_kw * DEMAND_CHARGE_ZMW_KW_MONTH

    # 95% Prediction Interval Coverage Probability (PICP) using validation residual sigma
    band = 1.96 * max(sigma_val, 1e-3)
    inside_95 = (y >= (p - band)) & (y <= (p + band))
    picp_95 = float(np.mean(inside_95) * 100.0) if len(y) else 0.0

    # Forecast skill scores vs persistence and vs 7d seasonal naive
    skill_persist = (1.0 - cur_rmse / persist_rmse) * 100.0 if persist_rmse > 0 else 0.0
    skill_seasonal = (1.0 - cur_rmse / seasonal_rmse) * 100.0 if seasonal_rmse > 0 else 0.0

    return {
        "n": int(len(y)),
        "rmse": round(cur_rmse, 2),
        "mae": round(cur_mae, 2),
        "mape": round(cur_mape, 2),
        "wape": round(wape_pct, 2),
        "bias": round(cur_bias, 2),
        "peak_bias": round(peak_bias, 2),
        "peak_mae": round(peak_mae, 2),
        "cum_energy_bias_pct": round(cum_vol_bias_pct, 2),
        "window_30d_mape": round(window_30d_mape, 2),
        "monthly_peak_mae_kw": round(monthly_peak_mae_kw, 2),
        "monthly_peak_bias_kw": round(monthly_peak_bias_kw, 2),
        "monthly_peak_mae_zmw": round(monthly_peak_mae_zmw, 0),
        "picp_95": round(picp_95, 1),
        "interval_halfwidth_kw": round(band, 1),
        "skill_vs_persistence_pct": round(skill_persist, 1),
        "skill_vs_seasonal_pct": round(skill_seasonal, 1),
    }


# --------------------------------------------------------------------------- #
# Daily aggregation & horizon dataset builder
# --------------------------------------------------------------------------- #
def build_daily_base(site: str) -> pd.DataFrame:
    """Aggregate hourly features_<site>.csv to daily resolution with gap awareness."""
    path = PROCESSED / f"features_{site}.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp").sort_index()

    # Map readiness_code (4=routine..1=surge) to physical multiplier (1.00..1.50)
    mult_map = {code: mult for code, (mult, _) in READINESS.items()}
    df["readiness_mult"] = df["readiness_code"].map(mult_map).fillna(1.0)
    df["cdd_24_h"] = np.clip(df["temperature_2m"] - 24.0, 0.0, None)

    grp = df.resample("1D")
    daily = pd.DataFrame(index=grp.size().index)
    daily.index.name = "date"

    # Observed targets: valid only if <= 6 hours were missing/imputed on that day
    imputed_hours = grp["is_target_imputed"].sum()
    daily["imputed_hours"] = imputed_hours
    daily["target_valid"] = (imputed_hours <= 6).astype(int)

    # Feature-continuous load (uses linearly interpolated short gaps) for origin history
    daily["mean_kw_feat"] = grp["load_kw_feature"].mean()
    daily["peak_kw_feat"] = grp["load_kw_feature"].max()

    # True observed targets (NaN if target_valid == 0)
    obs_mean = grp["load_kw"].mean()
    obs_peak = grp["load_kw"].max()
    daily["daily_mean_kw"] = np.where(daily["target_valid"] == 1, obs_mean, np.nan)
    daily["daily_peak_kw"] = np.where(daily["target_valid"] == 1, obs_peak, np.nan)

    # Weather daily summaries
    daily["temp_mean"] = grp["temperature_2m"].mean()
    daily["temp_max"] = grp["temperature_2m"].max()
    daily["humidity_mean"] = grp["relative_humidity_2m"].mean()
    daily["cloud_mean"] = grp["cloud_cover"].mean()
    daily["shortwave_mean"] = grp["shortwave_radiation"].mean()
    daily["precip_sum"] = grp["precipitation"].sum()
    daily["wind_mean"] = grp["wind_speed_10m"].mean()
    daily["cdd_24"] = grp["cdd_24_h"].mean()

    # Calendar & operational daily summaries
    daily["is_holiday"] = (grp["is_holiday"].max() > 0).astype(int)
    daily["is_weekend"] = (daily.index.dayofweek >= 5).astype(int)
    daily["readiness_mult_mean"] = grp["readiness_mult"].mean()
    daily["readiness_mult_max"] = grp["readiness_mult"].max()
    daily["maintenance_share"] = grp["disruption_maintenance"].mean()
    daily["grid_fault_hours"] = grp["grid_fault"].sum()

    # Cyclic calendar features
    dow = daily.index.dayofweek.to_numpy()
    month = daily.index.month.to_numpy()
    doy = daily.index.dayofyear.to_numpy()
    daily["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    daily["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    daily["month_sin"] = np.sin(2 * np.pi * month / 12.0)
    daily["month_cos"] = np.cos(2 * np.pi * month / 12.0)
    daily["doy_sin1"] = np.sin(2 * np.pi * doy / 365.25)
    daily["doy_cos1"] = np.cos(2 * np.pi * doy / 365.25)
    daily["doy_sin2"] = np.sin(4 * np.pi * doy / 365.25)
    daily["doy_cos2"] = np.cos(4 * np.pi * doy / 365.25)

    # Origin load history features (known through day s-1 at origin s)
    for lag in (1, 7, 14, 28):
        daily[f"lag_{lag}d"] = daily["mean_kw_feat"].shift(lag)
        daily[f"peak_lag_{lag}d"] = daily["peak_kw_feat"].shift(lag)

    daily["roll_mean_7d"] = daily["mean_kw_feat"].shift(1).rolling(7).mean()
    daily["roll_std_7d"] = daily["mean_kw_feat"].shift(1).rolling(7).std()
    daily["roll_mean_28d"] = daily["mean_kw_feat"].shift(1).rolling(28).mean()
    daily["origin_peak_roll_7d"] = daily["peak_kw_feat"].shift(1).rolling(7).mean()

    daily["peak_roll_mean_7d"] = daily["peak_kw_feat"].shift(1).rolling(7).mean()
    daily["peak_roll_std_7d"] = daily["peak_kw_feat"].shift(1).rolling(7).std()
    daily["peak_roll_mean_28d"] = daily["peak_kw_feat"].shift(1).rolling(28).mean()
    daily["origin_mean_roll_7d"] = daily["mean_kw_feat"].shift(1).rolling(7).mean()

    daily["origin_temp_roll_7d"] = daily["temp_mean"].shift(1).rolling(7).mean()
    return daily


def inject_midterm_weather_proxy(
    daily: pd.DataFrame, exog: pd.DataFrame, site: str, horizon_days: int
) -> pd.DataFrame:
    """
    Blend actual target weather toward 2024 Fourier seasonal climatology as horizon grows.
    At D=7d skill weight gamma = exp(-7/7) = 0.37; at D=14d gamma = 0.14;
    at D=30..90d gamma -> 0 (pure seasonal climatology + realistic AR(1) weather noise).
    """
    out = exog.copy()
    train_mask = daily.index <= pd.Timestamp("2024-12-31")
    harm_cols = ["doy_sin1", "doy_cos1", "doy_sin2", "doy_cos2"]
    H_train = daily.loc[train_mask, harm_cols].to_numpy()
    H_target = exog[harm_cols].to_numpy()
    valid_h = ~np.isnan(H_target).any(axis=1)

    gamma = float(np.exp(-horizon_days / 7.0))
    rng = np.random.default_rng(stable_site_seed(site) + horizon_days * 31337)
    n = len(out)

    for col in TARGET_WEATHER_COLS:
        y_tr = daily.loc[train_mask, col].to_numpy()
        reg = LinearRegression().fit(H_train, y_tr)
        clim = np.full(n, np.nan)
        clim[valid_h] = reg.predict(H_target[valid_h])
        resid_sd = float(np.std(y_tr - reg.predict(H_train)))

        # Stationary AR(1) weather anomaly noise with phi=0.65
        phi = 0.65
        eps = rng.normal(0.0, resid_sd * np.sqrt(1.0 - phi ** 2), size=n)
        noise = np.empty(n)
        noise[0] = rng.normal(0.0, resid_sd)
        for i in range(1, n):
            noise[i] = phi * noise[i - 1] + eps[i]

        actual = out[col].to_numpy()
        blended = clim + gamma * (actual - clim) + np.sqrt(max(0.0, 1.0 - gamma ** 2)) * 0.35 * noise

        if col in ("humidity_mean", "cloud_mean"):
            blended = np.clip(blended, 0.0, 100.0)
        elif col in ("precip_sum", "shortwave_mean", "wind_mean", "cdd_24"):
            blended = np.clip(blended, 0.0, None)
        out[col] = blended
    return out


def build_midterm_horizon(
    daily: pd.DataFrame, site: str, horizon_days: int, target_col: str
) -> tuple[pd.DataFrame, list[str]]:
    """
    Build one direct mid/long-term dataset indexed by forecast origin day s.
    At origin s, history through s-1 is known; target is day t = s + D - 1.
    """
    shift = horizon_days - 1
    origin_cols = ORIGIN_COLS_MEAN if target_col == "daily_mean_kw" else ORIGIN_COLS_PEAK
    feat_cols = origin_cols + TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS + TARGET_OP_COLS

    target_date = daily.index + pd.Timedelta(days=shift)
    target = daily[target_col].shift(-shift)
    target_valid = daily["target_valid"].shift(-shift).fillna(0).astype(int)

    exog = daily[TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS].shift(-shift)
    exog = inject_midterm_weather_proxy(daily, exog, site, horizon_days)
    ops = daily[TARGET_OP_COLS].shift(-shift)

    # Strictly observed historical series for naive baselines
    last_obs = daily[target_col].ffill()
    off7 = (horizon_days - 1) % 7

    out = pd.DataFrame(index=daily.index)
    out.index.name = "origin_date"
    out["target_date"] = target_date
    out["target"] = target
    out["target_valid"] = (target.notna() & (target_valid == 1)).astype(int)

    for col in origin_cols:
        out[col] = daily[col]
    for col in TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS:
        out[col] = exog[col]
    for col in TARGET_OP_COLS:
        out[col] = ops[col]

    # Baselines using only observations available at or before s-1
    out["persistence"] = last_obs.shift(1)
    out["rolling_persistence_7d"] = last_obs.shift(1).rolling(7, min_periods=1).mean()
    out["seasonal_naive_7d"] = last_obs.shift(7 - off7)

    out = out.loc[out["target_date"] <= daily.index.max()]
    out = out.dropna(subset=feat_cols)
    out["site"] = site
    out["horizon_days"] = horizon_days
    out["target_name"] = target_col
    return out, feat_cols


# --------------------------------------------------------------------------- #
# Models: Statistical SARIMAX/Harmonic, XGBoost, OOF Residuals
# --------------------------------------------------------------------------- #
def fit_predict_sarimax_harmonic(
    frame: pd.DataFrame, tr_mask: np.ndarray, origin_cols: list[str]
) -> np.ndarray:
    """
    Statistical harmonic regression + autoregressive lag baseline (Fourier seasonality
    + weekend/holiday flags + AR(1)/AR(7) origin terms).
    """
    stat_cols = [
        origin_cols[0], origin_cols[1], origin_cols[4],
        "dow_sin", "dow_cos", "doy_sin1", "doy_cos1", "doy_sin2", "doy_cos2",
        "is_weekend", "is_holiday",
    ]
    X = frame[stat_cols].to_numpy(np.float64)
    y = frame["target"].to_numpy(np.float64)
    scaler = StandardScaler().fit(X[tr_mask])
    reg = Ridge(alpha=5.0).fit(scaler.transform(X[tr_mask]), y[tr_mask])
    return reg.predict(scaler.transform(X))


def fit_xgb_midterm(x: np.ndarray, y: np.ndarray, mask: np.ndarray) -> XGBRegressor:
    model = XGBRegressor(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=2.0,
        min_child_weight=5,
        n_jobs=2,
        random_state=42,
    )
    model.fit(x[mask], y[mask])
    return model


def oof_residuals_midterm(
    x: np.ndarray, y: np.ndarray, valid: np.ndarray, td: pd.Series
) -> tuple[np.ndarray, list[dict]]:
    resid = np.full(len(y), np.nan, dtype=np.float64)
    fold_info: list[dict] = []
    for k, (start, end) in enumerate(OOF_FOLDS):
        t_start = pd.Timestamp(start)
        t_end = pd.Timestamp(end)
        tr = (td < t_start).to_numpy() & valid
        fold = ((td >= t_start) & (td <= t_end)).to_numpy()
        if tr.sum() < 45 or fold.sum() == 0:
            continue
        m = fit_xgb_midterm(x, y, tr)
        pred = m.predict(x[fold])
        ok = valid[fold]
        resid[np.where(fold)[0][ok]] = y[fold][ok] - pred[ok]
        fold_info.append({
            "fold": k,
            "n_train": int(tr.sum()),
            "n_fold": int(ok.sum()),
            "rmse": round(rmse(y[fold][ok], pred[ok]), 2) if ok.any() else None,
        })
    return resid, fold_info


def train_one_midterm(
    daily: pd.DataFrame,
    site: str,
    horizon_days: int,
    target_col: str,
    out_dir: Path,
) -> tuple[list[dict], dict]:
    t0 = time.time()
    frame, feat_cols = build_midterm_horizon(daily, site, horizon_days, target_col)
    origin_cols = ORIGIN_COLS_MEAN if target_col == "daily_mean_kw" else ORIGIN_COLS_PEAK

    td = pd.to_datetime(frame["target_date"])
    valid = frame["target_valid"].to_numpy().astype(bool)

    tr = (td <= pd.Timestamp("2024-12-31")).to_numpy() & valid
    va = ((td >= pd.Timestamp("2025-01-01")) & (td <= pd.Timestamp("2025-06-30"))).to_numpy() & valid
    va_fit = ((td >= pd.Timestamp("2025-01-01")) & (td <= pd.Timestamp("2025-03-31"))).to_numpy() & valid
    va_sel = ((td >= pd.Timestamp("2025-04-01")) & (td <= pd.Timestamp("2025-06-30"))).to_numpy() & valid
    te = ((td >= pd.Timestamp("2025-07-01")) & (td <= pd.Timestamp("2025-12-31"))).to_numpy() & valid

    baselines = ["persistence", "rolling_persistence_7d", "seasonal_naive_7d"]
    baseline_ok = frame[baselines].notna().all(axis=1).to_numpy()
    te = te & baseline_ok

    x_raw = frame[feat_cols].to_numpy(np.float64)
    y = frame["target"].to_numpy(np.float64)

    # ---- Stage 1: Regularized XGBoost ------------------------------------
    xgb = fit_xgb_midterm(x_raw, y, tr)
    xgb_pred = xgb.predict(x_raw)

    # ---- Statistical Baseline: SARIMAX / Harmonic Regression -------------
    sarimax_pred = fit_predict_sarimax_harmonic(frame, tr, origin_cols)

    # ---- Ablations -------------------------------------------------------
    ablate_sets = {
        "xgb_no_readiness": [c for c in feat_cols if c not in TARGET_OP_COLS],
        "xgb_no_weather": [c for c in feat_cols if c not in TARGET_WEATHER_COLS],
        "xgb_core": [
            c for c in feat_cols
            if c not in TARGET_OP_COLS and c not in TARGET_WEATHER_COLS
        ],
    }
    ablation_preds: dict[str, np.ndarray] = {}
    for name, cols in ablate_sets.items():
        xa = frame[cols].to_numpy(np.float64)
        ma = fit_xgb_midterm(xa, y, tr)
        ablation_preds[name] = ma.predict(xa)

    # ---- Stage 2: Out-of-fold residual learners --------------------------
    oof, fold_info = oof_residuals_midterm(x_raw, y, valid, td)
    fit_oof_mask = tr & np.isfinite(oof)

    candidates: dict[str, dict] = {}
    preds_all: dict[str, np.ndarray] = {
        "xgb": xgb_pred,
        "sarimax_harmonic": sarimax_pred,
        **{b: frame[b].to_numpy(np.float64) for b in baselines},
        **ablation_preds,
    }

    if fit_oof_mask.sum() >= 60 and va_fit.sum() >= 20 and va_sel.sum() >= 20:
        # Candidate 1: Tabular HistGradientBoosting on OOF residuals
        hgb = HistGradientBoostingRegressor(
            max_iter=80, max_depth=3, learning_rate=0.04,
            l2_regularization=2.0, min_samples_leaf=15, random_state=42,
        )
        hgb.fit(x_raw[fit_oof_mask], oof[fit_oof_mask])
        hgb_res = hgb.predict(x_raw)

        # Candidate 2: Regularized Ridge on OOF residuals
        r_scaler = StandardScaler().fit(x_raw[fit_oof_mask])
        ridge = Ridge(alpha=25.0)
        ridge.fit(r_scaler.transform(x_raw[fit_oof_mask]), oof[fit_oof_mask])
        ridge_res = ridge.predict(r_scaler.transform(x_raw))

        for cname, res_vec, model_obj in (
            ("hgb", hgb_res, hgb),
            ("ridge", ridge_res, (r_scaler, ridge)),
        ):
            denom = float(np.dot(res_vec[va_fit], res_vec[va_fit]))
            alpha = (
                float(np.clip(
                    np.dot(y[va_fit] - xgb_pred[va_fit], res_vec[va_fit]) / denom,
                    0.0, 1.0,
                ))
                if denom > 1e-9 else 0.0
            )
            comb_pred = xgb_pred + alpha * res_vec
            val_sel_rmse = rmse(y[va_sel], comb_pred[va_sel])
            val_corr = (
                float(np.corrcoef(res_vec[va_sel], y[va_sel] - xgb_pred[va_sel])[0, 1])
                if np.std(res_vec[va_sel]) > 1e-6 else 0.0
            )
            preds_all[f"hybrid_{cname}"] = comb_pred
            candidates[cname] = {
                "alpha": round(alpha, 4),
                "val_select_rmse": val_sel_rmse,
                "val_corr": round(val_corr, 4),
                "pred": comb_pred,
                "model_obj": model_obj,
            }

    # ---- Validation Selection Gate (0.5% margin + non-degenerate corr) ---
    xgb_val_sel_rmse = rmse(y[va_sel], xgb_pred[va_sel])
    best_name = "xgb"
    best_pred = xgb_pred
    best_val_rmse = xgb_val_sel_rmse

    for cname, bundle in candidates.items():
        if (
            bundle["val_corr"] >= MIN_VAL_CORR
            and bundle["val_select_rmse"] < xgb_val_sel_rmse * (1.0 - SELECTION_MARGIN)
            and bundle["val_select_rmse"] < best_val_rmse
        ):
            best_name = cname
            best_pred = bundle["pred"]
            best_val_rmse = bundle["val_select_rmse"]

    preds_all["hybrid"] = best_pred

    # ---- Compute Test Metrics --------------------------------------------
    y_test = y[te]
    dates_test = pd.DatetimeIndex(td[te])
    persist_rmse = rmse(y_test, preds_all["persistence"][te])
    seasonal_rmse = rmse(y_test, preds_all["seasonal_naive_7d"][te])

    rows: list[dict] = []
    for mname, p_vec in preds_all.items():
        sigma_val = float(np.std(y[va] - p_vec[va])) if va.any() else 1.0
        m = eval_midterm_metrics(
            y_test, p_vec[te], dates_test, sigma_val, persist_rmse, seasonal_rmse
        )
        m.update({
            "site": site,
            "target": target_col,
            "horizon_days": horizon_days,
            "horizon_label": f"{horizon_days}d",
            "model": mname,
            "selected_stage2": best_name if mname == "hybrid" else mname,
        })
        rows.append(m)

    # Save primary model bundle
    short_t = "mean" if target_col == "daily_mean_kw" else "peak"
    joblib.dump(
        {
            "xgb": xgb,
            "selected": best_name,
            "alpha": candidates[best_name]["alpha"] if best_name in candidates else 0.0,
            "stage2": candidates[best_name]["model_obj"] if best_name in candidates else None,
            "feat_cols": feat_cols,
            "target": target_col,
            "site": site,
            "horizon_days": horizon_days,
        },
        out_dir / f"midterm_{short_t}_{site}_d{horizon_days}.pkl",
    )

    run_info = {
        "site": site,
        "target": target_col,
        "horizon_days": horizon_days,
        "train_days": int(tr.sum()),
        "val_days": int(va.sum()),
        "test_days": int(te.sum()),
        "xgb_val_select_rmse": round(xgb_val_sel_rmse, 2),
        "selected": best_name,
        "candidates": {
            k: {kk: vv for kk, vv in v.items() if kk not in ("pred", "model_obj")}
            for k, v in candidates.items()
        },
        "oof_folds": fold_info,
        "seconds": round(time.time() - t0, 2),
    }
    return rows, run_info


def _predict_bundle(bundle: dict, x_raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    xgb_pred = bundle["xgb"].predict(x_raw)
    selected = bundle.get("selected", "xgb")
    alpha = float(bundle.get("alpha", 0.0))
    stage2 = bundle.get("stage2")
    hybrid = xgb_pred.copy()
    if selected == "hgb" and stage2 is not None:
        hybrid = xgb_pred + alpha * stage2.predict(x_raw)
    elif selected == "ridge" and stage2 is not None:
        r_scaler, ridge = stage2
        hybrid = xgb_pred + alpha * ridge.predict(r_scaler.transform(x_raw))
    return xgb_pred, hybrid, selected


def build_midterm_replays(sites: list[str], horizons: list[int], out_dir: Path) -> None:
    """Write data/v2/midterm_<site>_d<D>.csv from the saved midterm .pkl bundles."""
    replay_dir = Path(__file__).resolve().parents[1] / "data" / "v2"
    replay_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for site in sites:
        daily = build_daily_base(site)
        for d in horizons:
            f_mean, cols_mean = build_midterm_horizon(daily, site, d, "daily_mean_kw")
            f_peak, cols_peak = build_midterm_horizon(daily, site, d, "daily_peak_kw")

            b_mean = joblib.load(out_dir / f"midterm_mean_{site}_d{d}.pkl")
            b_peak = joblib.load(out_dir / f"midterm_peak_{site}_d{d}.pkl")

            td = pd.to_datetime(f_mean["target_date"])
            valid = f_mean["target_valid"].to_numpy().astype(bool)
            va = ((td >= pd.Timestamp("2025-01-01")) & (td <= pd.Timestamp("2025-06-30"))).to_numpy() & valid
            te = ((td >= pd.Timestamp("2025-07-01")) & (td <= pd.Timestamp("2025-12-31"))).to_numpy() & valid

            xm = f_mean[cols_mean].to_numpy(np.float64)
            xp = f_peak[cols_peak].to_numpy(np.float64)
            ym = f_mean["target"].to_numpy(np.float64)
            yp = f_peak["target"].to_numpy(np.float64)

            xgb_m, hyb_m, sel_m = _predict_bundle(b_mean, xm)
            xgb_p, hyb_p, sel_p = _predict_bundle(b_peak, xp)

            sig_m = float(np.std(ym[va] - hyb_m[va])) if va.any() else 50.0
            sig_p = float(np.std(yp[va] - hyb_p[va])) if va.any() else 80.0
            band_m = 1.96 * sig_m
            band_p = 1.96 * sig_p

            dates_te = pd.to_datetime(f_mean["target_date"].to_numpy()[te])
            base_at = daily.reindex(dates_te)

            rep = pd.DataFrame({
                "date": dates_te.strftime("%Y-%m-%d"),
                "actual_mean_kw": np.round(ym[te], 1),
                "xgb_mean_kw": np.round(xgb_m[te], 1),
                "hybrid_mean_kw": np.round(hyb_m[te], 1),
                "lower_mean_kw": np.round(hyb_m[te] - band_m, 1),
                "upper_mean_kw": np.round(hyb_m[te] + band_m, 1),
                "selected_mean_model": sel_m,
                "actual_energy_mwh": np.round(ym[te] * 24.0 / 1000.0, 2),
                "hybrid_energy_mwh": np.round(hyb_m[te] * 24.0 / 1000.0, 2),
                "actual_peak_kw": np.round(yp[te], 1),
                "xgb_peak_kw": np.round(xgb_p[te], 1),
                "hybrid_peak_kw": np.round(hyb_p[te], 1),
                "lower_peak_kw": np.round(hyb_p[te] - band_p, 1),
                "upper_peak_kw": np.round(hyb_p[te] + band_p, 1),
                "selected_peak_model": sel_p,
                "temp_mean_c": np.round(base_at["temp_mean"].to_numpy(), 1),
                "temp_max_c": np.round(base_at["temp_max"].to_numpy(), 1),
                "humidity_pct": np.round(base_at["humidity_mean"].to_numpy(), 1),
                "readiness_mult_max": np.round(base_at["readiness_mult_max"].to_numpy(), 2),
                "is_holiday": base_at["is_holiday"].fillna(0).astype(int).to_numpy(),
                "is_weekend": base_at["is_weekend"].fillna(0).astype(int).to_numpy(),
            })
            rep.to_csv(replay_dir / f"midterm_{site}_d{d}.csv", index=False)
            count += 1
    print(f"Wrote {count} midterm replay CSVs to {replay_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sites", nargs="+", default=SITES)
    ap.add_argument("--horizons", nargs="+", type=int, default=MIDTERM_HORIZONS)
    ap.add_argument("--targets", nargs="+", default=TARGETS)
    ap.add_argument("--out-dir", type=Path, default=MODELS)
    ap.add_argument("--replay-only", action="store_true", help="build data/v2/midterm_*.csv from saved .pkl bundles")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.replay_only:
        build_midterm_replays(args.sites, args.horizons, args.out_dir)
        return

    print(
        f"v2 mid/long-term training | sites={args.sites} "
        f"horizons_days={args.horizons} targets={args.targets}"
    )

    all_rows: list[dict] = []
    all_runs: list[dict] = []

    for site in args.sites:
        daily = build_daily_base(site)
        for target_col in args.targets:
            for d in args.horizons:
                rows, run_info = train_one_midterm(daily, site, d, target_col, args.out_dir)
                all_rows.extend(rows)
                all_runs.append(run_info)

                xgb_r = next(r for r in rows if r["model"] == "xgb")
                hyb_r = next(r for r in rows if r["model"] == "hybrid")
                sar_r = next(r for r in rows if r["model"] == "sarimax_harmonic")
                per_r = next(r for r in rows if r["model"] == "persistence")
                print(
                    f"{site:11s} {target_col:13s} D={d:2d}d n={hyb_r['n']:3d} | "
                    f"HYB {hyb_r['rmse']:5.1f} kW ({hyb_r['mape']:4.2f}%, 30dVol {hyb_r['window_30d_mape']:4.2f}%) | "
                    f"XGB {xgb_r['rmse']:5.1f} | SARIMAX {sar_r['rmse']:5.1f} | "
                    f"Persist {per_r['rmse']:5.1f} | sel={run_info['selected']:5s}",
                    flush=True,
                )

    df = pd.DataFrame(all_rows)
    df.to_csv(args.out_dir / "metrics_midterm.csv", index=False)

    # Cross-site summary table by target, horizon_days, and model
    summary_cols = [
        "rmse", "mae", "mape", "wape", "bias", "peak_bias", "peak_mae",
        "cum_energy_bias_pct", "window_30d_mape", "monthly_peak_mae_kw",
        "monthly_peak_mae_zmw", "picp_95", "skill_vs_persistence_pct", "skill_vs_seasonal_pct",
    ]
    summary = (
        df.groupby(["target", "horizon_days", "model"])[summary_cols]
        .mean()
        .round(2)
        .reset_index()
    )
    summary.to_csv(args.out_dir / "metrics_midterm_summary.csv", index=False)

    with open(args.out_dir / "midterm_manifest.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "horizons_days": args.horizons,
                "targets": args.targets,
                "runs": all_runs,
            },
            f,
            indent=2,
        )

    print(f"\nWrote {args.out_dir / 'metrics_midterm.csv'}")
    print(f"Wrote {args.out_dir / 'metrics_midterm_summary.csv'}")
    build_midterm_replays(args.sites, args.horizons, args.out_dir)


if __name__ == "__main__":
    main()
