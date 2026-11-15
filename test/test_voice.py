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
"""Voice page config, request routing and the Gemini TTS request shapes."""

import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from common import mock_generation
from config import gemini_tts as tts_cfg
from config import voice as voice_cfg
from models import gemini_tts, voice


def test_gemini_38_flash_tts_is_registered_and_default():
    assert tts_cfg.DEFAULT_GEMINI_TTS_MODEL == "gemini-3.8-flash-tts"
    assert tts_cfg.GEMINI_TTS_MODEL_NAMES[0] == "gemini-3.8-flash-tts"
    assert tts_cfg.gemini_tts_api("gemini-3.8-flash-tts") == "generate_content"
    assert tts_cfg.supports_multi_speaker("gemini-3.8-flash-tts")
    # Older models keep the Cloud TTS request shape; unknown ids default to it.
    for model in ("gemini-2.5-flash-tts", "gemini-2.5-pro-tts", "unknown-model"):
        assert tts_cfg.gemini_tts_api(model) == "cloud_tts"
    assert not tts_cfg.supports_multi_speaker("gemini-2.5-flash-lite-preview-tts")


def test_engine_options_list_gemini_first_then_chirp():
    values = [v for v, _, _ in voice_cfg.engine_options()]
    assert values[0] == "gemini-3.8-flash-tts"
    assert values[-1] == voice_cfg.CHIRP_ENGINE
    assert set(values[:-1]) == set(tts_cfg.GEMINI_TTS_MODELS)
    assert voice_cfg.DEFAULT_VOICE_ENGINE == "gemini-3.8-flash-tts"


def test_languages_and_dialogue_depend_on_engine():
    assert (
        voice_cfg.languages_for(voice_cfg.CHIRP_ENGINE) is tts_cfg.CHIRP3_HD_LANGUAGES
    )
    assert (
        voice_cfg.languages_for("gemini-3.8-flash-tts") is tts_cfg.GEMINI_TTS_LANGUAGES
    )
    assert not voice_cfg.engine_supports_dialogue(voice_cfg.CHIRP_ENGINE)
    assert voice_cfg.engine_supports_dialogue("gemini-3.8-flash-tts")


def test_legacy_routes_preselect_engine():
    assert voice_cfg.LEGACY_ENGINE_FOR_ROUTE["/chirp-3hd"] == voice_cfg.CHIRP_ENGINE
    assert voice_cfg.LEGACY_ENGINE_FOR_ROUTE["/gemini-tts"] == "gemini-3.8-flash-tts"


def test_style_direction_and_pace():
    assert voice_cfg.style_direction("natural", "normal") == ""
    text = voice_cfg.style_direction("calm", "slow", "  like a bedtime story ")
    assert text.startswith("Say this in a calm")
    assert "Speak slowly." in text
    assert text.endswith("like a bedtime story")
    assert voice_cfg.pace_rate("fast") == 1.3
    assert voice_cfg.pace_rate("missing") == 1.0


@pytest.mark.parametrize(
    "request_kwargs, message",
    [
        ({"text": "  "}, "Write a script first."),
        ({"engine": "nope"}, "Unknown voice model: nope."),
        (
            {"engine": voice_cfg.CHIRP_ENGINE, "multi_speaker": True},
            "This model reads one voice only",
        ),
        (
            {"multi_speaker": True, "speakers": [("Host", "Kore"), ("host", "Puck")]},
            "two speakers with different names",
        ),
    ],
)
def test_validate_gives_plain_messages(request_kwargs, message):
    base = {
        "engine": "gemini-3.8-flash-tts",
        "text": "Hello",
        "voice": "Kore",
        "language_code": "en-US",
    }
    base.update(request_kwargs)
    with pytest.raises(ValueError, match=message):
        voice.synthesize_voice(voice.VoiceRequest(**base))


def test_chirp_requests_go_to_chirp_model():
    req = voice.VoiceRequest(
        engine=voice_cfg.CHIRP_ENGINE,
        text="Hi",
        voice="Orus",
        language_code="en-GB",
        pace="brisk",
        pronunciations=[{"phrase": "Mesop", "pronunciation": "m e s O p"}],
        phonetic_encoding="PHONETIC_ENCODING_IPA",
    )
    with (
        patch.object(
            voice.chirp_3hd,
            "synthesize_chirp_speech",
            return_value=b"C",
        ) as chirp,
        patch.object(voice.gemini_tts, "synthesize_speech") as gemini,
    ):
        assert voice.synthesize_voice(req) == b"C"
    gemini.assert_not_called()
    kwargs = chirp.call_args.kwargs
    assert kwargs["voice_name"] == "Orus"
    assert kwargs["language_code"] == "en-GB"
    assert kwargs["speaking_rate"] == 1.15
    assert kwargs["pronunciations"] == req.pronunciations
    assert kwargs["phonetic_encoding"] == "PHONETIC_ENCODING_IPA"


def test_gemini_requests_go_to_gemini_tts_with_style_and_speakers():
    req = voice.VoiceRequest(
        engine="gemini-3.8-flash-tts",
        text="Host: Hi\nGuest: Hello",
        voice="Kore",
        language_code="en-US",
        style="cheerful",
        multi_speaker=True,
        speakers=[("Host", "Kore"), ("Guest", "Puck")],
    )
    with (
        patch.object(
            voice.gemini_tts,
            "synthesize_speech",
            return_value=b"G",
        ) as gemini,
        patch.object(voice.chirp_3hd, "synthesize_chirp_speech") as chirp,
    ):
        assert voice.synthesize_voice(req) == b"G"
    chirp.assert_not_called()
    kwargs = gemini.call_args.kwargs
    assert kwargs["model_name"] == "gemini-3.8-flash-tts"
    assert kwargs["prompt"].startswith("Say this cheerfully")
    assert kwargs["speakers"] == [("Host", "Kore"), ("Guest", "Puck")]
    assert "Puck" in voice.describe(req)


def test_parse_dialogue():
    text = "Host: Hi there\n  and welcome.\nGuest: Thanks!\nNarrator: not a speaker\n\nguest: bye"
    assert gemini_tts.parse_dialogue(text, ["Host", "Guest"]) == [
        ("Host", "Hi there and welcome."),
        ("Guest", "Thanks! Narrator: not a speaker"),
        ("Guest", "bye"),
    ]
    assert gemini_tts.parse_dialogue("No names here", ["A", "B"]) == [
        ("A", "No names here"),
    ]


def _wav_rate(data: bytes) -> int:
    with wave.open(io.BytesIO(data)) as wav:
        return wav.getframerate()


@patch("common.analytics.analytics_logger")
def test_generate_content_shape_for_gemini_38(_logger):
    part = SimpleNamespace(
        inline_data=SimpleNamespace(
            data=b"\x00\x01" * 10,
            mime_type="audio/L16;codec=pcm;rate=24000",
        ),
    )
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
    )
    client = MagicMock()
    client.models.generate_content.return_value = response
    with (
        patch("models.model_setup.GeminiModelSetup.init", return_value=client),
        patch("google.cloud.texttospeech.TextToSpeechClient") as cloud_tts,
    ):
        audio = gemini_tts.synthesize_speech(
            text="Hello",
            prompt="Say warmly:",
            model_name="gemini-3.8-flash-tts",
            voice_name="Kore",
            language_code="en-US",
        )
    cloud_tts.assert_not_called()
    assert audio[:4] == b"RIFF" and _wav_rate(audio) == 24000
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.8-flash-tts"
    assert kwargs["contents"] == "Say warmly:\n\nHello"
    config = kwargs["config"]
    assert config.response_modalities == ["AUDIO"]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    assert config.speech_config.language_code == "en-US"


@patch("common.analytics.analytics_logger")
def test_generate_content_multi_speaker(_logger):
    part = SimpleNamespace(
        inline_data=SimpleNamespace(data=b"RIFFxxxx", mime_type="audio/wav"),
    )
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
    )
    client = MagicMock()
    client.models.generate_content.return_value = response
    with patch("models.model_setup.GeminiModelSetup.init", return_value=client):
        audio = gemini_tts.synthesize_speech(
            text="Host: Hi\nGuest: Hey",
            prompt="",
            model_name="gemini-3.8-flash-tts",
            voice_name="Kore",
            language_code="en-US",
            speakers=[("Host", "Kore"), ("Guest", "Puck")],
        )
    assert audio == b"RIFFxxxx"
    speech = client.models.generate_content.call_args.kwargs["config"].speech_config
    configs = speech.multi_speaker_voice_config.speaker_voice_configs
    assert [
        (c.speaker, c.voice_config.prebuilt_voice_config.voice_name) for c in configs
    ] == [
        ("Host", "Kore"),
        ("Guest", "Puck"),
    ]


@patch("common.analytics.analytics_logger")
@patch("google.cloud.texttospeech.TextToSpeechClient")
def test_cloud_tts_multi_speaker_shape(mock_client, _logger):
    instance = MagicMock()
    instance.synthesize_speech.return_value = SimpleNamespace(audio_content=b"A")
    mock_client.return_value = instance
    gemini_tts.synthesize_speech(
        text="Host: Hi\nGuest: Hey",
        prompt="Be upbeat",
        model_name="gemini-2.5-flash-tts",
        voice_name="Kore",
        language_code="en-US",
        speakers=[("Host", "Kore"), ("Guest", "Puck")],
    )
    kwargs = instance.synthesize_speech.call_args.kwargs
    turns = kwargs["input"].multi_speaker_markup.turns
    assert [(t.speaker, t.text) for t in turns] == [("Host", "Hi"), ("Guest", "Hey")]
    assert kwargs["input"].prompt == "Be upbeat"
    voices = kwargs["voice"].multi_speaker_voice_config.speaker_voice_configs
    assert [(v.speaker_alias, v.speaker_id) for v in voices] == [
        ("Host", "Kore"),
        ("Guest", "Puck"),
    ]
    assert kwargs["voice"].model_name == "gemini-2.5-flash-tts"


def test_mock_audio_is_a_short_wav(monkeypatch):
    data = mock_generation.placeholder_wav(index=2, seconds=0.5)
    assert data[:4] == b"RIFF" and _wav_rate(data) == 16000
    assert mock_generation.sample_audio(1).startswith(mock_generation.MOCK_AUDIO_ROUTE)
    monkeypatch.setenv("GENMEDIA_MOCK_GENERATION", "true")
    monkeypatch.setenv("APP_ENV", "production")
    assert not mock_generation.mock_enabled()
