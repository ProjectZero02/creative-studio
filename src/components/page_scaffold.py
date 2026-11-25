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
from components.lang_manager.lang_manager import lang_manager, on_lang_load, page_title
from components.theme_manager.theme_manager import theme_manager
from components.user_menu.user_menu import user_menu_bar
from components.live_agent.live_agent import live_agent_bridge
from components.notify.notify import notify_bridge
from components.pref_sync.pref_sync import prefs
from state.notify_state import NotifyState
from config.default import Default

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
    if app_state.last_logged_page != page_name:
        log_page_view(page_name=page_name, session_id=app_state.session_id)
        app_state.last_logged_page = page_name

    # Only save a theme the user picked; otherwise follow the system setting.
    theme_manager(
        theme=app_state.theme_mode if app_state.theme_chosen else "",
        on_theme_load=on_theme_load,
        key="gm-theme-manager",
    )
    # Sets <html lang/dir> and saves the language (see common/i18n.py).
    lang_manager(
        current=app_state.lang,
        chosen=app_state.lang_chosen,
        on_lang_load=on_lang_load,
        title=page_title(page_name, app_state.lang),
    )

    # Voice agent: one invisible bridge per page; the call itself lives in the
    # browser outside Mesop's tree, so it survives navigation.
    if Default.LIVE_AGENT_ENABLED:
        live_agent_bridge(page=page_name)

    # Settings saved in this browser (Settings > General).
    prefs()

    # Browser notification when a generation finishes (common/notify.py).
    notice = me.state(NotifyState)
    notify_bridge(seq=notice.seq, title=notice.title, body=notice.body, key="gm-notify")

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
            # Soft colour fields behind every page (CSS .gm-aurora), the same
            # backdrop the home page has (decorative; still for reduced motion).
            with me.box(classes="gm-aurora"):
                me.box(classes="gm-aurora-a")
                me.box(classes="gm-aurora-b")
                me.box(classes="gm-aurora-c")
            user_menu_bar()
            me.slot()


@me.content_component
def page_frame():
    """Page Frame"""
    with me.box(style=MAIN_COLUMN_STYLE):
        with me.box(style=PAGE_BACKGROUND_STYLE):
            with me.box(classes="gm-frame", style=PAGE_BACKGROUND_PADDING_STYLE):
                me.slot()
