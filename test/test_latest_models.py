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

"""Newest-model defaults, and Veo call sites routed to Gemini Omni (mocked)."""

import dataclasses
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.error_handling import GenerationError
from config import video_studio_models as vsm
from config.default import Default
from config.omni_models import get_omni_model_config
from config.veo_models import VEO_MODELS
from models import workflow_video
from models.requests import APIReferenceImage, VideoGenerationRequest
from models.workflow_video import generate_video_any_model, to_omni_request

OMNI = "gemini-omni-1.2-flash"
VEO = VEO_MODELS[0].version_id


def _default(name: str):
    return Default.__dataclass_fields__[name].default


def _request(**overrides) -> VideoGenerationRequest:
    fields = dict(
        prompt="a fox runs",
        duration_seconds=8,
        video_count=1,
        aspect_ratio="16:9",
        resolution="720p",
        enhance_prompt=False,
        generate_audio=True,
        model_version_id=OMNI,
        person_generation="allow_adult",
    )
    fields.update(overrides)
    return VideoGenerationRequest(**fields)


# --- defaults ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("MODEL_ID", "gemini-4-neon"),
        ("GEMINI_CRITIQUE_MODEL_ID", "gemini-4-neon"),
        ("GEMINI_AUDIO_ANALYSIS_MODEL_ID", "gemini-4-neon"),
        ("GEMINI_STORYBOARDER_NARRATIVE_MODEL_ID", "gemini-4-neon"),
        ("STORY_SCENARIO_MODEL_ID", "gemini-4-neon"),
        ("STORY_LIVE_SETTINGS_MODEL", "gemini-3.5-flash-lite"),
        ("GEMINI_IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
        ("LIVE_MODEL", "gemini-3.8-live"),
        ("OMNI_MODEL_ID", OMNI),
        ("DEFAULT_VEO_MODEL_NAME", OMNI),
        ("CHARACTER_CONSISTENCY_VEO_MODEL", OMNI),
        ("LYRIA_DEFAULT_MODEL", "3-pro-preview"),
        ("LYRIA_MODEL_VERSION", "lyria-002"),
        ("VTO_MODEL_ID", "virtual-try-on-001"),
        ("SHOW_VEO_MODELS", False),
    ],
)
def test_newest_model_defaults(name: str, expected) -> None:
    assert _default(name) == expected


def test_lyria_default_is_a_registered_model() -> None:
    from config.lyria_models import get_lyria_model_config
    from state.lyria_state import PageState

    defaults = {f.name: f.default for f in dataclasses.fields(PageState)}
    assert defaults["selected_model_id"] == "3-pro-preview"
    assert get_lyria_model_config(defaults["selected_model_id"]) is not None


def test_default_video_model_is_omni_and_veo_names_switch_back() -> None:
    assert vsm.DEFAULT_STUDIO_MODEL_ID == OMNI
    veo = VEO_MODELS[0]
    assert vsm._default_video_model_id(veo.model_name) == veo.version_id
    assert vsm._default_video_model_id("not-a-model") == OMNI


def test_video_pages_start_on_omni() -> None:
    from components.veo.extend_dialog import VeoExtendDialogState
    from state.shop_the_look_state import PageState as LookState

    assert LookState().veo_model == OMNI
    assert VeoExtendDialogState().model_id == OMNI


# --- pickers -----------------------------------------------------------------


def test_pickers_hide_veo_by_default(monkeypatch) -> None:
    monkeypatch.setattr(vsm, "veo_models_shown", lambda: False)
    assert vsm.studio_model_ids() == [OMNI]
    assert vsm.video_model_choices() == [("Gemini Omni 1.2 Flash", OMNI)]
    # A Veo model reached by deep link stays listed so the picker can show it.
    assert vsm.studio_model_ids(VEO) == [OMNI, VEO]


def test_pickers_list_veo_with_show_veo_models(monkeypatch) -> None:
    monkeypatch.setattr(vsm, "veo_models_shown", lambda: True)
    assert vsm.studio_model_ids() == [OMNI] + [m.version_id for m in VEO_MODELS]


def test_extend_dialog_lists_models_that_can_extend(monkeypatch) -> None:
    from components.veo.extend_dialog import extension_model_ids

    monkeypatch.setattr(vsm, "veo_models_shown", lambda: False)
    assert extension_model_ids() == [OMNI]
    monkeypatch.setattr(vsm, "veo_models_shown", lambda: True)
    expected = [OMNI] + [m.version_id for m in VEO_MODELS if m.supports_video_extension]
    assert extension_model_ids() == expected


# --- Veo-shaped requests on Omni --------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "mode"),
    [
        ({}, "t2v"),
        ({"reference_image_gcs": "gs://b/a.png"}, "i2v"),
        (
            {
                "reference_image_gcs": "gs://b/a.png",
                "last_reference_image_gcs": "gs://b/z.png",
            },
            "first_last",
        ),
        (
            {
                "r2v_references": [
                    APIReferenceImage(gcs_uri="gs://b/r.png", mime_type="image/png")
                ]
            },
            "ref2v",
        ),
        (
            {"video_input_gcs": "gs://b/v.mp4", "video_input_mime_type": "video/mp4"},
            "extend",
        ),
    ],
)
def test_to_omni_request_picks_mode_from_inputs(overrides, mode) -> None:
    omni = get_omni_model_config(OMNI)
    req = to_omni_request(_request(**overrides), omni)
    assert req.omni_mode == mode
    assert req.model_version_id == OMNI
    if mode == "extend":
        assert req.reference_video_gcs == "gs://b/v.mp4"
        assert req.reference_video_mime_type == "video/mp4"


def test_to_omni_request_keeps_settings_in_range() -> None:
    omni = get_omni_model_config(OMNI)
    req = to_omni_request(
        _request(duration_seconds=30, aspect_ratio="1:1", resolution="8k"), omni
    )
    assert req.duration_seconds == omni.max_duration
    assert req.aspect_ratio == omni.supported_aspect_ratios[0]
    assert req.resolution == "720p"
    assert to_omni_request(_request(duration_seconds=1), omni).duration_seconds == 3


def test_first_last_frame_is_capped_at_ten_seconds() -> None:
    omni = get_omni_model_config(OMNI)
    req = to_omni_request(
        _request(
            duration_seconds=15,
            reference_image_gcs="gs://b/a.png",
            last_reference_image_gcs="gs://b/z.png",
        ),
        omni,
    )
    assert req.duration_seconds == workflow_video.FIRST_LAST_MAX_SECONDS == 10


def test_to_omni_request_rejects_unsupported_mode() -> None:
    preview = get_omni_model_config("gemini-omni-flash-preview")
    with pytest.raises(GenerationError):
        to_omni_request(
            _request(
                model_version_id=preview.version_id,
                reference_image_gcs="gs://b/a.png",
                last_reference_image_gcs="gs://b/z.png",
            ),
            preview,
        )


@patch.object(workflow_video, "generate_video")
@patch.object(
    workflow_video, "generate_omni_video", return_value=("gs://b/out.mp4", "i1")
)
def test_any_model_runs_omni_ids_on_omni(mock_omni, mock_veo) -> None:
    uris, resolution = generate_video_any_model(_request(resolution="1080p"))
    assert uris == ["gs://b/out.mp4"]
    assert resolution == "1080p"
    mock_veo.assert_not_called()
    assert mock_omni.call_args.args[0].omni_mode == "t2v"


@patch.object(
    workflow_video, "generate_video", return_value=(["gs://b/veo.mp4"], "720p")
)
@patch.object(workflow_video, "generate_omni_video")
def test_any_model_keeps_veo_ids_on_veo(mock_omni, mock_veo) -> None:
    request = _request(model_version_id=VEO)
    assert generate_video_any_model(request) == (["gs://b/veo.mp4"], "720p")
    mock_veo.assert_called_once_with(request)
    mock_omni.assert_not_called()


@patch.object(workflow_video, "generate_omni_video", return_value=("", "i1"))
def test_any_model_returns_no_uris_when_omni_returns_nothing(_mock) -> None:
    assert generate_video_any_model(_request())[0] == []


# --- call sites --------------------------------------------------------------


def test_video_job_service_uses_the_router() -> None:
    from services import veo_service

    request = _request()
    with (
        patch.object(
            veo_service,
            "generate_video_any_model",
            return_value=(["gs://b/o.mp4"], "720p"),
        ) as router,
        patch.object(veo_service, "_update_job_status"),
        patch.object(veo_service, "_complete_job") as complete,
        patch.object(veo_service, "enqueue_thumbnail_task", return_value=True),
    ):
        veo_service.process_veo_generation_task("job1", request, "a@b.c")
    router.assert_called_once_with(request)
    assert complete.call_args.args[:3] == ("job1", ["gs://b/o.mp4"], "720p")


def test_shop_the_look_omni_result_has_veo_operation_shape() -> None:
    from models import shop_the_look_handlers as handlers
    from state.shop_the_look_state import PageState as LookState

    state = LookState(result_image_gcs_uri="gs://b/look.png")
    with patch.object(
        handlers, "generate_video_any_model", return_value=(["gs://b/look.mp4"], "720p")
    ) as router:
        op = handlers._omni_look_video(state, OMNI, "walk the runway")
    sent = router.call_args.args[0]
    assert sent.model_version_id == OMNI
    assert sent.reference_image_gcs == "gs://b/look.png"
    assert op == {"done": True, "response": {"videos": [{"gcsUri": "gs://b/look.mp4"}]}}


def test_character_consistency_routes_omni_through_workflow_video() -> None:
    try:
        import models.character_consistency as cc  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"character_consistency import unavailable: {exc}")
    assert cc.is_omni_model_name(cc.cfg.CHARACTER_CONSISTENCY_VEO_MODEL)
    assert (
        cc.generate_workflow_image_to_video
        is workflow_video.generate_workflow_image_to_video
    )


# --- thinking settings -------------------------------------------------------


def test_gemini_4_models_get_no_thinking_budget() -> None:
    from models.thinking import dynamic_thinking, uses_thinking_level

    # A thinking budget is a 400 error on Gemini 4; they think by default.
    assert uses_thinking_level("gemini-4-neon") and uses_thinking_level("gemini-4-argon")
    assert dynamic_thinking("gemini-4-neon") is None
    assert dynamic_thinking("gemini-3.8-flash").thinking_budget == -1


def test_default_text_model_gets_a_thinking_setting_it_accepts() -> None:
    from models.thinking import dynamic_thinking

    model = _default("CHARACTER_CONSISTENCY_GEMINI_MODEL")
    config = dynamic_thinking(model)
    assert config is None or config.thinking_budget is None
