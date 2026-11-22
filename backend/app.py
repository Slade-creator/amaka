"""AMAKA FastAPI application (v2 research pipeline, multi-horizon).

Run from the prototype root:
    python -m uvicorn backend.app:app --port 8000

Data sources (see docs/V2_DASHBOARD_CONTRACT.md):
    config/v2_sites.json
    data/v2/replay_<site>_h<h>.csv   h ∈ {1, 6, 24, 48}
    data/v2/shap_<site>_h<h>.npz
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth, ingest_api, narrate, reports, store, live_api
from .settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("amaka.app")

BASE = Path(__file__).resolve().parents[1]
DIST_DIR = BASE / "frontend" / "dist"

HORIZON_DESC = ("Forecast horizon in hours: 1, 6, 24 or 48 "
                "(default = config default_horizon)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = store.load_config()
    sites = [s["id"] for s in cfg["sites"]]
    horizons = store.available_horizons()
    log.info("=" * 60)
    log.info("AMAKA backend starting (pipeline %s)",
             cfg.get("version", "v2"))
    log.info("  model      : %s", cfg["model"]["name"])
    log.info("  horizons   : %s (default %s)", horizons,
             store.default_horizon())
    log.info("  sites      : %d (%s)", len(sites), ", ".join(sites))
    log.info("  test period: %s .. %s", cfg["test_period"]["start"],
             cfg["test_period"]["end"])
    log.info("  config     : %s", store.CONFIG_PATH.relative_to(BASE))
    log.info("  data dir   : %s", store.PROC_DIR.relative_to(BASE))
    created = auth.ensure_seed_users()
    if created:
        log.info("  accounts   : created %d demo accounts from %s", created,
                 auth.SEED_PATH.relative_to(BASE))
    log.info("  auth       : %s (%d accounts)",
             "bearer token required" if auth.auth_required() else "OFF (SENTINEL_AUTH=off)",
             len(auth.list_users()))
    nc = narrate.capabilities()
    log.info("  narrative  : %s",
             f"{nc['provider']}:{nc['model']}" if nc["configured"]
             else "rules only (no model configured)")
    log.info("  frontend   : %s", "dist found — serving at /" if DIST_DIR.exists()
             else "dist absent — API-only root response")
    log.info("=" * 60)
    # Pre-warm matplotlib (imports + font cache) so the first PDF export
    # during the demo is fast. Never let this kill startup.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: F401
        log.info("  matplotlib pre-warmed for PDF reports")
    except Exception as exc:
        log.warning("matplotlib unavailable, PDFs render without charts: %s", exc)
    yield


app = FastAPI(
    title="AMAKA API",
    version="0.3.0",
    description="AI energy-demand forecasting backend for the AMAKA "
                "prototype (v2 research pipeline: direct multi-horizon "
                "1 / 6 / 24 / 48 hours ahead, synthetic demo data). Every "
                "data endpoint accepts a `horizon` query parameter.",
    lifespan=lifespan,
)

# Local Vite dev server + Capacitor WebView origins. Native builds run from
# https://localhost on Android (androidScheme) and capacitor://localhost on iOS,
# and call this API cross-origin. Extra origins (for example a deployed web
# frontend) can be appended with SENTINEL_ALLOWED_ORIGINS as a comma-separated
# list, e.g. "https://amaka.example.com".
# Origins come from backend/settings.py (SENTINEL_ALLOWED_ORIGINS adds more).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.exception_handler(store.SiteNotFound)
async def site_not_found_handler(_req: Request, exc: store.SiteNotFound):
    return JSONResponse(
        status_code=404,
        content={"detail": f"Unknown site '{exc.args[0] if exc.args else exc}'. "
                           f"Available sites: {', '.join(store.site_ids())}"},
    )


@app.exception_handler(store.BadDate)
async def bad_date_handler(_req: Request, exc: store.BadDate):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(store.BadHorizon)
async def bad_horizon_handler(_req: Request, exc: store.BadHorizon):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(store.DataNotFound)
async def data_not_found_handler(_req: Request, exc: store.DataNotFound):
    """A v2 data file is missing for an otherwise valid (site, horizon).
    Clear 404 — never a silent fallback to v1 data."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(store.StoreError)
async def store_error_handler(_req: Request, exc: store.StoreError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


def _http_400(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _horizon(horizon: Optional[str]) -> int:
    """Validate the `horizon` query param → int (400 on anything unknown)."""
    try:
        return store.resolve_horizon(horizon)
    except store.BadHorizon as exc:
        raise _http_400(str(exc))


def _site_or_404(site: str) -> dict:
    try:
        return store.get_site(site)
    except store.SiteNotFound:
        raise store.SiteNotFound(site)


def _parse_range(from_: Optional[str], to_: Optional[str]):
    """Parse from/to query params → (start, end) timestamps or raise 400."""
    try:
        start = store.parse_date(from_, param="from")
        end = store.parse_date(to_, param="to")
    except store.BadDate as exc:
        raise _http_400(str(exc))
    if start is not None and end is not None and start > end:
        raise _http_400(
            f"'from' ({start.isoformat()}) must not be later than "
            f"'to' ({end.isoformat()})")
    return start, end


# ---------------------------------------------------------------------------
# API routes (registered before the static mount so /api always wins)
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    cfg = store.load_config()
    return {
        "status": "ok",
        "version": cfg.get("version", "v2"),
        "horizons": store.available_horizons(),
        "default_horizon": store.default_horizon(),
        "sites": len(cfg["sites"]),
        "generated_at": cfg.get("generated_at"),
        "narrative": narrate.capabilities(),
        "auth_required": auth.auth_required(),
    }


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request):
    """Exchange a username and password for a bearer token.

    Five failed attempts per username or client address within five minutes
    lock that key out for the rest of the window (HTTP 429)."""
    uname = auth.normalize_username(body.username)
    client = request.client.host if request.client else "unknown"
    keys = (f"user:{uname}", f"ip:{client}")
    wait = auth.check_rate_limit(*keys)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed sign-in attempts. Try again in {wait} s.",
            headers={"Retry-After": str(wait)})
    user = auth.authenticate(uname, body.password)
    if user is None:
        auth.record_failure(*keys)
        log.info("login failed for %r from %s", uname, client)
        raise HTTPException(status_code=401,
                            detail="Incorrect username or password")
    auth.clear_failures(*keys)
    log.info("login ok: %s (%s) from %s", user.username, user.role, client)
    return auth.issue_token(user)


@app.get("/api/auth/me")
def me(user: auth.User = Depends(auth.current_user)):
    """The signed-in account (used by clients to restore a saved session)."""
    return {"user": user.public(), "auth_required": auth.auth_required()}


@app.get("/api/overview", dependencies=[Depends(auth.current_user)])
def overview(horizon: Optional[str] = Query(
    None, description=HORIZON_DESC)):
    """Full config for one horizon: every site's top-level metrics / load /
    cost / alerts come from `site.horizons[horizon]`, while the nested
    `horizons` map, `available_horizons`, `default_horizon`,
    `fleet_anchor_by_horizon` and `fleet_anchor` are preserved."""
    h = _horizon(horizon)
    cfg = store.load_config()

    # Shallow copy only: the cached config itself is never mutated.
    out = dict(cfg)
    out["sites"] = [store.horizon_view(s, h) for s in cfg["sites"]]
    out["version"] = cfg.get("version", "v2")
    out["horizon"] = h
    out["available_horizons"] = store.available_horizons()
    out["default_horizon"] = store.default_horizon()
    anchors = cfg.get("fleet_anchor_by_horizon") or {}
    out["fleet_anchor_by_horizon"] = anchors
    out["fleet_anchor"] = (anchors.get(str(h))
                           or cfg.get("fleet_anchor"))
    out["served_at"] = store.now_iso()
    return out


@app.get("/api/fleet", dependencies=[Depends(auth.current_user)])
def fleet(at: Optional[str] = Query(None),
          horizon: Optional[str] = Query(None, description=HORIZON_DESC)):
    """Fleet map snapshot for one horizon: one nearest-hour row per site
    (from that horizon's replay) plus totals."""
    h = _horizon(horizon)
    try:
        ts = store.parse_date(at, param="at")
    except store.BadDate as exc:
        raise _http_400(str(exc))
    return store.compute_fleet(ts, h)


@app.get("/api/sites/{site}/series", dependencies=[Depends(auth.current_user)])
def series(site: str,
           horizon: Optional[str] = Query(None, description=HORIZON_DESC),
           from_: Optional[str] = Query(None, alias="from"),
           to: Optional[str] = Query(None, alias="to")):
    _site_or_404(site)
    h = _horizon(horizon)
    start, end = _parse_range(from_, to)

    df = store.load_replay(site, h)
    ts_min, ts_max = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    # Clamp out-of-range bounds rather than failing (never 500 on dates).
    if start is not None:
        start = store.clamp_to_range(start, ts_min, ts_max)
    if end is not None:
        end = store.clamp_to_range(end, ts_min, ts_max)

    mask = store.window_mask(df, start, end)
    window = df[mask]

    rows = window.copy()
    rows["timestamp"] = rows["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "site": site,
        "horizon": h,
        "rows": rows.to_dict(orient="records"),
    }


@app.get("/api/sites/{site}/explain", dependencies=[Depends(auth.current_user)])
def explain(site: str,
            at: Optional[str] = Query(None),
            horizon: Optional[str] = Query(None, description=HORIZON_DESC)):
    _site_or_404(site)
    h = _horizon(horizon)
    try:
        ts = store.parse_date(at, param="at")
    except store.BadDate as exc:
        raise _http_400(str(exc))

    archive = store.load_shap(site, h)
    if len(archive.ts_ns) == 0:
        raise _http_400(f"no SHAP data for site '{site}'")
    result = archive.explain_row(ts)
    return {"site": site, "horizon": h, **result}


@app.get("/api/sites/{site}/narrative", dependencies=[Depends(auth.current_user)])
async def narrative(site: str,
                    at: Optional[str] = Query(None),
                    horizon: Optional[str] = Query(None,
                                                   description=HORIZON_DESC),
                    from_: Optional[str] = Query(None, alias="from"),
                    to: Optional[str] = Query(None),
                    role: str = Query("operator"),
                    mode: str = Query(
                        "auto",
                        description="auto = grounded model prose with a rule "
                                    "fallback; fast = rules only, no model call"),
                    user: auth.User = Depends(auth.current_user)):
    """Grounded explanation of the visible chart window and selected hour.

    Facts are computed server-side; the model only writes prose from them.
    `mode=fast` never calls the model (used for the immediate UI pass)."""
    _site_or_404(site)
    h = _horizon(horizon)
    try:
        ts = store.parse_date(at, param="at")
    except store.BadDate as exc:
        raise _http_400(str(exc))
    start, end = _parse_range(from_, to)
    if auth.auth_required():
        role = user.role  # the account's role decides the narrative voice
    try:
        role_norm = narrate.normalize_role(role)
        mode_norm = narrate.normalize_mode(mode)
    except ValueError as exc:
        raise _http_400(str(exc))
    return await narrate.narrative(
        site, h, ts, start, end, role_norm, use_model=(mode_norm == "auto"))


class NarrativeAskRequest(BaseModel):
    """Free-text question about the chart, scoped to the same window/facts."""

    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(min_length=3, max_length=280)
    at: Optional[str] = None
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    horizon: Optional[int] = None
    role: Optional[str] = "operator"


@app.post("/api/sites/{site}/narrative/ask", dependencies=[Depends(auth.require_roles("operator", "analyst"))])
async def narrative_ask(site: str, body: NarrativeAskRequest,
                        user: auth.User = Depends(auth.current_user)):
    """Answer a question about the chart using only the computed fact pack."""
    _site_or_404(site)
    h = _horizon(body.horizon)
    try:
        ts = store.parse_date(body.at, param="at")
    except store.BadDate as exc:
        raise _http_400(str(exc))
    start, end = _parse_range(body.from_, body.to)
    try:
        role_norm = narrate.normalize_role(
            user.role if auth.auth_required() else body.role)
    except ValueError as exc:
        raise _http_400(str(exc))
    return await narrate.answer(
        site, h, ts, start, end, role_norm, body.question)


@app.get("/api/sites/{site}/alerts", dependencies=[Depends(auth.current_user)])
def alerts(site: str,
           at: Optional[str] = Query(None),
           hours: int = Query(24, ge=1, le=24 * 180),
           horizon: Optional[str] = Query(None, description=HORIZON_DESC)):
    _site_or_404(site)
    h = _horizon(horizon)
    try:
        ts = store.parse_date(at, param="at")
    except store.BadDate as exc:
        raise _http_400(str(exc))
    return store.compute_alerts(site, ts, hours, h)


@app.get("/api/midterm/overview", dependencies=[Depends(auth.current_user)])
def midterm_overview(horizon_days: Optional[str] = Query(
    None, description="Mid/long-term horizon in days: 7, 14, 30, 60 or 90")):
    try:
        d = store.resolve_midterm_horizon(horizon_days)
    except store.BadHorizon as exc:
        raise _http_400(str(exc))
    return store.get_midterm_overview(d)


@app.get("/api/sites/{site}/midterm", dependencies=[Depends(auth.current_user)])
def site_midterm(site: str,
                 horizon_days: Optional[str] = Query(
                     None, description="Mid/long-term horizon in days: 7, 14, 30, 60 or 90")):
    _site_or_404(site)
    try:
        d = store.resolve_midterm_horizon(horizon_days)
    except store.BadHorizon as exc:
        raise _http_400(str(exc))
    return store.get_site_midterm(site, d)


@app.get("/api/sites/{site}/report.csv", dependencies=[Depends(auth.current_user)])
def report_csv(site: str,
               horizon: Optional[str] = Query(None, description=HORIZON_DESC),
               from_: Optional[str] = Query(None, alias="from"),
               to: Optional[str] = Query(None, alias="to")):
    _site_or_404(site)
    h = _horizon(horizon)
    start, end = _parse_range(from_, to)
    try:
        text = reports.build_csv(site, start, end, h)
    except ValueError as exc:
        raise _http_400(str(exc))
    if not text.strip() or text.strip().count("\n") == 0:
        raise _http_400("No rows in the selected range; adjust from/to.")
    # Count data rows (exclude header)
    if len(text.strip().splitlines()) <= 1:
        raise _http_400("No rows in the selected range; adjust from/to.")
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="amaka_{site}_h{h}_report.csv"'
        },
    )


@app.get("/api/sites/{site}/report.pdf", dependencies=[Depends(auth.current_user)])
def report_pdf(site: str,
               horizon: Optional[str] = Query(None, description=HORIZON_DESC),
               from_: Optional[str] = Query(None, alias="from"),
               to: Optional[str] = Query(None, alias="to")):
    _site_or_404(site)
    h = _horizon(horizon)
    start, end = _parse_range(from_, to)
    try:
        pdf = reports.build_pdf(site, start, end, h)
    except ValueError as exc:
        raise _http_400(str(exc))
    if not pdf.startswith(b"%PDF"):
        raise HTTPException(status_code=500, detail="PDF generation failed")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="amaka_{site}_h{h}_report.pdf"'
        },
    )


# Live data ingestion: meter kits, enrolment, CSV uploads (backend/ingest_api.py).
app.include_router(ingest_api.router)
app.include_router(live_api.router)


# Catch-all for unknown /api paths → JSON 404 (before the static mount).
@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT",
                                                  "PATCH", "DELETE", "HEAD"])
async def api_not_found(full_path: str):
    return JSONResponse(
        status_code=404,
        content={"detail": f"Unknown API endpoint /api/{full_path}. "
                           "See /docs for the API contract."},
    )


# ---------------------------------------------------------------------------
# Frontend static serving (registered last so every route above wins)
# ---------------------------------------------------------------------------

def _index_file() -> Optional[Path]:
    if DIST_DIR.is_dir() and (DIST_DIR / "index.html").is_file():
        return DIST_DIR / "index.html"
    return None


@app.get("/")
def root():
    idx = _index_file()
    if idx is not None:
        return FileResponse(idx)
    # Friendly API-only landing page when frontend/dist is absent.
    return JSONResponse({
        "service": "AMAKA backend",
        "status": "ok",
        "version": store.load_config().get("version", "v2"),
        "message": "frontend/dist is not built yet — API is live (v2 "
                   "research pipeline, direct multi-horizon forecasts).",
        "horizons": store.available_horizons(),
        "default_horizon": store.default_horizon(),
        "horizon_param": "every data endpoint accepts ?horizon=1|6|24|48 "
                         "(default = default_horizon)",
        "endpoints": [
            "GET /api/health",
            "POST /api/auth/login",
            "GET /api/auth/me",
            "GET /api/overview?horizon=",
            "GET /api/fleet?at=&horizon=",
            "GET /api/sites/{site}/series?horizon=&from=&to=",
            "GET /api/sites/{site}/explain?horizon=&at=",
            "GET /api/sites/{site}/narrative?horizon=&at=&from=&to=&role=&mode=",
            "POST /api/sites/{site}/narrative/ask",
            "GET /api/sites/{site}/alerts?horizon=&at=&hours=24",
            "GET /api/sites/{site}/report.csv?horizon=&from=&to=",
            "GET /api/sites/{site}/report.pdf?horizon=&from=&to=",
            "GET /docs",
        ],
        "sites": store.site_ids(),
    })


@app.get("/{full_path:path}")
def spa(full_path: str, request: Request):
    """SPA fallback: serve real files from dist, else index.html.
    Unknown /api paths never reach here (handled above)."""
    idx = _index_file()
    if idx is None:
        # dist absent — JSON 404 for unknown paths, helpful root handled above.
        return JSONResponse(
            status_code=404,
            content={"detail": f"Not found: /{full_path} "
                               "(frontend/dist is not built)"},
        )
    # Serve the exact file when it exists (assets, favicon, …).
    candidate = (DIST_DIR / full_path).resolve()
    try:
        candidate.relative_to(DIST_DIR.resolve())
    except ValueError:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    # Unknown non-file path → hand the SPA shell to the router.
    return FileResponse(idx)
