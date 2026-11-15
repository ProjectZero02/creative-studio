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
"""Page header: icon tile, title, one-line purpose and an optional info button."""

import functools
import json
import os
import typing

import mesop as me

from components.pill import pill
from components.svg_icon.svg_icon import svg_icon

# Icons drawn by svg_icon instead of the Material icon font.
CUSTOM_ICONS = ["spark", "style", "scene", "banana"]

_NAV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "navigation.json"
)


@functools.lru_cache(maxsize=1)
def nav_descriptions() -> dict[str, str]:
    """Page title -> one-line purpose, from config/navigation.json."""
    try:
        with open(_NAV_FILE, encoding="utf-8") as f:
            pages = json.load(f).get("pages", [])
    except (OSError, ValueError):
        return {}
    return {
        p["display"].lower(): p["description"]
        for p in pages
        if p.get("display") and p.get("description") and p.get("display") != "Home"
    }


def _md_escape(text: str) -> str:
    """Escape characters that markdown would treat as formatting."""
    for ch in "\\`*_[]<>#":
        text = text.replace(ch, "\\" + ch)
    return text


def _render_icon(icon_name: str) -> None:
    if icon_name in CUSTOM_ICONS:
        with me.box(style=me.Style(width=22, height=22)):
            svg_icon(icon_name=icon_name)
    else:
        me.icon(icon=icon_name, style=me.Style(font_size=22, width=22, height=22))


@me.component
def header(
    title: str,
    icon: str,
    show_info_button: bool = False,
    on_info_click: typing.Callable[..., None] | None = None,
    current_status: str = None,
    description: str | None = None,
):
    """Render the page header.

    `description` defaults to the page's line in config/navigation.json, so
    every page says what it is for without per-page edits. Pass "" to hide it.
    """
    purpose = (
        description
        if description is not None
        else nav_descriptions().get(title.lower())
    )

    with me.box(
        classes="gm-header",
        style=me.Style(
            display="flex",
            justify_content="space-between",
            align_items="center",
            gap=16,
            margin=me.Margin(bottom=20),
        ),
    ):
        with me.box(
            style=me.Style(display="flex", align_items="center", gap=14, min_width=0)
        ):
            with me.box(
                style=me.Style(
                    width=44,
                    height=44,
                    flex_shrink=0,
                    border_radius=12,
                    display="flex",
                    align_items="center",
                    justify_content="center",
                    background=me.theme_var("primary-container"),
                    color=me.theme_var("on-primary-container"),
                ),
            ):
                _render_icon(icon)
            with me.box(
                style=me.Style(
                    display="flex", flex_direction="column", gap=2, min_width=0
                )
            ):
                with me.box(
                    style=me.Style(
                        display="flex", align_items="center", gap=10, flex_wrap="wrap"
                    )
                ):
                    # Markdown renders a real <h1>, so screen readers can name the page.
                    with me.box(classes="gm-title gm-title-page"):
                        me.markdown("# " + _md_escape(title))
                    if current_status:
                        pill(current_status, "stage")
                if purpose:
                    me.text(
                        purpose,
                        style=me.Style(
                            font_size=14,
                            line_height="1.45",
                            color=me.theme_var("on-surface-variant"),
                            max_width=720,
                        ),
                    )

        if show_info_button and on_info_click:
            with (
                me.content_button(type="icon", on_click=on_info_click),
                me.tooltip(message="About this page"),
            ):
                me.icon(icon="info_outline")
                with me.box(classes="gm-sr-only"):
                    me.text("About this page")
