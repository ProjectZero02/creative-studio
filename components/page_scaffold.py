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
import mesop as me

from common.analytics import log_page_view
from components.side_nav import sidenav
from state.state import AppState
from components.styles import (
    MAIN_COLUMN_STYLE,
    PAGE_BACKGROUND_PADDING_STYLE,
    PAGE_BACKGROUND_STYLE,
)
from components.theme_manager.theme_manager import theme_manager

def on_theme_load(e: me.WebEvent):
    s = me.state(AppState)
    s.theme_mode = e.value["theme"]
    s.theme_chosen = True
    me.set_theme_mode(s.theme_mode)
    yield


@me.content_component
def page_scaffold(page_name: str):
    """page scaffold component"""

    app_state = me.state(AppState)
    app_state.current_page = page_name
    log_page_view(page_name=page_name, session_id=app_state.session_id)

    # Only save a theme the user picked; otherwise follow the system setting.
    theme_manager(
        theme=app_state.theme_mode if app_state.theme_chosen else "",
        on_theme_load=on_theme_load,
    )

    sidenav("")

    # The content margin follows the nav width. On phones the open menu
    # overlays the page instead (see .gm-content in assets/ui/studio.css).
    with me.box(
        classes="gm-content gm-nav-open" if app_state.sidenav_open else "gm-content",
        style=me.Style(
            display="flex",
            flex_direction="column",
            height="100%",
        ),
    ):
        with me.box(
            classes="gm-page",
            style=me.Style(
                background=me.theme_var("background"),
                height="100%",
                overflow_y="auto",
            ),
        ):
            me.slot()


@me.content_component
def page_frame():
    """Page Frame"""
    with me.box(style=MAIN_COLUMN_STYLE):
        with me.box(style=PAGE_BACKGROUND_STYLE):
            with me.box(classes="gm-frame", style=PAGE_BACKGROUND_PADDING_STYLE):
                me.slot()
