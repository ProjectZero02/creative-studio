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
"""Users admin page (/admin/users), session sign-in only.

Security: the middleware already returns 403 for /admin/* to non-admins, and
this page checks again on render and at the top of EVERY handler. The check
reads the role the middleware set on this very request (internal header in the
WSGI environ), never the Mesop state, because Mesop state round-trips through
the browser.
"""

from __future__ import annotations

import datetime
import json

import mesop as me
from flask import request

from common.i18n import plural, t
from common.identity import (
    INTERNAL_VERIFIED_EMAIL_ENVIRON,
    INTERNAL_VERIFIED_ROLE_ENVIRON,
)
from common.passwords import generate_password, password_problem
from common.session_auth import forget_user
from common.user_store import (
    ROLE_ADMIN,
    ROLE_USER,
    UserStoreError,
    get_user_store,
    normalize_email,
    public_user,
)
from common.verified_identity import AUTH_MODE_SESSION, auth_mode
from components.dialog import dialog, dialog_actions
from components.header import header
from components.page_scaffold import page_frame, page_scaffold

ADMIN_ONLY = "Only admins can manage users."


def current_admin_email(environ: dict | None = None) -> str | None:
    """Return the caller's email if this request is from an admin, else None."""
    if auth_mode() != AUTH_MODE_SESSION:
        return None
    env = environ if environ is not None else request.environ
    if env.get(INTERNAL_VERIFIED_ROLE_ENVIRON, "") != ROLE_ADMIN:
        return None
    return normalize_email(env.get(INTERNAL_VERIFIED_EMAIL_ENVIRON)) or None


@me.stateclass
class AdminUsersState:
    users_json: str = "[]"
    search: str = ""
    notice: str = ""
    error: str = ""
    add_open: bool = False
    add_name: str = ""
    add_email: str = ""
    add_role: str = ROLE_USER
    add_password: str = ""
    add_error: str = ""
    reset_open: bool = False
    reset_email: str = ""
    reset_password: str = ""
    reset_error: str = ""


def _load_users(state: AdminUsersState) -> None:
    users = [public_user(r) for r in get_user_store().list_users()]
    state.users_json = json.dumps(users)


def _users(state: AdminUsersState) -> list[dict]:
    try:
        return json.loads(state.users_json or "[]")
    except ValueError:
        return []


def _guard(state: AdminUsersState) -> str | None:
    """Per-handler admin check. Sets an error and returns None if not admin."""
    admin = current_admin_email()
    if admin is None:
        state.error = ADMIN_ONLY
        state.notice = ""
        state.add_open = False
        state.reset_open = False
    return admin


def _would_remove_last_admin(email: str, *, new_role=None, new_active=None) -> bool:
    store = get_user_store()
    record = store.get(email)
    if not record or record.get("role") != ROLE_ADMIN or not record.get("active"):
        return False
    losing = (new_role is not None and new_role != ROLE_ADMIN) or new_active is False
    return losing and store.active_admin_count() <= 1


# --------------------------------------------------------------------------- #
# Handlers (each one re-checks admin first)                                   #
# --------------------------------------------------------------------------- #
def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    try:
        _load_users(state)
    except Exception as exc:  # noqa: BLE001
        print(f"[admin_users] load failed: {type(exc).__name__}: {exc}")
        state.error = "Could not load users. Try again."
    yield


def on_search(e: me.InputEvent):
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        return
    state.search = e.value


def open_add(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    state.add_open = True
    state.add_name = ""
    state.add_email = ""
    state.add_role = ROLE_USER
    state.add_password = generate_password()
    state.add_error = ""
    yield


def close_add(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    state.add_open = False
    yield


def on_add_name(e: me.InputBlurEvent):
    me.state(AdminUsersState).add_name = e.value


def on_add_email(e: me.InputBlurEvent):
    me.state(AdminUsersState).add_email = e.value


def on_add_password(e: me.InputBlurEvent):
    me.state(AdminUsersState).add_password = e.value


def on_add_role(e: me.SelectSelectionChangeEvent):
    me.state(AdminUsersState).add_role = e.value


def new_add_password(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    state.add_password = generate_password()
    yield


def submit_add(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    problem = password_problem(state.add_password)
    if problem:
        state.add_error = problem
        yield
        return
    try:
        record = get_user_store().create(
            email=state.add_email,
            name=state.add_name,
            role=state.add_role
            if state.add_role in (ROLE_ADMIN, ROLE_USER)
            else ROLE_USER,
            password=state.add_password,
        )
    except UserStoreError as exc:
        state.add_error = str(exc)
        yield
        return
    state.add_open = False
    state.error = ""
    state.notice = (
        f"Added {record['email']}. Temporary password: {state.add_password} "
        "(shown once; share it privately)."
    )
    state.add_password = ""
    _load_users(state)
    yield


def on_role_change(e: me.SelectSelectionChangeEvent):
    state = me.state(AdminUsersState)
    admin = _guard(state)
    if admin is None:
        yield
        return
    email = normalize_email(e.key)
    role = e.value if e.value in (ROLE_ADMIN, ROLE_USER) else None
    if role is None:
        yield
        return
    if email == admin and role != ROLE_ADMIN:
        state.error = "You can't remove your own admin role."
    elif _would_remove_last_admin(email, new_role=role):
        state.error = "Keep at least one active admin."
    else:
        try:
            get_user_store().update(email, role=role)
            forget_user(email)
            state.error = ""
            state.notice = (
                f"{email} is now {'an admin' if role == ROLE_ADMIN else 'a user'}."
            )
        except UserStoreError as exc:
            state.error = str(exc)
    _load_users(state)
    yield


def toggle_active(e: me.ClickEvent):
    state = me.state(AdminUsersState)
    admin = _guard(state)
    if admin is None:
        yield
        return
    email = normalize_email(e.key)
    record = get_user_store().get(email)
    if record is None:
        state.error = "No such user."
        yield
        return
    new_active = not record.get("active")
    if email == admin and not new_active:
        state.error = "You can't disable your own account."
    elif _would_remove_last_admin(email, new_active=new_active):
        state.error = "Keep at least one active admin."
    else:
        get_user_store().update(email, active=new_active)
        forget_user(email)
        state.error = ""
        state.notice = f"{email} is {'enabled' if new_active else 'disabled'}."
    _load_users(state)
    yield


def open_reset(e: me.ClickEvent):
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    state.reset_email = normalize_email(e.key)
    state.reset_password = generate_password()
    state.reset_error = ""
    state.reset_open = True
    yield


def close_reset(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    state.reset_open = False
    state.reset_password = ""
    yield


def on_reset_password(e: me.InputBlurEvent):
    me.state(AdminUsersState).reset_password = e.value


def submit_reset(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    if _guard(state) is None:
        yield
        return
    problem = password_problem(state.reset_password)
    if problem:
        state.reset_error = problem
        yield
        return
    try:
        get_user_store().set_password(state.reset_email, state.reset_password)
    except UserStoreError as exc:
        state.reset_error = str(exc)
        yield
        return
    forget_user(state.reset_email)
    state.reset_open = False
    state.error = ""
    state.notice = (
        f"New password for {state.reset_email}: {state.reset_password} "
        "(shown once; their other sessions are signed out)."
    )
    state.reset_password = ""
    _load_users(state)
    yield


def dismiss_notice(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(AdminUsersState)
    state.notice = ""
    state.error = ""
    yield


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #
def _fmt(ts: str) -> str:
    if not ts:
        return t("admin.never")
    try:
        dt = datetime.datetime.fromisoformat(ts)
    except ValueError:
        return ts
    return dt.strftime("%d %b %Y, %H:%M UTC")


_COLS = "minmax(140px,1.2fr) minmax(200px,1.6fr) 130px 100px 170px 170px 220px"


def _cell_text(text: str, *, muted: bool = False, strong: bool = False):
    me.text(
        text,
        style=me.Style(
            font_size=14,
            font_weight=600 if strong else 400,
            color=me.theme_var("on-surface-variant" if muted else "on-surface"),
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
    )


def _status_pill(active: bool):
    me.text(
        t("admin.active") if active else t("admin.disabled"),
        style=me.Style(
            display="inline-block",
            padding=me.Padding.symmetric(vertical=2, horizontal=10),
            border_radius=999,
            font_size=12,
            font_weight=600,
            background=me.theme_var(
                "tertiary-container" if active else "surface-container-highest",
            ),
            color=me.theme_var(
                "on-tertiary-container" if active else "on-surface-variant",
            ),
        ),
    )


def _row(user: dict, me_email: str):
    email = user["email"]
    is_self = email == me_email
    with me.box(
        style=me.Style(
            display="grid",
            grid_template_columns=_COLS,
            gap=12,
            align_items="center",
            padding=me.Padding.symmetric(vertical=8, horizontal=16),
            border=me.Border(
                bottom=me.BorderSide(
                    width=1, style="solid", color=me.theme_var("outline-variant"),
                ),
            ),
        ),
    ):
        _cell_text(user.get("name") or "-", strong=True)
        _cell_text(email + (t("admin.you") if is_self else ""), muted=True)
        me.select(
            key=email,
            label=t("admin.role"),
            appearance="outline",
            options=[
                me.SelectOption(label=t("admin.role_admin"), value=ROLE_ADMIN),
                me.SelectOption(label=t("admin.role_user"), value=ROLE_USER),
            ],
            value=user.get("role", ROLE_USER),
            disabled=is_self,
            on_selection_change=on_role_change,
            style=me.Style(width=120, margin=me.Margin(top=4)),
        )
        with me.box():
            _status_pill(bool(user.get("active")))
        _cell_text(_fmt(user.get("created_at", "")), muted=True)
        _cell_text(_fmt(user.get("last_login", "")), muted=True)
        with me.box(style=me.Style(display="flex", gap=4, flex_wrap="wrap")):
            me.button(
                t("admin.reset_password"),
                key=email,
                on_click=open_reset,
                type="stroked",
            )
            me.button(
                t("admin.disable") if user.get("active") else t("admin.enable"),
                key=email,
                on_click=toggle_active,
                type="flat" if not user.get("active") else "stroked",
                disabled=is_self,
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
        for key in (
            "admin.col_name",
            "admin.col_email",
            "admin.col_role",
            "admin.col_status",
            "admin.col_created",
            "admin.col_last",
            "admin.col_actions",
        ):
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


def _add_dialog(state: AdminUsersState):
    with dialog(is_open=state.add_open, key="add-user-dialog"):  # pylint: disable=not-context-manager
        me.text(t("admin.add_user"), type="headline-6")
        me.text(
            t("admin.add_help"),
            style=me.Style(
                font_size=14,
                color=me.theme_var("on-surface-variant"),
                margin=me.Margin(bottom=12),
            ),
        )
        me.input(
            label=t("admin.name"),
            value=state.add_name,
            on_blur=on_add_name,
            appearance="outline",
            style=me.Style(width="100%"),
        )
        me.input(
            label=t("admin.email"),
            value=state.add_email,
            on_blur=on_add_email,
            type="email",
            appearance="outline",
            style=me.Style(width="100%"),
        )
        me.select(
            label=t("admin.role"),
            appearance="outline",
            options=[
                me.SelectOption(label=t("admin.role_user_long"), value=ROLE_USER),
                me.SelectOption(label=t("admin.role_admin_long"), value=ROLE_ADMIN),
            ],
            value=state.add_role,
            on_selection_change=on_add_role,
            style=me.Style(width="100%"),
        )
        with me.box(style=me.Style(display="flex", gap=8, align_items="center")):
            me.input(
                label=t("admin.temp_password"),
                value=state.add_password,
                on_blur=on_add_password,
                appearance="outline",
                style=me.Style(flex_grow=1),
            )
            me.button(t("admin.new"), on_click=new_add_password, type="stroked")
        if state.add_error:
            me.text(
                state.add_error,
                style=me.Style(color=me.theme_var("error"), font_size=14),
            )
        with dialog_actions():  # pylint: disable=not-context-manager
            me.button(t("admin.cancel"), on_click=close_add)
            me.button(t("admin.add_user"), on_click=submit_add, type="flat")


def _reset_dialog(state: AdminUsersState):
    with dialog(is_open=state.reset_open, key="reset-dialog"):  # pylint: disable=not-context-manager
        me.text(t("admin.reset_password"), type="headline-6")
        me.text(
            t("admin.reset_help", email=state.reset_email),
            style=me.Style(
                font_size=14,
                color=me.theme_var("on-surface-variant"),
                margin=me.Margin(bottom=12),
            ),
        )
        me.input(
            label=t("admin.new_password"),
            value=state.reset_password,
            on_blur=on_reset_password,
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


def admin_users_content():
    state = me.state(AdminUsersState)
    admin = current_admin_email()
    with page_frame():  # pylint: disable=not-context-manager
        header(
            "Users",
            "group",
            description="Add people, set their role and reset passwords. Only admins see this page.",
        )
        if admin is None:
            _banner(t("admin.only_admins"), error=True)
            return

        if state.error:
            _banner(state.error, error=True)
        elif state.notice:
            _banner(state.notice, error=False)

        users = _users(state)
        query = state.search.strip().lower()
        if query:
            users = [
                u
                for u in users
                if query in u.get("email", "").lower()
                or query in u.get("name", "").lower()
            ]

        with me.box(
            style=me.Style(
                display="flex",
                gap=12,
                align_items="center",
                justify_content="space-between",
                flex_wrap="wrap",
                margin=me.Margin(bottom=12),
            ),
        ):
            with me.box(style=me.Style(flex="1 1 260px", max_width=420)):
                me.input(
                    label=t("admin.search"),
                    value=state.search,
                    on_input=on_search,
                    appearance="outline",
                    style=me.Style(width="100%"),
                )
            me.button(t("admin.add_user"), on_click=open_add, type="flat")

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
        ), me.box(style=me.Style(min_width=1100)):
            _header_row()
            for user in users:
                _row(user, admin)
            if not users:
                with me.box(style=me.Style(padding=me.Padding.all(24))):
                    _cell_text(
                        t("admin.no_match") if query else t("admin.no_users"),
                        muted=True,
                    )

        me.text(
            plural("admin.count", len(users)),
            style=me.Style(
                font_size=13,
                color=me.theme_var("on-surface-variant"),
                margin=me.Margin(top=10),
            ),
        )

        _add_dialog(state)
        _reset_dialog(state)


@me.page(path="/admin/users", title="Users | GenMedia Studio", on_load=on_load)
def page():
    with page_scaffold(page_name="admin_users"):  # pylint: disable=not-context-manager
        admin_users_content()
