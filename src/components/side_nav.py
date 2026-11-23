# Copyright 2024 Google LLC
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
"""Side navigation: a slim icon rail that expands into a grouped menu."""

from typing import Optional

import mesop as me

from common import app_settings
from common.i18n import current_lang, is_rtl, route_key, t, tr
from components.styles import SIDENAV_MAX_WIDTH, SIDENAV_MIN_WIDTH
from components.svg_icon.svg_icon import svg_icon
from components.user_menu.user_menu import rail_user_menu
from config.default import Default, get_welcome_page_config
from state.state import AppState

cfg = Default()

GROUP_LABELS = {
    "foundation": "Create",
    "workflows": "Industry demos",
    "studio": "Your work",
}

# Nav group of the industry demo pages, hidden unless "Show demos" is on.
DEMO_GROUP = "workflows"


def _tooltip_side() -> str:
    """Tooltips open away from the nav: right in LTR, left in RTL."""
    return "left" if is_rtl(current_lang()) else "right"


# Page names (as passed to page_scaffold) that differ from their nav route.
_PAGE_ALIASES = {
    "gemini_image_generation": "nano_banana",
    "interior_design_v2": "interior_design",
    "library": "library_v2",
    "object_rotation": "object_rotation",
}

# Icons drawn by the svg_icon component instead of the Material icon font.
CUSTOM_ICONS = ["spark", "style", "scene"]

ICON_SIZE = 20
ITEM_SIZE = 40

# System items pinned to the bottom of the rail, below the pages.
SYSTEM_ITEMS = [
    {"id": "settings", "display": "Settings", "icon": "settings", "route": "/settings", "label_key": "menu.settings"},
]


def _norm(value: str) -> str:
    return value.strip("/").replace("-", "_").lower()


def is_active(route: Optional[str], current_page: Optional[str]) -> bool:
    """True when the nav item for `route` is the page being shown."""
    if not route or not current_page:
        return False
    page = _norm(current_page)
    return _norm(route) == _PAGE_ALIASES.get(page, page)


def on_sidenav_menu_click(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Open or close the menu."""
    state = me.state(AppState)
    state.sidenav_open = not state.sidenav_open


def on_click_title(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Go to the home page."""
    me.navigate(url="/home")


def navigate_to(e: me.ClickEvent):
    """Go to the page whose route is the button key."""
    s = me.state(AppState)
    route_to_navigate = e.key
    if route_to_navigate:
        s.current_page = route_to_navigate
        me.navigate(route_to_navigate)


def sr_only(text: str):
    """Text only screen readers hear (names icon-only buttons)."""
    with me.box(classes="gm-sr-only"):
        me.text(text)


def _render_icon(icon_name: str, active: bool = False):
    color = me.theme_var("on-surface") if active else me.theme_var("on-surface-variant")
    if icon_name in CUSTOM_ICONS:
        with me.box(style=me.Style(width=ICON_SIZE, height=ICON_SIZE, color=color, flex_shrink=0)):
            svg_icon(icon_name=icon_name)
    else:
        me.icon(
            icon=icon_name,
            style=me.Style(color=color, font_size=ICON_SIZE, width=ICON_SIZE, height=ICON_SIZE, flex_shrink=0),
        )


@me.component
def sidenav(current_page: Optional[str]):
    """Render side navigation.

    Like Gemini's rail: pages from the top (they scroll on short screens, with
    no visible bar); Settings, light/dark, language and the account at the
    bottom. Closed, the rail sits on the page background; open, it becomes a
    panel.

    Open and closed render the same elements, so opening only animates the
    width and fades the labels in (studio.src.css, .gm-nav-*): icons never
    move or redraw.
    """
    app_state = me.state(AppState)
    current = current_page or app_state.current_page
    opened = app_state.sidenav_open

    # align "menu" pages (My brand, Usage) live in the avatar menu and Settings.
    # The industry demos (group "workflows") show only when an admin turns on
    # "Show demos" in Settings (common/app_settings.py).
    show_demos = bool(app_settings.get("show_demos"))
    pages = [
        p
        for p in get_welcome_page_config()
        if p.get("route")
        and p.get("align") != "menu"
        and (show_demos or p.get("group") != DEMO_GROUP)
    ]
    top_items = [p for p in pages if p.get("align") != "bottom"]
    bottom_items = [p for p in pages if p.get("align") == "bottom"]

    # Keep the nav order from navigation.json, grouped by section.
    sections: list[tuple[str, list[dict]]] = []
    for page in top_items:
        group = page.get("group", "")
        if not sections or sections[-1][0] != group:
            sections.append((group, []))
        sections[-1][1].append(page)

    with me.sidenav(
        opened=True,
        style=me.Style(
            width=SIDENAV_MAX_WIDTH if opened else SIDENAV_MIN_WIDTH,
            background="var(--gm-panel)" if opened else "transparent",
            border=me.Border(right=me.BorderSide(width=0, style="none")),
            transition="width 220ms cubic-bezier(0.2, 0, 0, 1), background-color 220ms ease",
            box_shadow="none",
            z_index=20,
        ),
    ):
        with me.box(
            classes="gm-nav" if opened else "gm-nav gm-nav-collapsed",
            style=me.Style(
                display="flex",
                flex_direction="column",
                height="100%",
                padding=me.Padding.all(12),
                box_sizing="border-box",
                overflow="hidden",
            ),
        ):
            # Brand row: menu toggle + wordmark (the wordmark fades in when open).
            with me.box(
                style=me.Style(
                    display="flex",
                    align_items="center",
                    gap=8,
                    height=ITEM_SIZE,
                    margin=me.Margin(bottom=12),
                    flex_shrink=0,
                ),
            ):
                with me.box(classes="gm-nav-toggle"):
                    with me.content_button(
                        type="icon",
                        style=me.Style(width=ITEM_SIZE, height=ITEM_SIZE, padding=me.Padding.all(8), flex_shrink=0),
                    ):
                        me.icon(icon="menu")
                        sr_only(t("nav.close_menu") if opened else t("nav.open_menu"))
                with me.box(classes="gm-nav-brand"):
                    with me.content_button(
                        on_click=on_click_title,
                        style=me.Style(padding=me.Padding.symmetric(horizontal=4)),
                    ):
                        with me.box(style=me.Style(display="flex", flex_direction="column", align_items="flex-start", line_height="1.1")):
                            me.text(
                                "GenMedia Studio",
                                style=me.Style(font_size=16, font_weight=600, color=me.theme_var("on-surface"), white_space="nowrap"),
                            )
                            me.text(
                                t("brand.sub"),
                                style=me.Style(font_size=11, color=me.theme_var("on-surface-variant"), white_space="nowrap"),
                            )

            # Pages, from the top.
            with me.box(
                classes="gm-nav-pages",
                style=me.Style(flex_grow=1, min_height=0, overflow_y="auto", overflow_x="hidden"),
            ):
                for group, items in sections:
                    label = (
                        tr(f"nav.group.{group}", GROUP_LABELS[group])
                        if group in GROUP_LABELS
                        else ""
                    )
                    if label:
                        # A gap when closed, a small heading when open (CSS).
                        with me.box(classes="gm-nav-group"):
                            with me.box(classes="gm-nav-label"):
                                me.text(label)
                    for page in items:
                        _nav_item(page, current, minimized=not opened)

            # Bottom: align "bottom" pages, Settings, then light/dark, language
            # and the account (the top bar holds these only on phones).
            with me.box(
                style=me.Style(
                    padding=me.Padding(top=8),
                    display="flex",
                    flex_direction="column",
                    flex_shrink=0,
                ),
            ):
                for page in bottom_items:
                    _nav_item(page, current, minimized=not opened)
                for item in SYSTEM_ITEMS:
                    menu_item(
                        item_id=item["id"],
                        icon=item["icon"],
                        text=t(item["label_key"], item["display"]),
                        route=item["route"],
                        minimized=not opened,
                        active=is_active(item["route"], current),
                    )
                with me.box(classes="gm-nav-account"):
                    rail_user_menu(expanded=opened)


def _nav_item(page: dict, current: Optional[str], minimized: bool):
    menu_item(
        item_id=f"{page.get('id', '')}_{page.get('display', '').lower().replace(' ', '_')}",
        icon=page.get("icon", "circle"),
        text=tr(f"nav.{route_key(page.get('route'))}", page.get("display", "")),
        route=page.get("route"),
        minimized=minimized,
        active=is_active(page.get("route"), current),
    )


def _item_style(active: bool, minimized: bool) -> me.Style:  # pylint: disable=unused-argument
    """One style open or closed: the icon keeps its place, the label is clipped."""
    return me.Style(
        width="100%",
        min_width=0,
        height=ITEM_SIZE,
        padding=me.Padding.symmetric(horizontal=10),
        border_radius=ITEM_SIZE // 2,
        justify_content="flex-start",
        background=("var(--gm-active-nav)" if active else "transparent"),
        color=me.theme_var("on-surface"),
        font_weight=600 if active else 400,
        margin=me.Margin(bottom=2),
        overflow="hidden",
    )


def menu_item(
    item_id: str,
    icon: str,
    text: str,
    route: Optional[str],
    minimized: bool = True,
    content_style: Optional[me.Style] = None,  # pylint: disable=unused-argument
    active: bool = False,
):
    """Render one menu item. The label is always there; closed, it is clipped
    and faded (CSS), and the tooltip names the item instead."""
    is_clickable = bool(route)
    button_key = route if is_clickable else f"item_{item_id}"

    with me.tooltip(message=text, position=_tooltip_side(), disabled=not minimized):
        with me.content_button(
            key=button_key,
            on_click=navigate_to if is_clickable else None,
            disabled=not is_clickable,
            style=_item_style(active, minimized),
        ):
            with me.box(
                style=me.Style(display="flex", align_items="center", gap=14, width="100%"),
            ):
                _render_icon(icon, active)
                with me.box(classes="gm-nav-label"):
                    me.text(text, style=me.Style(text_align="start", font_size=14, white_space="nowrap"))


def toggle_theme(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Switch between light and dark."""
    s = me.state(AppState)
    if me.theme_brightness() == "light":
        me.set_theme_mode("dark")
        s.theme_mode = "dark"
    else:
        me.set_theme_mode("light")
        s.theme_mode = "light"
    s.theme_chosen = True


def theme_toggle_icon(key: int, icon: str, text: str, min: bool = True):  # pylint: disable=redefined-builtin,unused-argument
    """Light/dark switch."""
    is_dark = me.theme_brightness() == "dark"
    label = t("nav.to_light") if is_dark else t("nav.to_dark")
    icon_name = "light_mode" if is_dark else "dark_mode"
    if min:
        with me.tooltip(message=label, position=_tooltip_side()):
            with me.content_button(
                key=str(key),
                on_click=toggle_theme,
                style=_item_style(False, True),
            ):
                _render_icon(icon_name)
                sr_only(label)
    else:
        with me.content_button(
            key=str(key),
            on_click=toggle_theme,
            style=_item_style(False, False),
        ):
            with me.box(style=me.Style(display="flex", align_items="center", gap=12, width="100%")):
                _render_icon(icon_name)
                me.text(
                    t("nav.light_mode") if is_dark else t("nav.dark_mode"),
                    style=me.Style(font_size=14, white_space="nowrap"),
                )


MENU_BOTTOM = me.Style(
    margin=me.Margin(top="auto"),
    padding=me.Padding(bottom=12),
)
