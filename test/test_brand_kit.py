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
"""Brand kit: cleaning, prompt lines, the logo overlay and Story use."""

import json

from PIL import Image

from common import brand_kit as bk
from services import story_models as sm
from services import story_timeline as st

KIT = {"name": " Acme  Labs ", "colors": ["#1A73E8", "fff", "nope", "#1a73e8"],
       "tone": "warm and plain", "logo_uri": "gs://b/logo.png", "corner": "tl"}


def test_clean():
    k = bk.clean(KIT)
    assert k["name"] == "Acme Labs"
    assert k["colors"] == ["#1a73e8", "#ffffff"]
    assert k["corner"] == "tl" and k["logo_uri"] == "gs://b/logo.png"
    assert bk.clean({"logo_uri": "javascript:x", "corner": "middle"})["logo_uri"] == ""
    assert bk.clean({"corner": "middle"})["corner"] == "auto"
    assert bk.clean({"colors": [f"#00000{i}" for i in range(9)]})["colors"][-1] == "#000004"
    assert bk.is_empty({}) and not bk.is_empty({"tone": "calm"})
    assert bk.from_json("not json") == bk.empty()


def test_prompt_line():
    line = bk.prompt_line(KIT)
    assert line.startswith("Brand: Acme Labs.")
    assert "#1a73e8, #ffffff" in line and "Tone of voice: warm and plain." in line
    assert bk.prompt_line({}) == ""


def test_story_prompts_carry_the_brand_only_when_on():
    story = sm.Story(idea="A bakery opens at dawn", scene_count=2)
    scene = sm.Scene(visual="A baker kneads dough.")
    assert "Brand:" not in sm.scenario_prompt(story)
    assert "#1a73e8" not in sm.frame_prompt(story, scene, False)
    story.brand_json = json.dumps(bk.clean(KIT))
    assert "- Brand: Brand: Acme Labs." in sm.scenario_prompt(story)
    assert "never show the brand name or a logo" in sm.scenario_prompt(story)
    assert "#1a73e8" in sm.frame_prompt(story, scene, False)


def test_logo_overlay_sits_in_the_corner(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 200), (255, 0, 0, 255)).save(logo)
    out = bk.logo_overlay_png(str(logo), 1280, 720, str(tmp_path / "o.png"), "br")
    img = Image.open(out)
    assert img.size == (1280, 720)
    assert img.getpixel((5, 5))[3] == 0  # top left is clear
    bbox = img.getchannel("A").getbbox()
    assert bbox[2] <= 1280 - 28 and bbox[3] <= 720 - 28 and bbox[0] > 1280 / 2
    tl = Image.open(bk.logo_overlay_png(str(logo), 1280, 720, str(tmp_path / "t.png"), "tl"))
    assert tl.getchannel("A").getbbox()[0] == round(720 * 0.05)


def test_render_args_overlay_the_logo_last():
    tl = st.normalize({
        "width": 640, "height": 360, "fps": 24,
        "tracks": [
            {"kind": "video", "clips": [{"id": "a", "src": "a.mp4", "start": 0, "in": 0, "out": 4}]},
        ],
    })
    plain = st.render_args(tl, {"a.mp4": "a.mp4"}, {"a.mp4": False}, {}, "out.mp4")
    with_logo = st.render_args(tl, {"a.mp4": "a.mp4"}, {"a.mp4": False}, {}, "out.mp4",
                               logo_png="logo.png")
    assert "logo.png" not in plain and "logo.png" in with_logo
    graph = with_logo[with_logo.index("-filter_complex") + 1]
    assert "overlay=0:0[logo]" in graph and "[logo]format=yuv420p[vout]" in graph
