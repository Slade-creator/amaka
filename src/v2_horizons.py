"""
Direct multi-horizon dataset builder for v2.

Definition of a forecast instance
---------------------------------
At origin row s, the model knows load history through s-1 (all load_lag_* and
rolling features). The target is load at t = s + h - 1, i.e. exactly h hours
after the last observed hour s-1.

Load-history features come from row s unchanged. Calendar, weather, readiness
and scheduled-maintenance features come from the TARGET time (shifted by
-(h-1)). Weather is passed through a reproducible forecast-error proxy because
a real deployment would use a weather forecast, not the archived observation.

Baselines are computed from the last observed (never model-imputed) load:
  * persistence: last observed load before the origin
  * seasonal_naive_24: last observed load at the target's hour of day
  * seasonal_naive_168: last observed load at the target's hour of week
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from v2_config import (
    HORIZONS, PROCESSED, SITES, WEATHER_ERROR, WEATHER_ERROR_AR1_PHI,
    stable_site_seed,
)

LOAD_HISTORY_COLS = [
    "load_lag_1h", "load_lag_2h", "load_lag_24h", "load_lag_168h",
    "load_roll_mean_24h", "load_roll_std_24h",
]
TARGET_CALENDAR_COLS = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "is_holiday", "is_weekend",
]
TARGET_WEATHER_COLS = [
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "cloud_cover", "shortwave_radiation", "wind_speed_10m",
]
TARGET_OPERATION_COLS = ["readiness_code", "disruption_maintenance"]
FEATURE_COLS = (
    LOAD_HISTORY_COLS + TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS
    + TARGET_OPERATION_COLS
)
DIAGNOSTIC_COLS = [
    "target", "target_imputed", "target_valid", "grid_fault",
    "persistence", "seasonal_naive_24", "seasonal_naive_168",
]


@dataclass(frozen=True)
class HorizonData:
    site: str
    horizon: int
    frame: pd.DataFrame


def ar1_noise(rng: np.random.Generator, n: int, sd: float, phi: float) -> np.ndarray:
    """Stationary AR(1) noise with marginal standard deviation sd."""
    eps = rng.normal(0.0, sd * np.sqrt(1.0 - phi ** 2), size=n)
    out = np.empty(n)
    out[0] = rng.normal(0.0, sd)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + eps[i]
    return out


def horizon_seed(site: str, horizon: int) -> int:
    return stable_site_seed(site) + horizon * 10007


def inject_weather_error(
    exog: pd.DataFrame, site: str, horizon: int
) -> pd.DataFrame:
    """Replace target-time weather observations with a forecast-error proxy."""
    out = exog.copy()
    rng = np.random.default_rng(horizon_seed(site, horizon))
    n = len(out)
    for col, (base_sd, slope) in WEATHER_ERROR.items():
        sd = base_sd + slope * horizon
        noise = ar1_noise(rng, n, sd, WEATHER_ERROR_AR1_PHI)
        if col == "relative_humidity_2m":
            out[col] = np.clip(out[col].to_numpy() + noise, 0.0, 100.0)
        elif col == "cloud_cover":
            out[col] = np.clip(out[col].to_numpy() + noise, 0.0, 100.0)
        elif col == "precipitation":
            out[col] = np.clip(out[col].to_numpy() + noise, 0.0, None)
        elif col == "shortwave_radiation":
            actual = out[col].to_numpy()
            out[col] = np.where(actual > 0.0, np.clip(actual + noise, 0.0, None), 0.0)
        elif col == "wind_speed_10m":
            out[col] = np.clip(out[col].to_numpy() + noise, 0.0, None)
        else:
            out[col] = out[col].to_numpy() + noise
    return out


def build_horizon(df: pd.DataFrame, site: str, horizon: int) -> pd.DataFrame:
    """Build one direct-horizon frame indexed by forecast origin."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    shift = horizon - 1

    target_time = df.index + pd.Timedelta(hours=shift)
    target = df["load_kw"].shift(-shift)
    target_imputed = df["is_target_imputed"].shift(-shift).fillna(1).astype(int)
    target_valid = (target.notna() & (target_imputed == 0)).astype(int)
    grid_fault = df["grid_fault"].shift(-shift).fillna(0).astype(int)

    # Target-time features. Weather is noisy: a forecast proxy, not the future
    # observed value. Calendar and readiness/maintenance are known schedules.
    exog = df[TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS].shift(-shift)
    exog = inject_weather_error(exog, site, horizon)
    readiness = df["readiness_code"].shift(-shift)
    maintenance = df["disruption_maintenance"].shift(-shift)

    # Baselines. Persistence uses the last known load; seasonal-naive uses the
    # exact observation 1 day / 1 week before the target and is left NaN if that
    # observation is missing (the evaluator uses a common valid mask).
    last_observed = df["load_kw"].ffill()
    off24 = (horizon - 1) % 24
    off168 = (horizon - 1) % 168

    out = pd.DataFrame(index=df.index)
    out.index.name = "origin_time"
    out["target_time"] = target_time
    out["target"] = target
    out["target_imputed"] = target_imputed
    out["target_valid"] = target_valid
    out["grid_fault"] = grid_fault

    for col in LOAD_HISTORY_COLS:
        out[col] = df[col]
    for col in TARGET_CALENDAR_COLS + TARGET_WEATHER_COLS:
        out[col] = exog[col]
    out["readiness_code"] = readiness
    out["disruption_maintenance"] = maintenance

    out["persistence"] = last_observed.shift(1)
    out["seasonal_naive_24"] = df["load_kw"].shift(24 - off24)
    out["seasonal_naive_168"] = df["load_kw"].shift(168 - off168)

    # Keep only rows whose target time exists in the data, then drop warm-up
    # rows where any model feature is unavailable.
    out = out.loc[out["target_time"] <= df.index.max()]
    out = out.dropna(subset=FEATURE_COLS)

    # Metadata columns for splitting/auditing. Not model features.
    out["site"] = site
    out["horizon"] = horizon
    return out


def load_base(site: str) -> pd.DataFrame:
    path = PROCESSED / f"features_{site}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing; run src/v2_preprocess.py after src/v2_generate_load.py"
        )
    return (
        pd.read_csv(path, parse_dates=["timestamp"])
        .set_index("timestamp")
        .sort_index()
    )


def build_all(sites: list[str] | None = None, horizons: list[int] | None = None) -> dict[tuple[str, int], pd.DataFrame]:
    sites = sites or SITES
    horizons = horizons or HORIZONS
    out: dict[tuple[str, int], pd.DataFrame] = {}
    for site in sites:
        base = load_base(site)
        for h in horizons:
            out[(site, h)] = build_horizon(base, site, h)
    return out


if __name__ == "__main__":
    for (site, h), frame in build_all().items():
        valid = frame[frame["target_valid"] == 1]
        print(
            f"{site:11s} h={h:2d} rows={len(frame):5d} valid={len(valid):5d} "
            f"target=[{valid['target'].min():.0f},{valid['target'].max():.0f}] "
            f"features={len(FEATURE_COLS)}"
        )
