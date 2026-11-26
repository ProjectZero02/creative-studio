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
"""TTS tokens, Omni input estimates, grounding and Veo extensions."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from common import analytics, usage
from config import pricing


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake_record(owner, model, status, units=None, *a, **k):
        calls.append({"model": model, "status": status, "units": dict(units or {})})

    monkeypatch.setattr(usage, "record", fake_record)
    return calls


# 6a. Gemini TTS --------------------------------------------------------------


def _tts_response():
    usage_metadata = SimpleNamespace(
        prompt_token_count=40,
        candidates_token_count=250,
        total_token_count=290,
        prompt_tokens_details=[],
        candidates_tokens_details=[SimpleNamespace(modality="AUDIO", token_count=250)],
    )
    part = SimpleNamespace(
        inline_data=SimpleNamespace(data=b"\0\0" * 24000, mime_type="audio/L16;rate=24000")
    )
    return SimpleNamespace(
        usage_metadata=usage_metadata,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
    )


def test_gemini_tts_generate_content_uses_reported_tokens(recorded):
    from models import gemini_tts

    client = MagicMock()
    client.models.generate_content.return_value = _tts_response()
    with (
        patch.object(gemini_tts, "gemini_tts_api", lambda m: "generate_content"),
        patch("models.model_setup.GeminiModelSetup.init", return_value=client),
    ):
        gemini_tts.synthesize_speech(
            "Hello there", "Warm and slow", "gemini-3.8-flash-tts", "Kore", "en-US"
        )
    units = recorded[-1]["units"]
    assert units["prompt_tokens"] == 40 and units["output_audio_tokens"] == 250
    assert units["characters_synthesized"] == len("Hello there") + len("Warm and slow")
    _, details = pricing.estimate_details(
        "gemini-3.8-flash-tts", units, fetch=False
    )
    assert details["pricing_basis"] == "reported tokens"


def test_cloud_tts_counts_the_style_prompt(recorded):
    from models import gemini_tts

    with patch.object(gemini_tts, "_synthesize_cloud_tts", return_value=b"RIFF" + b"\0" * 40):
        gemini_tts.synthesize_speech("Hi", "Cheerful", "gemini-2.5-flash-tts", "Kore", "en-US")
    assert recorded[-1]["units"]["characters_synthesized"] == len("Hi") + len("Cheerful")


# 6b. Omni input estimate -------------------------------------------------------


def _omni(mode, **kw):
    from models.requests import OmniVideoGenerationRequest

    return OmniVideoGenerationRequest(
        prompt="p",
        duration_seconds=4,
        aspect_ratio="16:9",
        resolution="360p",
        omni_mode=mode,
        model_version_id="gemini-omni-1.2-flash",
        **kw,
    )


def test_omni_input_units_for_edit_and_images():
    from models.omni import _build_input_parts, input_media_units

    edit = _omni("edit", reference_video_gcs="gs://b/v.mp4", reference_image_gcs="gs://b/i.png")
    assert input_media_units(_build_input_parts(edit), edit) == {
        "input_image_count": 1,
        "input_video_seconds": 4,
    }
    first_last = _omni(
        "first_last", reference_image_gcs="gs://b/a.png", last_reference_image_gcs="gs://b/b.png"
    )
    assert input_media_units(_build_input_parts(first_last), first_last)[
        "input_image_count"
    ] == 2


def test_omni_input_units_for_chat_history(monkeypatch):
    from models import omni

    def no_download(uri):
        raise AssertionError("follow-up turns must not download earlier clips")

    monkeypatch.setattr(omni, "download_from_gcs", no_download)
    history = [
        {"type": "user_input", "content": [{"type": "text", "text": "a"}]},
        {"type": "model_output", "content": [{"type": "video", "gcs_uri": "gs://b/1.mp4"}]},
        {"type": "model_output", "content": [{"type": "video", "gcs_uri": "gs://b/2.mp4"}]},
        {"type": "model_output", "content": [{"type": "video", "gcs_uri": "gs://b/3.mp4"}]},
    ]
    req = _omni("t2v", previous_interaction_id="i1", chat_history_json=json.dumps(history))
    # No clip is sent (only previous_interaction_id), but the API re-reads
    # all three earlier clips from the thread.
    assert omni.input_media_units(omni._build_input_parts(req), req) == {
        "input_image_count": 0,
        "input_video_seconds": 12,
    }


def test_omni_fallback_input_estimate_is_not_zero():
    units = {
        "video_seconds_generated": 4,
        "resolution": "360p",
        "input_video_seconds": 4,
        "input_image_count": 1,
    }
    _, details = pricing.estimate_details("gemini-omni-1.2-flash", units, fetch=False)
    assert details["tokens_in"] == 4 * 1931 + 1120


@patch("models.omni.get_omni_client")
@patch("models.omni._save_video_to_gcs", return_value="gs://b/out.mp4")
def test_omni_call_records_input_units(_save, get_client, recorded):
    from models.omni import generate_omni_video

    content = SimpleNamespace(type="video", data="ZGF0YQ==")
    get_client.return_value.interactions.create.return_value = SimpleNamespace(
        id="i", status="completed", usage=None,
        steps=[SimpleNamespace(type="model_output", content=[content])],
    )
    generate_omni_video(_omni("i2v", reference_image_gcs="gs://b/i.png"))
    assert recorded[-1]["units"]["input_image_count"] == 1


# 6d. Grounding -------------------------------------------------------------------


def test_grounding_queries_are_recorded_and_priced():
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=50),
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(web_search_queries=["a", "b", "c"])
            )
        ],
    )
    units = analytics.extract_usage_metadata(response)
    assert units["web_search_queries"] == 3
    plain, _ = pricing.estimate_details(
        "gemini-3.5-flash", {"prompt_tokens": 100, "candidates_tokens": 50}, fetch=False
    )
    grounded, details = pricing.estimate_details("gemini-3.5-flash", units, fetch=False)
    assert grounded - plain == pytest.approx(3 * 0.014)
    assert details["cost_by_sku"]["Grounding with Google Search"] == pytest.approx(0.042)


def test_grounding_on_gemini_2_bills_per_prompt():
    units = {"prompt_tokens": 0, "web_search_queries": 4}
    cost, _ = pricing.estimate_details("gemini-2.5-flash", units, fetch=False)
    assert cost == pytest.approx(0.035)


# 6e. Veo extension -------------------------------------------------------------


@patch("models.veo.get_veo_client")
def test_veo_extension_bills_the_new_seconds(get_client, recorded):
    from config.veo_models import VEO_MODELS
    from models.requests import VideoGenerationRequest
    from models.veo import generate_video

    model = next((m for m in VEO_MODELS if m.supports_video_extension), None)
    if model is None:
        pytest.skip("no Veo model supports extension")
    result = SimpleNamespace(
        rai_media_filtered_count=0,
        generated_videos=[SimpleNamespace(video=SimpleNamespace(uri="gs://b/x.mp4"))],
    )
    client = MagicMock()
    client.models.generate_videos.return_value = SimpleNamespace(
        done=True, error=None, response=True, result=result, name="op"
    )
    get_client.return_value = client
    request = VideoGenerationRequest(
        prompt="keep going",
        model_version_id=model.version_id,
        aspect_ratio="16:9",
        resolution="720p",
        duration_seconds=7,
        video_count=1,
        enhance_prompt=True,
        generate_audio=False,
        person_generation="Allow (Adults only)",
        video_input_gcs="gs://b/base.mp4",
    )
    with patch("models.veo.english_for_model", lambda p: p):
        generate_video(request)
    units = recorded[-1]["units"]
    assert units["is_extension"] is True
    cost, details = pricing.estimate_details(model.model_name, units, fetch=False)
    assert details["pricing_basis"].startswith("7 s")
