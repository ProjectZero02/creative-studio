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
"""Calls that fail after Google returned output are still priced."""

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


def _cost(call):
    return pricing.estimate_details(
        call["model"], call["units"], call["status"], fetch=False
    )[0]


def test_billed_statuses_are_priced_and_others_are_not():
    units = {"sample_count": 1}
    assert pricing.estimate("lyria-002", units, "failed_after_output") == 0.06
    assert pricing.estimate("lyria-002", units, "timeout_maybe_billed") == 0.06
    assert pricing.estimate("lyria-002", units, "failure") == 0.0


def test_plain_api_error_stays_at_zero(recorded):
    with pytest.raises(RuntimeError):
        with analytics.track_model_call("lyria-002", billing_units={"sample_count": 1}):
            raise RuntimeError("400 bad request")
    assert recorded[0]["status"] == "failure" and _cost(recorded[0]) == 0.0


def test_timeout_only_counts_when_the_call_may_be_billed(recorded):
    for flag in (True, False):
        with pytest.raises(TimeoutError):
            with analytics.track_model_call("lyria-002") as ctx:
                ctx["bill_on_timeout"] = flag
                raise TimeoutError("read timed out")
    assert [c["status"] for c in recorded] == ["timeout_maybe_billed", "failure"]


def test_is_timeout_follows_the_cause():
    class ReadTimeout(Exception):
        pass

    try:
        try:
            raise ReadTimeout("x")
        except ReadTimeout as e:
            raise ValueError("wrapped") from e
    except ValueError as wrapped:
        assert analytics.is_timeout(wrapped)
    assert not analytics.is_timeout(ValueError("400"))


def _omni_request():
    from models.requests import OmniVideoGenerationRequest

    return OmniVideoGenerationRequest(
        prompt="a city at dusk",
        duration_seconds=4,
        aspect_ratio="16:9",
        resolution="360p",
        omni_mode="t2v",
        model_version_id="gemini-omni-1.2-flash",
    )


@patch("models.omni.get_omni_client")
@patch("models.omni._save_video_to_gcs", side_effect=RuntimeError("GCS down"))
def test_omni_gcs_failure_after_output_is_priced(_save, get_client, recorded):
    from models.omni import generate_omni_video

    content = SimpleNamespace(type="video", data="ZGF0YQ==")
    interaction = SimpleNamespace(
        id="int-1",
        status="completed",
        steps=[SimpleNamespace(type="model_output", content=[content])],
        usage=None,
    )
    get_client.return_value.interactions.create.return_value = interaction
    with pytest.raises(Exception):
        generate_omni_video(_omni_request())
    call = recorded[-1]
    assert call["status"] == "failed_after_output"
    assert _cost(call) > 0


@patch("models.omni.get_omni_client")
def test_omni_client_timeout_may_be_billed(get_client, recorded):
    from models.omni import generate_omni_video

    class ReadTimeout(Exception):
        pass

    get_client.return_value.interactions.create.side_effect = ReadTimeout("t/o")
    with pytest.raises(Exception):
        generate_omni_video(_omni_request())
    assert recorded[-1]["status"] == "timeout_maybe_billed"
    assert _cost(recorded[-1]) > 0


@patch("models.omni.get_omni_client")
def test_omni_api_error_is_not_priced(get_client, recorded):
    from models.omni import generate_omni_video

    get_client.return_value.interactions.create.side_effect = RuntimeError("400")
    with pytest.raises(Exception):
        generate_omni_video(_omni_request())
    assert recorded[-1]["status"] == "failure" and _cost(recorded[-1]) == 0.0


@patch("models.lyria.store_to_gcs", side_effect=RuntimeError("GCS down"))
@patch("models.lyria.aiplatform.gapic.PredictionServiceClient")
def test_lyria_gcs_failure_after_output_is_priced(client_cls, _store, recorded):
    from models import lyria

    client_cls.return_value.predict.return_value = SimpleNamespace(
        predictions=[{"bytesBase64Encoded": "AAAA"}, {"bytesBase64Encoded": "BBBB"}]
    )
    with patch.object(lyria, "english_for_model", lambda p: p):
        with pytest.raises(Exception):
            lyria.generate_music_with_lyria("calm piano", "lyria-002", sample_count=2)
    call = recorded[-1]
    assert call["status"] == "failed_after_output"
    assert _cost(call) == pytest.approx(0.12)


@patch("models.veo.get_veo_client")
def test_partly_filtered_veo_call_is_priced_for_the_returned_videos(
    get_client, recorded
):
    from config.veo_models import get_veo_model_config
    from models.requests import VideoGenerationRequest
    from models.veo import generate_video

    model = get_veo_model_config("3.1-fast")
    if model is None:
        pytest.skip("no Veo 3.1 Fast config")
    result = SimpleNamespace(
        rai_media_filtered_count=1,
        rai_media_filtered_reasons=["filtered"],
        generated_videos=[SimpleNamespace(video=SimpleNamespace(uri="gs://b/1.mp4"))],
    )
    operation = SimpleNamespace(
        done=True, error=None, response=True, result=result, name="op"
    )
    client = MagicMock()
    client.models.generate_videos.return_value = operation
    get_client.return_value = client
    request = VideoGenerationRequest(
        prompt="a dog on a beach",
        model_version_id=model.version_id,
        aspect_ratio="16:9",
        resolution="720p",
        duration_seconds=4,
        video_count=2,
        enhance_prompt=True,
        generate_audio=False,
        person_generation="Allow (Adults only)",
    )
    with patch("models.veo.english_for_model", lambda p: p):
        with pytest.raises(Exception):
            generate_video(request)
    call = recorded[-1]
    assert call["status"] == "failed_after_output"
    assert call["units"]["videos_generated"] == 1
    # One 4 s video at Veo 3 Fast 720p without audio, not two.
    assert _cost(call) == pytest.approx(4 * 0.08)
