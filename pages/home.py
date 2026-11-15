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
"""Home: what the studio does, quick starts, then every capability by group."""

from collections import defaultdict

import mesop as me

from components.capability_card.capability_card import capability_card
from components.page_scaffold import page_frame, page_scaffold
from config.default import get_welcome_page_config
from state.state import AppState


@me.page(
    path="/home",
    title="GenMedia Studio · Google Cloud Vertex AI",
    security_policy=me.SecurityPolicy(
        dangerously_disable_trusted_types=True,
    ),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Google+Symbols:opsz,wght,FILL,GRAD,ROND@20..48,100..700,0..1,-50..200,0..100&icon_names=spark",
    ],
)
def page():
    """Main Page."""
    state = me.state(AppState)
    with page_scaffold(page_name="home"):  # pylint: disable=E1129:not-context-manager
        with page_frame():  # pylint: disable=E1129:not-context-manager
            home_page_content(state)


def handle_tile_click(e: me.WebEvent):
    route = e.value.get("route")
    if route:
        me.navigate(route)


def on_quick_start(e: me.ClickEvent):
    if e.key:
        me.navigate(e.key)


GROUP_ORDER = ["foundation", "workflows", "studio"]

SECTIONS = {
    "foundation": ("Models", "Google's generative models. Open one to try it with your own prompt."),
    "workflows": ("Workflows", "Ready-made flows that combine models for a real task."),
    "studio": ("Studio", "Everything you've made, and tools to edit it."),
}

# Quick starts shown under the hero: (label, route, icon). Only routes that are
# enabled in navigation.json are shown.
QUICK_STARTS = [
    ("Generate an image", "/nano-banana", "image"),
    ("Create a video", "/veo", "movie"),
    ("Make music", "/lyria", "music_note"),
    ("Open library", "/library_v2", "photo_library"),
]


def _mode_label(mode: str) -> str:
    """'image,video' -> 'Image + video'."""
    parts = [p.strip() for p in (mode or "").split(",") if p.strip()]
    return " + ".join(parts).capitalize() if parts else ""


def home_page_content(app_state: me.state):  # pylint: disable=unused-argument
    """Home page body."""
    pages = [p for p in get_welcome_page_config() if p.get("display") != "Home"]
    enabled_routes = {p.get("route") for p in pages}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for page_data in pages:
        if page_data.get("group") and page_data.get("align") != "bottom":
            grouped[page_data["group"]].append(page_data)

    with me.box(style=me.Style(display="flex", flex_direction="column", gap=40)):
        _hero(enabled_routes)

        for group_name in GROUP_ORDER:
            items = grouped.get(group_name)
            if not items:
                continue
            title, blurb = SECTIONS.get(group_name, (group_name.title(), ""))
            with me.box(style=me.Style(display="flex", flex_direction="column", gap=16)):
                with me.box(style=me.Style(display="flex", flex_direction="column", gap=4)):
                    with me.box(classes="gm-title gm-title-section"):
                        me.markdown("## " + title)
                    if blurb:
                        me.text(
                            blurb,
                            style=me.Style(font_size=14, color=me.theme_var("on-surface-variant")),
                        )
                media = group_name == "foundation"
                with me.box(
                    classes="gm-grid gm-grid-media" if media else "gm-grid gm-grid-compact",
                    style=me.Style(
                        display="grid",
                        grid_template_columns=(
                            "repeat(auto-fill, minmax(260px, 1fr))"
                            if media
                            else "repeat(auto-fill, minmax(280px, 1fr))"
                        ),
                        gap=16,
                    ),
                ):
                    for page_data in items:
                        capability_card(
                            key=f"card-{page_data.get('route')}",
                            label=page_data.get("display", ""),
                            route=page_data.get("route", ""),
                            description=page_data.get("description", ""),
                            icon=page_data.get("icon", ""),
                            icon_family=page_data.get("icon_family", ""),
                            mode=_mode_label(page_data.get("mode", "")),
                            video_url=page_data.get("video_url", "") if media else "",
                            video_object_position=page_data.get("video_object_position", "center"),
                            size="media" if media else "compact",
                            on_click=handle_tile_click,
                        )


def _hero(enabled_routes: set):
    with me.box(
        classes="gm-hero",
        style=me.Style(
            display="flex",
            flex_direction="column",
            gap=20,
            padding=me.Padding(top=36, bottom=32, left=36, right=36),
            border_radius=20,
            background=me.theme_var("surface-container-lowest"),
            border=me.Border.all(me.BorderSide(width=1, style="solid", color="var(--gm-border)")),
        ),
    ):
        with me.box(style=me.Style(display="flex", flex_direction="column", gap=10, max_width=760)):
            me.text(
                "Google Cloud · Vertex AI",
                style=me.Style(
                    font_size=13,
                    font_weight=600,
                    letter_spacing="0.02em",
                    color=me.theme_var("primary"),
                ),
            )
            with me.box(classes="gm-title gm-title-hero"):
                me.markdown("# Create images, video, music and speech with Google's generative AI")
            me.text(
                "Pick a model to try it with your own prompt, or start from a workflow. "
                "Everything you make is saved to your library.",
                style=me.Style(
                    font_size=16,
                    line_height="1.5",
                    color=me.theme_var("on-surface-variant"),
                ),
            )
        with me.box(classes="gm-quick", style=me.Style(display="flex", flex_wrap="wrap", gap=10)):
            first = True
            for label, route, icon in QUICK_STARTS:
                if route not in enabled_routes:
                    continue
                with me.content_button(
                    key=route,
                    type="flat" if first else "stroked",
                    color="primary" if first else None,
                    on_click=on_quick_start,
                    style=me.Style(height=44, padding=me.Padding.symmetric(horizontal=18)),
                ):
                    with me.box(style=me.Style(display="flex", align_items="center", gap=8)):
                        me.icon(icon, style=me.Style(font_size=20, width=20, height=20))
                        me.text(label, style=me.Style(font_size=14, font_weight=500))
                first = False
