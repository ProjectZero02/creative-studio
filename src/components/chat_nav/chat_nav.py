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
"""Python API for <gm-chat-nav>: New chat, Library, Projects and Recents."""

from __future__ import annotations

import json

import mesop as me

from common.i18n import tr
from state.state import AppState

_STRINGS = {
    "nav": ("chatnav.nav", "Chats"),
    "new_chat": ("chatnav.new_chat", "New chat"),
    "library": ("nav.library_v2", "Library"),
    "create": ("chatnav.create", "Create"),
    "kind_image": ("home.mode.image.label", "Image"),
    "kind_video": ("home.mode.video.label", "Video"),
    "kind_music": ("home.mode.music.label", "Music"),
    "kind_voice": ("home.mode.voice.label", "Voice"),
    "kind_film": ("home.mode.film.label", "Film"),
    "search": ("chatnav.search", "Search chats"),
    "projects": ("chatnav.projects", "Projects"),
    "new_project": ("chatnav.new_project", "New project"),
    "project_name": ("chatnav.project_name", "Project name"),
    "projects_empty": (
        "chatnav.projects_empty",
        "Group chats for one client or campaign.",
    ),
    "new_in_project": ("chatnav.new_in_project", "New chat here"),
    "show_chats": ("chatnav.show_chats", "Show chats"),
    "recents": ("chatnav.recents", "Recents"),
    "recents_empty": ("chatnav.recents_empty", "Your chats show up here."),
    "no_match": ("chatnav.no_match", "No chats match."),
    "pinned": ("chatnav.pinned", "Pinned"),
    "today": ("chatnav.today", "Today"),
    "yesterday": ("chatnav.yesterday", "Yesterday"),
    "week": ("chatnav.week", "Previous 7 days"),
    "older": ("chatnav.older", "Older"),
    "untitled": ("chatnav.untitled", "New chat"),
    "options": ("chatnav.options", "Options"),
    "rename": ("chatnav.rename", "Rename"),
    "pin": ("chatnav.pin", "Pin"),
    "unpin": ("chatnav.unpin", "Unpin"),
    "move": ("chatnav.move", "Move to project"),
    "no_project": ("chatnav.no_project", "Remove from project"),
    "delete": ("chatnav.delete", "Delete"),
    "confirm_delete": ("chatnav.confirm_delete", "Click again to delete"),
    "confirm_delete_project": ("chatnav.confirm_delete_project", "Delete? Chats stay"),
}


def strings() -> dict:
    return {k: tr(key, english) for k, (key, english) in _STRINGS.items()}


def on_chat_nav(e: me.WebEvent):
    """Open a page the side menu or project page asked for (/home?chat=...,
    /project?id=..., /library_v2)."""
    value = e.value or {}
    url = str(value.get("url") or "/home")
    if not url.startswith("/") or url.startswith("//"):
        url = "/home"
    params = {str(k): str(v) for k, v in (value.get("params") or {}).items() if v}
    me.state(AppState).current_page = url
    me.navigate(url, query_params=params or None)
    yield


@me.web_component(path="./chat_nav.js")
def chat_nav(*, open: bool, current: str = "", key: str | None = "chat-nav"):  # pylint: disable=redefined-builtin
    return me.insert_web_component(
        key=key,
        name="gm-chat-nav",
        properties={
            "open": open,
            "current": current or "",
            "stringsJson": json.dumps(strings(), ensure_ascii=False),
        },
        events={"navEvent": on_chat_nav},
    )
