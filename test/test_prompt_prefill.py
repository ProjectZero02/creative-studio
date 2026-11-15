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
"""?prompt= prefill on the studio pages (home page prompt box hand-off)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from common import prompt_prefill
from common.prompt_prefill import MAX_PROMPT_PREFILL_CHARS, prefill_prompt


def _load(handler, state, params):
    """Run an on_load generator with mocked query params and state."""
    with (
        patch("mesop.query_params", params),
        patch("mesop.state", return_value=state),
    ):
        list(handler(MagicMock()))


# --- helper ------------------------------------------------------------------


def _st(**kw):
    return SimpleNamespace(**{"prompt": "", "prompt_prefill_seen": "", **kw})


def test_read_prompt_param_trims_and_caps():
    long = "a" * (MAX_PROMPT_PREFILL_CHARS + 500)
    assert prompt_prefill.read_prompt_param({"prompt": "  hi  "}) == "hi"
    assert len(prompt_prefill.read_prompt_param({"prompt": long})) == 2000
    assert prompt_prefill.read_prompt_param({}) == ""
    assert prompt_prefill.read_prompt_param({"prompt": ["x", "y"]}) == "x"


def test_prefill_fills_empty_field_once():
    state = _st()
    assert prefill_prompt(state, "prompt", params={"prompt": "a cat"})
    assert state.prompt == "a cat"
    # The user clears it; a re-run of on_load for the same arrival does nothing.
    state.prompt = ""
    assert not prefill_prompt(state, "prompt", params={"prompt": "a cat"})
    assert state.prompt == ""


def test_prefill_never_overwrites_user_text():
    state = _st(prompt="my own words")
    assert not prefill_prompt(state, "prompt", params={"prompt": "a cat"})
    assert state.prompt == "my own words"


def test_prefill_treats_placeholder_defaults_as_empty():
    state = _st(prompt="Sample text")
    assert prefill_prompt(
        state,
        "prompt",
        empty_values=("Sample text",),
        params={"prompt": "x y"},
    )
    assert state.prompt == "x y"


def test_prefill_without_param_is_noop():
    state = _st()
    assert not prefill_prompt(state, "prompt", params={})
    assert state.prompt == ""
    assert state.prompt_prefill_seen == ""


# --- /nano-banana and /banana-studio -----------------------------------------


def test_nano_banana_prefills_and_keeps_image_uri():
    from pages.gemini_image_generation import PageState, on_load

    state = PageState()
    _load(on_load, state, {"prompt": "a red fox", "image_uri": "gs://b/x.png"})
    assert state.prompt == "a red fox"
    assert state.prompt_key == 1
    assert state.uploaded_image_gcs_uris == ["gs://b/x.png"]


def test_banana_studio_prefills():
    from pages.banana_studio import PageState, on_load

    state = PageState()
    with patch(
        "pages.banana_studio.prompt_template_service.load_templates",
        return_value=[],
    ):
        _load(on_load, state, {"prompt": "a red fox"})
    assert state.prompt == "a red fox"


# --- /veo ----------------------------------------------------------------------


def test_veo_prefills_text_prompt():
    from pages.veo import on_veo_load
    from state.veo_state import PageState

    state = PageState()
    _load(on_veo_load, state, {"prompt": "waves at dusk"})
    assert state.veo_prompt_input == "waves at dusk"
    assert state.veo_mode == "t2v"


@patch("pages.veo.create_display_url", side_effect=lambda u: u)
def test_veo_prompt_beats_image_default(_display):
    from pages.veo import on_veo_load
    from state.veo_state import PageState

    state = PageState()
    _load(on_veo_load, state, {"image_path": "b/i.jpg", "prompt": "slow zoom in"})
    assert state.veo_mode == "i2v"
    assert state.reference_image_gcs == "gs://b/i.jpg"
    assert state.veo_prompt_input == "slow zoom in"


def test_veo_keeps_user_prompt():
    from pages.veo import on_veo_load
    from state.veo_state import PageState

    state = PageState(veo_prompt_input="mine")
    _load(on_veo_load, state, {"prompt": "theirs"})
    assert state.veo_prompt_input == "mine"


# --- /voice --------------------------------------------------------------------


def test_voice_replaces_sample_script_and_keeps_engine():
    from config.voice import DEFAULT_SCRIPT
    from pages.voice import on_voice_load
    from state.voice_state import VoiceState

    state = VoiceState()
    assert state.text == DEFAULT_SCRIPT
    _load(on_voice_load, state, {"prompt": "Welcome aboard.", "engine": "chirp-3-hd"})
    assert state.text == "Welcome aboard."
    assert state.text_key == 1
    assert state.engine == "chirp-3-hd"


def test_voice_keeps_user_script():
    from pages.voice import on_voice_load
    from state.voice_state import VoiceState

    state = VoiceState(text="My own script.")
    _load(on_voice_load, state, {"prompt": "Welcome aboard."})
    assert state.text == "My own script."


# --- /lyria --------------------------------------------------------------------


def test_lyria_prefills_once():
    from pages.lyria import on_lyria_load
    from state.lyria_state import PageState

    state = PageState()
    _load(on_lyria_load, state, {"prompt": "lofi beat"})
    assert state.music_prompt_input == "lofi beat"
    assert state.music_prompt_placeholder == "lofi beat"
    assert state.music_prompt_textarea_key == 1
    state.music_prompt_input = ""  # user clears it
    _load(on_lyria_load, state, {"prompt": "lofi beat"})
    assert state.music_prompt_input == ""
    assert not state.is_loading


# --- /story --------------------------------------------------------------------


@pytest.fixture
def story(monkeypatch):
    import pages.story_studio as ss

    monkeypatch.setattr(ss, "_refresh_stories", lambda: None)
    return ss


def test_story_prompt_opens_create_with_idea(story):
    from state.story_state import StoryState

    state = StoryState()
    _load(story.on_load, state, {"prompt": "A lighthouse keeper and a whale"})
    assert state.step == "create"
    assert state.idea == "A lighthouse keeper and a whale"
    assert state.job_id == ""
    assert not state.job_running


def test_story_prompt_does_not_replace_draft(story):
    from state.story_state import StoryState

    state = StoryState(loaded=True, step="create", idea="my draft")
    _load(story.on_load, state, {"prompt": "something else"})
    assert (state.step, state.idea) == ("create", "my draft")


def test_story_id_param_wins_over_prompt(story, monkeypatch):
    from state.story_state import StoryState

    opened = []
    monkeypatch.setattr(story, "_open_story", opened.append)
    state = StoryState()
    _load(story.on_load, state, {"id": "s1", "prompt": "ignored"})
    assert opened == ["s1"]
    assert state.idea == ""
