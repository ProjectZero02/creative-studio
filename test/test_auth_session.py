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
"""Tests for session sign-in (AUTH_MODE=session). No network, no GCP."""

# ruff: noqa: D103

import re
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import session_auth as sa
from common import user_store as us
from common.identity import (
    INTERNAL_VERIFIED_EMAIL_ENVIRON,
    INTERNAL_VERIFIED_ROLE_ENVIRON,
)
from common.passwords import (
    generate_password,
    hash_password,
    password_problem,
    verify_password,
)
from common.verified_identity import (
    AUTH_MODE_IAP,
    AUTH_MODE_LOCAL,
    AUTH_MODE_SESSION,
    IdentityConfigError,
    VerifiedIdentity,
    get_verified_user_identity,
    resolve_auth_mode,
    validate_identity_config,
)
from routers import auth_router


@pytest.fixture
def session_env(monkeypatch, tmp_path):
    """Session mode, local env, a temp file store with one admin and one user."""
    for marker in ("K_SERVICE", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("AUTH_MODE", "session")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    store = us.FileUserStore(tmp_path / "users.json")
    us.set_user_store(store)
    sa.forget_user()
    sa.login_limiter._hits.clear()
    sa.ip_limiter._hits.clear()
    creds = {
        "admin": ("admin@example.test", generate_password()),
        "user": ("user@example.test", generate_password()),
    }
    store.create(
        email=creds["admin"][0],
        name="Ada Admin",
        role="admin",
        password=creds["admin"][1],
    )
    store.create(
        email=creds["user"][0], name="Uma User", role="user", password=creds["user"][1],
    )
    yield SimpleNamespace(store=store, creds=creds)
    us.set_user_store(None)
    sa.forget_user()


# --------------------------------------------------------------------------- #
# Passwords                                                                   #
# --------------------------------------------------------------------------- #
def test_hash_and_verify_roundtrip():
    pw = generate_password()
    stored = hash_password(pw)
    assert stored.startswith("scrypt$")
    assert pw not in stored
    assert verify_password(pw, stored)
    assert not verify_password(pw + "x", stored)


def test_same_password_gets_different_salts():
    pw = generate_password()
    assert hash_password(pw) != hash_password(pw)


def test_verify_handles_garbage():
    assert not verify_password("x", None)
    assert not verify_password("x", "")
    assert not verify_password("x", "scrypt$bad")
    assert not verify_password("x", "bcrypt$1$2$3$4$5")
    assert not verify_password("", hash_password("something-long"))


def test_password_problem():
    assert password_problem("short")
    assert password_problem(generate_password()) is None


# --------------------------------------------------------------------------- #
# Cookies                                                                     #
# --------------------------------------------------------------------------- #
def test_cookie_sign_and_verify():
    secret = secrets.token_urlsafe(48)
    record = {"email": "a@example.test", "password_hash": "h1"}
    token = sa.issue_session(record, secret)
    payload = sa.read_session(token, secret, max_age=60)
    assert payload["e"] == "a@example.test"
    assert payload["v"] == sa.password_version("h1", secret)


def test_cookie_tamper_and_wrong_secret_rejected():
    secret = secrets.token_urlsafe(48)
    token = sa.issue_session({"email": "a@example.test", "password_hash": "h"}, secret)
    assert (
        sa.read_session(
            token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1], secret, 60,
        )
        is None
    )
    assert sa.read_session(token, secrets.token_urlsafe(48), 60) is None
    assert sa.read_session("", secret, 60) is None
    assert sa.read_session("x" * 5000, secret, 60) is None


def test_cookie_expiry(monkeypatch):
    secret = secrets.token_urlsafe(48)
    token = sa.issue_session({"email": "a@example.test", "password_hash": "h"}, secret)
    import itsdangerous.timed

    real = itsdangerous.timed.TimestampSigner.get_timestamp
    monkeypatch.setattr(
        itsdangerous.timed.TimestampSigner,
        "get_timestamp",
        lambda self: real(self) + 3600,
    )
    assert sa.read_session(token, secret, max_age=60) is None


def test_password_reset_invalidates_old_cookie(session_env):
    email, _ = session_env.creds["user"]
    token = sa.issue_session(session_env.store.get(email))
    assert sa.identity_from_token(token).email == email
    session_env.store.set_password(email, generate_password())
    sa.forget_user(email)
    assert sa.identity_from_token(token) is None


def test_disabled_user_cookie_rejected(session_env):
    email, _ = session_env.creds["user"]
    token = sa.issue_session(session_env.store.get(email))
    session_env.store.update(email, active=False)
    sa.forget_user(email)
    assert sa.identity_from_token(token) is None


def test_role_comes_from_store_not_cookie(session_env):
    email, _ = session_env.creds["user"]
    token = sa.issue_session(session_env.store.get(email))
    identity = sa.identity_from_token(token)
    assert identity.role == "user"
    assert identity.source == "session"


# --------------------------------------------------------------------------- #
# Open redirect protection                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://evil.example/",
        "//evil.example/x",
        "/\\evil.example",
        "\\\\evil.example",
        "javascript:alert(1)",
        "home",
        "/login",
        "/logout",
        "/ok\r\nSet-Cookie: x=1",
        "/" + "a" * 3000,
    ],
)
def test_safe_next_rejects(value):
    assert sa.safe_next(value) == "/home"


@pytest.mark.parametrize("value", ["/veo", "/library?media=video", "/admin/users"])
def test_safe_next_allows_relative(value):
    assert sa.safe_next(value) == value


def test_login_redirect_url_encodes_target():
    assert (
        auth_router.login_redirect_url("/veo", "a=1&b=2")
        == "/login?next=/veo%3Fa%3D1%26b%3D2"
    )
    assert auth_router.login_redirect_url("/home", "") == "/login"


# --------------------------------------------------------------------------- #
# Rate limit                                                                  #
# --------------------------------------------------------------------------- #
def test_rate_limiter_window():
    now = [0.0]
    rl = sa.RateLimiter(limit=3, window=300, clock=lambda: now[0])
    for _ in range(3):
        assert not rl.blocked("k")
        rl.hit("k")
    assert rl.blocked("k")
    assert not rl.blocked("other")
    now[0] = 301
    assert not rl.blocked("k")


def test_rate_limiter_reset():
    rl = sa.RateLimiter(limit=1, window=300)
    rl.hit("k")
    assert rl.blocked("k")
    rl.reset("k")
    assert not rl.blocked("k")


def test_client_ip_uses_last_forwarded_entry():
    assert sa.client_ip({"x-forwarded-for": "1.1.1.1, 2.2.2.2"}, "9.9.9.9") == "2.2.2.2"
    assert sa.client_ip({}, "9.9.9.9") == "9.9.9.9"


# --------------------------------------------------------------------------- #
# Auth mode + config                                                          #
# --------------------------------------------------------------------------- #
def test_resolve_auth_mode_session_is_explicit_only():
    assert resolve_auth_mode("local") == AUTH_MODE_LOCAL
    assert resolve_auth_mode("prod") == AUTH_MODE_IAP
    assert resolve_auth_mode("prod", "session") == AUTH_MODE_SESSION
    assert resolve_auth_mode("local", "SESSION") == AUTH_MODE_SESSION
    assert resolve_auth_mode("prod", "local") == AUTH_MODE_IAP  # can't downgrade


def test_validate_requires_secret_outside_local(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "session")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(IdentityConfigError):
        validate_identity_config()
    monkeypatch.setenv("SESSION_SECRET", "too-short")
    with pytest.raises(IdentityConfigError):
        validate_identity_config()
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    validate_identity_config()


def test_validate_requires_secret_on_cloud_run_even_if_local(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "session")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("K_SERVICE", "genmedia")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(IdentityConfigError):
        validate_identity_config()


def test_local_dev_without_secret_is_allowed(monkeypatch):
    for marker in ("K_SERVICE", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setenv("AUTH_MODE", "session")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    validate_identity_config()
    assert sa.session_secret()
    assert sa.secure_cookies() is False


def test_get_verified_identity_reads_session_cookie(session_env):
    email, _ = session_env.creds["admin"]
    token = sa.issue_session(session_env.store.get(email))
    identity = get_verified_user_identity({"cookie": f"{sa.SESSION_COOKIE}={token}"})
    assert identity.email == email and identity.role == "admin"
    assert get_verified_user_identity({"cookie": f"{sa.SESSION_COOKIE}=forged"}) is None
    assert get_verified_user_identity({}) is None


def test_bootstrap_admin_only_when_no_admin(monkeypatch, tmp_path):
    store = us.FileUserStore(tmp_path / "u.json")
    us.set_user_store(store)
    try:
        pw = generate_password()
        monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "Boot@Example.test")
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", pw)
        assert us.bootstrap_admin() is True
        record = store.get("boot@example.test")
        assert record["role"] == "admin" and verify_password(
            pw, record["password_hash"],
        )
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", generate_password())
        assert us.bootstrap_admin() is False  # an admin exists; nothing changes
        assert verify_password(pw, store.get("boot@example.test")["password_hash"])
    finally:
        us.set_user_store(None)


def test_public_user_hides_hash():
    shown = us.public_user(
        {"email": "a@x", "password_hash": "secret-hash", "active": True},
    )
    assert "password_hash" not in shown


# --------------------------------------------------------------------------- #
# Middleware gate + login flow (tiny app with the real router and gate)       #
# --------------------------------------------------------------------------- #
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router.router)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        identity = get_verified_user_identity(request.headers)
        denied = auth_router.session_gate(
            identity,
            request.method,
            request.url.path,
            request.url.query,
            request.headers.get("accept"),
        )
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get("/home")
    async def home():
        return HTMLResponse("home")

    @app.get("/veo")
    async def veo():
        return HTMLResponse("veo")

    @app.get("/admin/users")
    async def admin():
        return HTMLResponse("admin")

    @app.post("/__ui__")
    async def ui():
        return JSONResponse({"ok": True})

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


HTML = {"accept": "text/html,application/xhtml+xml"}
ORIGIN = {"origin": "http://testserver"}


def _csrf(client: TestClient, path: str = "/login") -> str:
    page = client.get(path)
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)


def _login(client, email, password, next_path="/home", headers=ORIGIN):
    token = _csrf(client)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf": token, "next": next_path},
        headers=headers,
        follow_redirects=False,
    )


def test_unauthenticated_page_redirects_to_login(session_env):
    client = TestClient(_app())
    r = client.get("/veo?x=1", headers=HTML, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login?next=/veo%3Fx%3D1"


def test_unauthenticated_xhr_gets_401(session_env):
    client = TestClient(_app())
    assert client.post("/__ui__").status_code == 401
    assert client.get("/veo", headers={"accept": "application/json"}).status_code == 401


def test_public_paths_stay_public(session_env):
    client = TestClient(_app())
    assert client.get("/healthz").status_code == 200
    page = client.get("/login")
    assert page.status_code == 200
    assert "Welcome back" in page.text
    assert page.headers["cache-control"] == "no-store"


def test_login_success_sets_cookie_and_redirects(session_env):
    email, pw = session_env.creds["user"]
    client = TestClient(_app())
    r = _login(client, email.upper(), pw, next_path="/veo")
    assert r.status_code == 303
    assert r.headers["location"] == "/veo"
    cookie = r.headers["set-cookie"]
    assert (
        sa.SESSION_COOKIE in cookie
        and "HttpOnly" in cookie
        and "samesite=lax" in cookie.lower()
    )
    assert client.get("/veo", headers=HTML).text == "veo"
    assert session_env.store.get(email)["last_login"]


def test_login_open_redirect_blocked(session_env):
    email, pw = session_env.creds["user"]
    client = TestClient(_app())
    r = _login(client, email, pw, next_path="https://evil.example/")
    assert r.status_code == 303 and r.headers["location"] == "/home"


def test_login_wrong_password_generic_error(session_env):
    email, _ = session_env.creds["user"]
    client = TestClient(_app())
    for who in (email, "nobody@example.test"):
        r = _login(client, who, "wrong-password-123")
        assert r.status_code == 401
        assert "Email or password is wrong." in r.text
        assert sa.SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_login_disabled_user_generic_error(session_env):
    email, pw = session_env.creds["user"]
    session_env.store.update(email, active=False)
    r = _login(TestClient(_app()), email, pw)
    assert r.status_code == 401 and "Email or password is wrong." in r.text


def test_login_requires_csrf_and_origin(session_env):
    email, pw = session_env.creds["user"]
    client = TestClient(_app())
    _csrf(client)
    r = client.post(
        "/login",
        data={"email": email, "password": pw, "csrf": "forged"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert r.status_code == 400
    r = _login(client, email, pw, headers={"origin": "https://evil.example"})
    assert r.status_code == 400


def test_login_rate_limited_after_five_failures(session_env):
    email, pw = session_env.creds["user"]
    client = TestClient(_app())
    for _ in range(5):
        assert _login(client, email, "wrong-password-123").status_code == 401
    r = _login(client, email, pw)  # even the right password is held back
    assert r.status_code == 429
    assert "Too many tries" in r.text


def test_logout_clears_cookie(session_env):
    email, pw = session_env.creds["user"]
    client = TestClient(_app())
    _login(client, email, pw)
    assert (
        client.post("/logout", headers={"origin": "https://evil.example"}).status_code
        == 400
    )
    r = client.post("/logout", headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/veo", headers=HTML, follow_redirects=False).status_code == 302


def test_admin_path_needs_admin_role(session_env):
    user_client = TestClient(_app())
    _login(user_client, *session_env.creds["user"])
    assert user_client.get("/admin/users", headers=HTML).status_code == 403

    admin_client = TestClient(_app())
    _login(admin_client, *session_env.creds["admin"])
    assert admin_client.get("/admin/users", headers=HTML).text == "admin"


def test_gate_is_inactive_outside_session_mode(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    client = TestClient(_app_without_gate())
    assert client.get("/login", follow_redirects=False).status_code == 302


def _app_without_gate() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router.router)
    return app


def test_login_page_escapes_input(session_env):
    html = auth_router.render_login_page(
        csrf="t", next_path='/x"><svg onload=1>', email='"><img src=x>', error="<b>",
    )
    assert "<svg onload" not in html and "<img src=x>" not in html and "<b>" not in html


# --------------------------------------------------------------------------- #
# Admin page guard (every handler re-checks the per-request role)             #
# --------------------------------------------------------------------------- #
def test_current_admin_email(session_env):
    from pages import admin_users

    assert (
        admin_users.current_admin_email(
            {
                INTERNAL_VERIFIED_ROLE_ENVIRON: "admin",
                INTERNAL_VERIFIED_EMAIL_ENVIRON: "A@x.test",
            },
        )
        == "a@x.test"
    )
    assert (
        admin_users.current_admin_email(
            {
                INTERNAL_VERIFIED_ROLE_ENVIRON: "user",
                INTERNAL_VERIFIED_EMAIL_ENVIRON: "a@x.test",
            },
        )
        is None
    )
    assert admin_users.current_admin_email({}) is None


def _run(handler, event, state, monkeypatch, admin_users):
    monkeypatch.setattr(admin_users.me, "state", lambda cls: state)
    result = handler(event)
    if result is not None:
        list(result)


@pytest.mark.parametrize("role", ["user", ""])
def test_admin_handlers_refuse_non_admin(session_env, monkeypatch, role):
    from pages import admin_users

    target, _ = session_env.creds["admin"]
    monkeypatch.setattr(
        admin_users,
        "request",
        SimpleNamespace(
            environ={
                INTERNAL_VERIFIED_ROLE_ENVIRON: role,
                INTERNAL_VERIFIED_EMAIL_ENVIRON: session_env.creds["user"][0],
            },
        ),
    )
    state = admin_users.AdminUsersState()
    # Even with a forged client-side state, nothing changes.
    state.add_email = "new@example.test"
    state.add_password = generate_password()
    state.reset_email = target
    state.reset_password = generate_password()
    before = session_env.store.get(target)

    _run(
        admin_users.toggle_active,
        SimpleNamespace(key=target),
        state,
        monkeypatch,
        admin_users,
    )
    _run(
        admin_users.on_role_change,
        SimpleNamespace(key=target, value="user"),
        state,
        monkeypatch,
        admin_users,
    )
    _run(
        admin_users.submit_add, SimpleNamespace(key=""), state, monkeypatch, admin_users,
    )
    _run(
        admin_users.submit_reset,
        SimpleNamespace(key=""),
        state,
        monkeypatch,
        admin_users,
    )
    _run(admin_users.on_load, SimpleNamespace(), state, monkeypatch, admin_users)

    assert state.error == admin_users.ADMIN_ONLY
    assert session_env.store.get(target) == before
    assert session_env.store.get("new@example.test") is None
    assert state.users_json == "[]"


def test_admin_handlers_work_for_admin(session_env, monkeypatch):
    from pages import admin_users

    admin_email, _ = session_env.creds["admin"]
    user_email, _ = session_env.creds["user"]
    monkeypatch.setattr(
        admin_users,
        "request",
        SimpleNamespace(
            environ={
                INTERNAL_VERIFIED_ROLE_ENVIRON: "admin",
                INTERNAL_VERIFIED_EMAIL_ENVIRON: admin_email,
            },
        ),
    )
    state = admin_users.AdminUsersState()
    _run(
        admin_users.toggle_active,
        SimpleNamespace(key=user_email),
        state,
        monkeypatch,
        admin_users,
    )
    assert session_env.store.get(user_email)["active"] is False

    # Can't disable yourself or drop the last admin.
    _run(
        admin_users.toggle_active,
        SimpleNamespace(key=admin_email),
        state,
        monkeypatch,
        admin_users,
    )
    assert session_env.store.get(admin_email)["active"] is True
    _run(
        admin_users.on_role_change,
        SimpleNamespace(key=admin_email, value="user"),
        state,
        monkeypatch,
        admin_users,
    )
    assert session_env.store.get(admin_email)["role"] == "admin"

    state.add_email = "new@example.test"
    state.add_name = "New Person"
    state.add_role = "user"
    state.add_password = generate_password()
    _run(
        admin_users.submit_add, SimpleNamespace(key=""), state, monkeypatch, admin_users,
    )
    assert session_env.store.get("new@example.test")["role"] == "user"
    assert "password_hash" not in state.users_json


def test_identity_dataclass_defaults_keep_old_callers_working():
    identity = VerifiedIdentity(email="a@x", subject=None, source="iap")
    assert identity.role is None and identity.name is None


# --------------------------------------------------------------------------- #
# /account: users change their own password                                   #
# --------------------------------------------------------------------------- #
class _AccountPage:
    """Imports pages.account lazily, like the admin_users tests do."""

    def __getattr__(self, name):
        from pages import account

        return getattr(account, name)


account_page = _AccountPage()


def test_change_own_password_success_ends_old_sessions(session_env):
    email, old = session_env.creds["user"]
    old_cookie = sa.issue_session(session_env.store.get(email))
    new = generate_password()
    assert account_page.change_own_password(email, old, new, new) == ""
    assert verify_password(new, session_env.store.get(email)["password_hash"])
    # Every earlier session token is dead after the change.
    sa.forget_user(email)
    assert sa.identity_from_token(old_cookie) is None


def test_change_own_password_wrong_current_is_refused(session_env):
    email, old = session_env.creds["user"]
    before = session_env.store.get(email)["password_hash"]
    new = generate_password()
    assert (
        account_page.change_own_password(email, old + "x", new, new)
        == "account.err_current"
    )
    assert session_env.store.get(email)["password_hash"] == before


@pytest.mark.parametrize(
    "new, confirm, key",
    [
        ("short", "short", "account.err_short"),
        ("a-long-enough-pass", "a-different-pass!", "account.err_mismatch"),
        ("x" * 257, "x" * 257, "account.err_long"),
    ],
)
def test_change_own_password_rejects_bad_new_password(session_env, new, confirm, key):
    email, old = session_env.creds["user"]
    before = session_env.store.get(email)["password_hash"]
    assert account_page.change_own_password(email, old, new, confirm) == key
    assert session_env.store.get(email)["password_hash"] == before


def test_change_own_password_must_differ(session_env):
    email, old = session_env.creds["user"]
    assert account_page.change_own_password(email, old, old, old) == "account.err_same"


def test_change_own_password_refuses_disabled_user(session_env):
    email, old = session_env.creds["user"]
    session_env.store.update(email, active=False)
    new = generate_password()
    assert (
        account_page.change_own_password(email, old, new, new) == "account.err_current"
    )


def test_change_own_password_is_rate_limited(session_env):
    email, old = session_env.creds["user"]
    new = generate_password()
    for _ in range(sa.login_limiter.limit):
        assert (
            account_page.change_own_password(email, "wrong-password!", new, new)
            == "account.err_current"
        )
    assert (
        account_page.change_own_password(email, old, new, new) == "account.err_too_many"
    )


def _renew(client, token, headers=ORIGIN):
    return client.post(
        "/account/renew",
        data={"token": token},
        headers=headers,
        follow_redirects=False,
    )


def _changed(session_env):
    """Change the regular user's password; return (email, new password)."""
    email, old = session_env.creds["user"]
    new = generate_password()
    assert account_page.change_own_password(email, old, new, new) == ""
    return email, new


def test_renew_gives_fresh_session_after_change(session_env):
    email, _ = _changed(session_env)
    client = TestClient(_app())
    r = _renew(client, sa.issue_renewal(session_env.store.get(email)))
    assert r.status_code == 303
    assert r.headers["location"] == "/account?changed=1"
    assert sa.SESSION_COOKIE in r.headers["set-cookie"]
    # The new cookie works.
    assert client.get("/veo", headers=HTML, follow_redirects=False).status_code == 200


def test_renew_is_public(session_env):
    # The old cookie is already invalid when the browser posts here.
    assert sa.is_public_path("/account/renew")


@pytest.mark.parametrize("token", ["", "forged", "a.b.c"])
def test_renew_refuses_bad_token(session_env, token):
    client = TestClient(_app())
    r = _renew(client, token)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")
    assert sa.SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_renew_refuses_token_from_before_another_change(session_env):
    email, new = _changed(session_env)
    stale = sa.issue_renewal(session_env.store.get(email))
    newer = generate_password()
    assert account_page.change_own_password(email, new, newer, newer) == ""
    r = _renew(TestClient(_app()), stale)
    assert r.headers["location"].startswith("/login")
    assert sa.SESSION_COOKIE not in r.headers.get("set-cookie", "")


def test_renew_refuses_expired_token(session_env, monkeypatch):
    email, _ = _changed(session_env)
    token = sa.issue_renewal(session_env.store.get(email))
    monkeypatch.setattr(sa, "RENEW_MAX_AGE", -1)
    r = _renew(TestClient(_app()), token)
    assert r.headers["location"].startswith("/login")


def test_renew_refuses_cross_origin(session_env):
    email, _ = _changed(session_env)
    token = sa.issue_renewal(session_env.store.get(email))
    r = _renew(TestClient(_app()), token, headers={"origin": "https://evil.example"})
    assert r.status_code == 400
