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
"""Video Studio (/veo) with Gemini Omni as the default engine."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.video_studio_models import (  # noqa: E402
    StudioSettings,
    limits,
    normalise,
    omni_mode,
    studio_model_ids,
    studio_modes,
    typical_seconds,
)
from models.requests import OmniVideoGenerationRequest  # noqa: E402
from state.veo_state import PageState  # noqa: E402

OMNI = "gemini-omni-1.2-flash"


# --- config/video_studio_models -------------------------------------------


def test_omni_offers_every_mode_veo_lite_only_three() -> None:
    assert studio_modes(OMNI) == [
        "t2v",
        "i2v",
        "interpolation",
        "r2v",
        "edit",
        "extend",
        "upscale",
    ]
    assert studio_modes("3.1-lite") == ["t2v", "i2v", "interpolation"]
    assert "edit" not in studio_modes("3.1-fast")


def test_mode_ids_translate_to_omni() -> None:
    assert omni_mode("interpolation") == "first_last"
    assert omni_mode("r2v") == "ref2v"
    assert omni_mode("upscale") == "upscale"


def test_limits_come_from_each_registry() -> None:
    omni = limits(OMNI, "t2v")
    assert omni.durations == list(range(3, 16))
    assert omni.resolutions == ["360p", "720p", "1080p", "4k"]
    assert omni.max_references == 10
    assert not omni.supports_advanced
    veo = limits("3.1-fast", "r2v")
    assert veo.durations == [8]
    assert veo.max_samples == 4
    assert veo.supports_style_reference
    assert limits(OMNI, "extend").follows_input_video


def test_typical_seconds_from_model_config() -> None:
    from config.omni_models import get_omni_model_config

    assert (
        typical_seconds(OMNI) == get_omni_model_config(OMNI).typical_generation_seconds
    )
    assert typical_seconds("3.1") == 90


def test_preview_omni_from_deep_link_stays_in_chip() -> None:
    ids = studio_model_ids("gemini-omni-1.1-flash-preview")
    assert ids[:2] == [OMNI, "gemini-omni-1.1-flash-preview"]


def test_normalise_switching_to_veo_drops_omni_only_settings() -> None:
    fixed = normalise("3.1-fast", StudioSettings("upscale", "16:9", "360p", 12, 1))
    assert fixed == StudioSettings("t2v", "16:9", "720p", 8, 1)


def test_normalise_keeps_supported_settings() -> None:
    fixed = normalise(OMNI, StudioSettings("i2v", "9:16", "1080p", 6, 1))
    assert fixed == StudioSettings("i2v", "9:16", "1080p", 6, 1)


# --- pages/veo routing ----------------------------------------------------


def _run(handler, page_state, app_state, event=None):
    with patch("mesop.state") as mock_state:
        mock_state.side_effect = lambda cls: (
            page_state if cls is PageState else app_state
        )
        for _ in handler(event or MagicMock()):
            pass


@patch("pages.veo.add_media_item_to_firestore")
@patch("pages.veo.create_display_url", side_effect=lambda u: "https://x/" + u[5:])
@patch("pages.veo.generate_omni_video", return_value=("gs://b/out.mp4", "int-1"))
@patch("pages.veo.start_async_veo_job")
@patch("pages.veo.mock_enabled", return_value=False)
def test_omni_model_routes_to_generate_omni_video(
    _mock, mock_veo, mock_omni, _display, mock_save, app_state_factory
) -> None:
    from pages.veo import on_click_veo

    state = PageState(veo_prompt_input="a fox", veo_model=OMNI, video_length=12)
    _run(on_click_veo, state, app_state_factory(user_email="u@example.com"))

    mock_veo.assert_not_called()
    request = mock_omni.call_args[0][0]
    assert isinstance(request, OmniVideoGenerationRequest)
    assert (request.omni_mode, request.duration_seconds) == ("t2v", 12)
    assert state.result_display_urls == ["https://x/b/out.mp4"]
    assert state.history_urls[0] == "https://x/b/out.mp4"
    assert state.progress_status == "done"
    saved = mock_save.call_args[0][0]
    assert saved.model == "gemini-omni-1.2-flash"
    assert saved.user_email == "u@example.com"


@patch("pages.veo.generate_omni_video")
def test_omni_missing_video_stops_before_any_call(mock_omni, app_state_factory) -> None:
    from pages.veo import on_click_veo

    state = PageState(veo_prompt_input="night time", veo_model=OMNI, veo_mode="edit")
    _run(on_click_veo, state, app_state_factory())

    mock_omni.assert_not_called()
    assert state.show_error_dialog
    assert "base video" in state.error_message
    assert not state.is_loading


def test_build_omni_request_maps_modes() -> None:
    from pages.veo import build_omni_request

    state = PageState(
        veo_prompt_input="",
        veo_model=OMNI,
        veo_mode="upscale",
        resolution="4k",
        reference_image_gcs="gs://b/img.png",
        reference_video_gcs="gs://b/in.mp4",
    )
    req = build_omni_request(state)
    assert req.omni_mode == "upscale"
    assert req.reference_video_gcs == "gs://b/in.mp4"
    assert req.reference_image_gcs is None

    state.veo_mode = "interpolation"
    state.last_reference_image_gcs = "gs://b/last.png"
    req = build_omni_request(state)
    assert req.omni_mode == "first_last"
    assert req.last_reference_image_gcs == "gs://b/last.png"
    assert req.reference_video_gcs is None


@patch("pages.veo.fake_wait")
@patch("pages.veo.time.sleep")
@patch("pages.veo.generate_omni_video")
@patch("pages.veo.mock_enabled", return_value=True)
def test_mock_mode_covers_omni(_m, mock_omni, _sleep, _wait, app_state_factory) -> None:
    from pages.veo import on_click_veo

    state = PageState(veo_prompt_input="a fox", veo_model=OMNI)
    _run(on_click_veo, state, app_state_factory())

    mock_omni.assert_not_called()
    assert state.result_display_urls
    assert state.progress_stages[1] == "Sending to Gemini Omni"


def test_recent_card_offers_omni_actions_only_for_omni() -> None:
    from config.veo_models import get_veo_model_config
    from pages.veo import _recent_card_actions

    assert _recent_card_actions(OMNI, None).endswith("edit_video,extend,upscale")
    assert _recent_card_actions("3.1", get_veo_model_config("3.1")).endswith(",extend")


@pytest.mark.parametrize(
    "action,mode", [("edit_video", "edit"), ("upscale", "upscale")]
)
def test_recent_card_loads_clip_as_omni_input(action, mode, app_state_factory) -> None:
    from pages.veo import on_recent_video_action

    state = PageState(veo_model=OMNI)
    event = MagicMock()
    event.value = {"action": action, "src": "gs://b/clip.mp4"}
    _run(on_recent_video_action, state, app_state_factory(), event)

    assert state.veo_mode == mode
    assert state.reference_video_gcs == "gs://b/clip.mp4"


@patch("pages.veo.create_display_url", side_effect=lambda u: u)
def test_send_to_omni_deep_link_preselects_omni(_display) -> None:
    from pages.veo import on_veo_load

    state = PageState()
    with (
        patch(
            "pages.veo.me.query_params", {"image_path": "b/i.jpg", "veo_model": OMNI}
        ),
        patch("mesop.state", return_value=state),
    ):
        list(on_veo_load(MagicMock()))
    assert (state.veo_model, state.veo_mode) == (OMNI, "i2v")
    assert state.reference_image_gcs == "gs://b/i.jpg"


@patch("pages.veo.create_display_url", side_effect=lambda u: u)
def test_send_to_veo_deep_link_keeps_veo_fast(_display) -> None:
    from pages.veo import on_veo_load

    state = PageState()
    with (
        patch("pages.veo.me.query_params", {"image_path": "b/i.jpg"}),
        patch("mesop.state", return_value=state),
    ):
        list(on_veo_load(MagicMock()))
    assert (state.veo_model, state.veo_mode) == ("3.1-fast", "i2v")
