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
"""Story Studio AI fix: Gemini's plan JSON -> checked plan -> existing jobs."""
"""The voice agent reads and fills the page in front of the presenter."""

import json

from services import page_forms
from state.story_state import StoryState
from state.veo_state import PageState as VideoState
from state.voice_state import VoiceState


class _States:
    """A stand-in for me.state: one instance per state class."""

    def __init__(self):
        self.made = {}

    def __call__(self, cls):
        return self.made.setdefault(cls, cls())


def test_video_page_snapshot_shows_fields_values_and_choices():
    get = _States()
    get(VideoState).veo_prompt_input = "A fox in snow"
    rows = {r["name"]: r for r in page_forms.snapshot("veo", get)}
    assert rows["prompt"]["value"] == "A fox in snow"
    assert rows["aspect_ratio"]["options"] == ["16:9", "9:16"]
    assert rows["length"]["range"] == [4, 8]
    assert page_forms.snapshot("about", get) == []


def test_fill_sets_state_coerces_values_and_refuses_the_rest():
    get = _States()
    out = page_forms.fill(
        "veo",
        {
            "prompt": "A red fox running",
            "aspect_ratio": "tall",  # a label works too
            "length": 30,  # clamped
            "sound": "off",
            "resolution": "8K",  # not offered
            "generate": True,  # not a field
        },
        get,
    )
    st = get(VideoState)
    assert st.veo_prompt_input == "A red fox running" and st.veo_prompt_textarea_key == 1
    assert (st.aspect_ratio, st.video_length, st.generate_audio) == ("9:16", 8, False)
    assert set(out["changed"]) == {"prompt", "aspect_ratio", "length", "sound"}
    assert "choose 720p, 1080p" in out["refused"]["resolution"]
    assert out["refused"]["generate"] == "not a field on this page"
    assert st.resolution == "720p"


def test_story_fields_follow_the_step_and_are_pinned():
    get = _States()
    st = get(StoryState)
    st.step = "create"
    names = [r["name"] for r in page_forms.snapshot("story", get)]
    assert "idea" in names and "fix_request" not in names
    page_forms.fill("story", {"idea": "A fox learns to fly", "style": "Anime"}, get)
    assert st.idea == "A fox learns to fly" and st.style == "anime"
    assert json.loads(st.pinned_json) == ["style"]
    st.step = "video"
    out = page_forms.fill("story", {"idea": "x", "fix_request": "The end is too dark"}, get)
    assert st.fix_request == "The end is too dark" and "idea" in out["refused"]


def test_voice_page_choices_come_from_the_voice_config():
    get = _States()
    out = page_forms.fill("voice", {"voice": "puck", "pace": "Slow", "script": "Hi."}, get)
    st = get(VoiceState)
    assert (st.voice, st.pace, st.text, st.text_key) == ("Puck", "slow", "Hi.", 1)
    assert not out["refused"]
