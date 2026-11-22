"""
v2 preprocessing: gap-aware target handling, Zambian calendar features and
load-history features for direct multi-horizon forecasting.

Key differences from v1:
  * load_kw is NOT overwritten with imputed values. The observed target keeps
    its NaNs and is marked by is_target_imputed; the horizon builder excludes
    those targets from training loss and evaluation.
  * load_kw_feature is a continuous series used only for lag/rolling features:
    short gaps are linearly interpolated, longer gaps are carried forward so
    the feature sequence remains usable.
  * is_holiday and is_weekend are explicit features.
  * disruption one-hots are kept, but only scheduled maintenance is eligible as
    a forecast-time feature; fault/dropout flags are diagnostic.

Output: data/synthetic_v2/features_<site>.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from v2_config import PROCESSED, SITES
from v2_holidays import holiday_mask

SHORT_GAP_HOURS = 6


def add_cyclic_features(df: pd.DataFrame) -> pd.DataFrame:
    h = df.index.hour
    dow = df.index.dayofweek
    m = df.index.month
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    df["dow_sin"], df["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    df["month_sin"], df["month_cos"] = np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12)
    return df


def add_calendar_flags(df: pd.DataFrame) -> pd.DataFrame:
    df["is_holiday"] = holiday_mask(df.index).astype(int)
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(int)
    return df


def add_lag_and_rolling(df: pd.DataFrame) -> pd.DataFrame:
    for lag in (1, 2, 24, 168):
        df[f"load_lag_{lag}h"] = df["load_kw_feature"].shift(lag)
    df["load_roll_mean_24h"] = df["load_kw_feature"].shift(1).rolling(24).mean()
    df["load_roll_std_24h"] = df["load_kw_feature"].shift(1).rolling(24).std()
    return df


def preprocess_site(site: str) -> pd.DataFrame:
    raw_path = PROCESSED / f"facility_load_{site}.csv"
    df = pd.read_csv(raw_path, parse_dates=["timestamp"], index_col="timestamp").sort_index()

    # ---- target validity and feature-only imputation ------------------------
    df["is_target_imputed"] = df["load_kw"].isna().astype(int)
    feature = df["load_kw"].interpolate(
        method="linear", limit=SHORT_GAP_HOURS, limit_direction="both"
    )
    # Long gaps: carry the last observed level for lag/rolling continuity only.
    feature = feature.ffill().bfill()
    df["load_kw_feature"] = feature

    # ---- disruption indicators --------------------------------------------
    for t in ("fault_trip", "maintenance", "comms_dropout"):
        df[f"disruption_{t}"] = (df["disruption_type"] == t).astype(int)

    # ---- calendar and load-history features --------------------------------
    df = add_calendar_flags(df)
    df = add_cyclic_features(df)
    df = add_lag_and_rolling(df)
    df["readiness_code"] = df["readiness_code"].astype(int)

    # Diagnostic generator columns are not model inputs.
    df = df.drop(columns=["net_load_kw", "gross_load_kw", "pv_kw"], errors="ignore")

    out_path = PROCESSED / f"features_{site}.csv"
    df.to_csv(out_path)

    print(
        f"{site:11s} rows={len(df):5d} missing_target={int(df['is_target_imputed'].sum()):5d}h "
        f"({df['is_target_imputed'].mean() * 100:4.2f}%) holidays={int(df['is_holiday'].sum()):4d}h "
        f"features={df.shape[1]:3d} -> {out_path.name}",
        flush=True,
    )
    return df


def main() -> None:
    print(f"Preprocessing v2 sites from {PROCESSED}\n")
    for site in SITES:
        preprocess_site(site)


if __name__ == "__main__":
    main()
