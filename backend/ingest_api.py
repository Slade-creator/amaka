"""HTTP routes for live data ingestion (see backend/ingest.py).

Two kinds of caller:

* **People** (bearer token from /api/auth/login). Any signed-in role can read
  device status and live hourly data; adding sites, issuing enrolment codes,
  revoking kits and uploading CSVs are analyst tasks.
* **Meter kits** (device token from /api/devices/enroll). They can only post
  readings for the site they were enrolled to.

Routes
------
GET    /api/live/sites                      sites a kit can be enrolled to
POST   /api/live/sites                      add a new site (analyst)
GET    /api/live/sites/{site}/hourly        hourly kW + quality flags
POST   /api/live/sites/{site}/upload        CSV meter export (analyst)
GET    /api/devices                         kits and their health
POST   /api/devices/enrolment               one-time enrolment code (analyst)
DELETE /api/devices/{device_id}             revoke a kit (analyst)
POST   /api/devices/enroll                  kit: code → device token (no user login)
POST   /api/ingest                          kit: batch of readings (device token)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import auth, ingest

log = logging.getLogger("amaka.ingest")

router = APIRouter(tags=["live data"])
_bearer = HTTPBearer(auto_error=False)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _http(exc: ingest.IngestError) -> HTTPException:
    if isinstance(exc, ingest.Unauthorized):
        return HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"})
    if isinstance(exc, ingest.NotFound):
        return HTTPException(404, str(exc))
    return HTTPException(400, str(exc))


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@router.get("/api/live/sites", dependencies=[Depends(auth.current_user)])
def live_sites():
    return {"sites": ingest.list_sites()}


class SiteBody(BaseModel):
    id: str = Field(min_length=2, max_length=40, description="e.g. 'kabwe_barracks'")
    label: str = Field(min_length=2, max_length=80)
    location: str = Field(min_length=2, max_length=60)
    type: str = Field(default="Barracks", max_length=80)
    lat: float
    lon: float
    threshold_kw: float = Field(gt=0)
    headcount: Optional[int] = Field(default=None, ge=0)
    floor_area_m2: Optional[float] = Field(default=None, ge=0)
    pv_kwp: Optional[float] = Field(default=None, ge=0)


@router.post("/api/live/sites", status_code=201)
def add_site(body: SiteBody, user: auth.User = Depends(auth.require_roles("analyst"))):
    try:
        site = ingest.create_site(ingest.SiteProfile(**body.model_dump()), user.username)
    except ingest.IngestError as exc:
        raise _http(exc)
    log.info("site added: %s by %s", site["id"], user.username)
    return site


@router.get("/api/live/sites/{site}/hourly", dependencies=[Depends(auth.current_user)])
def live_hourly(site: str, hours: int = Query(168, ge=1, le=24 * 92)):
    try:
        return ingest.hourly(site, hours)
    except ingest.IngestError as exc:
        raise _http(exc)


@router.post("/api/live/sites/{site}/upload")
async def upload_csv(site: str, request: Request,
                     user: auth.User = Depends(auth.require_roles("analyst"))):
    """Raw CSV body (Content-Type text/csv). Needs a timestamp column and a kW
    column; timestamps without an offset are read as Zambian local time."""
    raw = await request.body()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "CSV larger than 20 MB; split it by month")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        result = ingest.store_csv(site, text, user.username)
    except ingest.IngestError as exc:
        raise _http(exc)
    log.info("csv upload for %s by %s: %s accepted, %s rejected",
             site, user.username, result["accepted"], result["rejected"])
    return result


# ---------------------------------------------------------------------------
# Devices (people)
# ---------------------------------------------------------------------------

@router.get("/api/devices", dependencies=[Depends(auth.current_user)])
def devices(site: Optional[str] = None):
    return {"devices": ingest.list_devices(site)}


class EnrolmentBody(BaseModel):
    site_id: str
    label: Optional[str] = Field(default=None, max_length=80,
                                 description="e.g. 'Main incomer, substation 2'")


@router.post("/api/devices/enrolment", status_code=201)
def new_enrolment(body: EnrolmentBody,
                  user: auth.User = Depends(auth.require_roles("analyst"))):
    try:
        out = ingest.create_enrolment(body.site_id, body.label, user.username)
    except ingest.IngestError as exc:
        raise _http(exc)
    log.info("enrolment code issued for %s by %s", body.site_id, user.username)
    return out


@router.delete("/api/devices/{device_id}")
def revoke(device_id: str, user: auth.User = Depends(auth.require_roles("analyst"))):
    try:
        ingest.revoke_device(device_id)
    except ingest.IngestError as exc:
        raise _http(exc)
    log.info("device revoked: %s by %s", device_id, user.username)
    return {"revoked": device_id}


# ---------------------------------------------------------------------------
# Meter kits
# ---------------------------------------------------------------------------

class EnrollBody(BaseModel):
    code: str = Field(min_length=8, max_length=20)
    device_id: str = Field(min_length=3, max_length=64,
                           description="Stable hardware id, e.g. the gateway serial")
    hardware: Optional[str] = Field(default=None, max_length=120)
    interval_s: Optional[int] = Field(default=None, ge=5, le=3600)


@router.post("/api/devices/enroll", status_code=201)
def enroll(body: EnrollBody, request: Request):
    """Kit enrolment. Rate limited like sign-in (5 bad codes / 5 min per address)."""
    client = request.client.host if request.client else "unknown"
    key = f"enroll:{client}"
    wait = auth.check_rate_limit(key)
    if wait is not None:
        raise HTTPException(429, f"Too many attempts. Try again in {wait} s.",
                            headers={"Retry-After": str(wait)})
    try:
        out = ingest.enroll(body.code, body.device_id, body.hardware, body.interval_s)
    except ingest.Unauthorized as exc:
        auth.record_failure(key)
        raise _http(exc)
    except ingest.IngestError as exc:
        raise _http(exc)
    auth.clear_failures(key)
    log.info("device enrolled: %s -> %s from %s", out["device_id"], out["site"]["id"], client)
    return out


def current_device(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
    if not token:
        raise HTTPException(401, "Device token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return ingest.device_for_token(token)
    except ingest.IngestError as exc:
        raise _http(exc)


class IngestBody(BaseModel):
    readings: list[dict] = Field(
        description="[{ts: ISO-8601 or epoch s, kw, kwh?, voltage_v?, pf?}, ...] — max 5000")


@router.post("/api/ingest")
def ingest_readings(body: IngestBody, device: dict = Depends(current_device)):
    try:
        result = ingest.store_readings(device, body.readings)
    except ingest.IngestError as exc:
        raise _http(exc)
    return {"device_id": device["id"], "site_id": device["site_id"], **result}
