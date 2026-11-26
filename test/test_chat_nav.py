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
"""Side menu: chats on top, studios off the list, demos behind a switch."""

from types import SimpleNamespace
from unittest.mock import patch

from components import side_nav
from components.chat_nav import chat_nav
from config.default import get_welcome_page_config


def test_strings_cover_every_label():
    s = chat_nav.strings()
    for key in (
        "new_chat",
        "library",
        "projects",
        "recents",
        "today",
        "rename",
        "delete",
        "move",
    ):
        assert s[key], key


def test_studios_and_chat_routes_leave_the_plain_list():
    pages = get_welcome_page_config()
    studios = {p["route"] for p in pages if p.get("group") in side_nav.HIDDEN_GROUPS}
    assert {"/nano-banana", "/veo", "/story", "/voice"} <= studios
    assert (
        "/home" in side_nav.CHAT_NAV_ROUTES
        and "/library" in side_nav.CHAT_NAV_ROUTES
    )


def test_nav_event_opens_only_local_pages():
    seen = []
    state = SimpleNamespace(current_page="")
    with (
        patch(
            "mesop.navigate",
            lambda url, query_params=None: seen.append((url, query_params)),
        ),
        patch("mesop.state", return_value=state),
    ):
        list(
            chat_nav.on_chat_nav(
                SimpleNamespace(
                    value={"url": "/home", "params": {"chat": "abc", "new": ""}}
                )
            )
        )
        list(
            chat_nav.on_chat_nav(SimpleNamespace(value={"url": "https://evil.test/x"}))
        )
    assert seen == [("/home", {"chat": "abc"}), ("/home", None)]
    assert state.current_page == "/home"
