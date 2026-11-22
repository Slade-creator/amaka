"""Authentication for the AMAKA API: user accounts, password hashing and
signed bearer tokens.

Design
------
* Accounts live in ``config/users.json`` (override with ``SENTINEL_USERS_FILE``).
  Each account has a username, display name, role (commander / operator /
  analyst) and a PBKDF2-SHA256 password hash. Plain passwords are never stored.
* Tokens are HS256 JWTs signed with ``SENTINEL_JWT_SECRET``. When the variable
  is unset a random secret is generated once and kept in ``config/.jwt_secret``
  so tokens survive a restart on the same machine.
* The role inside the token decides what the client shows. The server checks
  the token on every data endpoint; role-restricted endpoints (for example the
  report exports) also check the role.
* Failed logins are rate limited per username and per client address.

Manage accounts with the CLI (run from the prototype root)::

    python -m backend.users add <username> --role operator --name "Display Name"
    python -m backend.users list
    python -m backend.users passwd <username>
    python -m backend.users remove <username>

When the users file does not exist the server creates the three demo accounts
from ``config/users.seed.json`` (see docs/MOBILE_APP.md) unless
``SENTINEL_DEMO_USERS=0``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import settings

log = logging.getLogger("amaka.auth")

_cfg = settings.auth

# Module-level names kept so other modules (app.py, users.py, tests) keep working.
BASE = Path(__file__).resolve().parents[1]
USERS_PATH = _cfg.users_file
SEED_PATH = _cfg.seed_file
SECRET_PATH = _cfg.secret_file
ROLES = _cfg.roles
ALGORITHM = _cfg.algorithm
ISSUER = _cfg.issuer
TOKEN_TTL_S = _cfg.token_ttl_s
PBKDF2_ITERATIONS = _cfg.pbkdf2_iterations
MIN_PASSWORD_LEN = _cfg.min_password_len
MAX_FAILURES = _cfg.max_failures
FAILURE_WINDOW_S = _cfg.failure_window_s


class AuthError(Exception):
    """Invalid account data or password policy violation."""


# ---------------------------------------------------------------------------
# Password hashing (stdlib PBKDF2 — no extra dependency)
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<salt>$<hash>``."""
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iters, salt, digest = encoded.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                        _unb64(salt), int(iters))
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


# Constant-time dummy check so a wrong username costs the same as a wrong password.
_DUMMY_HASH = (f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
               f"{_b64(b'sentinel-dummy-s')}${_b64(b'0' * 32)}")


# ---------------------------------------------------------------------------
# User store
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class User:
    username: str
    name: str
    role: str
    disabled: bool = False

    def public(self) -> dict:
        return {"username": self.username, "name": self.name, "role": self.role}


_lock = threading.Lock()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _read_users() -> dict[str, dict]:
    if not USERS_PATH.is_file():
        return {}
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Cannot read {USERS_PATH}: {exc}") from exc
    users = data.get("users", []) if isinstance(data, dict) else []
    return {normalize_username(u["username"]): u for u in users
            if isinstance(u, dict) and u.get("username")}


def _write_users(users: dict[str, dict]) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_PATH.with_suffix(".tmp")
    payload = {"users": sorted(users.values(), key=lambda u: u["username"])}
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(USERS_PATH)


def list_users() -> list[User]:
    with _lock:
        rows = _read_users()
    return [User(u["username"], u.get("name", u["username"]), u["role"],
                 bool(u.get("disabled", False))) for u in rows.values()]


def get_user(username: str) -> Optional[User]:
    with _lock:
        row = _read_users().get(normalize_username(username))
    if not row:
        return None
    return User(row["username"], row.get("name", row["username"]), row["role"],
                bool(row.get("disabled", False)))


def upsert_user(username: str, password: Optional[str], role: str,
                name: Optional[str] = None, disabled: bool = False) -> User:
    uname = normalize_username(username)
    if not uname or not uname.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise AuthError("Username may only contain letters, digits, '.', '-' and '_'")
    if role not in ROLES:
        raise AuthError(f"Role must be one of: {', '.join(ROLES)}")
    with _lock:
        users = _read_users()
        existing = users.get(uname)
        if existing is None and not password:
            raise AuthError("A new user needs a password")
        row = dict(existing or {})
        row.update({"username": uname, "role": role,
                    "name": name or row.get("name") or uname,
                    "disabled": disabled})
        if password:
            row["password"] = hash_password(password)
        users[uname] = row
        _write_users(users)
    return User(uname, row["name"], role, disabled)


def remove_user(username: str) -> bool:
    uname = normalize_username(username)
    with _lock:
        users = _read_users()
        if uname not in users:
            return False
        del users[uname]
        _write_users(users)
    return True


def authenticate(username: str, password: str) -> Optional[User]:
    uname = normalize_username(username)
    with _lock:
        row = _read_users().get(uname)
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, row.get("password", "")):
        return None
    if row.get("disabled"):
        return None
    return User(row["username"], row.get("name", uname), row["role"])


def ensure_seed_users() -> int:
    """Create demo accounts from config/users.seed.json on first start.

    Returns the number of accounts created (0 when users already exist,
    seeding is disabled, or there is no seed file)."""
    if not _cfg.demo_users:
        return 0
    if USERS_PATH.is_file() or not SEED_PATH.is_file():
        return 0
    try:
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot read %s: %s", SEED_PATH, exc)
        return 0
    created = 0
    for row in seed.get("users", []):
        try:
            upsert_user(row["username"], row["password"], row["role"],
                        row.get("name"))
            created += 1
        except (AuthError, KeyError) as exc:
            log.warning("Skipping seed user %r: %s", row.get("username"), exc)
    return created


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

_secret_cache: Optional[str] = None


def _secret() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    env = _cfg.jwt_secret
    if env:
        _secret_cache = env
        return env
    with _lock:
        if SECRET_PATH.is_file():
            _secret_cache = SECRET_PATH.read_text(encoding="utf-8").strip()
        if not _secret_cache:
            _secret_cache = secrets.token_urlsafe(48)
            SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
            SECRET_PATH.write_text(_secret_cache, encoding="utf-8")
            log.info("Generated a new token signing secret at %s", SECRET_PATH)
    return _secret_cache


def issue_token(user: User) -> dict:
    now = int(time.time())
    claims = {
        "sub": user.username,
        "name": user.name,
        "role": user.role,
        "iat": now,
        "exp": now + TOKEN_TTL_S,
        "iss": ISSUER,
    }
    token = jwt.encode(claims, _secret(), algorithm=ALGORITHM)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_TTL_S,
        "expires_at": now + TOKEN_TTL_S,
        "user": user.public(),
    }


def decode_token(token: str) -> User:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM],
                            issuer=[ISSUER, *_cfg.legacy_issuers], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired — sign in again")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid session token")
    # Re-check the account so a removed/disabled user loses access at once.
    user = get_user(str(claims.get("sub", "")))
    if user is None or user.disabled:
        raise _unauthorized("Account is no longer active")
    return user


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                         detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


# ---------------------------------------------------------------------------
# Rate limiting for login
# ---------------------------------------------------------------------------

_failures: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def _prune(key: str, now: float) -> list[float]:
    hits = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW_S]
    _failures[key] = hits
    return hits


def check_rate_limit(*keys: str) -> Optional[int]:
    """Seconds to wait when any key is locked out, else None."""
    now = time.time()
    with _fail_lock:
        for key in keys:
            hits = _prune(key, now)
            if len(hits) >= MAX_FAILURES:
                return int(FAILURE_WINDOW_S - (now - hits[0])) + 1
    return None


def record_failure(*keys: str) -> None:
    now = time.time()
    with _fail_lock:
        for key in keys:
            _prune(key, now).append(now)


def clear_failures(*keys: str) -> None:
    with _fail_lock:
        for key in keys:
            _failures.pop(key, None)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def auth_required() -> bool:
    """Auth can be switched off for local research runs (SENTINEL_AUTH=off)."""
    return _cfg.required


_bearer = HTTPBearer(auto_error=False)

_ANONYMOUS = User("local", "Local user", "analyst")


def current_user(request: Request,
                 creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
                 ) -> User:
    if not auth_required():
        return _ANONYMOUS
    token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
    if not token:
        raise _unauthorized("Sign in required")
    user = decode_token(token)
    request.state.user = user
    return user


def require_roles(*roles: str):
    """Dependency factory: 403 unless the signed-in user has one of `roles`."""
    def _check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Your role does not have access to this")
        return user
    return _check
