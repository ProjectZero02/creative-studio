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
"""Home: one prompt box that opens any studio, then every capability by group."""

import os
from collections import defaultdict

import mesop as me

from components.capability_card.capability_card import capability_card
from components.home_prompt.home_prompt import home_prompt
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


# The hero prompt box: one mode per Create studio. The studio reads ?prompt=.
PROMPT_MODES = [
    {
        "id": "image",
        "route": "/nano-banana",
        "label": "Image",
        "icon": "image",
        "placeholder": "Describe an image to create or edit",
        "examples": [
            "A perfume bottle on wet black stone, studio light",
            "Our sneaker on a Tokyo street at night",
        ],
    },
    {
        "id": "video",
        "route": "/veo",
        "label": "Video",
        "icon": "movie",
        "placeholder": "Describe a shot: subject, action, camera",
        "examples": [
            "Slow dolly in on a barista pouring latte art",
            "Drone shot over a desert road at sunrise",
        ],
    },
    {
        "id": "film",
        "route": "/story",
        "label": "Film",
        "icon": "movie_filter",
        "placeholder": "One idea for a short film, with music and voice",
        "examples": [
            "A 30-second ad for an electric bike in the city",
            "A lighthouse keeper finds a message in a bottle",
        ],
    },
    {
        "id": "voice",
        "route": "/voice",
        "label": "Voice",
        "icon": "record_voice_over",
        "placeholder": "Type a script to turn into natural speech",
        "examples": [
            "Welcome to our store. Today only, everything is 20% off.",
            "Thanks for calling. Your order is on its way.",
        ],
    },
    {
        "id": "music",
        "route": "/lyria",
        "label": "Music",
        "icon": "music_note",
        "placeholder": "Describe a track: mood, instruments, tempo",
        "examples": [
            "Warm lo-fi beat with soft piano, 80 bpm",
            "Uplifting cinematic strings for a product launch",
        ],
    },
]
_MODE_ROUTES = {m["id"]: m["route"] for m in PROMPT_MODES}
MAX_PROMPT_LEN = 2000


def on_prompt_submit(e: me.WebEvent):
    """Open the chosen studio, carrying the idea in ?prompt=."""
    route = _MODE_ROUTES.get((e.value or {}).get("mode", ""))
    if not route:
        return
    prompt = ((e.value or {}).get("prompt") or "").strip()[:MAX_PROMPT_LEN]
    if prompt:
        me.navigate(route, query_params={"prompt": prompt})
    else:
        me.navigate(route)


# The library lives in the side menu, so the home page shows only these two.
GROUP_ORDER = ["foundation", "workflows"]

SECTIONS = {
    "foundation": ("Create", "Google's latest models for images, video, film, voice and music."),
    "workflows": ("Industry demos", "Ready-made flows for retail, products, real estate and marketing."),
}

# Small label on each Create card: the model behind it.
CARD_BADGES = {
    "/nano-banana": "Nano Banana 2.1",
    "/veo": "Gemini Omni 1.2 · New",
    "/story": "Idea to film",
    "/voice": "Gemini 3.8 TTS · New",
    "/lyria": "Lyria 3",
}

_POSTER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "ui", "posters")


def poster_for(video_url: str) -> str:
    """Local still frame for a preview video (assets/ui/posters/<name>.webp), if present."""
    if not video_url:
        return ""
    name = os.path.splitext(os.path.basename(video_url.split("?")[0]))[0]
    return f"/ui/posters/{name}.webp" if os.path.exists(os.path.join(_POSTER_DIR, f"{name}.webp")) else ""


# Bento layout: video and film get the big tiles.
FEATURED_ROUTES = {"/veo", "/story"}


def home_page_content(app_state: me.state):  # pylint: disable=unused-argument
    """Home page body."""
    pages = [p for p in get_welcome_page_config() if p.get("display") != "Home"]
    enabled_routes = {p.get("route") for p in pages}

    grouped: dict[str, list[dict]] = defaultdict(list)
    for page_data in pages:
        if page_data.get("group") and page_data.get("align") != "bottom":
            grouped[page_data["group"]].append(page_data)

    with me.box(classes="gm-home"):
        # Soft colour behind the glass (decorative; frozen for reduced motion).
        with me.box(classes="gm-aurora"):
            me.box(classes="gm-aurora-a")
            me.box(classes="gm-aurora-b")
            me.box(classes="gm-aurora-c")

        _hero(enabled_routes)

        for group_name in GROUP_ORDER:
            items = grouped.get(group_name)
            if not items:
                continue
            _section(group_name, items)


def _hero(enabled_routes: set):
    modes = [m for m in PROMPT_MODES if m["route"] in enabled_routes]
    with me.box(classes="gm-home-hero"):
        with me.box(classes="gm-home-eyebrow"):
            me.text("Google Cloud · Vertex AI")
        with me.box(classes="gm-title gm-home-title"):
            me.markdown("# Google's creative AI, in one studio")
        with me.box(classes="gm-home-lede"):
            me.text("Turn one idea into images, video, voice and music, or a finished short film.")
        if modes:
            with me.box(classes="gm-home-prompt"):
                home_prompt(key="home-prompt", modes=modes, on_submit=on_prompt_submit)


def _section(group_name: str, items: list[dict]):
    title, blurb = SECTIONS.get(group_name, (group_name.title(), ""))
    media = group_name == "foundation"
    with me.box(classes="gm-home-section"):
        with me.box(classes="gm-home-section-head"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## " + title)
            if blurb:
                with me.box(classes="gm-home-blurb"):
                    me.text(blurb)
        with me.box(classes="gm-bento" if media else "gm-demos"):
            for page_data in items:
                route = page_data.get("route", "")
                featured = media and route in FEATURED_ROUTES
                cell = "gm-bento-big" if featured else ("gm-bento-cell" if media else "gm-demo-cell")
                with me.box(classes=cell):
                    capability_card(
                        key=f"card-{route}",
                        label=page_data.get("display", ""),
                        route=route,
                        description=page_data.get("description", ""),
                        icon=page_data.get("icon", ""),
                        icon_family=page_data.get("icon_family", ""),
                        mode=CARD_BADGES.get(route, "") if media else "",
                        video_url=page_data.get("video_url", "") if media else "",
                        poster=poster_for(page_data.get("video_url", "")) if media else "",
                        video_object_position=page_data.get("video_object_position", "center"),
                        size=("featured" if featured else "media") if media else "compact",
                        on_click=handle_tile_click,
                    )
