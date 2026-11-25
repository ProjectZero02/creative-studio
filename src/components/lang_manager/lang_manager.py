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
"""Keeps <html lang/dir> in sync with AppState.lang and saves the choice."""

import typing

import mesop as me

from common.i18n import AR, apply_lang, route_key, tx_lang
from state.state import AppState


@me.web_component(path="./lang_manager.js")
def lang_manager(
    *,
    current: str,
    chosen: bool,
    on_lang_load: typing.Callable[[me.WebEvent], typing.Any],
    title: str = "",
):
    """`title`: the browser tab title in the page language ("" keeps Mesop's)."""
    return me.insert_web_component(
        key="gm-lang-manager",
        name="lang-manager",
        properties={"current": current, "chosen": chosen, "title": title},
        events={"langLoaded": on_lang_load},
    )


def on_lang_load(e: me.WebEvent):
    """The saved language (or, before any choice, the browser language)."""
    value = e.value if isinstance(e.value, dict) else {}
    apply_lang(
        me.state(AppState),
        str(value.get("lang", "")),
        chosen=bool(value.get("chosen")),
    )
    yield


# Page names (as passed to page_scaffold) whose tab title is not nav.<name>.
_TITLE_KEYS = {
    "gemini_image_generation": "nav.nano_banana",
    "interior_design_v2": "nav.interior_design",
    "library": "nav.library_v2",
    "settings": "settings.title",
    "config": "settings.title",
    "account": "account.title",
    "gemini-omni": "nav.gemini_omni",
    "gemini-tts": "nav.gemini_tts",
    "gemini-writers-workshop": "nav.gemini_writers_workshop",
    "starter-pack": "nav.starter_pack",
}


def page_title(page_name: str, lang: str) -> str:
    """The tab title for a page in Arabic; "" in English (keep @me.page's)."""
    if lang != "ar":
        return ""
    if page_name == "not_found":
        name = tx_lang(lang, "Page not found")
    else:
        key = _TITLE_KEYS.get(page_name) or f"nav.{route_key(page_name)}"
        name = AR.get(key, "")
    return f"{name} | Creative Studio" if name else ""
