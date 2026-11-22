"""Central configuration for the AMAKA backend.

Every environment variable and tunable constant lives here, read once at
import. Modules import `settings` instead of calling os.environ or defining
their own magic numbers, so deployment config is one file to read and the
tests can point the whole backend somewhere else with env vars.

Environment variables (names unchanged since before the AMAKA rename, so
existing deployments keep working):

    SENTINEL_AUTH=off              turn authentication off (local research runs only)
    SENTINEL_JWT_SECRET            token signing secret (else generated into config/.jwt_secret)
    SENTINEL_TOKEN_TTL_HOURS=12    session length
    SENTINEL_USERS_FILE            accounts file (default config/users.json)
    SENTINEL_DEMO_USERS=0          do not create demo accounts on first start
    SENTINEL_ALLOWED_ORIGINS       extra CORS origins, comma separated
    SENTINEL_LLM_*                 chart-explanation model (see backend/narrate.py)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "off", "false", "no", "")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class AuthSettings:
    required: bool = field(default_factory=lambda: _flag("SENTINEL_AUTH", True))
    demo_users: bool = field(default_factory=lambda: _flag("SENTINEL_DEMO_USERS", True))
    users_file: Path = field(default_factory=lambda: Path(
        os.environ.get("SENTINEL_USERS_FILE", BASE / "config" / "users.json")))
    seed_file: Path = BASE / "config" / "users.seed.json"
    secret_file: Path = BASE / "config" / ".jwt_secret"
    jwt_secret: str = field(default_factory=lambda: os.environ.get("SENTINEL_JWT_SECRET", "").strip())
    roles: tuple[str, ...] = ("commander", "operator", "analyst")
    algorithm: str = "HS256"
    issuer: str = "amaka-api"
    #: Tokens signed before the SENTINEL -> AMAKA rename stay valid until they expire.
    legacy_issuers: tuple[str, ...] = ("sentinel-api",)
    token_ttl_s: int = field(default_factory=lambda: _int("SENTINEL_TOKEN_TTL_HOURS", 12) * 3600)
    pbkdf2_iterations: int = 260_000
    min_password_len: int = 8
    #: Rate limit: this many failed sign-ins per username / address per window.
    max_failures: int = 5
    failure_window_s: int = 300


@dataclass(frozen=True)
class LiveForecastSettings:
    model_dir: Path = BASE / "config" / "v2"
    raw_weather_dir: Path = BASE / "data" / "raw"
    #: Africa/Lusaka is UTC+2 all year (no daylight saving).
    utc_offset_h: int = 2
    horizons: tuple[int, ...] = (1, 6, 24, 48)
    #: Hours of good readings needed before a forecast is made at all.
    min_history_h: int = 48
    #: Gaps up to this long are interpolated (as in training).
    short_gap_h: int = 6
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_timeout_s: int = 8
    weather_past_days: int = 10
    weather_forecast_days: int = 3
    weather_ttl_s: int = 30 * 60
    #: Hours forecast ahead, and hours of recent history backtested.
    forecast_hours: int = 48
    backtest_hours: int = 24
    recent_hours: int = 48


@dataclass(frozen=True)
class ServerSettings:
    #: Dev server and Capacitor WebView origins that may call the API cross-origin.
    default_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://localhost",
        "http://localhost",
        "capacitor://localhost",
    )
    extra_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in os.environ.get("SENTINEL_ALLOWED_ORIGINS", "").split(",") if o.strip()))

    @property
    def allowed_origins(self) -> list[str]:
        return [*self.default_origins, *self.extra_origins]


@dataclass(frozen=True)
class Settings:
    auth: AuthSettings = field(default_factory=AuthSettings)
    live: LiveForecastSettings = field(default_factory=LiveForecastSettings)
    server: ServerSettings = field(default_factory=ServerSettings)


settings = Settings()
