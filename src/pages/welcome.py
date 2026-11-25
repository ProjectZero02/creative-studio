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

"""UI onboarding welcome page for GenMedia Creative Studio."""

import json
from collections.abc import Generator

import mesop as me

from common.analytics import log_page_view
from common.i18n import tx
from components.lang_manager.lang_manager import lang_manager, on_lang_load
from components.page_scaffold import on_theme_load
from components.theme_manager.theme_manager import theme_manager
from components.welcome_hero.welcome_hero import welcome_hero
from state.state import AppState


@me.stateclass
class PageState:
    """Page state for onboarding welcome page."""


def on_tile_click(e: me.WebEvent) -> Generator[None, None, None]:
    """Handle clicking on onboarding tiles to navigate routes."""
    route = e.value["route"]
    me.navigate(route)
    yield


@me.page(
    path="/welcome",
    title="Welcome - Creative Studio",
)
def page() -> None:
    """Define the Mesop page route for the welcome page."""
    app_state = me.state(AppState)
    log_page_view(page_name="welcome", session_id=app_state.session_id)

    theme_manager(theme=app_state.theme_mode, on_theme_load=on_theme_load)
    # Sets <html lang/dir> and loads the saved language, as page_scaffold does.
    lang_manager(
        current=app_state.lang,
        chosen=app_state.lang_chosen,
        on_lang_load=on_lang_load,
    )

    tiles_data = [
        {"icon": "home", "route": "/home"},
        {"label": "Gemini Omni", "route": "/gemini-omni"},
        {"label": "Video Studio", "route": "/veo"},
        {"label": "Gemini Image Generation", "icon": "banana", "route": "/nano-banana"},
        {"label": "Lyria", "route": "/lyria"},
        {"label": "Speech", "route": "/home"},
        {"label": "Workflows", "route": "/home"},
    ]

    for tile in tiles_data:
        if "label" in tile:
            tile["label"] = tx(tile["label"])

    welcome_hero(
        title="Creative Studio",
        subtitle=tx(
            "Fuel your creativity with Google's generative media models on Gemini Enterprise Agent Platform, plus custom workflows."
        ),
        video_url="https://storage.googleapis.com/gdm-deepmind-com-prod-public/media/media/veo__page-cover-1_hcTy7l3.mp4",
        tiles=json.dumps(tiles_data),
        on_tile_click=on_tile_click,
    )
