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
"""Image Studio uses aspect, size and count typed in the prompt."""

from unittest.mock import MagicMock, patch

import pages.gemini_image_generation as page
from pages.gemini_image_generation import PageState


def _run(handler, page_state, app_state):
    with patch("mesop.state") as mock_state:
        mock_state.side_effect = lambda cls: (
            page_state if cls is PageState else app_state
        )
        for _ in handler(MagicMock()):
            pass


def _generate(state, app_state):
    """Run generate_images in mock mode; return the prompt the run used."""
    seen = {}

    def fake_run(final_prompt, shown_prompt=None):
        seen["sent"] = final_prompt
        seen["shown"] = shown_prompt
        yield

    with (
        patch.object(page, "mock_enabled", return_value=True),
        patch.object(page, "_mock_image_run", side_effect=fake_run),
    ):
        _run(page.generate_images, state, app_state)
    return seen


def test_typed_ratio_and_size_win_over_chips(app_state_factory):
    state = PageState(prompt="A red bike at 16:9 in 4K", aspect_ratio="1:1")
    seen = _generate(state, app_state_factory())
    assert state.aspect_ratio == "16:9"
    assert state.image_size == "4K"
    assert seen["sent"] == "A red bike"
    assert seen["shown"] == "A red bike at 16:9 in 4K"
    assert "16:9 (was 1:1)" in state.settings_notice
    assert state.settings_undo_json


def test_unsupported_count_is_explained_not_applied(app_state_factory):
    state = PageState(prompt="2 images of a cat")
    seen = _generate(state, app_state_factory())
    # Still one image (0 is "Auto"; the Image Studio P1 fix pins it to 1).
    assert max(1, state.num_images_to_generate) == 1
    assert seen["sent"] == "a cat"
    assert "one image at a time" in state.settings_notice
    assert state.settings_undo_json == ""  # nothing to undo


def test_no_settings_leaves_everything_alone(app_state_factory):
    state = PageState(prompt="A 16:9 TV on the wall", aspect_ratio="1:1")
    seen = _generate(state, app_state_factory())
    assert state.aspect_ratio == "1:1"
    assert seen["sent"] == "A 16:9 TV on the wall"
    assert state.settings_notice == ""


def test_undo_restores_chips_and_is_remembered(app_state_factory):
    app_state = app_state_factory()
    state = PageState(prompt="a lake, 16:9", aspect_ratio="1:1")
    _generate(state, app_state)
    _run(page.on_image_settings_undo, state, app_state)
    assert state.aspect_ratio == "1:1"
    assert state.settings_undo_json == ""
    assert "next run" in state.settings_notice
    # The same words aren't applied again on the next run.
    seen = _generate(state, app_state)
    assert state.aspect_ratio == "1:1"
    assert seen["sent"] == "a lake, 16:9"


def test_clear_forgets_undone_words(app_state_factory):
    app_state = app_state_factory()
    state = PageState(prompt="a lake, 16:9", aspect_ratio="1:1")
    _generate(state, app_state)
    _run(page.on_image_settings_undo, state, app_state)
    with patch.object(page, "progress_clear"):
        _run(page.on_clear_click, state, app_state)
    assert state.settings_ignored_json == ""
    assert state.settings_notice == ""
