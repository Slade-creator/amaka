"""
Generate v2 synthetic hourly electricity load for Zambian military facilities
(2024-01-01 .. 2025-12-31), driven by real Open-Meteo weather.

What changed from v1 (src/generate_load.py):
  * process-stable site seeds (no salted Python hash());
  * per-site HVAC and lighting sized from floor area, occupancy from headcount,
    and a small humidity/latent-load term;
  * readiness multipliers applied to GROSS load before rooftop PV netting;
  * readiness events anchored to 04:00-06:00 as documented;
  * realistic planned-maintenance rate, plus occasional multi-day feeder faults
    that exercise the extended-gap branch;
  * complete Zambian public-holiday calendar with observed Mondays;
  * output to data/synthetic_v2, leaving data/processed (v1) intact.

Output: data/synthetic_v2/facility_load_<site>.csv
        data/synthetic_v2/generation_manifest.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from v2_config import (
    BASE_SEED, GRID_FAULT, HVAC, PROCESSED, RAW, READINESS, READINESS_P,
    SITE_CONFIGS, SITES, VERSION, stable_site_seed,
)
from v2_holidays import holiday_mask, holiday_set


def hourly_range(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, f"{end} 23:00", freq="h")


def double_hump(hour: np.ndarray) -> np.ndarray:
    """Daily occupancy shape normalised to mean 1."""
    morning = np.exp(-0.5 * ((hour - 8.0) / 2.0) ** 2)
    midday = 0.55 * np.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2)
    evening = np.exp(-0.5 * ((hour - 19.0) / 2.5) ** 2)
    shape = 0.18 + morning + midday + evening
    return shape / shape.mean()


def gross_load(df: pd.DataFrame, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    """Physically-motivated gross facility load in kW before PV and outages."""
    hour = df.index.hour.to_numpy(float)
    dow = df.index.dayofweek.to_numpy()
    temp = df["temperature_2m"].to_numpy(float)
    rh = df["relative_humidity_2m"].to_numpy(float)
    swr = df["shortwave_radiation"].to_numpy(float)

    occ = double_hump(hour)
    occ_c = occ - 1.0

    # Fixed infrastructure plus headcount-driven activity.
    activity = cfg["base_load_kw"] * (1.0 + 0.15 * occ_c)
    activity = activity + cfg["headcount"] * cfg["occupancy_kw_per_person"] * occ

    # Reduced admin/training activity on weekends and public holidays. Critical
    # HVAC/lighting below is not reduced.
    weekend = dow >= 5
    holidays = holiday_mask(df.index)
    activity = np.where(weekend, activity * cfg["weekend_factor"], activity)
    activity = np.where(holidays, activity * cfg["holiday_factor"], activity)

    hvac_kw_per_c = cfg["floor_area_m2"] * cfg["hvac_w_m2_c"] / 1000.0
    cooling = np.maximum(0.0, temp - HVAC["cooling_threshold_c"]) * hvac_kw_per_c
    heating = (
        np.maximum(0.0, HVAC["heating_threshold_c"] - temp)
        * hvac_kw_per_c
        * cfg["heating_ratio"]
    )
    humidity = (
        np.maximum(0.0, rh - HVAC["humidity_threshold_pct"])
        * cfg["floor_area_m2"]
        * cfg["humidity_kw_per_m2_pct"]
    )

    dark = np.clip(1.0 - swr / 400.0, 0.0, 1.0)
    lighting_kw = cfg["floor_area_m2"] * cfg["lighting_w_m2"] / 1000.0
    lighting = dark * lighting_kw * (1.0 + 0.25 * occ_c)

    load = activity + cooling + heating + humidity + lighting

    # Consumption noise: 1.5% Gaussian plus a slow AR(1) drift.
    noise = rng.normal(0.0, 0.015, size=len(df))
    drift = np.zeros(len(df))
    for i in range(1, len(df)):
        drift[i] = 0.98 * drift[i - 1] + rng.normal(0.0, 0.003)
    load = load * (1.0 + noise + drift)
    return np.clip(load, 0.0, None)


def rooftop_pv(df: pd.DataFrame, cfg: dict) -> np.ndarray:
    """Rooftop PV output in kW from real solar irradiance."""
    swr = df["shortwave_radiation"].to_numpy(float)
    pv = swr / 1000.0 * cfg["pv_kwp"] * cfg["pv_performance_ratio"]
    return np.clip(pv, 0.0, cfg["pv_kwp"])


def _next_morning_start(i: int, rng: np.random.Generator) -> int:
    """Next 04:00-06:00 start at or after index i (hourly series starting 00:00)."""
    hour = i % 24
    if hour < 4:
        delta = 4 - hour + int(rng.integers(0, 3))
    elif hour <= 6:
        delta = int(rng.integers(0, 3))
    else:
        delta = 24 - hour + 4 + int(rng.integers(0, 3))
    return i + delta


def simulate_readiness(n: int, rng: np.random.Generator) -> np.ndarray:
    """Readiness codes 4..1 with morning-anchored, multi-hour events."""
    codes = np.full(n, 4, dtype=np.int8)
    i = 0
    while i < n:
        roll = rng.random()
        if roll < READINESS_P[3]:
            dur, code = int(rng.integers(12, 49)), 3
        elif roll < READINESS_P[3] + READINESS_P[2]:
            dur, code = int(rng.integers(6, 25)), 2
        elif roll < READINESS_P[3] + READINESS_P[2] + READINESS_P[1]:
            dur, code = int(rng.integers(8, 73)), 1
        else:
            i += 1
            continue

        start = _next_morning_start(i, rng)
        if start >= n:
            break
        end = min(n, start + dur)
        codes[start:end] = np.minimum(codes[start:end], code)
        i = max(i + 1, end)
    return codes


def simulate_disruptions(
    n: int, hours: np.ndarray, cfg: dict, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """
    Internal disruptions on the base's own distribution system:
      * feeder faults, mostly 1-3 h, occasionally 8-24 h (major fault);
      * planned maintenance, daytime 2-6 h;
      * random meter/comms dropouts.

    These are telemetry gaps, not load-shedding events; defence sites are
    assumed exempt from scheduled ZESCO load shedding.
    """
    fault = np.zeros(n, dtype=bool)
    maint = np.zeros(n, dtype=bool)

    i = 0
    while i < n:
        if rng.random() < cfg["fault_p_hour"]:
            if rng.random() < cfg["major_fault_prob"]:
                dur = int(rng.integers(8, 25))
            else:
                dur = int(rng.integers(1, 4))
            fault[i:i + dur] = True
            i += dur + int(rng.integers(6, 48))
        else:
            i += 1

    i = 0
    while i < n:
        if rng.random() < cfg["maintenance_p_hour"] and 8 <= hours[i] <= 15:
            dur = int(rng.integers(2, 7))
            maint[i:i + dur] = True
            i += dur + int(rng.integers(24, 168))
        else:
            i += 1
    return fault, maint


def simulate_grid_faults(n: int, rng: np.random.Generator) -> np.ndarray:
    """
    Unscheduled ZESCO-side faults. Returns event_hour where 0 = on grid and
    1..duration = hours since the generator pickup. These do NOT create missing
    telemetry: the backup generator carries the load for the whole event.
    """
    event_hour = np.zeros(n, dtype=np.int16)
    i = 0
    while i < n:
        if rng.random() < GRID_FAULT["p_hour"]:
            if rng.random() < GRID_FAULT["long_prob"]:
                dur = int(rng.integers(8, GRID_FAULT["long_duration_max"] + 1))
            else:
                dur = int(rng.integers(GRID_FAULT["duration_min"], GRID_FAULT["duration_max"] + 1))
            end = min(n, i + dur)
            event_hour[i:end] = np.arange(1, end - i + 1, dtype=np.int16)
            i = end + int(rng.integers(GRID_FAULT["cooldown_h_min"], GRID_FAULT["cooldown_h_max"]))
        else:
            i += 1
    return event_hour


def generate_site(site: str, cfg: dict) -> tuple[pd.DataFrame, dict]:
    seed = stable_site_seed(site)
    rng = np.random.default_rng(seed)

    weather_file = RAW / f"weather_{site}.csv"
    if not weather_file.exists() and site == "tug_argan":
        # Same Open-Meteo grid cell as Peter Zuze (documented in fetch_weather).
        weather_file = RAW / "weather_peter_zuze.csv"
    wx = pd.read_csv(weather_file, parse_dates=["timestamp"]).set_index("timestamp").sort_index()

    idx = hourly_range("2024-01-01", "2025-12-31")
    df = wx.reindex(idx)
    if df["temperature_2m"].isna().any():
        raise ValueError(f"{site}: weather gaps found after reindex")

    gross = gross_load(df, cfg, rng)
    pv = rooftop_pv(df, cfg)

    codes = simulate_readiness(len(df), rng)
    mult = np.array([READINESS[c][0] for c in codes])
    net_load = np.clip(gross * mult - pv, 0.0, None)

    # Unscheduled ZESCO-side fault: generator pickup surge, then a small
    # sustained generator-efficiency penalty. Load remains observed.
    event_hour = simulate_grid_faults(len(df), rng)
    grid_fault = event_hour > 0
    gen_factor = np.where(
        event_hour == 1,
        GRID_FAULT["start_factor"],
        np.where(event_hour > 1, GRID_FAULT["sustain_factor"], 1.0),
    )
    net_load = np.clip(net_load * gen_factor, 0.0, None)

    hours = df.index.hour.to_numpy()
    fault, maint = simulate_disruptions(len(df), hours, cfg, rng)
    dropout = rng.random(len(df)) < cfg["comms_dropout_p_hour"]
    outage = fault | maint | dropout
    observed_load = np.where(outage, np.nan, net_load)

    # Preserve the most severe/telemetry-relevant cause where events overlap.
    dtype = np.full(len(df), "none", dtype=object)
    dtype[dropout] = "comms_dropout"
    dtype[maint] = "maintenance"
    dtype[fault] = "fault_trip"

    out = pd.DataFrame(
        {
            "load_kw": np.round(observed_load, 1),
            "net_load_kw": np.round(net_load, 1),
            "gross_load_kw": np.round(gross, 1),
            "pv_kw": np.round(pv, 1),
            "readiness_code": codes,
            "readiness_label": [READINESS[c][1] for c in codes],
            "disruption_type": dtype,
            "grid_fault": grid_fault.astype(int),
            "generator_backup": grid_fault.astype(int),
            "temperature_2m": df["temperature_2m"].round(2).to_numpy(),
            "relative_humidity_2m": df["relative_humidity_2m"].round(1).to_numpy(),
            "precipitation": df["precipitation"].round(2).to_numpy(),
            "cloud_cover": df["cloud_cover"].astype("Int64"),
            "shortwave_radiation": df["shortwave_radiation"].round(1).to_numpy(),
            "wind_speed_10m": df["wind_speed_10m"].round(1).to_numpy(),
        },
        index=df.index,
    )
    out.index.name = "timestamp"

    out_path = PROCESSED / f"facility_load_{site}.csv"
    out.to_csv(out_path)

    valid = out["load_kw"].dropna()
    mask = out["load_kw"].isna()
    runs = np.diff(np.concatenate(([0], mask.astype(int), [0])))
    starts, ends = np.where(runs == 1)[0], np.where(runs == -1)[0]
    max_gap = int((ends - starts).max()) if len(starts) else 0

    summary = {
        "label": cfg["label"],
        "location": cfg["location"],
        "type": cfg["type"],
        "lat": cfg["lat"],
        "lon": cfg["lon"],
        "seed": seed,
        "rows": int(len(out)),
        "mean_load_kw": round(float(valid.mean()), 1),
        "peak_load_kw": round(float(valid.max()), 1),
        "missing_hours": int(mask.sum()),
        "missing_pct": round(float(mask.mean() * 100), 2),
        "max_gap_h": max_gap,
        "fault_events": int((np.diff(np.concatenate(([0], fault.astype(int), [0]))) == 1).sum()),
        "maintenance_events": int((np.diff(np.concatenate(([0], maint.astype(int), [0]))) == 1).sum()),
        "major_fault_hours": int((fault & (np.convolve(fault.astype(int), np.ones(8, dtype=int), mode="same") >= 8)).sum()),
        "grid_fault_events": int((np.diff(np.concatenate(([0], grid_fault.astype(int), [0]))) == 1).sum()),
        "grid_fault_hours": int(grid_fault.sum()),
        "generator_backup_hours": int(grid_fault.sum()),
        "dropout_hours": int(dropout.sum()),
        "holiday_hours": int(holiday_mask(out.index).sum()),
        "readiness_counts": {int(k): int(v) for k, v in out["readiness_code"].value_counts().sort_index().items()},
        "config": {k: cfg[k] for k in (
            "base_load_kw", "pv_kwp", "headcount", "floor_area_m2",
            "hvac_w_m2_c", "lighting_w_m2", "occupancy_kw_per_person",
            "fault_p_hour", "maintenance_p_hour", "major_fault_prob",
            "comms_dropout_p_hour",
        )},
    }

    print(
        f"{site:11s} {cfg['label']:34s} rows={len(out)} "
        f"mean={summary['mean_load_kw']:7.0f} kW peak={summary['peak_load_kw']:7.0f} kW "
        f"missing={summary['missing_pct']:4.2f}% max_gap={max_gap:2d}h "
        f"fault_events={summary['fault_events']:3d} maint_events={summary['maintenance_events']:3d} "
        f"grid_faults={summary['grid_fault_events']:2d}",
        flush=True,
    )
    return out, summary


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    print(f"Generating v{VERSION} synthetic facility loads for {len(SITES)} sites...")

    summaries = {}
    frames = {}
    for site in SITES:
        frames[site], summaries[site] = generate_site(site, SITE_CONFIGS[site])

    manifest = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_seed": BASE_SEED,
        "weather_source": "Open-Meteo archive API, timezone Africa/Lusaka",
        "sites": summaries,
        "holidays": sorted(d.isoformat() for d in holiday_set(2024, 2025)),
        "notes": [
            "load_kw is hourly net facility load; NaN means missing telemetry",
            "net_load_kw/gross_load_kw/pv_kw are diagnostics, not model features",
            "readiness is synthetic and applied to gross load before PV netting",
            "all six sites are security-wing facilities assumed exempt from SCHEDULED ZESCO load shedding",
            "disruption_type labels are internal telemetry gaps; grid_fault is an unscheduled ZESCO-side fault",
            "grid faults use generator backup: +6% restart surge, +2% sustained efficiency penalty, load remains observed",
            "weather forecast error is injected later, in the horizon builder",
        ],
    }
    with open(PROCESSED / "generation_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nSaved {len(frames)} CSVs + generation_manifest.json to {PROCESSED}")
    print("\nDisruption summary:")
    for site, df in frames.items():
        counts = df["disruption_type"].value_counts().to_dict()
        print(f"  {site:11s} " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
