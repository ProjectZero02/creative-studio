# Copyright 2025 Google LLC
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
"""Prompts improved on send (common/auto_enhance.py)."""

from common import auto_enhance as ae


def test_wanted_short_prompts_only():
    assert ae.wanted("a red fox")
    assert not ae.wanted("")
    assert not ae.wanted("   ")
    assert not ae.wanted("word " * ae.MAX_WORDS)
    assert not ae.wanted("a red fox", enabled=False)


def test_rewrites_short_prompt():
    calls = []

    def fake(prompt, instructions, **kwargs):
        calls.append((prompt, instructions, kwargs))
        return "  a red fox in deep snow, golden hour  "

    out = ae.enhance_on_send("a red fox", "RULES", enabled=True, rewrite=fake)
    assert out == "a red fox in deep snow, golden hour"
    assert calls == [("a red fox", "RULES", {})]


def test_passes_images():
    seen = {}

    def fake(prompt, instructions, **kwargs):
        seen.update(kwargs)
        return "better"

    ae.enhance_on_send("x y", "R", [("gs://b/a.png", "image/png")], enabled=True, rewrite=fake)
    assert seen == {"images": [("gs://b/a.png", "image/png")]}


def test_keeps_original_when_off_long_empty_or_failing():
    def boom(*_a, **_k):
        raise RuntimeError("quota")

    long = "word " * 50
    assert ae.enhance_on_send("a fox", "R", enabled=False, rewrite=lambda *a, **k: "no") == "a fox"
    assert ae.enhance_on_send(long, "R", enabled=True, rewrite=lambda *a, **k: "no") == long
    assert ae.enhance_on_send("a fox", "R", enabled=True, rewrite=lambda *a, **k: "") == "a fox"
    assert ae.enhance_on_send("a fox", "R", enabled=True, rewrite=boom) == "a fox"


def test_setting_defaults_on_outside_mesop():
    assert ae.setting_on() is True
