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
"""Story Studio keeps going through blocked music prompts and passing
service errors (both seen on real renders)."""

import pytest

from common.error_handling import GenerationError
from services import story_service
from services.story_models import MUSIC_FALLBACK_PROMPTS, Story, music_declined

RECITATION = ValueError(
    "Lyria API Error: 400 Audio generation failed with the following error: "
    "All responses were blocked by recitation checks."
)


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(story_service, "TRANSIENT_RETRY_WAITS", (0.0, 0.0))
    return story_service.VertexStoryBackend()


def test_music_declined_spots_blocks_not_outages():
    assert music_declined(RECITATION)
    assert not music_declined(RuntimeError("503 Service Unavailable"))


def test_a_blocked_music_prompt_falls_back_to_a_plainer_one(backend, monkeypatch):
    import models.lyria as lyria

    seen = []

    def fake(prompt, model_name="", **_):
        seen.append(prompt)
        if len(seen) == 1:
            raise RECITATION
        return ["gs://b/music.wav"], None, []

    monkeypatch.setattr(lyria, "generate_music_with_lyria", fake)
    uri = backend.generate_music(
        Story(title="The Ocean's Whisper"), "Score: The Ocean's Whisper", 12
    )
    assert uri == "gs://b/music.wav"
    assert seen == ["Score: The Ocean's Whisper", MUSIC_FALLBACK_PROMPTS[0]]


def test_music_gives_up_with_a_clear_message_when_every_prompt_is_blocked(
    backend, monkeypatch
):
    import models.lyria as lyria

    def fake(*_, **__):
        raise RECITATION

    monkeypatch.setattr(lyria, "generate_music_with_lyria", fake)
    with pytest.raises(GenerationError, match="declined"):
        backend.generate_music(Story(), "x", 12)


def test_a_music_outage_is_not_retried_with_other_prompts(backend, monkeypatch):
    import models.lyria as lyria

    calls = []

    def fake(*_, **__):
        calls.append(1)
        raise RuntimeError("Lyria API Error: 503 Service Unavailable")

    monkeypatch.setattr(lyria, "generate_music_with_lyria", fake)
    with pytest.raises(RuntimeError):
        backend.generate_music(Story(), "x", 12)
    assert len(calls) == 1


def test_retry_transient_retries_service_errors_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("503 502:Bad Gateway")
        return b"audio"

    story_service.TRANSIENT_RETRY_WAITS = (0.0, 0.0)
    try:
        assert story_service._retry_transient(flaky, "voiceover") == b"audio"
    finally:
        story_service.TRANSIENT_RETRY_WAITS = (3.0, 8.0)
    assert len(calls) == 3


def test_retry_transient_does_not_retry_a_bad_request():
    calls = []

    def bad():
        calls.append(1)
        raise ValueError("400 Invalid argument: voice not found")

    with pytest.raises(ValueError):
        story_service._retry_transient(bad, "voiceover")
    assert len(calls) == 1

