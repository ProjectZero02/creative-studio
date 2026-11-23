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
"""Home page: the one-box chat, its headline words and starters."""

import os

from common import i18n
from components.home_chat import home_chat as hc
from config.default import get_welcome_page_config

ASSETS = os.path.join(os.path.dirname(__file__), "..", "src", "assets", "ui")


def test_lede_words_open_real_studios():
    routes = {p.get("route") for p in get_welcome_page_config()}
    words = [s for s in hc.lede_segments() if s.get("kind")]
    assert [w["kind"] for w in words] == ["image", "video", "voice", "music", "film"]
    for w in words:
        assert w["href"] in routes, w
        assert w["tip"]


def test_lede_reads_as_one_sentence_in_both_languages(monkeypatch):
    joined = "".join(s["text"] for s in hc.lede_segments())
    assert joined == "Turn one idea into images, video, voice and music, or a finished short film."
    monkeypatch.setattr(i18n, "current_lang", lambda: "ar")
    ar = hc.lede_segments()
    assert len([s for s in ar if s.get("kind")]) == 5
    assert "{" not in "".join(s["text"] for s in ar)


def test_lede_is_plain_text():
    assert hc.lede() == "Turn one idea into images, video, voice and music, or a finished short film."


def test_type_chips_open_real_studios_with_samples(monkeypatch):
    routes = {p.get("route") for p in get_welcome_page_config()}
    chips = hc.kinds()
    assert [c["kind"] for c in chips] == ["image", "video", "music", "voice", "film"]
    for c in chips:
        assert c["href"] in routes, c
        assert c["label"]
        assert len(c["samples"]) >= 2 and all(c["samples"])
    monkeypatch.setattr(i18n, "current_lang", lambda: "ar")
    assert all(c["label"] != "Image" for c in hc.kinds() if c["kind"] == "image")


def test_placeholder_is_short():
    assert hc.strings()["placeholder"] == "Ask me anything"


def test_examples_cover_different_kinds():
    ex = hc.examples()
    assert len(ex) >= 3
    kinds = [e["kind"] for e in ex]
    assert len(set(kinds)) == len(kinds)
    assert "film" in kinds
    assert all(e["text"] for e in ex)
    assert len({e["text"] for e in ex}) == len(ex)


def test_strings_have_every_label():
    s = hc.strings()
    for key in ("placeholder", "send", "new_chat", "making", "ready", "failed", "download"):
        assert s[key], key
