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
"""Music uses the track count and "instrumental" typed in the prompt."""

from unittest.mock import MagicMock, patch

import pages.lyria as page
from state.lyria_state import PageState


def _run(handler, page_state, app_state):
    with patch("mesop.state") as mock_state:
        mock_state.side_effect = lambda cls: (
            page_state if cls is PageState else app_state
        )
        for _ in handler(MagicMock()):
            pass


def _generate(state, app_state):
    """Run on_click_lyria with the Lyria call mocked; return its kwargs."""
    with (
        patch.object(page, "mock_enabled", return_value=False),
        patch.object(
            page, "generate_music_with_lyria", return_value=([], None, [])
        ) as gen,
        patch.object(page, "add_media_item_to_firestore"),
    ):
        _run(page.on_click_lyria, state, app_state)
    return gen.call_args.kwargs


def test_track_count_on_lyria_2(app_state_factory):
    state = PageState(music_prompt_input="3 tracks of calm jazz", selected_model_id="2")
    sent = _generate(state, app_state_factory())
    assert state.sample_count == 3
    assert sent["sample_count"] == 3
    assert sent["prompt"] == "calm jazz"
    assert "3 tracks (was 1 track)" in state.settings_notice


def test_instrumental_turns_lyrics_off_for_this_run(app_state_factory):
    state = PageState(
        music_prompt_input="lofi beat, instrumental",
        selected_model_id="3-clip-preview",
        show_lyrics=True,
        lyrics_input="la la la",
    )
    sent = _generate(state, app_state_factory())
    assert state.show_lyrics is False
    assert sent["lyrics"] == ""
    # The word stays: Lyria only hears "instrumental" from the text.
    assert sent["prompt"] == "lofi beat, instrumental"
    assert "instrumental (was with lyrics)" in state.settings_notice


def test_lyria_3_makes_one_track(app_state_factory):
    state = PageState(
        music_prompt_input="2 songs of rock", selected_model_id="3-pro-preview"
    )
    sent = _generate(state, app_state_factory())
    assert sent["sample_count"] == 1
    assert "one track at a time" in state.settings_notice


def test_undo_restores_lyrics_chip(app_state_factory):
    app_state = app_state_factory()
    state = PageState(
        music_prompt_input="jazz, instrumental",
        selected_model_id="3-clip-preview",
        show_lyrics=True,
    )
    page._apply_typed_settings(state)
    assert state.show_lyrics is False
    _run(page.on_music_settings_undo, state, app_state)
    assert state.show_lyrics is True
    assert page._apply_typed_settings(state) == ("jazz, instrumental", False)
    assert state.show_lyrics is True
