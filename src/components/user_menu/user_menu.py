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
"""Light/dark, language and the account menu.

On wider screens they sit at the bottom of the side rail (rail_user_menu,
rendered by components/side_nav); on phones in the top bar (user_menu_bar,
rendered by page_scaffold).
"""

import json
import typing

import mesop as me

from common.i18n import apply_lang, other_lang, t, tl
from common.identity import ANONYMOUS_USER_EMAIL
from common.verified_identity import AUTH_MODE_SESSION, auth_mode
from state.state import AppState


@me.web_component(path="./user_menu.js")
def _user_menu(
    *,
    name: str,
    email: str,
    role: str,
    dark: bool,
    show_sign_out: bool,
    show_users: bool,
    show_settings: bool = False,
    show_account: bool = False,
    lang: str = "en",
    labels: str = "{}",
    rail: bool = False,
    expanded: bool = False,
    on_theme: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    on_lang: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    key: str | None = None,
):
    return me.insert_web_component(
        key=key,
        name="user-menu",
        properties={
            "name": name,
            "email": email,
            "role": role,
            "dark": dark,
            "showSignOut": show_sign_out,
            "showUsers": show_users,
            "showSettings": show_settings,
            "showAccount": show_account,
            "lang": lang,
            "labels": labels,
            "rail": rail,
            "expanded": expanded,
        },
        events={"themeEvent": on_theme, "langEvent": on_lang},
    )


_MENU_KEYS = (
    "menu.account",
    "menu.account_of",
    "menu.admin",
    "menu.user",
    "menu.dark_mode",
    "nav.light_mode",
    "menu.notify",
    "menu.brand",
    "menu.theme_to_dark",
    "menu.theme_to_light",
    "menu.users",
    "menu.settings",
    "menu.account_settings",
    "menu.about",
    "menu.sign_out",
    "lang.label",
    "lang.switch",
    "lang.name.en",
    "lang.name.ar",
)


def menu_labels(lang: str) -> str:
    """The menu's text in `lang`, as JSON for the web component."""
    return json.dumps(
        {k.split(".", 1)[1]: tl(lang, k) for k in _MENU_KEYS}, ensure_ascii=False
    )


def on_lang(e: me.WebEvent):
    """Globe button / menu item: switch to the language the event names."""
    value = e.value if isinstance(e.value, dict) else {}
    s = me.state(AppState)
    apply_lang(s, str(value.get("lang") or other_lang(s.lang)))
    yield


def on_theme(e: me.WebEvent):
    """Light/dark switch in the menu (same effect as the side nav toggle)."""
    s = me.state(AppState)
    mode = "dark" if e.value.get("dark") else "light"
    me.set_theme_mode(mode)
    s.theme_mode = mode
    s.theme_chosen = True
    yield


def _menu(*, key: str, rail: bool = False, expanded: bool = False):
    s = me.state(AppState)
    session_mode = auth_mode() == AUTH_MODE_SESSION
    email = "" if s.user_email == ANONYMOUS_USER_EMAIL else s.user_email
    _user_menu(
        key=key,
        name=s.user_name or (t("menu.guest") if not email else ""),
        email=email or t("menu.not_signed_in"),
        role=s.user_role if session_mode else "",
        dark=me.theme_brightness() == "dark",
        show_sign_out=session_mode,
        show_users=session_mode and s.user_role == "admin",
        # Everyone has a Settings page (/settings); the system details in
        # it are admin-only. Account (password) lives there too.
        show_settings=True,
        show_account=False,
        lang=s.lang,
        labels=menu_labels(s.lang),
        rail=rail,
        expanded=expanded,
        on_theme=on_theme,
        on_lang=on_lang,
    )


def rail_user_menu(expanded: bool):
    """Theme, language and account at the bottom of the side rail."""
    _menu(key="rail-user-menu", rail=True, expanded=expanded)


@me.component
def user_menu_bar():
    """The phone top bar: theme, language and avatar on the right.

    Hidden on wider screens (studio.src.css), where they sit in the rail.
    """
    with me.box(
        classes="gm-topbar",
        style=me.Style(
            display="flex",
            justify_content="flex-end",
            align_items="center",
            padding=me.Padding(top=8, right=20, left=20),
            min_height=52,
        ),
    ):
        _menu(key="user-menu")
