"""
Generate synthetic hourly electricity load for Zambian military facilities
(2024-01-01 .. 2025-12-31), driven by REAL weather from Open-Meteo.

Per-site configuration covers facility type, base load, rooftop PV capacity,
and internal disruption rates. One CSV is produced per site.

Components (grounded in the proposal, Ch. 1 & 3):
  1. Baseline facility load (barracks, HQ, radar/comms, mess, residential)
  2. Daily occupancy cycles (double-hump: morning + evening activity)
  3. Weekly seasonality (reduced weekend operations)
  4. Temperature-driven HVAC cooling/heating (from real Open-Meteo temps)
  5. Lighting load driven by real solar radiation (dark hours)
  6. Rooftop solar-PV self-consumption (net metered load = gross - PV)
  7. Zambian public holiday effects
  8. Simulated OPERATIONAL READINESS CODES -> demand surge overlay
  9. Internal network disruptions -> missing telemetry:
       - fault trips (random, 1-3 h): equipment faults tripping feeders
       - planned maintenance (daytime, 2-6 h): generator/switchgear service
     NOTE: Military bases are EXEMPT from ZESCO load shedding (critical
     loads), so grid outages do NOT create NaN gaps in facility telemetry.

Output: prototype/data/processed/facility_load_<site>.csv (one per site)
"""

import numpy as np
import pandas as pd
from pathlib import Path

BASE_SEED = 42

# ----------------------------------------------------------------- config ---
# Per-site facility parameters. Adjust any number here.
SITE_CONFIGS = {
    "kohima": {
        "label": "Kohima Barracks (Lusaka)",
        "type": "HQ + logistics barracks",
        "base_load_kw": 2200.0,
        "pv_kwp": 500.0,
        "headcount": 2500,
        "floor_area_m2": 18000,
        # disruption rates (per-hour probability of an event starting)
        "fault_p_hour": 0.0035,       # ~2-3 fault trips / month
        "maintenance_p_hour": 0.0006, # ~1-2 planned maintenance / month
    },
    "arakan": {
        "label": "Arakan Barracks (Lusaka)",
        "type": "Admin + residential barracks",
        "base_load_kw": 1800.0,
        "pv_kwp": 400.0,
        "headcount": 2000,
        "floor_area_m2": 15000,
        "fault_p_hour": 0.0030,
        "maintenance_p_hour": 0.0005,
    },
    "peter_zuze": {
        "label": "Peter Zuze AFB (Ndola)",
        "type": "Air force base (hangars, radar, runway)",
        "base_load_kw": 3000.0,
        "pv_kwp": 800.0,
        "headcount": 1800,
        "floor_area_m2": 26000,
        "fault_p_hour": 0.0040,
        "maintenance_p_hour": 0.0007,
    },
    "tug_argan": {
        "label": "Tug Argan Barracks (Ndola)",
        "type": "Army garrison barracks",
        "base_load_kw": 1500.0,
        "pv_kwp": 300.0,
        "headcount": 1400,
        "floor_area_m2": 12000,
        "fault_p_hour": 0.0028,
        "maintenance_p_hour": 0.0005,
    },
    "mikango": {
        "label": "Mikango Barracks (Chongwe)",
        "type": "Training depot",
        "base_load_kw": 1200.0,
        "pv_kwp": 350.0,
        "headcount": 1100,
        "floor_area_m2": 10000,
        "fault_p_hour": 0.0025,
        "maintenance_p_hour": 0.0004,
    },
    "makeni": {
        "label": "ZNS Makeni (Lusaka)",
        "type": "ZNS camp",
        "base_load_kw": 1000.0,
        "pv_kwp": 250.0,
        "headcount": 900,
        "floor_area_m2": 8000,
        "fault_p_hour": 0.0022,
        "maintenance_p_hour": 0.0004,
    },
}

# Shared HVAC + readiness parameters (proposal Ch. 3.2.1)
HVAC = {
    "cooling_threshold_c": 24.0,
    "cooling_kw_per_c": 55.0,
    "heating_threshold_c": 16.0,
    "heating_kw_per_c": 25.0,
}

# Readiness codes (4 = routine .. 1 = combat/exercise surge)
# code -> (multiplier, label)
READINESS = {
    4: (1.00, "routine"),
    3: (1.08, "elevated"),
    2: (1.25, "high_readiness"),
    1: (1.50, "exercise_surge"),
}
# Per-hour event-start probabilities (derived: 1 event per ~N days)
READINESS_P = {
    3: 0.0019,   # elevated ~ every 22 days, 12-48 h
    2: 0.00083,  # high readiness ~ every 50 days, 6-24 h
    1: 0.00042,  # exercise surge ~ every 100 days, 8-72 h
}

DATA = Path(__file__).resolve().parents[1] / "data"
RAW = DATA / "raw"
OUT = DATA / "processed"
OUT.mkdir(parents=True, exist_ok=True)

# Rough Zambian public holidays 2024-2025 (fixed dates + known moveable ones)
HOLIDAYS = {
    "2024-01-01", "2024-03-12", "2024-03-29", "2024-04-01", "2024-05-01",
    "2024-05-25", "2024-07-01", "2024-07-02", "2024-08-05", "2024-10-24",
    "2024-12-25",
    "2025-01-01", "2025-03-12", "2025-04-18", "2025-04-21", "2025-05-01",
    "2025-05-25", "2025-07-07", "2025-07-08", "2025-08-04", "2025-10-24",
    "2025-12-25",
}


def hourly_range(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, f"{end} 23:00", freq="h")


def double_hump(hour: np.ndarray) -> np.ndarray:
    """Daily occupancy profile: morning ramp, office plateau, evening peak."""
    morning = np.exp(-0.5 * ((hour - 8.0) / 2.0) ** 2)          # 06-10 ramp
    midday = 0.55 * np.exp(-0.5 * ((hour - 13.0) / 3.0) ** 2)   # office plateau
    evening = np.exp(-0.5 * ((hour - 19.0) / 2.5) ** 2)         # 17-21 peak
    night = 0.18                                                # night lights/comms
    return night + morning + midday + evening


def gross_load(df: pd.DataFrame, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    """Physically-motivated gross facility load in kW (before PV)."""
    hour = df.index.hour.to_numpy(float)
    dow = df.index.dayofweek.to_numpy()
    temp = df["temperature_2m"].to_numpy(float)
    swr = df["shortwave_radiation"].to_numpy(float)  # W/m2

    # occupancy shape, scaled ~35% swing around mean
    occ = double_hump(hour)
    occ = occ / occ.mean() - 1.0
    load = cfg["base_load_kw"] * (1.0 + 0.35 * occ)

    # weekends: ~25% lighter (admin/training reduced)
    load = np.where(dow >= 5, load * 0.75, load)

    # holidays: another ~15% lighter
    dates = pd.Series(df.index.strftime("%Y-%m-%d"), index=df.index)
    load = np.where(dates.isin(HOLIDAYS), load * 0.85, load)

    # HVAC cooling (dominant in Zambian hot season Sep-Dec)
    load += np.maximum(0.0, temp - HVAC["cooling_threshold_c"]) * HVAC["cooling_kw_per_c"]

    # HVAC heating (rare: only cold June-July nights)
    load += np.maximum(0.0, HVAC["heating_threshold_c"] - temp) * HVAC["heating_kw_per_c"]

    # lighting: inverse of daylight, plus evening activity bump
    dark = np.clip(1.0 - swr / 400.0, 0.0, 1.0)
    load += dark * 180.0 * (1.0 + 0.4 * occ)

    # consumption noise: 2% gaussian + slow AR(1) drift
    noise = rng.normal(0, 0.02, size=len(df))
    drift = np.zeros(len(df))
    for i in range(1, len(df)):
        drift[i] = 0.98 * drift[i - 1] + rng.normal(0, 0.004)
    load *= (1.0 + noise + drift)
    return load


def rooftop_pv(df: pd.DataFrame, cfg: dict) -> np.ndarray:
    """Rooftop solar-PV output in kW from real solar irradiance (W/m2)."""
    swr = df["shortwave_radiation"].to_numpy(float)
    performance_ratio = 0.85
    return swr / 1000.0 * cfg["pv_kwp"] * performance_ratio


def simulate_readiness(n: int, rng: np.random.Generator) -> np.ndarray:
    """
    Simulate operational readiness codes driven by tactical events.
    Returns array of codes 4..1. Events start mostly at 04:00-06:00
    (morning briefings) and last from hours to days.
    """
    codes = np.full(n, 4, dtype=np.int8)
    i = 0
    while i < n:
        roll = rng.random()
        if roll < READINESS_P[3]:
            dur, code = rng.integers(12, 49), 3
        elif roll < READINESS_P[3] + READINESS_P[2]:
            dur, code = rng.integers(6, 25), 2
        elif roll < READINESS_P[3] + READINESS_P[2] + READINESS_P[1]:
            dur, code = rng.integers(8, 73), 1
        else:
            i += 1
            continue
        start = i + int(rng.integers(0, 24))
        codes[start:start + dur] = np.minimum(codes[start:start + dur], code)
        i = max(i + dur, start + dur)
    return codes


def simulate_disruptions(
    n: int, hours: np.ndarray, cfg: dict, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """
    Internal network disruptions on the base's OWN distribution system
    (NOT ZESCO load shedding - bases are exempt):
      - fault trips: random 1-3 h feeder trips from equipment faults
      - planned maintenance: 2-6 h daytime windows for generator/switchgear
    Returns (fault_mask, maintenance_mask).
    """
    fault = np.zeros(n, dtype=bool)
    maint = np.zeros(n, dtype=bool)

    # fault trips: random starts, 1-3 h
    i = 0
    while i < n:
        if rng.random() < cfg["fault_p_hour"]:
            dur = int(rng.integers(1, 4))
            fault[i:i + dur] = True
            i += dur + int(rng.integers(6, 48))
        else:
            i += 1

    # planned maintenance: daytime-anchored starts, 2-6 h
    i = 0
    while i < n:
        if rng.random() < cfg["maintenance_p_hour"] and 8 <= hours[i] <= 15:
            dur = int(rng.integers(2, 7))
            maint[i:i + dur] = True
            i += dur + int(rng.integers(24, 168))  # weeks apart
        else:
            i += 1
    return fault, maint


def simulate_meter_dropouts(n: int, rng: np.random.Generator) -> np.ndarray:
    """Small random meter comms dropouts (~0.4% of hours) -> NaN telemetry."""
    return rng.random(n) < 0.004


def generate_site(site: str, cfg: dict) -> pd.DataFrame:
    seed = BASE_SEED + abs(hash(site)) % 10000
    rng = np.random.default_rng(seed)

    weather_file = RAW / f"weather_{site}.csv"
    wx = pd.read_csv(weather_file, parse_dates=["timestamp"])
    wx = wx.set_index("timestamp").sort_index()

    idx = hourly_range("2024-01-01", "2025-12-31")
    df = wx.reindex(idx)
    assert df["temperature_2m"].notna().all(), f"{site}: weather gaps found"

    # ---- gross load + PV netting ------------------------------------------
    load = gross_load(df, cfg, rng)
    pv = rooftop_pv(df, cfg)
    net_load = load - pv  # assume all PV self-consumed (load >> PV)

    # ---- readiness overlay ------------------------------------------------
    codes = simulate_readiness(len(df), rng)
    mult = np.array([READINESS[c][0] for c in codes])
    net_load = net_load * mult

    # ---- internal disruptions + meter dropouts ----------------------------
    hours = df.index.hour.to_numpy()
    fault, maint = simulate_disruptions(len(df), hours, cfg, rng)
    dropout = simulate_meter_dropouts(len(df), rng)
    outage = fault | maint | dropout
    load_kw = np.where(outage, np.nan, net_load)

    # disruption label column
    dtype = np.full(len(df), "none", dtype=object)
    dtype[fault] = "fault_trip"
    dtype[maint] = "maintenance"
    dtype[dropout] = "comms_dropout"

    # ---- assemble final table ---------------------------------------------
    out = pd.DataFrame(
        {
            "load_kw": np.round(load_kw, 1),
            "readiness_code": codes,
            "readiness_label": [READINESS[c][1] for c in codes],
            "disruption_type": dtype,
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

    path = OUT / f"facility_load_{site}.csv"
    out.to_csv(path)

    valid = out["load_kw"].dropna()
    print(
        f"{site:11s} {cfg['label']:34s} rows={len(out)} "
        f"mean={valid.mean():7.0f} kW  peak={valid.max():7.0f} kW  "
        f"fault={int(fault.sum())}h maint={int(maint.sum())}h "
        f"dropout={int(dropout.sum())}h"
    )
    return out


def main() -> None:
    print(f"Generating synthetic facility loads for {len(SITE_CONFIGS)} sites...")
    frames = {site: generate_site(site, cfg) for site, cfg in SITE_CONFIGS.items()}
    print(f"\nSaved {len(frames)} CSVs to {OUT}")
    print("\nDisruption summary across sites:")
    for site, df in frames.items():
        types = df["disruption_type"].value_counts()
        print(f"  {site:11s} " + ", ".join(f"{k}={v}" for k, v in types.items()))


if __name__ == "__main__":
    main()