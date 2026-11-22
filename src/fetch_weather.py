"""
Fetch historical hourly weather for Zambian military facility sites
from the Open-Meteo Archive API (free, no API key required).

Outputs: prototype/data/raw/weather_<site>.csv (hourly, Africa/Lusaka timezone)
"""

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import pandas as pd

# Military facility sites (approximate coordinates)
# NOTE: Peter Zuze AFB and Tug Argan Barracks (Ndola) are ~3 km apart ->
# same Open-Meteo weather grid cell, so we fetch Ndola once and copy
# the file to weather_tug_argan.csv afterwards.
SITES = {
    "kohima": (-14.406, 28.488),      # Kohima Barracks, Lusaka
    "arakan": (-15.435, 28.321),      # Arakan Barracks, Lusaka
    "peter_zuze": (-12.9972, 28.6639),  # Peter Zuze AFB, Ndola
    "mikango": (-15.329, 28.682),     # Mikango Barracks, Chongwe
    "makeni": (-15.47, 28.25),        # ZNS Makeni, Lusaka
}

# Tug Argan is ~3 km from Peter Zuze and shares the same Open-Meteo grid cell.
# Fetch Ndola once and derive the second file; this is recorded in the manifest.
DERIVED_SITES = {
    "tug_argan": "peter_zuze",
}

URL = "https://archive-api.open-meteo.com/v1/archive"

MAX_RETRIES = 4


def fetch_chunk(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    """Fetch one date range with retry/backoff (handles flaky connections)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": start,
                    "end_date": end,
                    "hourly": ",".join(HOURLY_VARS),
                    "timezone": "Africa/Lusaka",
                },
                timeout=120,
            )
            r.raise_for_status()
            return pd.DataFrame(r.json()["hourly"])
        except (requests.RequestException, ValueError) as e:
            wait = 5 * attempt
            print(f"  attempt {attempt}/{MAX_RETRIES} failed ({e.__class__.__name__}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {start}..{end} after {MAX_RETRIES} attempts")

# Variables used as model features in the proposal (Ch. 3.2.1):
# ambient temperature, relative humidity, solar irradiance, cloud cover
HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
]

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def fetch_site(name: str, lat: float, lon: float) -> pd.DataFrame:
    # Fetch in monthly chunks — large responses break on flaky connections
    frames = []
    for year in (2024, 2025):
        for month in range(1, 13):
            start = f"{year}-{month:02d}-01"
            end_day = {"1": 31, "2": 29 if year % 4 == 0 else 28, "3": 31, "4": 30,
                       "5": 31, "6": 30, "7": 31, "8": 31, "9": 30, "10": 31,
                       "11": 30, "12": 31}[str(month)]
            end = f"{year}-{month:02d}-{end_day:02d}"
            print(f"  {name} {start} .. {end}")
            frames.append(fetch_chunk(lat, lon, start, end))
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"])
    df = df.rename(columns={"time": "timestamp"})
    out = RAW_DIR / f"weather_{name}.csv"
    df.to_csv(out, index=False)
    print(f"{name}: {len(df)} rows -> {out}")
    return df


def copy_derived_sites() -> None:
    for derived, source in DERIVED_SITES.items():
        out = RAW_DIR / f"weather_{derived}.csv"
        src = RAW_DIR / f"weather_{source}.csv"
        if out.exists():
            print(f"{derived}: exists, skipping ({out})")
            continue
        if not src.exists():
            raise FileNotFoundError(
                f"cannot derive weather_{derived}: missing source {src}"
            )
        shutil.copyfile(src, out)
        print(f"{derived}: derived from {source} -> {out}")


def write_manifest() -> None:
    rows = {}
    for site in [*SITES, *DERIVED_SITES]:
        path = RAW_DIR / f"weather_{site}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        rows[site] = {
            "rows": int(len(df)),
            "start": str(df["timestamp"].min()),
            "end": str(df["timestamp"].max()),
            "source": DERIVED_SITES.get(site, site),
            "derived": site in DERIVED_SITES,
        }
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": URL,
        "timezone": "Africa/Lusaka",
        "hourly_variables": HOURLY_VARS,
        "coordinates": {k: {"lat": v[0], "lon": v[1]} for k, v in SITES.items()},
        "derived_sites": DERIVED_SITES,
        "files": rows,
    }
    out = RAW_DIR / "weather_manifest.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {out}")


if __name__ == "__main__":
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, (lat, lon) in SITES.items():
        out = RAW_DIR / f"weather_{name}.csv"
        if out.exists():  # already fetched in a previous run
            print(f"{name}: exists, skipping ({out})")
            continue
        fetch_site(name, lat, lon)
        time.sleep(1)  # be polite to the free API

    copy_derived_sites()
    write_manifest()