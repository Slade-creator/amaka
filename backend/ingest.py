"""Live data ingestion: portable meter kits, enrolment and readings storage.

The research pipeline replays pre-computed forecasts from CSV files. This
module is the live path for real deployments: a portable meter kit (clamp-on
3-phase energy meter + small gateway) is plugged in at a site, enrolled with a
one-time code, and streams load readings to the API.

Flow
----
1. An analyst creates an **enrolment code** for a site (an existing fleet site,
   or a new site with its profile). The app shows it as a QR code.
2. The gateway scans/receives the code and calls ``enroll()``; it gets a
   **device token** bound to that site. Codes are single use and expire.
3. The gateway posts batches of readings with the device token. It buffers
   locally while offline and uploads the backlog later (store-and-forward), so
   duplicate timestamps are expected and ignored.
4. Readings are rolled up to hourly values with data-quality flags for the
   analyst (gaps, low coverage, flat line, spikes, zeros).

Storage is a single SQLite file (``data/live/ingest.db``, override with
``SENTINEL_INGEST_DB``): no extra service to install on a demo laptop, and the
schema maps directly onto TimescaleDB/PostgreSQL for a larger deployment.
Only hashes of codes and device tokens are stored.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from . import store

BASE = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("SENTINEL_INGEST_DB", BASE / "data" / "live" / "ingest.db"))

# Zambia has no daylight saving: local time is always UTC+2 (CAT).
LOCAL_TZ = timezone(timedelta(hours=2), "CAT")

CODE_TTL_S = 24 * 3600
MAX_BATCH = 5000
MAX_KW = 50_000.0            # sanity ceiling for one site (50 MW)
MAX_FUTURE_S = 300           # device clock may run at most 5 min ahead
MAX_PAST_DAYS = 400          # backlog older than this is rejected
DEFAULT_INTERVAL_S = 60

ONLINE_GRACE_S = 120         # online when last reading < 3 intervals + grace
STALE_AFTER_S = 3600         # stale until 1 h silent, then offline

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L
_SITE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class IngestError(Exception):
    """Bad input from a device or the analyst (maps to HTTP 400)."""


class NotFound(IngestError):
    """Unknown device / site / code (maps to HTTP 404)."""


class Unauthorized(IngestError):
    """Bad or revoked device token / enrolment code (maps to HTTP 401)."""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_sites (
    id            TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    location      TEXT NOT NULL,
    type          TEXT NOT NULL,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    threshold_kw  REAL NOT NULL,
    headcount     INTEGER,
    floor_area_m2 REAL,
    pv_kwp        REAL,
    created_at    INTEGER NOT NULL,
    created_by    TEXT
);
CREATE TABLE IF NOT EXISTS enrol_codes (
    code_hash   TEXT PRIMARY KEY,
    site_id     TEXT NOT NULL,
    label       TEXT,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    created_by  TEXT,
    used_at     INTEGER,
    device_id   TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,
    site_id       TEXT NOT NULL,
    label         TEXT,
    hardware      TEXT,
    interval_s    INTEGER NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    enrolled_at   INTEGER NOT NULL,
    revoked_at    INTEGER,
    last_seen     INTEGER,
    last_kw       REAL,
    last_batch_at INTEGER,
    readings      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS readings (
    device_id  TEXT NOT NULL,
    site_id    TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    kw         REAL NOT NULL,
    kwh        REAL,
    voltage_v  REAL,
    pf         REAL,
    PRIMARY KEY (device_id, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS readings_site_ts ON readings (site_id, ts);
"""

_lock = threading.Lock()
_initialised: set[str] = set()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    path = str(DB_PATH)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if path not in _initialised:
            with _lock:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                _initialised.add(path)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


def _iso(epoch: Optional[int]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, LOCAL_TZ).isoformat()


# ---------------------------------------------------------------------------
# Sites (fleet config sites + sites added in the field)
# ---------------------------------------------------------------------------

def _config_site(site_id: str) -> Optional[dict]:
    try:
        s = store.get_site(site_id)
    except store.SiteNotFound:
        return None
    load = s.get("load") or {}
    return {
        "id": s["id"], "label": s["label"], "location": s["location"],
        "type": s["type"], "lat": s["lat"], "lon": s["lon"],
        "threshold_kw": float(load.get("threshold_kw", 0.0)),
        "headcount": s.get("headcount"), "floor_area_m2": s.get("floor_area_m2"),
        "pv_kwp": s.get("pv_kwp"), "source": "fleet",
    }


def get_site(site_id: str) -> dict:
    cfg = _config_site(site_id)
    if cfg:
        return cfg
    with _db() as conn:
        row = conn.execute("SELECT * FROM live_sites WHERE id = ?", (site_id,)).fetchone()
    if row is None:
        raise NotFound(f"Unknown site '{site_id}'")
    out = dict(row)
    out["source"] = "field"
    out.pop("created_by", None)
    out["created_at"] = _iso(out["created_at"])
    return out


def list_sites() -> list[dict]:
    fleet = [_config_site(sid) for sid in store.site_ids()]
    with _db() as conn:
        rows = conn.execute("SELECT * FROM live_sites ORDER BY label").fetchall()
    field = []
    for r in rows:
        d = dict(r)
        d.pop("created_by", None)
        d["created_at"] = _iso(d["created_at"])
        d["source"] = "field"
        field.append(d)
    return [s for s in fleet if s] + field


@dataclass
class SiteProfile:
    id: str
    label: str
    location: str
    type: str
    lat: float
    lon: float
    threshold_kw: float
    headcount: Optional[int] = None
    floor_area_m2: Optional[float] = None
    pv_kwp: Optional[float] = None


def create_site(p: SiteProfile, created_by: str) -> dict:
    sid = p.id.strip().lower()
    if not _SITE_ID_RE.match(sid):
        raise IngestError("Site id must be 2–40 characters: lowercase letters, digits and '_', starting with a letter")
    if _config_site(sid):
        raise IngestError(f"'{sid}' is already a fleet site")
    # Zambia's bounding box (with a margin) — catches swapped lat/lon.
    if not (-18.5 <= p.lat <= -8.0 and 21.5 <= p.lon <= 34.0):
        raise IngestError("Coordinates must be inside Zambia (lat -18.5..-8, lon 21.5..34)")
    if not (0 < p.threshold_kw <= MAX_KW):
        raise IngestError("Peak threshold must be between 0 and 50,000 kW")
    with _db() as conn:
        if conn.execute("SELECT 1 FROM live_sites WHERE id = ?", (sid,)).fetchone():
            raise IngestError(f"Site '{sid}' already exists")
        conn.execute(
            "INSERT INTO live_sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, p.label.strip(), p.location.strip(), p.type.strip(), p.lat, p.lon,
             p.threshold_kw, p.headcount, p.floor_area_m2, p.pv_kwp, _now(), created_by),
        )
    return get_site(sid)


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

def _new_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    c = re.sub(r"[^A-Z0-9]", "", code.upper())
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else c


def create_enrolment(site_id: str, label: Optional[str], created_by: str) -> dict:
    """One-time code that lets one meter kit join `site_id` (valid 24 h)."""
    get_site(site_id)  # 404 on an unknown site
    code = _new_code()
    now = _now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO enrol_codes (code_hash, site_id, label, created_at, expires_at, created_by)"
            " VALUES (?,?,?,?,?,?)",
            (_hash(code), site_id, (label or "").strip() or None, now, now + CODE_TTL_S, created_by),
        )
    return {
        "code": code,
        "site_id": site_id,
        "label": label,
        "expires_at": _iso(now + CODE_TTL_S),
        # What the QR code encodes; the gateway adds the server origin it was given.
        "qr_payload": f"amaka://enroll?code={code}&site={site_id}",
    }


def enroll(code: str, device_id: str, hardware: Optional[str],
           interval_s: Optional[int]) -> dict:
    """Exchange an enrolment code for a device token. Returns the token once."""
    did = device_id.strip()
    if not re.match(r"^[A-Za-z0-9._:-]{3,64}$", did):
        raise IngestError("device_id must be 3–64 characters: letters, digits, '.', '_', ':' or '-'")
    interval = int(interval_s or DEFAULT_INTERVAL_S)
    if not (5 <= interval <= 3600):
        raise IngestError("interval_s must be between 5 and 3600 seconds")
    now = _now()
    token = "dev_" + secrets.token_urlsafe(32)
    with _db() as conn:
        row = conn.execute("SELECT * FROM enrol_codes WHERE code_hash = ?",
                           (_hash(normalize_code(code)),)).fetchone()
        if row is None or row["used_at"] is not None or row["expires_at"] < now:
            raise Unauthorized("Enrolment code is invalid, expired or already used")
        existing = conn.execute("SELECT revoked_at FROM devices WHERE id = ?", (did,)).fetchone()
        if existing is not None and existing["revoked_at"] is None:
            raise IngestError(f"Device '{did}' is already enrolled; revoke it first to move it")
        conn.execute("DELETE FROM devices WHERE id = ?", (did,))
        conn.execute(
            "INSERT INTO devices (id, site_id, label, hardware, interval_s, token_hash, enrolled_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (did, row["site_id"], row["label"], (hardware or "")[:120] or None, interval,
             _hash(token), now),
        )
        conn.execute("UPDATE enrol_codes SET used_at = ?, device_id = ? WHERE code_hash = ?",
                     (now, did, row["code_hash"]))
    site = get_site(row["site_id"])
    return {
        "device_id": did,
        "device_token": token,
        "site": {"id": site["id"], "label": site["label"], "lat": site["lat"], "lon": site["lon"]},
        "interval_s": interval,
        "ingest_path": "/api/ingest",
    }


def device_for_token(token: str) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE token_hash = ?", (_hash(token),)).fetchone()
    if row is None or row["revoked_at"] is not None:
        raise Unauthorized("Device token is invalid or revoked")
    return dict(row)


def revoke_device(device_id: str) -> None:
    with _db() as conn:
        cur = conn.execute("UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                           (_now(), device_id))
        if cur.rowcount == 0:
            raise NotFound(f"No active device '{device_id}'")


# ---------------------------------------------------------------------------
# Readings
# ---------------------------------------------------------------------------

def parse_ts(value: object) -> int:
    """ISO-8601 (offset required, or 'Z') or epoch seconds → epoch seconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError("timestamp is not finite")
        return int(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Meter exports from the field are in local time (CAT, UTC+2).
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return int(dt.timestamp())


def _num(value: object, name: str, lo: float, hi: float, required: bool) -> Optional[float]:
    if value is None or value == "":
        if required:
            raise ValueError(f"missing {name}")
        return None
    v = float(value)  # ValueError on junk
    if not math.isfinite(v) or not (lo <= v <= hi):
        raise ValueError(f"{name} {v} out of range {lo}..{hi}")
    return v


def store_readings(device: dict, readings: Iterable[dict]) -> dict:
    """Validate and store one batch. Duplicates (same device + timestamp) are
    ignored, so a gateway can safely re-send its offline backlog."""
    batch = list(readings)
    if not batch:
        raise IngestError("Empty batch")
    if len(batch) > MAX_BATCH:
        raise IngestError(f"Batch too large ({len(batch)} > {MAX_BATCH}); split it")
    now = _now()
    oldest_ok = now - MAX_PAST_DAYS * 86400
    rows, errors = [], []
    for i, r in enumerate(batch):
        try:
            if not isinstance(r, dict):
                raise ValueError("reading must be an object")
            ts = parse_ts(r.get("ts", r.get("timestamp")))
            if ts > now + MAX_FUTURE_S:
                raise ValueError("timestamp is in the future (check the gateway clock)")
            if ts < oldest_ok:
                raise ValueError(f"timestamp older than {MAX_PAST_DAYS} days")
            kw = _num(r.get("kw"), "kw", 0.0, MAX_KW, True)
            kwh = _num(r.get("kwh"), "kwh", 0.0, 1e12, False)
            volt = _num(r.get("voltage_v"), "voltage_v", 0.0, 50_000.0, False)
            pf = _num(r.get("pf"), "pf", -1.0, 1.0, False)
            rows.append((device["id"], device["site_id"], ts, kw, kwh, volt, pf))
        except (ValueError, TypeError) as exc:
            if len(errors) < 20:
                errors.append({"index": i, "error": str(exc)})
            else:
                errors.append(None)
    accepted = 0
    with _db() as conn:
        if rows:
            before = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO readings VALUES (?,?,?,?,?,?,?)", rows)
            accepted = conn.total_changes - before
            latest = max(rows, key=lambda x: x[2])
            conn.execute(
                "UPDATE devices SET readings = readings + ?, last_batch_at = ?,"
                " last_seen = MAX(COALESCE(last_seen, 0), ?),"
                " last_kw = CASE WHEN ? >= COALESCE(last_seen, 0) THEN ? ELSE last_kw END"
                " WHERE id = ?",
                (accepted, now, latest[2], latest[2], latest[3], device["id"]),
            )
        else:
            conn.execute("UPDATE devices SET last_batch_at = ? WHERE id = ?", (now, device["id"]))
    rejected = len(batch) - len(rows)
    return {
        "received": len(batch),
        "accepted": accepted,
        "duplicates": len(rows) - accepted,
        "rejected": rejected,
        "errors": [e for e in errors if e is not None],
    }


def upload_device(site_id: str, user: str) -> dict:
    """Pseudo-device that owns CSV uploads for a site (one per site)."""
    get_site(site_id)
    did = f"upload:{site_id}"
    with _db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (did,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO devices (id, site_id, label, hardware, interval_s, token_hash, enrolled_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (did, site_id, "CSV uploads", f"manual upload by {user}", 3600,
                 _hash(secrets.token_urlsafe(32)), _now()),
            )
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (did,)).fetchone()
    return dict(row)


_TS_COLS = ("timestamp", "ts", "time", "datetime", "date_time", "reading_time")
_KW_COLS = ("kw", "load_kw", "power_kw", "demand_kw", "active_power_kw", "actual_kw")


def parse_csv(text: str) -> list[dict]:
    """Meter-export / billing CSV → readings. Needs a timestamp and a kW column."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise IngestError("CSV has no header row")
    cols = {c.strip().lower(): c for c in reader.fieldnames if c}
    ts_col = next((cols[c] for c in _TS_COLS if c in cols), None)
    kw_col = next((cols[c] for c in _KW_COLS if c in cols), None)
    if not ts_col or not kw_col:
        raise IngestError(
            "CSV needs a timestamp column (" + ", ".join(_TS_COLS) + ") and a kW column ("
            + ", ".join(_KW_COLS) + ")")
    out = []
    for row in reader:
        out.append({"ts": (row.get(ts_col) or "").strip(), "kw": (row.get(kw_col) or "").strip()})
        if len(out) > 200_000:
            raise IngestError("CSV too large (over 200,000 rows); split it by month")
    if not out:
        raise IngestError("CSV has no data rows")
    return out


def store_csv(site_id: str, text: str, user: str) -> dict:
    dev = upload_device(site_id, user)
    readings = parse_csv(text)
    totals = {"received": 0, "accepted": 0, "duplicates": 0, "rejected": 0, "errors": []}
    for i in range(0, len(readings), MAX_BATCH):
        res = store_readings(dev, readings[i:i + MAX_BATCH])
        for k in ("received", "accepted", "duplicates", "rejected"):
            totals[k] += res[k]
        totals["errors"].extend({**e, "index": e["index"] + i} for e in res["errors"])
    totals["errors"] = totals["errors"][:20]
    return totals


# ---------------------------------------------------------------------------
# Device status and hourly roll-ups with quality flags
# ---------------------------------------------------------------------------

def _status(dev: dict, now: int) -> str:
    if dev.get("revoked_at"):
        return "revoked"
    if dev["id"].startswith("upload:"):
        return "manual"
    seen = dev.get("last_seen")
    if not seen:
        return "waiting"           # enrolled, nothing received yet
    age = now - seen
    if age <= 3 * dev["interval_s"] + ONLINE_GRACE_S:
        return "online"
    if age <= STALE_AFTER_S:
        return "stale"
    return "offline"


def list_devices(site_id: Optional[str] = None) -> list[dict]:
    now = _now()
    q = "SELECT * FROM devices"
    args: tuple = ()
    if site_id:
        q += " WHERE site_id = ?"
        args = (site_id,)
    with _db() as conn:
        rows = [dict(r) for r in conn.execute(q + " ORDER BY site_id, id", args).fetchall()]
        day_ago = now - 86400
        counts = {
            r["device_id"]: r["n"]
            for r in conn.execute(
                "SELECT device_id, COUNT(*) AS n FROM readings WHERE ts >= ? GROUP BY device_id",
                (day_ago,),
            ).fetchall()
        }
    labels = {s["id"]: s["label"] for s in list_sites()}
    out = []
    for d in rows:
        expected = 86400 / d["interval_s"]
        n24 = counts.get(d["id"], 0)
        out.append({
            "id": d["id"],
            "site_id": d["site_id"],
            "site_label": labels.get(d["site_id"], d["site_id"]),
            "label": d["label"],
            "hardware": d["hardware"],
            "interval_s": d["interval_s"],
            "status": _status(d, now),
            "enrolled_at": _iso(d["enrolled_at"]),
            "revoked_at": _iso(d["revoked_at"]),
            "last_seen": _iso(d["last_seen"]),
            "last_seen_age_s": (now - d["last_seen"]) if d["last_seen"] else None,
            "last_kw": d["last_kw"],
            "readings_total": d["readings"],
            "readings_24h": n24,
            "coverage_24h_pct": None if d["id"].startswith("upload:")
            else round(min(100.0, 100.0 * n24 / expected), 1),
        })
    return out


def hourly(site_id: str, hours: int = 168, end: Optional[int] = None) -> dict:
    """Hourly mean kW for a site with quality flags per hour.

    Flags: ``gap`` (no readings), ``low_coverage`` (<80% of expected samples),
    ``flatline`` (identical values all hour — stuck meter or CT off),
    ``zero`` (0 kW all hour — breaker open or clamp unplugged),
    ``spike`` (hour mean over 3× the window median)."""
    site = get_site(site_id)
    hours = max(1, min(int(hours), 24 * 92))
    with _db() as conn:
        devs = conn.execute(
            "SELECT id, interval_s FROM devices WHERE site_id = ?", (site_id,)).fetchall()
        if end is None:
            last = conn.execute("SELECT MAX(ts) AS m FROM readings WHERE site_id = ?",
                                (site_id,)).fetchone()["m"]
            end = last if last else _now()
        end_h = (int(end) // 3600 + 1) * 3600       # exclusive, aligned to the hour
        start_h = end_h - hours * 3600
        rows = conn.execute(
            "SELECT ts, kw FROM readings WHERE site_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (site_id, start_h, end_h),
        ).fetchall()
    interval = min((d["interval_s"] for d in devs if not d["id"].startswith("upload:")),
                   default=3600)
    expected = max(1, 3600 // interval)

    buckets: dict[int, list[float]] = {}
    for r in rows:
        buckets.setdefault(r["ts"] // 3600 * 3600, []).append(r["kw"])
    means = [statistics.fmean(v) for v in buckets.values()]
    median = statistics.median(means) if means else 0.0

    out, flagged = [], {"gap": 0, "low_coverage": 0, "flatline": 0, "zero": 0, "spike": 0}
    for h in range(start_h, end_h, 3600):
        vals = buckets.get(h, [])
        flags = []
        if not vals:
            flags.append("gap")
            mean = peak = None
        else:
            mean = statistics.fmean(vals)
            peak = max(vals)
            if len(vals) < 0.8 * expected and expected > 1:
                flags.append("low_coverage")
            if len(vals) >= 10 and max(vals) - min(vals) < 1e-9:
                flags.append("zero" if mean == 0 else "flatline")
            elif mean == 0:
                flags.append("zero")
            if median > 0 and mean > 3 * median:
                flags.append("spike")
        for f in flags:
            flagged[f] += 1
        out.append({
            "hour": _iso(h),
            "mean_kw": None if mean is None else round(mean, 2),
            "peak_kw": None if peak is None else round(peak, 2),
            "samples": len(vals),
            "expected": expected,
            "over_threshold": bool(mean is not None and mean > site["threshold_kw"]),
            "flags": flags,
        })
    with_data = hours - flagged["gap"]
    return {
        "site": {"id": site["id"], "label": site["label"], "threshold_kw": site["threshold_kw"]},
        "from": _iso(start_h),
        "to": _iso(end_h),
        "hours": hours,
        "completeness_pct": round(100.0 * with_data / hours, 1),
        "flag_counts": flagged,
        "rows": out,
    }
