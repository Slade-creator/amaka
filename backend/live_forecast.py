"""Live forecasting: run the trained v2 models on real ingested readings.

Input  — hourly measured load from meter kits / SCADA connectors / CSV uploads
         (backend.ingest.hourly), live weather from Open-Meteo, and the
         readiness level the operator sets.
Output — a 48-hour forecast curve with a 95% range, the exact direct-horizon
         points (H1, H6, H24, H48), the next-24 h peak against the site's peak
         threshold, and a rolling H1 backtest over recent hours.

Model (same as training, see src/v2_train.py and docs/MODEL_CARD_V2.md)
-----------------------------------------------------------------------
Stage 1 is the per-site, per-horizon XGBoost model on the 22 v2 features.
Stage 2 adds the HistGradientBoosting residual correction (with its fitted
weight alpha) where validation selected it. Where validation selected the
LSTM residual, the live service serves Stage 1 alone: the LSTM needs a
168-hour sequence of model-scaled inputs that a freshly enrolled kit cannot
supply, and serving it on padded history would be worse than not serving it.

Feature construction follows src/v2_horizons.py exactly: load-history features
from the hours before the forecast origin; calendar, weather, readiness and
maintenance features at the TARGET hour; all times in Africa/Lusaka (UTC+2).

The 48-hour curve: hour k ahead uses the shortest trained horizon that covers
it (H1 for k=1, H6 for 2–6, H24 for 7–24, H48 for 25–48). Only k = 1, 6, 24,
48 are exact direct forecasts; the rest are flagged ``exact: false``.

Sites added in the field have no trained model of their own; they use the
fleet site with the closest peak threshold as a proxy, and the response says so.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import requests

from . import ingest, store
from .settings import settings

log = logging.getLogger("amaka.live")

_cfg = settings.live
BASE = Path(__file__).resolve().parents[1]
MODEL_DIR = _cfg.model_dir
RAW_WEATHER = _cfg.raw_weather_dir
LOCAL = timezone(timedelta(hours=_cfg.utc_offset_h))

sys.path.insert(0, str(BASE / "src"))
from v2_holidays import zambian_holidays  # noqa: E402

FEATURES = [
    "load_lag_1h", "load_lag_2h", "load_lag_24h", "load_lag_168h",
    "load_roll_mean_24h", "load_roll_std_24h",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "is_holiday", "is_weekend",
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "cloud_cover", "shortwave_radiation", "wind_speed_10m",
    "readiness_code", "disruption_maintenance",
]
WEATHER = FEATURES[14:20]
HORIZONS = _cfg.horizons
MIN_HISTORY_H = _cfg.min_history_h
SHORT_GAP_H = _cfg.short_gap_h
WEATHER_TTL_S = _cfg.weather_ttl_s


class NotEnoughData(Exception):
    """Too little measured history to build the load-history features."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _models(site: str, horizon: int) -> dict:
    run_path = MODEL_DIR / "metrics" / f"run_{site}_h{horizon}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    selected = (run.get("selection") or {}).get("selected", "xgb")
    xgb = joblib.load(MODEL_DIR / f"xgb_{site}_h{horizon}.pkl")
    hgb, alpha = None, 0.0
    if selected == "hgb":
        hgb = joblib.load(MODEL_DIR / f"resid_hgb_{site}_h{horizon}.pkl")
        alpha = float((run.get("resid_hgb") or {}).get("alpha", 0.0))
    cfg = store.get_site_horizon(site, horizon)
    band = float((cfg.get("metrics") or {}).get("band_kw", 0.0))
    avg = float((cfg.get("load") or {}).get("avg_kw", 0.0))
    return {"xgb": xgb, "hgb": hgb, "alpha": alpha, "selected": selected,
            "band_kw": band, "avg_kw": avg}


def model_site_for(site_id: str) -> tuple[str, bool]:
    """(fleet site whose models to use, is_proxy)."""
    if site_id in store.site_ids():
        return site_id, False
    target = ingest.get_site(site_id)
    thr = float(target.get("threshold_kw") or 0.0)
    best = min(store.site_ids(), key=lambda s: abs(
        float(store.get_site(s).get("load", {}).get("threshold_kw", 0.0)) - thr))
    return best, True


def stage2_name(selected: str) -> str:
    return {"hgb": "XGBoost + HGB residual",
            "lstm": "XGBoost (LSTM residual not served live)",
            "xgb": "XGBoost"}.get(selected, "XGBoost")


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

_weather_cache: dict[tuple[float, float], tuple[float, pd.DataFrame, str]] = {}
_weather_lock = threading.Lock()


def _open_meteo(lat: float, lon: float) -> pd.DataFrame:
    r = requests.get(_cfg.weather_url, timeout=_cfg.weather_timeout_s, params={
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "hourly": ",".join(WEATHER), "timezone": "Africa/Lusaka",
        "past_days": _cfg.weather_past_days, "forecast_days": _cfg.weather_forecast_days, "wind_speed_unit": "kmh",
    })
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame({c: h[c] for c in WEATHER}, index=pd.to_datetime(h["time"]))
    return df.astype(float)


@lru_cache(maxsize=8)
def _climatology(model_site: str) -> pd.DataFrame:
    """Mean weather by (month, hour) from the archived site weather."""
    df = pd.read_csv(RAW_WEATHER / f"weather_{model_site}.csv", parse_dates=["timestamp"])
    df["month"] = df["timestamp"].dt.month
    df["hour"] = df["timestamp"].dt.hour
    return df.groupby(["month", "hour"])[WEATHER].mean()


def weather_for(lat: float, lon: float, model_site: str,
                times: pd.DatetimeIndex) -> tuple[pd.DataFrame, str]:
    """Weather at the given local-time hours: Open-Meteo, else climatology."""
    key = (round(lat, 2), round(lon, 2))
    with _weather_lock:
        hit = _weather_cache.get(key)
    df, source = None, "open-meteo"
    if hit and time.time() - hit[0] < WEATHER_TTL_S:
        df, source = hit[1], hit[2]
    else:
        try:
            df = _open_meteo(lat, lon)
            with _weather_lock:
                _weather_cache[key] = (time.time(), df, "open-meteo")
        except Exception as exc:  # network down, rate limit, bad payload
            log.warning("Open-Meteo unavailable (%s); using climatology", exc)
            df, source = None, "climatology"
    clim = _climatology(model_site)
    rows = []
    for t in times:
        if df is not None and t in df.index and not df.loc[t].isna().any():
            rows.append(df.loc[t].to_numpy())
        else:
            rows.append(clim.loc[(t.month, t.hour)].to_numpy())
            if df is not None:
                source = "open-meteo + climatology"
    return pd.DataFrame(rows, index=times, columns=WEATHER), source


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def _history(site_id: str, hours: int = 240) -> tuple[pd.Series, list[str]]:
    """Hourly measured load (local time), short gaps filled, with notes."""
    h = ingest.hourly(site_id, hours=hours)
    idx = pd.to_datetime([r["hour"] for r in h["rows"]]).tz_convert(LOCAL).tz_localize(None)
    y = pd.Series([r["mean_kw"] for r in h["rows"]], index=idx, dtype=float)
    # The hour in progress is a partial average, not a finished hour: forecast
    # it instead of feeding it to the model as history.
    while len(h["rows"]) and h["rows"][-1]["samples"] < 0.8 * h["rows"][-1]["expected"]:
        h["rows"] = h["rows"][:-1]
        y = y.iloc[:-1]
    # Drop hours flagged as stuck/zero: they are meter faults, not load.
    bad = [i for i, r in enumerate(h["rows"]) if {"flatline", "zero"} & set(r["flags"])]
    if bad:
        y.iloc[bad] = np.nan
    notes = []
    observed = y.dropna()
    if len(observed) < MIN_HISTORY_H:
        raise NotEnoughData(
            f"Needs at least {MIN_HISTORY_H} hours of good readings to forecast; "
            f"this site has {len(observed)}.")
    y = y.loc[observed.index[0]:observed.index[-1]]
    filled = y.interpolate(limit=SHORT_GAP_H, limit_area="inside")
    if filled.isna().any():
        # Longer gaps: same hour yesterday (seasonal fill), as a last resort.
        filled = filled.fillna(filled.shift(24))
        notes.append("long gaps filled from the same hour a day earlier")
    if bad:
        notes.append(f"{len(bad)} faulty hours (flatline/zero) excluded")
    return filled, notes


def _calendar(t: pd.Timestamp) -> list[float]:
    hols = zambian_holidays(t.year)
    return [
        math.sin(2 * math.pi * t.hour / 24), math.cos(2 * math.pi * t.hour / 24),
        math.sin(2 * math.pi * t.dayofweek / 7), math.cos(2 * math.pi * t.dayofweek / 7),
        math.sin(2 * math.pi * t.month / 12), math.cos(2 * math.pi * t.month / 12),
        float(t.date() in hols), float(t.dayofweek >= 5),
    ]


def _history_feats(y: pd.Series, origin: pd.Timestamp, notes: set[str]) -> list[float]:
    def at(t: pd.Timestamp) -> float:
        v = y.get(t, np.nan)
        return float(v) if v == v else np.nan

    lag1, lag2, lag24 = at(origin - pd.Timedelta(hours=1)), at(origin - pd.Timedelta(hours=2)), \
        at(origin - pd.Timedelta(hours=24))
    lag168 = at(origin - pd.Timedelta(hours=168))
    if lag168 != lag168:
        lag168 = lag24
        notes.add("less than 7 days of history: last-week load approximated by yesterday")
    win = y.loc[origin - pd.Timedelta(hours=24): origin - pd.Timedelta(hours=1)].dropna()
    mean24 = float(win.mean()) if len(win) else lag1
    std24 = float(win.std()) if len(win) > 1 else 0.0
    return [lag1, lag2, lag24, lag168, mean24, std24]


def _predict(model_site: str, horizon: int, x: np.ndarray) -> float:
    m = _models(model_site, horizon)
    pred = float(m["xgb"].predict(x)[0])
    if m["hgb"] is not None:
        pred += m["alpha"] * float(m["hgb"].predict(x)[0])
    return pred


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def forecast(site_id: str, readiness: int = 4, maintenance: int = 0) -> dict:
    site = ingest.get_site(site_id)           # raises ingest.NotFound
    model_site, proxy = model_site_for(site_id)
    readiness = int(min(4, max(1, readiness)))
    y, hist_notes = _history(site_id)
    notes: set[str] = set(hist_notes)
    origin = y.index[-1] + pd.Timedelta(hours=1)   # first hour not yet measured
    threshold = float(site.get("threshold_kw") or 0.0)

    # Weather for the 48 target hours and for the backtest hours.
    targets = pd.date_range(origin, periods=_cfg.forecast_hours, freq="h")
    back_targets = pd.date_range(origin - pd.Timedelta(hours=_cfg.backtest_hours), periods=_cfg.backtest_hours, freq="h")
    wx, wx_source = weather_for(site["lat"], site["lon"], model_site,
                                back_targets.append(targets))

    hist = _history_feats(y, origin, notes)
    if any(v != v for v in hist):
        raise NotEnoughData("The last two hours have no readings; wait for the kit to report.")

    # Proxy sites: scale the training band to the live load level.
    level = float(y.iloc[-24:].mean())
    points = []
    for k in range(1, _cfg.forecast_hours + 1):
        h = next(hh for hh in HORIZONS if hh >= k)
        t = targets[k - 1]
        x = np.array([hist + _calendar(t) + list(wx.loc[t].to_numpy())
                      + [float(readiness), float(maintenance)]], dtype=np.float32)
        kw = max(0.0, _predict(model_site, h, x))
        m = _models(model_site, h)
        band = m["band_kw"] * (level / m["avg_kw"] if proxy and m["avg_kw"] > 0 else 1.0)
        points.append({
            "t": t.isoformat(), "k": k, "model_h": h, "exact": k == h,
            "kw": round(kw, 1), "lower": round(max(0.0, kw - band), 1),
            "upper": round(kw + band, 1),
            "over_threshold": bool(threshold and kw > threshold),
        })

    # Rolling H1 backtest: what the model would have said one hour ahead.
    bt = []
    for t in back_targets:
        actual = y.get(t, np.nan)
        if actual != actual:
            continue
        f = _history_feats(y, t, set())
        if any(v != v for v in f):
            continue
        x = np.array([f + _calendar(t) + list(wx.loc[t].to_numpy())
                      + [float(readiness), float(maintenance)]], dtype=np.float32)
        bt.append({"t": t.isoformat(), "actual": round(float(actual), 1),
                   "forecast": round(max(0.0, _predict(model_site, 1, x)), 1)})
    mae = float(np.mean([abs(r["actual"] - r["forecast"]) for r in bt])) if bt else None
    mape = (float(np.mean([abs(r["actual"] - r["forecast"]) / r["actual"]
                           for r in bt if r["actual"] > 0])) * 100 if bt else None)

    next24 = points[:24]
    peak = max(next24, key=lambda p: p["kw"])
    m1 = _models(model_site, 1)
    return {
        "site": {"id": site["id"], "label": site["label"], "threshold_kw": threshold,
                 "source": site.get("source", "fleet")},
        "model": {
            "site": model_site, "proxy": proxy,
            "name": stage2_name(m1["selected"]),
            "stage2_by_horizon": {str(h): _models(model_site, h)["selected"] for h in HORIZONS},
            "note": (f"No trained model for this site yet; using {store.get_site(model_site)['label']}'s "
                     "models as the closest match by peak threshold.") if proxy else None,
        },
        "generated_at": datetime.now(LOCAL).isoformat(timespec="seconds"),
        "origin": origin.isoformat(),
        "last_reading_hour": y.index[-1].isoformat(),
        "readiness_code": readiness,
        "weather_source": wx_source,
        "history_hours": int(y.notna().sum()),
        "notes": sorted(notes),
        "points": points,
        "recent": [{"t": t.isoformat(), "kw": round(float(v), 1)}
                   for t, v in y.iloc[-_cfg.recent_hours:].items() if v == v],
        "peak_24h": {"kw": peak["kw"], "at": peak["t"],
                     "over_by_kw": round(peak["kw"] - threshold, 1) if threshold else None},
        "backtest_h1": {"n": len(bt), "mae_kw": None if mae is None else round(mae, 1),
                        "mape_pct": None if mape is None else round(mape, 2), "rows": bt},
    }
