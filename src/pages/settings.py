# Copyright 2025 Google LLC
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
"""Settings: one page for your preferences, brand, usage and account.

Sections are listed on the left (a row of pills on phones), like the
settings in Linear, Vercel and ChatGPT. General holds the switches; My
brand, Usage and Account reuse those pages' bodies; admins also get links
to Users and the system details (/config). Open a section directly with
``/settings?section=usage``.
"""

from __future__ import annotations

from dataclasses import dataclass

import mesop as me

from common import app_settings
from common.i18n import apply_lang, tr
from common.identity import ANONYMOUS_USER_EMAIL
from common.verified_identity import AUTH_MODE_SESSION, auth_mode
from components.demo_flow.demo_flow import demo_mode_switch, mode_switch_value
from components.header import header
from components.notify.notify import notify_toggle
from components.page_scaffold import page_frame, page_scaffold
from components.test_mode_pill import can_switch as can_switch_test_mode
from components.test_mode_pill import is_on as test_mode_is_on
from components.test_mode_pill import on_test_mode_toggle
from state.state import AppState


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    icon: str
    admin: bool = False
    signed_in: bool = False
    session: bool = False  # only with session sign-in (user accounts)


SECTIONS = [
    Section("general", "General", "tune"),
    Section("brand", "My brand", "palette"),
    Section("usage", "Usage", "monitoring"),
    Section("account", "Account", "lock", signed_in=True),
    Section("users", "Users", "group", admin=True, session=True),
    Section("admin", "Admin", "admin_panel_settings", admin=True),
    Section("about", "About", "info"),
]


@me.stateclass
class SettingsState:
    section: str = "general"


def _session() -> bool:
    return auth_mode() == AUTH_MODE_SESSION


def _is_admin() -> bool:
    # Without session sign-in (local runs, IAP) the old Settings page was
    # open to everyone, so the admin section is too.
    return (not _session()) or me.state(AppState).user_role == "admin"


def _signed_in() -> bool:
    email = me.state(AppState).user_email
    return _session() and bool(email) and email != ANONYMOUS_USER_EMAIL


def visible_sections() -> list[Section]:
    return [
        s
        for s in SECTIONS
        if (not s.admin or _is_admin())
        and (not s.signed_in or _signed_in())
        and (not s.session or _session())
    ]


def _open(key: str):
    """Show a section and load what it needs (generator).

    Loads before the first yield on purpose: the first render mounts the
    theme, language and pref web components, which send their own events
    straight away. A render in between (spinner state) let one of those
    events return the stale "not loaded" state, so My brand could hang on
    its spinner when opened from a link.
    """
    keys = {s.key for s in visible_sections()}
    key = key if key in keys else "general"
    me.state(SettingsState).section = key
    if key == "usage":
        from pages import usage

        s = me.state(usage.UsageState)
        usage._load(s)  # pylint: disable=protected-access
        s.loading = False
    elif key == "brand":
        from pages import brand

        brand.on_load(None)
    elif key == "account":
        from pages import account

        for _ in account.on_load(None):
            pass
    elif key == "users":
        from pages import admin_users

        for _ in admin_users.on_load(None):
            pass
    yield


def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    yield from _open(me.query_params.get("section", "general"))


def on_section(e: me.ClickEvent):
    yield from _open((e.key or "").removeprefix("settings-nav-"))


def on_theme_pick(e: me.ClickEvent):
    s = me.state(AppState)
    mode = "dark" if mode_switch_value(e) == "dark" else "light"
    me.set_theme_mode(mode)
    s.theme_mode = mode
    s.theme_chosen = True
    yield


def on_lang_pick(e: me.ClickEvent):
    apply_lang(me.state(AppState), mode_switch_value(e))
    yield


def on_auto_enhance(e: me.SlideToggleChangeEvent):  # pylint: disable=unused-argument
    s = me.state(AppState)
    s.auto_enhance = not s.auto_enhance
    yield


@me.page(
    path="/settings",
    title="Settings | Creative Studio",
    on_load=on_load,
    security_policy=me.SecurityPolicy(dangerously_disable_trusted_types=True),
)
def page():
    with page_scaffold(page_name="settings"):  # pylint: disable=not-context-manager
        settings_content()


def _text(text: str, cls: str) -> None:
    with me.box(classes=cls):
        me.text(text)


def _general() -> None:
    app = me.state(AppState)
    dark = me.theme_brightness() == "dark"
    with me.box(classes="gm-set-card"):
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-text"):
                _text(tr("settings.theme", "Appearance"), "gm-set-row-title")
            demo_mode_switch(
                value="dark" if dark else "light",
                options=[
                    ("light", "Light", "Bright backgrounds"),
                    ("dark", "Dark", "Dark backgrounds, easier at night"),
                ],
                on_click=on_theme_pick,
                key="settings-theme",
            )
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-text"):
                _text(tr("settings.lang", "Language"), "gm-set-row-title")
            demo_mode_switch(
                value=app.lang,
                options=[("en", "English", ""), ("ar", "العربية", "")],
                on_click=on_lang_pick,
                key="settings-lang",
            )
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-text"):
                _text(tr("settings.enhance", "Improve my prompts"), "gm-set-row-title")
                _text(
                    tr(
                        "settings.enhance_desc",
                        "Gemini adds detail to short prompts when you send them.",
                    ),
                    "gm-set-row-desc",
                )
            me.slide_toggle(
                checked=app.auto_enhance,
                on_change=on_auto_enhance,
                key="settings-enhance",
            )
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-text"):
                _text(tr("menu.notify", "Notify me when done"), "gm-set-row-title")
                _text(
                    tr(
                        "settings.notify_desc",
                        "Shows a browser notice when a job finishes in another tab.",
                    ),
                    "gm-set-row-desc",
                )
            notify_toggle(
                label=tr("menu.notify", "Notify me when done"), key="settings-notify"
            )


def _admin() -> None:
    links = [
        (
            "/config",
            "dns",
            tr("settings.system", "System details"),
            tr(
                "settings.system_desc",
                "Project, storage, models and prompt templates for this deployment.",
            ),
        ),
    ]
    with me.box(classes="gm-set-card"):
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-icon"):
                me.icon("science")
            with me.box(classes="gm-set-row-text"):
                _text(tr("testmode.switch", "Test Mode"), "gm-set-row-title")
                _text(
                    tr(
                        "settings.testmode_desc",
                        "Use the studio with your real media without paying for "
                        "generation. Only affects you.",
                    ),
                    "gm-set-row-desc",
                )
            me.slide_toggle(
                checked=test_mode_is_on(),
                disabled=not can_switch_test_mode(),
                on_change=on_test_mode_toggle,
                key="settings-testmode",
            )
        with me.box(classes="gm-set-row"):
            with me.box(classes="gm-set-row-icon"):
                me.icon("storefront")
            with me.box(classes="gm-set-row-text"):
                _text(tr("settings.demos", "Show demos"), "gm-set-row-title")
                _text(
                    tr(
                        "settings.demos_desc",
                        "Adds Fashion, Interiors, Product 360 and Brand kit to the "
                        "side menu for everyone.",
                    ),
                    "gm-set-row-desc",
                )
            me.slide_toggle(
                checked=bool(app_settings.get("show_demos")),
                on_change=on_show_demos,
                key="settings-demos",
            )
        for route, icon, title, desc in links:
            with me.box(classes="gm-set-row"):
                with me.box(classes="gm-set-row-icon"):
                    me.icon(icon)
                with me.box(classes="gm-set-row-text"):
                    _text(title, "gm-set-row-title")
                    _text(desc, "gm-set-row-desc")
                me.button(
                    tr("settings.open", "Open"),
                    key=f"settings-open-{route}",
                    on_click=on_open_link,
                    type="stroked",
                )


def on_show_demos(e: me.SlideToggleChangeEvent):  # pylint: disable=unused-argument
    """Admins only: show or hide the industry demos in everyone's side menu."""
    if not _is_admin():
        yield
        return
    app_settings.set_value("show_demos", not bool(app_settings.get("show_demos")))
    yield


def on_open_link(e: me.ClickEvent):
    me.navigate((e.key or "").removeprefix("settings-open-") or "/settings")
    yield


def settings_content() -> None:
    state = me.state(SettingsState)
    sections = visible_sections()
    current = state.section if state.section in {s.key for s in sections} else "general"
    with page_frame():  # pylint: disable=not-context-manager
        # The centred page header; .gm-set-top keeps its title solid and the
        # icon tile quiet (studio.src.css, Settings section).
        with me.box(classes="gm-set-top"):
            header(
                tr("settings.title", "Settings"),
                "settings",
                description=tr(
                    "settings.purpose", "Your preferences, brand, usage and account."
                ),
                centered=True,
            )
        with me.box(classes="gm-settings"):
            with me.box(classes="gm-set-nav"):
                for s in sections:
                    label = tr(f"settings.nav.{s.key}", s.label)
                    with me.box(
                        classes="gm-set-nav-item is-on"
                        if s.key == current
                        else "gm-set-nav-item"
                    ):
                        with me.content_button(
                            key=f"settings-nav-{s.key}", on_click=on_section
                        ):
                            me.icon(s.icon)
                            me.text(label)
            # A key per section, so Mesop builds each body fresh. Without it
            # Mesop reused the last section's elements and kept their classes:
            # Account showed an empty icon box and overlapping labels.
            with me.box(classes="gm-set-body", key=f"settings-body-{current}"):
                label = next(x.label for x in sections if x.key == current)
                _text(tr(f"settings.nav.{current}", label), "gm-set-heading")
                if current == "brand":
                    from pages.brand import brand_content

                    brand_content(embedded=True)
                elif current == "usage":
                    from pages.usage import usage_content

                    usage_content(embedded=True)
                elif current == "users":
                    from pages.admin_users import admin_users_content

                    admin_users_content(embedded=True)
                elif current == "about":
                    from pages.about import about_page_content

                    about_page_content(embedded=True)
                elif current == "account":
                    from pages.account import account_content

                    account_content(embedded=True)
                elif current == "admin":
                    _admin()
                else:
                    _general()
