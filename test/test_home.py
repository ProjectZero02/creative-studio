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
"""Home page: the hero prompt box and preview posters."""

from types import SimpleNamespace

import pytest

import pages.home as home


@pytest.fixture
def navigations(monkeypatch):
    calls = []
    monkeypatch.setattr(home.me, "navigate", lambda url, query_params=None: calls.append((url, query_params)))
    return calls


def test_every_mode_points_at_a_create_studio():
    routes = {m["route"] for m in home.PROMPT_MODES}
    assert routes == {"/nano-banana", "/veo", "/story", "/voice", "/lyria"}
    for m in home.PROMPT_MODES:
        assert m["label"] and m["placeholder"] and m["examples"]


def test_submit_opens_studio_with_prompt(navigations):
    home.on_prompt_submit(SimpleNamespace(value={"mode": "video", "prompt": "  A drone shot  "}))
    assert navigations == [("/veo", {"prompt": "A drone shot"})]


def test_submit_without_prompt_just_opens_studio(navigations):
    home.on_prompt_submit(SimpleNamespace(value={"mode": "music", "prompt": ""}))
    assert navigations == [("/lyria", None)]


def test_submit_caps_prompt_length(navigations):
    home.on_prompt_submit(SimpleNamespace(value={"mode": "image", "prompt": "x" * 5000}))
    assert len(navigations[0][1]["prompt"]) == home.MAX_PROMPT_LEN


def test_unknown_mode_does_nothing(navigations):
    home.on_prompt_submit(SimpleNamespace(value={"mode": "hologram", "prompt": "hi"}))
    assert navigations == []


def test_posters_exist_for_every_create_video():
    from config.default import get_welcome_page_config

    for page in get_welcome_page_config():
        if page.get("route") in home.CARD_BADGES and page.get("video_url"):
            assert home.poster_for(page["video_url"]).startswith("/ui/posters/"), page["route"]


def test_poster_for_unknown_video_is_empty():
    assert home.poster_for("https://example.com/nothing-here.mp4") == ""
    assert home.poster_for("") == ""
