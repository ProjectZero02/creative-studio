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
"""Sign-in routes for ``AUTH_MODE=session``: GET/POST /login, POST /logout.

The login page is plain server-rendered HTML (no Mesop), styled by
``/ui/login.css``. It complies with the app CSP (only self, Google Fonts and an
inline toggle script, which the CSP already allows).
"""

from __future__ import annotations

import html
import logging
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from common import session_auth as sa
from common.passwords import burn_time, verify_password
from common.user_store import ROLE_ADMIN, get_user_store, normalize_email
from common.verified_identity import AUTH_MODE_SESSION, auth_mode

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

FONT_CSS = (
    "https://fonts.googleapis.com/css2?"
    "family=Google+Sans:opsz,wght@17..18,400..700&display=swap"
)

BRAND_MARK = """<svg class="brand-mark" viewBox="0 0 36 36" aria-hidden="true">
<rect width="36" height="36" rx="10" fill="#1a5fd8"/>
<path d="M18 7.5l2.6 7.9 7.9 2.6-7.9 2.6L18 28.5l-2.6-7.9L7.5 18l7.9-2.6z" fill="#fff"/>
</svg>"""

_TILES = """
<div class="mosaic" aria-hidden="true">
  <div class="tile tile-image">
    <svg class="art" viewBox="0 0 300 188" preserveAspectRatio="xMidYMid slice">
      <rect width="300" height="188" fill="#13213d"/>
      <circle cx="212" cy="58" r="22" fill="#8cb4ff" opacity=".85"/>
      <path d="M0 150 L70 92 L120 128 L178 74 L300 152 L300 188 L0 188Z" fill="#1d3361"/>
      <path d="M0 170 L90 128 L160 160 L230 124 L300 168 L300 188 L0 188Z" fill="#274580"/>
    </svg>
    <span class="tile-label">Image</span>
    <span class="tile-sub">Gemini Image and Imagen</span>
  </div>
  <div class="tile tile-video">
    <svg class="art" viewBox="0 0 300 88" preserveAspectRatio="xMidYMid slice">
      <rect width="300" height="88" fill="#121c33"/>
      <g fill="#1c2b4d"><rect x="150" y="14" width="40" height="60" rx="6"/>
      <rect x="198" y="14" width="40" height="60" rx="6"/><rect x="246" y="14" width="40" height="60" rx="6"/></g>
      <path d="M212 34 L228 44 L212 54Z" fill="#8cb4ff"/>
    </svg>
    <span class="tile-label">Video</span>
    <span class="tile-sub">Veo</span>
  </div>
  <div class="tile tile-music">
    <svg class="art" viewBox="0 0 300 88" preserveAspectRatio="xMidYMid slice">
      <rect width="300" height="88" fill="#121c33"/>
      <g fill="#2a4a87"><rect x="160" y="40" width="8" height="30" rx="4"/>
      <rect x="176" y="24" width="8" height="46" rx="4"/><rect x="192" y="32" width="8" height="38" rx="4"/>
      <rect x="208" y="16" width="8" height="54" rx="4"/><rect x="224" y="36" width="8" height="34" rx="4"/>
      <rect x="240" y="26" width="8" height="44" rx="4"/><rect x="256" y="44" width="8" height="26" rx="4"/></g>
    </svg>
    <span class="tile-label">Music</span>
    <span class="tile-sub">Lyria</span>
  </div>
  <div class="tile tile-speech">
    <svg class="art" viewBox="0 0 620 88" preserveAspectRatio="xMidYMid slice">
      <rect width="620" height="88" fill="#121c33"/>
      <polyline fill="none" stroke="#3b64b0" stroke-width="3" stroke-linecap="round"
        points="300,44 316,30 332,58 348,22 364,66 380,36 396,52 412,26 428,62 444,40 460,48 476,32 492,56 508,42 524,46 540,38 556,50 572,44 604,44"/>
    </svg>
    <span class="tile-label">Speech</span>
    <span class="tile-sub">Gemini TTS and Chirp 3 HD</span>
  </div>
</div>
"""

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Sign in | GenMedia Studio</title>
<link rel="icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{font_css}">
<link rel="stylesheet" href="/ui/login.css">
</head>
<body>
<div class="auth">
  <aside class="auth-visual">
    <div class="brand">{brand_mark}<span>GenMedia Studio</span></div>
    <div class="visual-copy">
      <h2>Create with Google's generative media models.</h2>
      <p>Image, video, music and speech on Vertex AI, in one studio.</p>
    </div>
    {tiles}
    <p class="visual-foot">Your work stays in your own Google Cloud project.</p>
  </aside>
  <main class="auth-main">
    <div class="auth-card">
      <div class="brand">{brand_mark}<span>GenMedia Studio</span></div>
      <h1>Welcome back</h1>
      <p class="lead">Sign in to GenMedia Studio.</p>
      <form method="post" action="/login" autocomplete="on">
        <input type="hidden" name="csrf" value="{csrf}">
        <input type="hidden" name="next" value="{next}">
        <div class="field">
          <label for="email">Email</label>
          <input id="email" name="email" type="email" required autocomplete="username"
            inputmode="email" spellcheck="false" value="{email}"{invalid}{autofocus_email}>
        </div>
        <div class="field">
          <label for="password">Password</label>
          <div class="input-wrap">
            <input id="password" name="password" type="password" required
              autocomplete="current-password"{invalid}{autofocus_password}>
            <button type="button" class="reveal" id="reveal" aria-controls="password"
              aria-pressed="false">Show<span class="sr-only"> password</span></button>
          </div>
        </div>
        <button type="submit" class="submit">Sign in</button>
        <p class="error" id="form-error" role="alert"{error_hidden}>{error}</p>
      </form>
      <p class="help">No account yet? Ask your studio admin to add you.</p>
    </div>
  </main>
</div>
<script>
(function () {{
  var b = document.getElementById('reveal'), p = document.getElementById('password');
  if (!b || !p) return;
  b.addEventListener('click', function () {{
    var show = p.type === 'password';
    p.type = show ? 'text' : 'password';
    b.setAttribute('aria-pressed', show ? 'true' : 'false');
    b.firstChild.nodeValue = show ? 'Hide' : 'Show';
  }});
}})();
</script>
</body>
</html>
"""


def render_login_page(
    *,
    csrf: str,
    next_path: str,
    email: str = "",
    error: str = "",
) -> str:
    """Return the sign-in page HTML. Every dynamic value is escaped."""
    has_error = bool(error)
    return _PAGE.format(
        font_css=html.escape(FONT_CSS, quote=True),
        brand_mark=BRAND_MARK,
        tiles=_TILES,
        csrf=html.escape(csrf, quote=True),
        next=html.escape(next_path, quote=True),
        email=html.escape(email, quote=True),
        invalid=' aria-invalid="true" aria-describedby="form-error"'
        if has_error
        else "",
        autofocus_email="" if email else " autofocus",
        autofocus_password=" autofocus" if email else "",
        error=html.escape(error),
        error_hidden="" if has_error else " hidden",
    )


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_response(
    request: Request,
    *,
    next_path: str,
    email: str = "",
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    """Render the form with a fresh CSRF token (cookie + hidden field)."""
    token = sa.new_csrf_token()
    response = HTMLResponse(
        render_login_page(csrf=token, next_path=next_path, email=email, error=error),
        status_code=status_code,
    )
    response.set_cookie(
        sa.CSRF_COOKIE,
        token,
        max_age=3600,
        httponly=True,
        secure=sa.secure_cookies(),
        samesite="strict",
        path="/login",
    )
    return _no_store(response)


def _session_mode() -> bool:
    return auth_mode() == AUTH_MODE_SESSION


@router.get("/login")
async def login_page(request: Request):
    if not _session_mode():
        return RedirectResponse("/home", status_code=302)
    next_path = sa.safe_next(request.query_params.get("next"))
    identity = await run_in_threadpool(
        sa.identity_from_token, request.cookies.get(sa.SESSION_COOKIE),
    )
    if identity is not None:
        return RedirectResponse(next_path, status_code=302)
    return _login_response(request, next_path=next_path)


def _authenticate(email: str, password: str) -> dict | None:
    """Return the user record if the password is right and the user is active."""
    record = get_user_store().get(email) if email else None
    if record is None:
        burn_time(password)
        return None
    if not verify_password(password, record.get("password_hash")):
        return None
    if not record.get("active"):
        return None
    return record


@router.post("/login")
async def login_submit(request: Request):
    if not _session_mode():
        return RedirectResponse("/home", status_code=303)

    body = (await request.body())[:8192].decode("utf-8", errors="replace")
    form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
    email = normalize_email(form.get("email"))[:254]
    password = form.get("password", "")[:256]
    next_path = sa.safe_next(form.get("next"))

    if not sa.same_origin(request.headers) or not sa.csrf_matches(
        request.cookies.get(sa.CSRF_COOKIE), form.get("csrf"),
    ):
        return _login_response(
            request,
            next_path=next_path,
            email=email,
            error="This page expired. Please sign in again.",
            status_code=400,
        )

    ip = sa.client_ip(request.headers, request.client.host if request.client else None)
    keys = (f"acct:{email}|{ip}", f"ip:{ip}")
    if sa.login_limiter.blocked(keys[0]) or sa.ip_limiter.blocked(keys[1]):
        return _login_response(
            request,
            next_path=next_path,
            email=email,
            error="Too many tries. Wait 5 minutes, then try again.",
            status_code=429,
        )

    record = await run_in_threadpool(_authenticate, email, password)
    if record is None:
        sa.login_limiter.hit(keys[0])
        sa.ip_limiter.hit(keys[1])
        logger.info("Failed sign-in from %s", ip)
        return _login_response(
            request,
            next_path=next_path,
            email=email,
            error=sa.GENERIC_LOGIN_ERROR,
            status_code=401,
        )

    sa.login_limiter.reset(keys[0])
    await run_in_threadpool(get_user_store().record_login, record["email"])
    sa.forget_user(record["email"])

    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        sa.SESSION_COOKIE,
        sa.issue_session(record),
        max_age=sa.session_ttl_seconds(),
        httponly=True,
        secure=sa.secure_cookies(),
        samesite="lax",
        path="/",
    )
    response.delete_cookie(sa.CSRF_COOKIE, path="/login")
    return _no_store(response)


@router.post("/logout")
async def logout(request: Request):
    if not sa.same_origin(request.headers):
        return Response("Bad request", status_code=400)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(
        sa.SESSION_COOKIE,
        path="/",
        secure=sa.secure_cookies(),
        httponly=True,
        samesite="lax",
    )
    return _no_store(response)


def login_redirect_url(path: str, query: str) -> str:
    """``/login?next=<path?query>`` for an unauthenticated page load."""
    target = path + (f"?{query}" if query else "")
    target = sa.safe_next(target)
    if target == "/home":
        return "/login"
    return "/login?next=" + quote(target, safe="/")


def is_admin_path(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/")


def session_gate(identity, method: str, path: str, query: str, accept: str | None):
    """Session-mode access decision for one request; None means "let it through".

    * Public paths (login, health checks, /ui/*) always pass.
    * No valid session: page loads get a 302 to /login?next=..., everything
      else (Mesop /__ui__, /api, /media, assets) gets a 401.
    * /admin/* needs the admin role (the page re-checks in every handler too).
    """
    if sa.is_public_path(path):
        return None
    if identity is None:
        if sa.wants_html(method, path, accept):
            return RedirectResponse(login_redirect_url(path, query), status_code=302)
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    if is_admin_path(path) and identity.role != ROLE_ADMIN:
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return None
