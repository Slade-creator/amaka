"""Data access layer for the AMAKA backend (v2 research pipeline).

Loads config/v2_sites.json at startup and lazily loads + caches each site's
per-horizon replay CSV (data/v2/replay_<site>_h<h>.csv) and SHAP archive
(data/v2/shap_<site>_h<h>.npz). All data is precomputed by
src/build_v2_replay.py; no model inference happens here (the SHAP
attributions are read from disk).

The pipeline is direct multi-horizon: every data accessor is keyed by
(site, horizon) with horizon ∈ {1, 6, 24, 48}.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

log = logging.getLogger("amaka.store")

# backend/ -> prototype root
BASE = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE / "config" / "v2_sites.json"
PROC_DIR = BASE / "data" / "v2"

# Used only if the config file omits the horizon metadata.
DEFAULT_HORIZON = 24
SUPPORTED_HORIZONS = (1, 6, 24, 48)
MIDTERM_HORIZONS = (7, 14, 30, 60, 90)
DEFAULT_MIDTERM_HORIZON = 30
MIDTERM_METRICS_PATH = BASE / "config" / "v2" / "metrics_midterm.csv"

# Canonical readiness display names (docs/VOCABULARY.md). The UI always derives
# its label from readiness_code, so old CSV labels cannot leak into the screen.
READINESS_NAMES: dict[int, str] = {
    1: "Exercise surge",
    2: "High readiness",
    3: "Elevated",
    4: "Routine",
}
# Human labels for v2's 22 SHAP features (FEATURE_COLS in src/v2_horizons.py);
# unknown names fall back to a title-cased name.
FEATURE_LABELS: dict[str, str] = {
    # load history
    "load_lag_1h": "Load 1 hour ago",
    "load_lag_2h": "Load 2 hours ago",
    "load_lag_24h": "Load 24 hours ago",
    "load_lag_168h": "Load 1 week ago",
    "load_roll_mean_24h": "Average load, last 24 h",
    "load_roll_std_24h": "Load variability, last 24 h",
    # target-hour calendar
    "hour_sin": "Hour of day (sin)",
    "hour_cos": "Hour of day (cos)",
    "dow_sin": "Day of week (sin)",
    "dow_cos": "Day of week (cos)",
    "month_sin": "Month of year (sin)",
    "month_cos": "Month of year (cos)",
    "is_holiday": "Public holiday",
    "is_weekend": "Weekend",
    # target-hour weather
    "temperature_2m": "Temperature",
    "relative_humidity_2m": "Humidity",
    "precipitation": "Rainfall",
    "cloud_cover": "Cloud cover",
    "shortwave_radiation": "Solar radiation",
    "wind_speed_10m": "Wind speed",
    # target-hour operations
    "readiness_code": "Readiness level",
    "disruption_maintenance": "Planned maintenance",
}

# Exact column set of a v2 replay CSV (docs/V2_DASHBOARD_CONTRACT.md).
REPLAY_COLUMNS = [
    "timestamp", "actual_kw", "xgb_kw", "hybrid_kw", "lower_kw", "upper_kw",
    "selected_model", "readiness_code", "readiness_label", "temperature_c",
    "humidity_pct", "radiation_wm2", "cloud_cover_pct", "is_holiday",
    "is_weekend",
]


class StoreError(Exception):
    """Base error for data access problems."""


class SiteNotFound(StoreError):
    """Raised for an unknown site id."""


class BadDate(StoreError):
    """Raised when a query date cannot be parsed."""


class BadHorizon(StoreError):
    """Raised when a requested horizon is missing or malformed."""


class DataNotFound(StoreError):
    """Raised when a v2 data file for (site, horizon) is missing."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load config/v2_sites.json once; cached for the process lifetime.

    Callers must treat the returned dict as read-only — build derived views
    (e.g. `horizon_view`) instead of mutating it.
    """
    import json

    if not CONFIG_PATH.exists():
        raise StoreError(f"config file missing: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    log.info("loaded v2 config: %d sites, version=%s, horizons=%s, "
             "generated_at=%s",
             len(cfg.get("sites", [])), cfg.get("version", "?"),
             cfg.get("available_horizons"), cfg.get("generated_at"))
    return cfg


def site_ids() -> list[str]:
    return [s["id"] for s in load_config()["sites"]]


def get_site(site: str) -> dict:
    for s in load_config()["sites"]:
        if s["id"] == site:
            return s
    raise SiteNotFound(site)


def available_horizons() -> list[int]:
    """Horizons declared by the config (fallback: 1/6/24/48)."""
    hs = load_config().get("available_horizons")
    if not hs:
        return list(SUPPORTED_HORIZONS)
    return [int(h) for h in hs]


def default_horizon() -> int:
    """Config default horizon (fallback: 24)."""
    try:
        return int(load_config().get("default_horizon", DEFAULT_HORIZON))
    except (TypeError, ValueError):
        return DEFAULT_HORIZON


def resolve_horizon(value: Optional[Union[int, str]]) -> int:
    """Validate a `horizon` query param → int, or raise BadHorizon (400).

    None/empty → config default. Anything not in `available_horizons()`
    (including non-numeric input) is rejected with a clear message.
    """
    if value is None or str(value).strip() == "":
        return default_horizon()
    try:
        h = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BadHorizon(
            f"invalid horizon '{value}'; expected an integer hour horizon "
            f"one of {available_horizons()}") from exc
    if h not in available_horizons():
        raise BadHorizon(
            f"unknown horizon {h}; available horizons: {available_horizons()}")
    return h


def horizon_view(site_cfg: dict, horizon: int) -> dict:
    """Return `site_cfg` with metrics/load/alerts/cost replaced by the
    requested horizon's values.

    Returns a *new* dict; the cached config is never mutated. The nested
    `horizons` map is preserved so clients can swap horizons client-side.
    """
    horizons = site_cfg.get("horizons") or {}
    src = horizons.get(str(int(horizon)))
    if src is None and str(site_cfg.get("horizon")) == str(int(horizon)):
        src = site_cfg
    if src is None:
        raise DataNotFound(
            f"site '{site_cfg.get('id')}' has no horizon {horizon} data "
            f"(available: {sorted(horizons) or 'none'})")
    out = dict(site_cfg)
    out.update(src)
    out["horizons"] = site_cfg.get("horizons")
    out["horizon"] = int(horizon)
    return out


def get_site_horizon(site: str, horizon: int) -> dict:
    """Horizon-specific view of a site's config (raises SiteNotFound)."""
    return horizon_view(get_site(site), horizon)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Replay CSV (lazy + cached per site AND horizon)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=24)
def load_replay(site: str, horizon: int) -> pd.DataFrame:
    """Load data/v2/replay_<site>_h<h>.csv (cached per (site, horizon)).

    Timestamp parsed as naive local ISO. A missing file raises DataNotFound
    (404) — there is no v1 fallback.
    """
    if site not in site_ids():
        raise SiteNotFound(site)
    path = PROC_DIR / f"replay_{site}_h{int(horizon)}.csv"
    if not path.exists():
        raise DataNotFound(
            f"v2 replay missing for site '{site}' horizon {horizon}: "
            f"{path.relative_to(BASE)}")
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
    df = df.sort_values("timestamp").reset_index(drop=True)
    log.info("loaded replay for %s h=%s: %d rows", site, horizon, len(df))
    return df


# ---------------------------------------------------------------------------
# Date parsing / clamping helpers
# ---------------------------------------------------------------------------

def parse_date(value: Optional[str], *, param: str = "date",
               default: Optional[pd.Timestamp] = None) -> Optional[pd.Timestamp]:
    """Parse a flexible ISO query param.

    Accepts '2025-10-06', '2025-10-06 18:00', '2025-10-06T18:00',
    '2025-10-06T18:00:00' (seconds optional, space or T separator).
    Returns `default` when value is None/empty; raises BadDate otherwise.
    """
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    try:
        # pandas handles T/space, missing seconds, and date-only strings.
        ts = pd.Timestamp(text)
    except (ValueError, TypeError) as exc:
        raise BadDate(f"invalid {param} '{value}'; expected ISO-8601 like "
                      f"2025-10-06T18:00:00") from exc
    if pd.isna(ts):
        raise BadDate(f"invalid {param} '{value}'")
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def clamp_to_range(ts: pd.Timestamp, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.Timestamp:
    """Clamp a timestamp into [lo, hi] so out-of-range values never 500."""
    if ts < lo:
        return lo
    if ts > hi:
        return hi
    return ts


def window_mask(df: pd.DataFrame, start: Optional[pd.Timestamp],
                end: Optional[pd.Timestamp]) -> pd.Series:
    """Boolean mask for start <= ts <= end (bounds optional)."""
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["timestamp"] >= start
    if end is not None:
        mask &= df["timestamp"] <= end
    return mask


# ---------------------------------------------------------------------------
# SHAP npz (lazy + cached)
# ---------------------------------------------------------------------------

class ShapArchive:
    """Wrapper around shap_<site>_h<h>.npz providing nearest-hour lookup."""

    def __init__(self, site: str, horizon: int, npz: np.lib.npyio.NpzFile):
        self.site = site
        self.horizon = horizon
        self.values = npz["values"]              # (N, 22) float32
        self.feature_values = npz["feature_values"]  # (N, 22) float32
        self.bias = npz["bias"]                  # (N,) float32
        self.features = [str(f) for f in npz["features"]]  # 22 names
        # timestamps are int64 ns since epoch for the naive local time
        self.ts_ns = npz["timestamps"].astype("int64")
        self.timestamps = pd.to_datetime(self.ts_ns)

    def nearest_index(self, at: Optional[pd.Timestamp]) -> int:
        """Index of the row nearest to `at` (default: latest row)."""
        if at is None or len(self.ts_ns) == 0:
            return len(self.ts_ns) - 1
        target = np.int64(pd.Timestamp(at).value)
        idx = int(np.searchsorted(self.ts_ns, target))
        if idx <= 0:
            return 0
        if idx >= len(self.ts_ns):
            return len(self.ts_ns) - 1
        # pick the closer of idx-1 / idx
        if abs(int(self.ts_ns[idx - 1]) - int(target)) <= abs(int(self.ts_ns[idx]) - int(target)):
            return idx - 1
        return idx

    def explain_row(self, at: Optional[pd.Timestamp]) -> dict:
        """Build the explain payload for the hour nearest to `at`."""
        i = self.nearest_index(at)
        rows = []
        for j, name in enumerate(self.features):
            contrib = float(self.values[i, j])
            rows.append({
                "feature": name,
                "label": FEATURE_LABELS.get(name, name.replace("_", " ").title()),
                "value": round(float(self.feature_values[i, j]), 3),
                "contribution_kw": round(contrib, 3),
                "direction": "up" if contrib >= 0 else "down",
            })
        rows.sort(key=lambda r: abs(r["contribution_kw"]), reverse=True)
        return {
            "at": self.timestamps[i].isoformat(),
            "base_kw": round(float(self.bias[i]), 1),
            "top": rows[:10],
            "all": rows,
        }


@lru_cache(maxsize=24)
def load_shap(site: str, horizon: int) -> ShapArchive:
    """Load data/v2/shap_<site>_h<h>.npz (cached per (site, horizon))."""
    if site not in site_ids():
        raise SiteNotFound(site)
    path = PROC_DIR / f"shap_{site}_h{int(horizon)}.npz"
    if not path.exists():
        raise DataNotFound(
            f"v2 SHAP archive missing for site '{site}' horizon {horizon}: "
            f"{path.relative_to(BASE)}")
    npz = np.load(path)
    arch = ShapArchive(site, int(horizon), npz)
    log.info("loaded SHAP for %s h=%s: %d rows x %d features",
             site, horizon, len(arch.ts_ns), len(arch.features))
    return arch


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def _alert_id(site: str, kind: str, ts: pd.Timestamp, horizon: int) -> str:
    """Deterministic alert id: stable across restarts and identical requests."""
    raw = f"{site}|h{horizon}|{kind}|{ts.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def compute_alerts(site: str, at: Optional[pd.Timestamp], hours: int,
                   horizon: int) -> dict:
    """Evaluate alert rules over the window ending at `at` (default latest).

    Rules (from docs/BUILD_CONTRACT.md):
      peak     - critical when the forecast is above the peak threshold;
                 warning within 3% of it
      surge    - high readiness R1–R2 (R1 warning, R2 info)
      variance - warning when actual load is outside the 95% forecast range

    The threshold and band come from the requested horizon's config block and
    the rows from that horizon's replay CSV.

    Returns at most 8 alerts, newest first, deduplicated by kind (the newest
    occurrence of each kind in the window wins).
    """
    site_cfg = get_site_horizon(site, horizon)
    df = load_replay(site, horizon)

    ts_max = df["timestamp"].iloc[-1]
    ts_min = df["timestamp"].iloc[0]
    if at is None:
        at = ts_max
    at = clamp_to_range(at, ts_min, ts_max)

    start = at - pd.Timedelta(hours=int(hours))
    window = df[(df["timestamp"] > start) & (df["timestamp"] <= at)]

    threshold = float(site_cfg["load"]["threshold_kw"])
    band = float(site_cfg["metrics"]["band_kw"])

    candidates: list[dict] = []
    for _, row in window.iterrows():
        ts = row["timestamp"]
        hybrid = float(row["hybrid_kw"])
        actual = float(row["actual_kw"])
        iso = ts.isoformat()

        # --- peak ---
        if hybrid > threshold:
            over = (hybrid - threshold) / threshold * 100.0
            candidates.append({
                "id": _alert_id(site, "peak", ts, horizon),
                "severity": "critical",
                "kind": "peak",
                "title": "Peak threshold exceeded",
                "detail": (f"Forecast {hybrid:,.1f} kW is above the "
                           f"{threshold:,.1f} kW peak threshold by {over:.1f}%"),
                "timestamp": iso,
                "_ts": ts,
            })
        elif hybrid >= threshold * 0.97:
            pct = hybrid / threshold * 100.0
            candidates.append({
                "id": _alert_id(site, "peak", ts, horizon),
                "severity": "warning",
                "kind": "peak",
                "title": "Approaching peak threshold",
                "detail": (f"Forecast {hybrid:,.1f} kW is at {pct:.1f}% of the "
                           f"{threshold:,.1f} kW peak threshold"),
                "timestamp": iso,
                "_ts": ts,
            })

        # --- high readiness (R1–R2) ---
        code = int(row["readiness_code"])
        if code <= 2:
            label = READINESS_NAMES.get(code, str(row["readiness_label"]).replace("_", " "))
            candidates.append({
                "id": _alert_id(site, "surge", ts, horizon),
                "severity": "warning" if code == 1 else "info",
                "kind": "surge",
                "title": f"{label} in effect",
                "detail": (f"Readiness level R{code} · {label.lower()} — actual "
                           f"load {actual:,.1f} kW"),
                "timestamp": iso,
                "_ts": ts,
            })

        # --- variance ---
        dev = abs(actual - hybrid)
        if dev > band:
            candidates.append({
                "id": _alert_id(site, "variance", ts, horizon),
                "severity": "warning",
                "kind": "variance",
                "title": "Actual load outside forecast range",
                "detail": (f"Actual {actual:,.1f} kW vs forecast {hybrid:,.1f} kW — "
                           f"{dev:,.1f} kW outside the ±{band:,.1f} kW range"),
                "timestamp": iso,
                "_ts": ts,
            })

    # Deduplicate by kind: keep the newest occurrence of each kind.
    newest_per_kind: dict[str, dict] = {}
    for c in candidates:
        kind = c["kind"]
        if kind not in newest_per_kind or c["_ts"] > newest_per_kind[kind]["_ts"]:
            newest_per_kind[kind] = c

    alerts = sorted(newest_per_kind.values(), key=lambda c: c["_ts"], reverse=True)
    for a in alerts:
        a.pop("_ts", None)
    return {
        "site": site,
        "horizon": int(horizon),
        "threshold_kw": threshold,
        "band_kw": band,
        "at": at.isoformat(),
        "alerts": alerts[:8],
    }


def count_alerts(site: str, start: Optional[pd.Timestamp],
                 end: Optional[pd.Timestamp], horizon: int) -> dict:
    """Raw occurrence counts of each rule in a window (used by the PDF)."""
    site_cfg = get_site_horizon(site, horizon)
    df = load_replay(site, horizon)
    window = df[window_mask(df, start, end)]

    threshold = float(site_cfg["load"]["threshold_kw"])
    band = float(site_cfg["metrics"]["band_kw"])

    hybrid = window["hybrid_kw"].to_numpy(dtype=float)
    actual = window["actual_kw"].to_numpy(dtype=float)
    readiness = window["readiness_code"].to_numpy(dtype=int)

    return {
        "peak_critical": int(np.sum(hybrid > threshold)),
        "peak_warning": int(np.sum((hybrid <= threshold) & (hybrid >= threshold * 0.97))),
        "surge": int(np.sum(readiness <= 2)),
        "variance": int(np.sum(np.abs(actual - hybrid) > band)),
        "rows": int(len(window)),
    }


# ---------------------------------------------------------------------------
# Fleet snapshot (map landing view)
# ---------------------------------------------------------------------------

def _nearest_row(df: pd.DataFrame, target: pd.Timestamp) -> Optional[pd.Series]:
    """Row nearest to `target` (hourly data → nearest hour). None if empty."""
    ts = df["timestamp"]
    if ts.empty:
        return None
    i = int(ts.searchsorted(target))
    if i >= len(df):
        i = len(df) - 1
    if i > 0 and abs(ts.iloc[i - 1] - target) <= abs(ts.iloc[i] - target):
        i -= 1
    return df.iloc[i]


def compute_fleet(at: Optional[pd.Timestamp], horizon: int) -> dict:
    """Fleet snapshot for the map landing view, for one forecast horizon.

    For every configured site resolve the *horizon's* replay row nearest to
    `at` (default: latest row) and summarise status/headroom plus fleet
    totals, using that horizon's threshold / metrics / cost block.
    A site whose data cannot be loaded or has no row is skipped and logged —
    never a 500.
    """
    site_cfgs = load_config()["sites"]

    # Load all sites (cached), tracking the global replay time range.
    frames: list[tuple[dict, pd.DataFrame]] = []
    lo: Optional[pd.Timestamp] = None
    hi: Optional[pd.Timestamp] = None
    for sc in site_cfgs:
        site = sc["id"]
        try:
            df = load_replay(site, horizon)
            if df.empty:
                raise StoreError("replay has no rows")
        except Exception as exc:  # noqa: BLE001 — never 500 the fleet view
            log.warning("fleet h=%s: skipping site '%s': %s", horizon, site, exc)
            continue
        frames.append((sc, df))
        t0, t1 = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
        lo = t0 if lo is None else min(lo, t0)
        hi = t1 if hi is None else max(hi, t1)

    if not frames:
        # Nothing to show: fail loudly instead of returning an empty 200.
        raise DataNotFound(
            f"no v2 replay data available for horizon {horizon} "
            f"({len(site_cfgs)} sites configured; see {PROC_DIR})")

    # Clamp the requested instant into the global replay range.
    if at is None:
        target = hi
    elif lo is not None:
        target = clamp_to_range(at, lo, hi)
    else:
        target = at  # nothing loaded; nothing to clamp against

    sites_out: list[dict] = []
    for sc, df in frames:
        site = sc["id"]
        try:
            hcfg = horizon_view(sc, horizon)
            t_site = clamp_to_range(target, df["timestamp"].iloc[0],
                                    df["timestamp"].iloc[-1]) \
                if target is not None else df["timestamp"].iloc[-1]
            row = _nearest_row(df, t_site)
            if row is None:
                log.warning("fleet: skipping site '%s': no row near %s",
                            site, target)
                continue

            threshold = float(hcfg["load"]["threshold_kw"])
            hybrid = float(row["hybrid_kw"])
            code = int(row["readiness_code"])
            if hybrid > threshold:
                status = "critical"
            elif hybrid >= threshold * 0.97:
                status = "warning"
            else:
                status = "nominal"

            sites_out.append({
                "id": site,
                "label": hcfg.get("label", site),
                "location": hcfg.get("location", ""),
                "type": hcfg.get("type", ""),
                "lat": float(hcfg.get("lat", 0.0)),
                "lon": float(hcfg.get("lon", 0.0)),
                "actual_kw": float(row["actual_kw"]),
                "hybrid_kw": hybrid,
                "threshold_kw": threshold,
                "headroom_kw": round(threshold - hybrid, 1),
                "readiness_code": code,
                "readiness_label": READINESS_NAMES.get(
                    code, str(row["readiness_label"]).replace("_", " ")),
                "mape": float(hcfg.get("metrics", {}).get("hyb_mape", 0.0)),
                "monthly_saving_zmw": int(
                    hcfg.get("cost", {}).get("monthly_saving_zmw", 0)),
                "status": status,
            })
        except Exception as exc:  # noqa: BLE001 — never 500 the fleet view
            log.warning("fleet h=%s: skipping site '%s': %s",
                        horizon, site, exc)

    totals = {
        "load_kw": round(sum(s["actual_kw"] for s in sites_out), 1),
        "peak_kw": round(max((s["hybrid_kw"] for s in sites_out), default=0.0), 1),
        "saving_zmw": sum(s["monthly_saving_zmw"] for s in sites_out),
        "sites_at_risk": sum(1 for s in sites_out
                             if s["status"] in ("critical", "warning")),
        "surge_sites": sum(1 for s in sites_out if s["readiness_code"] <= 2),
    }
    return {
        "horizon": int(horizon),
        "at": target.isoformat() if target is not None else None,
        "sites": sites_out,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Mid- to Long-Term (7, 14, 30, 60, 90 days) strategic forecasts
# ---------------------------------------------------------------------------

def resolve_midterm_horizon(value: Optional[Union[int, str]]) -> int:
    """Validate a `horizon_days` query param -> int in {7, 14, 30, 60, 90}."""
    if value is None or str(value).strip() == "":
        return DEFAULT_MIDTERM_HORIZON
    try:
        d = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BadHorizon(
            f"invalid midterm horizon '{value}'; expected one of {list(MIDTERM_HORIZONS)}"
        ) from exc
    if d not in MIDTERM_HORIZONS:
        raise BadHorizon(
            f"unknown midterm horizon {d}; available days: {list(MIDTERM_HORIZONS)}"
        )
    return d


@lru_cache(maxsize=1)
def load_midterm_metrics_df() -> pd.DataFrame:
    if not MIDTERM_METRICS_PATH.exists():
        raise DataNotFound(
            f"midterm metrics file missing: {MIDTERM_METRICS_PATH.relative_to(BASE)}"
        )
    return pd.read_csv(MIDTERM_METRICS_PATH)


@lru_cache(maxsize=36)
def load_midterm_replay(site: str, horizon_days: int) -> pd.DataFrame:
    if site not in site_ids():
        raise SiteNotFound(site)
    path = PROC_DIR / f"midterm_{site}_d{int(horizon_days)}.csv"
    if not path.exists():
        raise DataNotFound(
            f"midterm replay missing for site '{site}' d={horizon_days}: "
            f"{path.relative_to(BASE)}"
        )
    return pd.read_csv(path)


def get_site_midterm(site: str, horizon_days: int) -> dict:
    """Return daily series + full metric comparison for (site, horizon_days)."""
    sc = get_site(site)
    df_rep = load_midterm_replay(site, horizon_days)
    mdf = load_midterm_metrics_df()
    sub = mdf[(mdf["site"] == site) & (mdf["horizon_days"] == int(horizon_days))]

    metrics_by_target: dict[str, dict[str, dict]] = {
        "daily_mean_kw": {},
        "daily_peak_kw": {},
    }
    for _, row in sub.iterrows():
        tname = str(row["target"])
        mname = str(row["model"])
        if tname in metrics_by_target:
            metrics_by_target[tname][mname] = {
                "rmse": float(row["rmse"]),
                "mae": float(row["mae"]),
                "mape": float(row["mape"]),
                "wape": float(row.get("wape", 0.0)),
                "bias": float(row["bias"]),
                "peak_bias": float(row["peak_bias"]),
                "peak_mae": float(row["peak_mae"]),
                "cum_energy_bias_pct": float(row["cum_energy_bias_pct"]),
                "window_30d_mape": float(row["window_30d_mape"]),
                "monthly_peak_mae_kw": float(row["monthly_peak_mae_kw"]),
                "monthly_peak_mae_zmw": float(row["monthly_peak_mae_zmw"]),
                "picp_95": float(row["picp_95"]),
                "interval_halfwidth_kw": float(row["interval_halfwidth_kw"]),
                "skill_vs_persistence_pct": float(row["skill_vs_persistence_pct"]),
                "skill_vs_seasonal_pct": float(row["skill_vs_seasonal_pct"]),
                "selected_stage2": str(row.get("selected_stage2", mname)),
            }

    return {
        "site": site,
        "label": sc.get("label", site),
        "location": sc.get("location", ""),
        "type": sc.get("type", ""),
        "horizon_days": int(horizon_days),
        "available_horizons_days": list(MIDTERM_HORIZONS),
        "threshold_kw": float((sc.get("load") or {}).get("threshold_kw", 0.0)),
        "metrics": metrics_by_target,
        "rows": df_rep.to_dict(orient="records"),
    }


def get_midterm_overview(horizon_days: int) -> dict:
    """Return cross-site summary for a given mid/long-term horizon in days."""
    mdf = load_midterm_metrics_df()
    sub = mdf[(mdf["horizon_days"] == int(horizon_days)) & (mdf["model"] == "hybrid")]
    sites_summary = []
    for sc in load_config()["sites"]:
        sid = sc["id"]
        s_rows = sub[sub["site"] == sid]
        mean_r = s_rows[s_rows["target"] == "daily_mean_kw"]
        peak_r = s_rows[s_rows["target"] == "daily_peak_kw"]
        sites_summary.append({
            "id": sid,
            "label": sc.get("label", sid),
            "location": sc.get("location", ""),
            "mean_metrics": mean_r.iloc[0].to_dict() if len(mean_r) else {},
            "peak_metrics": peak_r.iloc[0].to_dict() if len(peak_r) else {},
        })
    return {
        "horizon_days": int(horizon_days),
        "available_horizons_days": list(MIDTERM_HORIZONS),
        "default_horizon_days": DEFAULT_MIDTERM_HORIZON,
        "sites": sites_summary,
    }
