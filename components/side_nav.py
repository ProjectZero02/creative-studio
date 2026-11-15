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

from components.styles import SIDENAV_MAX_WIDTH, SIDENAV_MIN_WIDTH
from components.svg_icon.svg_icon import svg_icon
from config.default import Default, get_welcome_page_config
from state.state import AppState

cfg = Default()

GROUP_LABELS = {
    "foundation": "Create",
    "workflows": "Industry demos",
    "studio": "Your work",
}

# Page names (as passed to page_scaffold) that differ from their nav route.
_PAGE_ALIASES = {
    "gemini_image_generation": "nano_banana",
    "interior_design_v2": "interior_design",
    "library": "library_v2",
    "object_rotation": "object_rotation",
}

# Icons drawn by the svg_icon component instead of the Material icon font.
CUSTOM_ICONS = ["spark", "style", "scene"]


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
    yield


def navigate_to(e: me.ClickEvent):
    """Go to the page whose route is the button key."""
    s = me.state(AppState)
    route_to_navigate = e.key
    if route_to_navigate:
        s.current_page = route_to_navigate
        me.navigate(route_to_navigate)
    yield


def sr_only(text: str):
    """Text only screen readers hear (names icon-only buttons)."""
    with me.box(classes="gm-sr-only"):
        me.text(text)


def _render_icon(icon_name: str, active: bool = False):
    color = me.theme_var("primary") if active else me.theme_var("on-surface-variant")
    if icon_name in CUSTOM_ICONS:
        with me.box(style=me.Style(width=22, height=22, color=color, flex_shrink=0)):
            svg_icon(icon_name=icon_name)
    else:
        me.icon(
            icon=icon_name,
            style=me.Style(color=color, font_size=22, width=22, height=22, flex_shrink=0),
        )


@me.component
def sidenav(current_page: Optional[str]):
    """Render side navigation."""
    app_state = me.state(AppState)
    current = current_page or app_state.current_page
    opened = app_state.sidenav_open

    pages = [p for p in get_welcome_page_config() if p.get("route")]
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
            background=me.theme_var("surface-container-low"),
            border=me.Border(right=me.BorderSide(width=1, style="solid", color="var(--gm-border)")),
            transition="width 200ms cubic-bezier(0.2, 0, 0, 1)",
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
                padding=me.Padding(top=12, bottom=12, left=12, right=12),
                box_sizing="border-box",
                overflow_x="hidden",
                overflow_y="auto",
            ),
        ):
            # Brand row: menu toggle + wordmark.
            with me.box(
                style=me.Style(
                    display="flex",
                    align_items="center",
                    gap=8,
                    height=48,
                    margin=me.Margin(bottom=8),
                ),
            ):
                with me.content_button(
                    type="icon",
                    on_click=on_sidenav_menu_click,
                    style=me.Style(width=48, height=48, padding=me.Padding.all(12)),
                ):
                    me.icon(icon="menu_open" if opened else "menu")
                    sr_only("Close menu" if opened else "Open menu")
                if opened:
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
                                "on Vertex AI",
                                style=me.Style(font_size=11, color=me.theme_var("on-surface-variant"), white_space="nowrap"),
                            )

            for group, items in sections:
                label = GROUP_LABELS.get(group, "")
                if label:
                    if opened:
                        me.text(
                            label,
                            style=me.Style(
                                font_size=11,
                                font_weight=600,
                                letter_spacing="0.06em",
                                text_transform="uppercase",
                                color=me.theme_var("on-surface-variant"),
                                padding=me.Padding(left=12, top=14, bottom=6),
                                white_space="nowrap",
                            ),
                        )
                    else:
                        me.box(
                            style=me.Style(
                                height=1,
                                background="var(--gm-border)",
                                margin=me.Margin(top=10, bottom=10, left=8, right=8),
                            )
                        )
                for page in items:
                    _nav_item(page, current, minimized=not opened)

            # Bottom: settings, about, theme.
            with me.box(
                style=me.Style(
                    margin=me.Margin(top="auto"),
                    padding=me.Padding(top=12),
                    display="flex",
                    flex_direction="column",
                    gap=2,
                    border=me.Border(top=me.BorderSide(width=1, style="solid", color="var(--gm-border)")),
                ),
            ):
                for page in bottom_items:
                    _nav_item(page, current, minimized=not opened)
                theme_toggle_icon(9, "light_mode", "Theme", not opened)


def _nav_item(page: dict, current: Optional[str], minimized: bool):
    menu_item(
        item_id=f"{page.get('id', '')}_{page.get('display', '').lower().replace(' ', '_')}",
        icon=page.get("icon", "circle"),
        text=page.get("display", ""),
        route=page.get("route"),
        minimized=minimized,
        active=is_active(page.get("route"), current),
    )


def _item_style(active: bool, minimized: bool) -> me.Style:
    return me.Style(
        width="100%" if not minimized else 48,
        min_width=0,
        height=44,
        padding=me.Padding.symmetric(horizontal=12 if not minimized else 0),
        border_radius=10,
        justify_content="flex-start" if not minimized else "center",
        background=("var(--gm-active-nav)" if active else "transparent"),
        color=me.theme_var("primary") if active else me.theme_var("on-surface"),
        font_weight=600 if active else 500,
        margin=me.Margin(bottom=2),
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
    """Render one menu item (icon only when minimized)."""
    is_clickable = bool(route)
    button_key = route if is_clickable else f"item_{item_id}"

    if minimized:
        with me.tooltip(message=text, position="right"):
            with me.content_button(
                key=button_key,
                on_click=navigate_to if is_clickable else None,
                disabled=not is_clickable,
                style=_item_style(active, True),
            ):
                _render_icon(icon, active)
                sr_only(text)
    else:
        with me.content_button(
            key=button_key,
            on_click=navigate_to if is_clickable else None,
            disabled=not is_clickable,
            style=_item_style(active, False),
        ):
            with me.box(
                style=me.Style(display="flex", align_items="center", gap=12, width="100%"),
            ):
                _render_icon(icon, active)
                me.text(
                    text,
                    style=me.Style(
                        text_align="left",
                        font_size=14,
                        white_space="nowrap",
                        overflow="hidden",
                        text_overflow="ellipsis",
                    ),
                )


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
    label = "Switch to light mode" if is_dark else "Switch to dark mode"
    icon_name = "light_mode" if is_dark else "dark_mode"
    if min:
        with me.tooltip(message=label, position="right"):
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
                me.text("Light mode" if is_dark else "Dark mode", style=me.Style(font_size=14, white_space="nowrap"))


MENU_BOTTOM = me.Style(
    margin=me.Margin(top="auto"),
    padding=me.Padding(bottom=12),
)
