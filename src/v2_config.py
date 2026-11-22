"""
Shared configuration for the v2 synthetic Zambian military-facility pipeline.

v1 (data/processed + config/*.pkl) is frozen for the dashboard replay built by
src/build_forecasts.py. v2 writes to data/synthetic_v2 and config/v2 so the two
datasets and model sets can be compared without overwriting each other.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
VERSION = "v2"
PROCESSED = DATA / f"synthetic_{VERSION}"
MODELS = ROOT / "config" / VERSION

SITES = ["arakan", "kohima", "makeni", "mikango", "peter_zuze", "tug_argan"]

# Direct forecast horizons (hours ahead). Medium-term daily/weekly horizons are
# a later extension; the data contract here supports any positive integer h.
HORIZONS = [1, 6, 24, 48]

BASE_SEED = 42
SEQ_LEN = 168

# Chronological split on the TARGET timestamp, not the forecast origin.
TRAIN_START = "2024-01-01 00:00:00"
TRAIN_END = "2024-12-31 23:00:00"
VAL_START = "2025-01-01 00:00:00"
VAL_END = "2025-06-30 23:00:00"
TEST_START = "2025-07-01 00:00:00"
TEST_END = "2025-12-31 23:00:00"

# Expanding-window out-of-fold folds inside the training period. Fold 0 trains
# on Jan-Mar and predicts Apr-Jun; fold 1 trains through Jun and predicts
# Jul-Sep; fold 2 trains through Sep and predicts Oct-Dec.
OOF_FOLDS = [
    ("2024-04-01", "2024-06-30"),
    ("2024-07-01", "2024-09-30"),
    ("2024-10-01", "2024-12-31"),
]

# Per-site synthetic parameters. base_load_kw is fixed infrastructure load;
# occupancy, HVAC, lighting and humidity are added on top using the headcount
# and floor area below. Values are calibrated so site mean loads stay close to
# the v1 prototype while weather sensitivity scales with facility size.
SITE_CONFIGS = {
    "kohima": {
        "label": "Kohima Barracks (Lusaka)",
        "location": "Lusaka",
        "type": "HQ + logistics barracks",
        "lat": -14.406,
        "lon": 28.488,
        "base_load_kw": 2050.0,
        "pv_kwp": 500.0,
        "headcount": 2500,
        "floor_area_m2": 18000.0,
        "hvac_w_m2_c": 3.10,
        "heating_ratio": 0.45,
        "lighting_w_m2": 8.50,
        "occupancy_kw_per_person": 0.040,
        "humidity_kw_per_m2_pct": 0.00015,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.80,
        "holiday_factor": 0.90,
        "fault_p_hour": 0.0035,
        "maintenance_p_hour": 0.0095,
        "major_fault_prob": 0.06,
        "comms_dropout_p_hour": 0.0035,
    },
    "arakan": {
        "label": "Arakan Barracks (Lusaka)",
        "location": "Lusaka",
        "type": "Admin + residential barracks",
        "lat": -15.435,
        "lon": 28.321,
        "base_load_kw": 1700.0,
        "pv_kwp": 400.0,
        "headcount": 2000,
        "floor_area_m2": 15000.0,
        "hvac_w_m2_c": 3.00,
        "heating_ratio": 0.45,
        "lighting_w_m2": 8.00,
        "occupancy_kw_per_person": 0.045,
        "humidity_kw_per_m2_pct": 0.00015,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.80,
        "holiday_factor": 0.90,
        "fault_p_hour": 0.0030,
        "maintenance_p_hour": 0.0090,
        "major_fault_prob": 0.06,
        "comms_dropout_p_hour": 0.0035,
    },
    "peter_zuze": {
        "label": "Peter Zuze AFB (Ndola)",
        "location": "Ndola",
        "type": "Air force base (hangars, radar, runway)",
        "lat": -12.9972,
        "lon": 28.6639,
        "base_load_kw": 2720.0,
        "pv_kwp": 800.0,
        "headcount": 1800,
        "floor_area_m2": 26000.0,
        "hvac_w_m2_c": 3.20,
        "heating_ratio": 0.45,
        "lighting_w_m2": 9.00,
        "occupancy_kw_per_person": 0.050,
        "humidity_kw_per_m2_pct": 0.00012,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.82,
        "holiday_factor": 0.92,
        "fault_p_hour": 0.0040,
        "maintenance_p_hour": 0.0100,
        "major_fault_prob": 0.07,
        "comms_dropout_p_hour": 0.0035,
    },
    "tug_argan": {
        "label": "Tug Argan Barracks (Ndola)",
        "location": "Ndola",
        "type": "Army garrison barracks",
        "lat": -12.995,
        "lon": 28.665,
        "base_load_kw": 1470.0,
        "pv_kwp": 300.0,
        "headcount": 1400,
        "floor_area_m2": 12000.0,
        "hvac_w_m2_c": 2.80,
        "heating_ratio": 0.45,
        "lighting_w_m2": 7.50,
        "occupancy_kw_per_person": 0.045,
        "humidity_kw_per_m2_pct": 0.00015,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.80,
        "holiday_factor": 0.90,
        "fault_p_hour": 0.0028,
        "maintenance_p_hour": 0.0085,
        "major_fault_prob": 0.06,
        "comms_dropout_p_hour": 0.0035,
    },
    "mikango": {
        "label": "Mikango Barracks (Chongwe)",
        "location": "Chongwe",
        "type": "Training depot",
        "lat": -15.329,
        "lon": 28.682,
        "base_load_kw": 1210.0,
        "pv_kwp": 350.0,
        "headcount": 1100,
        "floor_area_m2": 10000.0,
        "hvac_w_m2_c": 2.80,
        "heating_ratio": 0.45,
        "lighting_w_m2": 7.50,
        "occupancy_kw_per_person": 0.040,
        "humidity_kw_per_m2_pct": 0.00015,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.82,
        "holiday_factor": 0.90,
        "fault_p_hour": 0.0025,
        "maintenance_p_hour": 0.0080,
        "major_fault_prob": 0.06,
        "comms_dropout_p_hour": 0.0035,
    },
    "makeni": {
        "label": "ZNS Makeni (Lusaka)",
        "location": "Lusaka",
        "type": "ZNS camp",
        "lat": -15.47,
        "lon": 28.25,
        "base_load_kw": 1030.0,
        "pv_kwp": 250.0,
        "headcount": 900,
        "floor_area_m2": 8000.0,
        "hvac_w_m2_c": 3.00,
        "heating_ratio": 0.45,
        "lighting_w_m2": 8.00,
        "occupancy_kw_per_person": 0.040,
        "humidity_kw_per_m2_pct": 0.00018,
        "pv_performance_ratio": 0.85,
        "weekend_factor": 0.82,
        "holiday_factor": 0.90,
        "fault_p_hour": 0.0022,
        "maintenance_p_hour": 0.0075,
        "major_fault_prob": 0.06,
        "comms_dropout_p_hour": 0.0035,
    },
}

# Weather-forecast error proxy: sigma(h) = base + slope * h. These stand in for
# real numerical weather forecasts; they are deliberately modest and grow with
# horizon. Used only when building horizon datasets.
WEATHER_ERROR = {
    "temperature_2m": (0.40, 0.03),
    "relative_humidity_2m": (2.0, 0.15),
    "precipitation": (0.20, 0.01),
    "cloud_cover": (4.0, 0.25),
    "shortwave_radiation": (8.0, 0.80),
    "wind_speed_10m": (1.0, 0.05),
}
WEATHER_ERROR_AR1_PHI = 0.70

HVAC = {
    "cooling_threshold_c": 24.0,
    "heating_threshold_c": 16.0,
    "humidity_threshold_pct": 60.0,
}

# Unscheduled ZESCO-side faults. All six sites are security-wing facilities and
# are assumed exempt from SCHEDULED load shedding (Minister of Energy statement,
# July 2024). They are not immune to faults/vandalism, so a small number of
# unscheduled grid faults are simulated. Backup generators carry the load:
# a short restart surge in the first hour, then a small sustained efficiency
# penalty. These are observed load events, not telemetry gaps.
GRID_FAULT = {
    "p_hour": 0.0005,
    "duration_min": 1,
    "duration_max": 6,
    "long_prob": 0.10,
    "long_duration_max": 12,
    "start_factor": 1.06,
    "sustain_factor": 1.02,
    "cooldown_h_min": 24,
    "cooldown_h_max": 168,
}

READINESS = {
    4: (1.00, "routine"),
    3: (1.08, "elevated"),
    2: (1.25, "high_readiness"),
    1: (1.50, "exercise_surge"),
}
READINESS_P = {
    3: 0.0019,
    2: 0.00083,
    1: 0.00042,
}


def stable_site_seed(site: str) -> int:
    """Process-stable seed. Python's built-in hash() is salted per process."""
    import zlib

    return BASE_SEED + zlib.crc32(site.encode("utf-8")) % 10000
