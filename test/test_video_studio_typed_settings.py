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
"""Video Studio uses aspect, resolution, length, count and sound typed in the prompt."""

from unittest.mock import MagicMock, patch

from state.veo_state import PageState

OMNI = "gemini-omni-1.2-flash"
VEO = "3.1-fast"


def _run(handler, page_state, app_state):
    with patch("mesop.state") as mock_state:
        mock_state.side_effect = lambda cls: (
            page_state if cls is PageState else app_state
        )
        for _ in handler(MagicMock()):
            pass


@patch("pages.veo.add_media_item_to_firestore")
@patch("pages.veo.create_display_url", side_effect=lambda u: "https://x/" + u[5:])
@patch("pages.veo.generate_omni_video", return_value=("gs://b/out.mp4", "int-1"))
@patch("pages.veo.mock_enabled", return_value=False)
def test_owner_prompt_on_omni(_m, mock_omni, _d, _s, app_state_factory):
    """The owner's case: '...8 seconds, 16:9' on a 9:16 / 4 s setup."""
    from pages.veo import on_click_veo

    typed = "A fox runs through snow, 8 seconds, 16:9, Generate audio on."
    state = PageState(
        veo_prompt_input=typed, veo_model=OMNI, aspect_ratio="9:16", video_length=4
    )
    _run(on_click_veo, state, app_state_factory())

    request = mock_omni.call_args[0][0]
    assert request.prompt == "A fox runs through snow."
    assert request.aspect_ratio == "16:9" and request.duration_seconds == 8
    assert state.aspect_ratio == "16:9" and state.video_length == 8
    assert "16:9 (was 9:16)" in state.settings_notice
    assert "8 s (was 4 s)" in state.settings_notice
    assert "always adds sound" in state.settings_notice
    # Recent keeps the prompt as typed.
    assert state.history_prompts[0] == typed


@patch("pages.veo.start_async_veo_job", return_value={})
@patch("pages.veo.mock_enabled", return_value=False)
def test_veo_audio_resolution_and_count(_m, mock_start, app_state_factory):
    from pages.veo import on_click_veo

    state = PageState(
        veo_prompt_input="a fox, 1080p, 2 videos, no audio", veo_model=VEO
    )
    _run(on_click_veo, state, app_state_factory())

    request = mock_start.call_args[0][0]
    assert request.prompt == "a fox"
    assert request.resolution == "1080p"
    assert request.video_count == 2
    assert request.generate_audio is False
    assert state.generate_audio is False


@patch("pages.veo.generate_omni_video", return_value=("gs://b/out.mp4", "int-1"))
@patch("pages.veo.add_media_item_to_firestore")
@patch("pages.veo.create_display_url", side_effect=lambda u: "https://x/" + u[5:])
@patch("pages.veo.mock_enabled", return_value=False)
def test_too_long_is_snapped_and_explained(_m, _d, _s, mock_omni, app_state_factory):
    from config.video_studio_models import limits
    from pages.veo import on_click_veo

    longest = max(limits(OMNI, "t2v").durations)
    state = PageState(veo_prompt_input="a fox, 60 seconds", veo_model=OMNI)
    _run(on_click_veo, state, app_state_factory())
    assert state.video_length == longest
    assert f"goes up to {longest} s" in state.settings_notice


def test_undo_puts_chips_back(app_state_factory):
    from pages.veo import _apply_typed_settings, on_veo_settings_undo

    state = PageState(
        veo_prompt_input="a fox, 16:9", veo_model=OMNI, aspect_ratio="9:16"
    )
    assert _apply_typed_settings(state) == "a fox"
    assert state.aspect_ratio == "16:9"
    _run(on_veo_settings_undo, state, app_state_factory())
    assert state.aspect_ratio == "9:16"
    assert state.settings_undo_json == ""
    # Undone words go to the model as typed next time.
    assert _apply_typed_settings(state) == "a fox, 16:9"
    assert state.aspect_ratio == "9:16"


def test_edit_mode_ignores_aspect_and_length():
    from pages.veo import _apply_typed_settings

    state = PageState(
        veo_prompt_input="make it night, 16:9, 8 seconds",
        veo_model=OMNI,
        veo_mode="edit",
        aspect_ratio="9:16",
        video_length=4,
    )
    _apply_typed_settings(state)
    assert state.aspect_ratio == "9:16" and state.video_length == 4
    assert state.settings_notice == ""


def test_build_omni_request_defaults_to_the_box():
    from pages.veo import build_omni_request

    state = PageState(veo_prompt_input="a fox, 16:9", veo_model=OMNI)
    assert build_omni_request(state).prompt == "a fox, 16:9"
    assert build_omni_request(state, "a fox").prompt == "a fox"


def _chips(model_id):
    """The chip_menu calls _veo_chips makes for a model, by key."""
    from pages import veo

    state = PageState(veo_model=model_id)
    with patch.object(veo, "chip_menu") as chip:
        veo._veo_chips(state)
    return {c.kwargs["key"]: c.kwargs for c in chip.call_args_list}


def test_omni_shows_sound_always_on():
    chip = _chips(OMNI)["veo_chip_sound_omni"]
    assert chip["checked"] is True and chip["disabled"] is True
    assert chip["value"] == "Sound: always on"
    assert "veo_chip_audio" not in _chips(OMNI)


def test_veo_keeps_its_audio_toggle():
    chips = _chips(VEO)
    assert "veo_chip_audio" in chips
    assert "veo_chip_sound_omni" not in chips
