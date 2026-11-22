"""
Sprint 1 preprocessing pipeline (proposal section 3.2.1).

For each facility CSV:
  1. Handle missing telemetry: linear interpolation for short gaps,
     historical forward-fill for extended outages + outage mask indicators
  2. Cyclic sine/cosine encoding of hour-of-day, day-of-week, month
     (avoids the artificial hour 23 -> 0 boundary discontinuity)
  3. Lag features: t-1, t-2, t-24 (1 day), t-168 (1 week)
  4. Rolling statistics: 24h moving average and standard deviation

NOTE: MinMax scaling is deliberately NOT applied here. It must be fit on
the training split only, inside the model-training script, to prevent
data leakage across the temporal cross-validation boundary.

Output: prototype/data/processed/features_<site>.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
PROCESSED = DATA / "processed"

# A gap longer than this many hours is treated as an extended outage and
# forward-filled from the same hour of the previous day(s) instead of
# linearly interpolated across the discontinuity.
LONG_GAP_HOURS = 6


def add_cyclic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclic sine/cosine temporal encodings (proposal 3.2.1)."""
    h = df.index.hour
    dow = df.index.dayofweek
    m = df.index.month
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    df["dow_sin"], df["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    df["month_sin"], df["month_cos"] = np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12)
    return df


def add_lag_and_rolling(df: pd.DataFrame) -> pd.DataFrame:
    """Lag features and rolling statistics expose short-term momentum and
    weekly seasonality to the predictive models (proposal 3.2.1)."""
    for lag in (1, 2, 24, 168):
        df[f"load_lag_{lag}h"] = df["load_kw"].shift(lag)
    df["load_roll_mean_24h"] = df["load_kw"].shift(1).rolling(24).mean()
    df["load_roll_std_24h"] = df["load_kw"].shift(1).rolling(24).std()
    return df


def preprocess_site(site: str) -> pd.DataFrame:
    raw_path = PROCESSED / f"facility_load_{site}.csv"
    df = pd.read_csv(raw_path, parse_dates=["timestamp"], index_col="timestamp")

    # ---- 1. missing telemetry handling ------------------------------------
    # mask BEFORE interpolation so models can be told where data was imputed
    df["is_imputed"] = df["load_kw"].isna().astype(int)

    gaps = df["load_kw"].isna()
    # linear interpolation for short gaps
    df["load_kw"] = df["load_kw"].interpolate(method="linear", limit=LONG_GAP_HOURS)
    # extended outages: forward-fill from the same hour one week earlier
    still_missing = df["load_kw"].isna()
    df.loc[still_missing, "load_kw"] = df["load_kw"].shift(168)[still_missing]
    # anything left (e.g. start of series): zero-fill then flag
    df["load_kw"] = df["load_kw"].fillna(df["load_kw"].median())

    # one-hot disruption indicators (faults/maintenance are informative)
    for t in ("fault_trip", "maintenance", "comms_dropout"):
        df[f"disruption_{t}"] = (df["disruption_type"] == t).astype(int)
    df = df.drop(columns=["disruption_type"])

    # ---- 2-4. features ------------------------------------------------------
    df = add_cyclic_features(df)
    df = add_lag_and_rolling(df)

    # readiness as ordinal numeric feature (4 routine .. 1 surge)
    df["readiness_code"] = df["readiness_code"].astype(int)

    out_path = PROCESSED / f"features_{site}.csv"
    df.to_csv(out_path)
    print(
        f"{site:11s} rows={len(df)}  imputed={int(df['is_imputed'].sum())}h  "
        f"features={df.shape[1]}  -> {out_path.name}"
    )
    return df


def main() -> None:
    sites = sorted(p.stem.replace("facility_load_", "")
                   for p in PROCESSED.glob("facility_load_*.csv"))
    print(f"Preprocessing {len(sites)} sites: {', '.join(sites)}\n")
    for site in sites:
        preprocess_site(site)


if __name__ == "__main__":
    main()