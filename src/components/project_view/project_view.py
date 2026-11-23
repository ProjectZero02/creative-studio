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
"""Python API for <gm-project-view>: the body of /project?id=<id>."""

from __future__ import annotations

import json

import mesop as me

from common.i18n import tr
from components.chat_nav.chat_nav import on_chat_nav

_STRINGS = {
    "new_chat": ("project.new_chat", "New chat"),
    "rename": ("project.rename", "Rename"),
    "name": ("project.name", "Project name"),
    "chats": ("project.chats", "Chats"),
    "media": ("project.media", "Media"),
    "untitled": ("project.new_chat", "New chat"),
    "empty_title": ("project.empty_title", "No chats yet"),
    "empty": (
        "project.empty",
        "Start a chat here, or drag one in from the side menu.",
    ),
    "media_empty": (
        "project.media_empty",
        "Pictures, videos and sounds made in these chats show up here.",
    ),
    "not_found": ("project.not_found", "Project not found"),
    "go_home": ("project.go_home", "Go to Home"),
    "drop": ("project.drop", "Drop to add to this project"),
    "open_chat": ("project.open_chat", "Open chat"),
    "download": ("project.download", "Download"),
    "close": ("project.close", "Close"),
}


def strings() -> dict:
    return {k: tr(key, english) for k, (key, english) in _STRINGS.items()}


@me.web_component(path="./project_view.js")
def project_view(*, project_id: str, key: str | None = "project-view"):
    return me.insert_web_component(
        key=key,
        name="gm-project-view",
        properties={
            "projectId": project_id or "",
            "stringsJson": json.dumps(strings(), ensure_ascii=False),
        },
        events={"navEvent": on_chat_nav},
    )
