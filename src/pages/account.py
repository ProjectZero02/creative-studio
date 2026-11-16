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
"""Account settings (/account): a signed-in user resets their own password.

Session sign-in only. Laid out like the Users admin page (same header, panel
and reset dialog), but it only ever acts on the caller's own account.

Security: the caller's email is read from the identity the middleware set on
this very request (internal header in the WSGI environ), never from Mesop
state, which round-trips through the browser. The current password is
required, and wrong attempts share the sign-in rate limit.

Changing the password invalidates every session token, including the one in
use, so the page then hands the browser a short-lived renewal token that it
POSTs to /account/renew for a fresh cookie (see components/session_renew).
"""

from __future__ import annotations

import mesop as me
from flask import request

from common import session_auth as sa
from common.i18n import t
from common.identity import INTERNAL_VERIFIED_EMAIL_ENVIRON
from common.passwords import MIN_PASSWORD_LENGTH, verify_password
from common.user_store import UserStoreError, get_user_store, normalize_email
from common.verified_identity import AUTH_MODE_SESSION, auth_mode
from components.dialog import dialog, dialog_actions
from components.header import header
from components.page_scaffold import page_frame, page_scaffold
from components.session_renew.session_renew import session_renew


def current_user_email(environ: dict | None = None) -> str | None:
    """The signed-in caller's email in session mode, else None."""
    if auth_mode() != AUTH_MODE_SESSION:
        return None
    env = environ if environ is not None else request.environ
    return normalize_email(env.get(INTERNAL_VERIFIED_EMAIL_ENVIRON)) or None


def new_password_error(current: str, new: str, confirm: str) -> str:
    """i18n key for what is wrong with the new password, or "" if it is fine."""
    if new != confirm:
        return "account.err_mismatch"
    if len(new) < MIN_PASSWORD_LENGTH:
        return "account.err_short"
    if len(new) > 256:
        return "account.err_long"
    if new == current:
        return "account.err_same"
    return ""


def change_own_password(email: str, current: str, new: str, confirm: str) -> str:
    """Change `email`'s password. Returns "" on success, else an i18n error key.

    Kept free of Mesop so it can be tested directly.
    """
    key = f"pw:{email}"
    if sa.login_limiter.blocked(key):
        return "account.err_too_many"
    store = get_user_store()
    record = store.get(email)
    if (
        record is None
        or not record.get("active")
        or not verify_password(current, record.get("password_hash"))
    ):
        sa.login_limiter.hit(key)
        return "account.err_current"
    problem = new_password_error(current, new, confirm)
    if problem:
        return problem
    sa.login_limiter.reset(key)
    store.set_password(email, new)
    sa.forget_user(email)
    return ""


@me.stateclass
class AccountState:
    notice: str = ""
    error: str = ""
    reset_open: bool = False
    current: str = ""
    new: str = ""
    confirm: str = ""
    reset_error: str = ""
    renew_token: str = ""


def _clear_form(state: AccountState) -> None:
    state.current = ""
    state.new = ""
    state.confirm = ""
    state.reset_error = ""


# --------------------------------------------------------------------------- #
# Handlers                                                                    #
# --------------------------------------------------------------------------- #
def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    state = me.state(AccountState)
    state.renew_token = ""
    if me.query_params.get("changed") == "1":
        state.notice = t("account.changed")
    yield


def open_reset(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AccountState)
    if current_user_email() is None:
        state.error = t("account.err_signed_out")
        yield
        return
    _clear_form(state)
    state.reset_open = True
    yield


def close_reset(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AccountState)
    state.reset_open = False
    _clear_form(state)
    yield


def on_current(e: me.InputBlurEvent):
    me.state(AccountState).current = e.value


def on_new(e: me.InputBlurEvent):
    me.state(AccountState).new = e.value


def on_confirm(e: me.InputBlurEvent):
    me.state(AccountState).confirm = e.value


def submit_reset(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AccountState)
    email = current_user_email()
    if email is None:
        state.reset_open = False
        state.error = t("account.err_signed_out")
        yield
        return
    try:
        problem = change_own_password(email, state.current, state.new, state.confirm)
    except UserStoreError as exc:
        state.reset_error = str(exc)
        yield
        return
    if problem:
        state.reset_error = t(problem, n=MIN_PASSWORD_LENGTH)
        yield
        return
    state.reset_open = False
    _clear_form(state)
    state.error = ""
    state.notice = t("account.changed")
    # Stay signed in: the browser swaps this for a fresh session cookie.
    state.renew_token = sa.issue_renewal(get_user_store().get(email))
    yield


def dismiss_notice(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AccountState)
    state.notice = ""
    state.error = ""
    yield


# --------------------------------------------------------------------------- #
# Rendering (mirrors pages/admin_users.py)                                    #
# --------------------------------------------------------------------------- #
_COLS = "minmax(140px,1fr) minmax(240px,2fr) 220px"


def _cell_text(text: str, *, muted: bool = False, strong: bool = False):
    me.text(
        text,
        style=me.Style(
            font_size=14,
            font_weight=600 if strong else 400,
            color=me.theme_var("on-surface-variant" if muted else "on-surface"),
        ),
    )


def _header_row():
    with me.box(
        style=me.Style(
            display="grid",
            grid_template_columns=_COLS,
            gap=12,
            padding=me.Padding.symmetric(vertical=10, horizontal=16),
            background=me.theme_var("surface-container"),
        ),
    ):
        for key in ("account.col_setting", "account.col_details", "admin.col_actions"):
            me.text(
                t(key),
                style=me.Style(
                    font_size=12,
                    font_weight=600,
                    letter_spacing="0.04em",
                    text_transform="uppercase",
                    color=me.theme_var("on-surface-variant"),
                ),
            )


def _password_row():
    with me.box(
        style=me.Style(
            display="grid",
            grid_template_columns=_COLS,
            gap=12,
            align_items="center",
            padding=me.Padding.symmetric(vertical=12, horizontal=16),
        ),
    ):
        _cell_text(t("account.password"), strong=True)
        _cell_text(t("account.password_details"), muted=True)
        with me.box(style=me.Style(display="flex", gap=4, flex_wrap="wrap")):
            me.button(t("admin.reset_password"), on_click=open_reset, type="stroked")


def _banner(text: str, *, error: bool):
    with me.box(
        style=me.Style(
            display="flex",
            align_items="center",
            justify_content="space-between",
            gap=12,
            padding=me.Padding.symmetric(vertical=10, horizontal=16),
            border_radius=12,
            margin=me.Margin(bottom=16),
            background=me.theme_var(
                "error-container" if error else "primary-container",
            ),
            color=me.theme_var(
                "on-error-container" if error else "on-primary-container",
            ),
        ),
    ):
        me.text(text, style=me.Style(font_size=14, word_wrap="break-word"))
        me.button(t("admin.dismiss"), on_click=dismiss_notice, type="flat")


def _reset_dialog(state: AccountState):
    with dialog(is_open=state.reset_open, key="account-reset-dialog"):  # pylint: disable=not-context-manager
        me.text(t("admin.reset_password"), type="headline-6")
        me.text(
            t("account.reset_help", n=MIN_PASSWORD_LENGTH),
            style=me.Style(
                font_size=14,
                color=me.theme_var("on-surface-variant"),
                margin=me.Margin(bottom=12),
            ),
        )
        me.input(
            label=t("account.current"),
            value=state.current,
            on_blur=on_current,
            type="password",
            appearance="outline",
            style=me.Style(width="100%"),
        )
        me.input(
            label=t("account.new"),
            value=state.new,
            on_blur=on_new,
            type="password",
            appearance="outline",
            style=me.Style(width="100%"),
        )
        me.input(
            label=t("account.confirm"),
            value=state.confirm,
            on_blur=on_confirm,
            type="password",
            appearance="outline",
            style=me.Style(width="100%"),
        )
        if state.reset_error:
            me.text(
                state.reset_error,
                style=me.Style(color=me.theme_var("error"), font_size=14),
            )
        with dialog_actions():  # pylint: disable=not-context-manager
            me.button(t("admin.cancel"), on_click=close_reset)
            me.button(t("admin.reset_password"), on_click=submit_reset, type="flat")


def account_content():
    state = me.state(AccountState)
    email = current_user_email()
    with page_frame():  # pylint: disable=not-context-manager
        header(
            t("account.title"), "manage_accounts", description=t("account.description"),
        )
        if email is None:
            _banner(t("account.err_signed_out"), error=True)
            return

        if state.error:
            _banner(state.error, error=True)
        elif state.notice:
            _banner(state.notice, error=False)

        with me.box(
            style=me.Style(
                border=me.Border.all(
                    me.BorderSide(
                        width=1, style="solid", color=me.theme_var("outline-variant"),
                    ),
                ),
                border_radius=16,
                overflow_x="auto",
                background=me.theme_var("surface"),
            ),
        ), me.box(style=me.Style(min_width=640)):
            _header_row()
            _password_row()

        _reset_dialog(state)
        if state.renew_token:
            session_renew(token=state.renew_token, key="session-renew")


@me.page(path="/account", title="Account settings | GenMedia Studio", on_load=on_load)
def page():
    with page_scaffold(page_name="account"):  # pylint: disable=not-context-manager
        account_content()
