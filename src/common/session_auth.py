# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Session sign-in (``AUTH_MODE=session``): signed cookies, CSRF, rate limit.

The session cookie is an itsdangerous-signed, timestamped payload holding the
user's email and a password version (an HMAC of the stored password hash, so a
password reset ends every older session). It is httponly, SameSite=Lax and
Secure outside local dev. On every request the cookie is verified, then the
user is re-read from the users store (cached for a few seconds) so disabling a
user or changing a role takes effect quickly. Role always comes from the
store, never from the cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Mapping
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from common.identity import LOCAL_APP_ENVS
from common.verified_identity import (
    IDENTITY_SOURCE_SESSION,
    MANAGED_PLATFORM_MARKERS,
    VerifiedIdentity,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "gm_session"
CSRF_COOKIE = "gm_csrf"
MIN_SECRET_LENGTH = 32
DEFAULT_TTL_HOURS = 12
_SALT = "gm-session-v1"

# Paths that never need a session (the login page itself, health checks, the
# theme stylesheet and the favicon).
# /account/renew is public because the renewal token in its body is the proof
# of identity: the caller's old session cookie died with their old password.
PUBLIC_PATHS = (
    "/login",
    "/logout",
    "/account/renew",
    "/healthz",
    "/readyz",
    "/favicon.ico",
)
PUBLIC_PREFIXES = ("/ui/",)

GENERIC_LOGIN_ERROR = "Email or password is wrong."


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #
def _is_local_only() -> bool:
    """Local env and no managed-platform marker (so a dev secret is tolerable)."""
    if os.environ.get("APP_ENV", "") not in LOCAL_APP_ENVS:
        return False
    return not any(os.environ.get(m) for m in MANAGED_PLATFORM_MARKERS)


_ephemeral_secret: str | None = None


def session_secret() -> str:
    """Return SESSION_SECRET (or a per-process random one in local dev)."""
    global _ephemeral_secret
    configured = os.environ.get("SESSION_SECRET", "")
    if configured:
        return configured
    if not _is_local_only():
        # validate_session_config() refuses to boot in this state.
        raise RuntimeError("SESSION_SECRET is not set.")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        logger.warning(
            "SESSION_SECRET is not set; using a random one for this process. "
            "Sessions end when the server restarts.",
        )
    return _ephemeral_secret


def validate_session_config() -> None:
    """Fail fast when session mode is misconfigured outside local dev."""
    if _is_local_only():
        return
    if len(os.environ.get("SESSION_SECRET", "")) < MIN_SECRET_LENGTH:
        raise ValueError(
            "AUTH_MODE=session requires SESSION_SECRET (at least "
            f"{MIN_SECRET_LENGTH} random characters). Refusing to serve.",
        )


def session_ttl_seconds() -> int:
    try:
        hours = float(os.environ.get("SESSION_TTL_HOURS", DEFAULT_TTL_HOURS))
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return max(300, int(hours * 3600))


def secure_cookies() -> bool:
    """Secure cookies everywhere except plain local dev over http."""
    return not _is_local_only()


# --------------------------------------------------------------------------- #
# Signed session cookie                                                       #
# --------------------------------------------------------------------------- #
def _serializer(secret: str | None = None) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret or session_secret(), salt=_SALT)


def password_version(password_hash: str | None, secret: str | None = None) -> str:
    """Short keyed fingerprint of the stored hash (changes on reset)."""
    key = (secret or session_secret()).encode("utf-8")
    return hmac.new(
        key, (password_hash or "").encode("utf-8"), hashlib.sha256,
    ).hexdigest()[:16]


def issue_session(record: Mapping, secret: str | None = None) -> str:
    """Return a signed session token for a user record."""
    return _serializer(secret).dumps(
        {
            "e": record["email"],
            "v": password_version(record.get("password_hash"), secret),
        },
    )


def read_session(
    token: str | None,
    secret: str | None = None,
    max_age: int | None = None,
) -> dict | None:
    """Return the payload of a valid, unexpired token, else None."""
    if not token or len(token) > 4096:
        return None
    try:
        payload = _serializer(secret).loads(
            token,
            max_age=max_age if max_age is not None else session_ttl_seconds(),
        )
    except SignatureExpired:
        return None
    except BadSignature:
        logger.warning("Rejected a session cookie with a bad signature.")
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("e"), str):
        return None
    return payload


# Re-sign-in after a user changes their own password. Changing the password
# invalidates every session token (they are bound to the password hash),
# including the one in use. The account page hands the browser this short-lived
# renewal token, which the browser POSTs (never in a URL) to /account/renew to
# get a fresh session cookie. It is bound to the email and the NEW password
# version, so it stops working if the password changes again.
_RENEW_SALT = "gm-session-renew-v1"
RENEW_MAX_AGE = 120


def issue_renewal(record: Mapping, secret: str | None = None) -> str:
    """Short-lived token that /account/renew swaps for a session cookie."""
    return URLSafeTimedSerializer(secret or session_secret(), salt=_RENEW_SALT).dumps(
        {
            "e": record["email"],
            "v": password_version(record.get("password_hash"), secret),
        },
    )


def read_renewal(token: str | None, secret: str | None = None) -> dict | None:
    """Payload of a valid, unexpired renewal token, else None."""
    if not token or len(token) > 4096:
        return None
    try:
        payload = URLSafeTimedSerializer(
            secret or session_secret(), salt=_RENEW_SALT,
        ).loads(token, max_age=RENEW_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("e"), str):
        return None
    return payload


# Short cache of user records so each request does not hit Firestore.
_USER_CACHE_TTL = 15.0
_user_cache: dict[str, tuple[float, dict | None]] = {}
_user_cache_lock = threading.Lock()


def _cached_user(email: str) -> dict | None:
    from common.user_store import get_user_store

    now = time.monotonic()
    with _user_cache_lock:
        hit = _user_cache.get(email)
        if hit and hit[0] > now:
            return hit[1]
    try:
        record = get_user_store().get(email)
    except Exception as exc:  # noqa: BLE001 - store outage => fail closed
        logger.error("Users store lookup failed: %s", type(exc).__name__)
        return None
    with _user_cache_lock:
        _user_cache[email] = (now + _USER_CACHE_TTL, record)
    return record


def forget_user(email: str | None = None) -> None:
    """Drop cached records (after an admin change)."""
    with _user_cache_lock:
        if email is None:
            _user_cache.clear()
        else:
            _user_cache.pop(email.strip().lower(), None)


def identity_from_token(token: str | None) -> VerifiedIdentity | None:
    payload = read_session(token)
    if payload is None:
        return None
    record = _cached_user(payload["e"])
    if not record or not record.get("active"):
        return None
    expected = password_version(record.get("password_hash"))
    if not hmac.compare_digest(str(payload.get("v", "")), expected):
        return None
    return VerifiedIdentity(
        email=record["email"],
        subject=None,
        source=IDENTITY_SOURCE_SESSION,
        role=record.get("role") or "user",
        name=record.get("name") or "",
    )


def cookie_from_headers(headers: Mapping[str, str], name: str) -> str | None:
    raw = headers.get("cookie") if headers else None
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


def identity_from_headers(headers: Mapping[str, str]) -> VerifiedIdentity | None:
    """Session-mode identity for ``get_verified_user_identity``."""
    return identity_from_token(cookie_from_headers(headers, SESSION_COOKIE))


# --------------------------------------------------------------------------- #
# Request helpers                                                             #
# --------------------------------------------------------------------------- #
def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES)


def wants_html(method: str, path: str, accept: str | None) -> bool:
    """True for a browser page load (redirect to /login); False for API/XHR."""
    if method != "GET":
        return False
    if path.startswith(("/__", "/api/", "/media/", "/static/")):
        return False
    return "text/html" in (accept or "")


def safe_next(value: str | None, default: str = "/home") -> str:
    """Return ``value`` only if it is a same-site relative path."""
    if not value or len(value) > 2048:
        return default
    if any(ord(ch) < 0x20 or ch == "\\" for ch in value):
        return default
    if not value.startswith("/") or value.startswith("//"):
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return default
    if parts.path in ("/login", "/logout"):
        return default
    return value


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, form_value: str | None) -> bool:
    if not cookie_value or not form_value:
        return False
    return hmac.compare_digest(cookie_value, form_value)


def same_origin(headers: Mapping[str, str]) -> bool:
    """True when Origin (or Referer) names this host. Used for POST forms."""
    host = headers.get("x-forwarded-host") or headers.get("host") or ""
    host = host.split(",", 1)[0].strip().lower()
    source = headers.get("origin") or headers.get("referer") or ""
    if not host or not source or source == "null":
        return False
    return urlsplit(source).netloc.lower() == host


def client_ip(headers: Mapping[str, str], fallback: str | None) -> str:
    """Best-effort client IP for rate limiting.

    Uses the LAST X-Forwarded-For entry (the one Cloud Run's front end appends);
    earlier entries are client-supplied and could be rotated to dodge limits.
    """
    forwarded = headers.get("x-forwarded-for") if headers else None
    if forwarded:
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return fallback or "unknown"


class RateLimiter:
    """In-memory sliding window: at most ``limit`` failures per ``window`` s.

    Per process (Cloud Run instances do not share it), which is enough to slow
    password guessing for a demo app.
    """

    def __init__(self, limit: int = 5, window: float = 300.0, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, self._clock())) >= self.limit

    def hit(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(key, now)
            self._hits.setdefault(key, []).append(now)
            if len(self._hits) > 10000:  # bound memory under a flood
                for other in list(self._hits):
                    self._prune(other, now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# 5 failures per account+IP and 20 per IP, each in 5 minutes.
login_limiter = RateLimiter(limit=5)
ip_limiter = RateLimiter(limit=20)
