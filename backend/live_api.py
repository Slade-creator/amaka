"""Live forecast route: the trained v2 models on real ingested readings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from . import auth, ingest, live_forecast

router = APIRouter()


@router.get("/api/live/sites/{site}/forecast", dependencies=[Depends(auth.current_user)])
def live_site_forecast(
    site: str,
    readiness: int = Query(4, ge=1, le=4, description="Readiness level R1–R4 for the next 48 h"),
    maintenance: int = Query(0, ge=0, le=1, description="1 if planned maintenance cuts load"),
):
    """48-hour forecast from live meter/SCADA readings (see backend/live_forecast.py)."""
    try:
        return live_forecast.forecast(site, readiness=readiness, maintenance=maintenance)
    except ingest.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except live_forecast.NotEnoughData as exc:
        raise HTTPException(status_code=409, detail=str(exc))
