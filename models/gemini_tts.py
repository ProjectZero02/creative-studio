# Copyright 2025 Google LLC
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

"""Model for Gemini Text-to-Speech.

Two request shapes, picked per model by `config.gemini_tts.gemini_tts_api`:

* Cloud Text-to-Speech `synthesize_speech` (Gemini 2.5 and 3.1 TTS models).
* Gemini `generate_content` with an AUDIO response (Gemini 3.8 Flash TTS).

Both accept an optional pair of speakers for a two-person dialogue, written
as "Name: line" lines in the text.
"""

import io
import re
import wave

from google.cloud import texttospeech

from common.analytics import get_logger, track_model_call
from config.default import Default
from config.gemini_tts import gemini_tts_api

cfg = Default()
logger = get_logger(__name__)

_TURN_RE = re.compile(r"^\s*([^:\n]{1,40}?)\s*:\s*(.*)$")


def parse_dialogue(text: str, speaker_names: list[str]) -> list[tuple[str, str]]:
    """Split "Name: line" text into (speaker, line) turns.

    Lines that don't start with a known speaker continue the previous turn
    (or belong to the first speaker when nothing came before).
    """
    names = {n.strip().lower(): n.strip() for n in speaker_names if n.strip()}
    first = next(iter(names.values()), "")
    turns: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _TURN_RE.match(line)
        if match and match.group(1).strip().lower() in names:
            speaker = names[match.group(1).strip().lower()]
            body = match.group(2).strip()
            if body:
                turns.append((speaker, body))
            continue
        if turns:
            speaker, body = turns[-1]
            turns[-1] = (speaker, f"{body} {line}")
        else:
            turns.append((first, line))
    return turns


def pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit little-endian PCM in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _as_wav(data: bytes, mime_type: str) -> bytes:
    """Gemini returns WAV or raw PCM (e.g. "audio/L16;codec=pcm;rate=24000")."""
    if data[:4] == b"RIFF":
        return data
    match = re.search(r"rate=(\d+)", mime_type or "")
    return pcm_to_wav(data, rate=int(match.group(1)) if match else 24000)


def _synthesize_cloud_tts(
    text: str,
    prompt: str,
    model_name: str,
    voice_name: str,
    language_code: str,
    speakers: list[tuple[str, str]] | None,
) -> bytes:
    client_options = {}
    if cfg.GEMINI_TTS_LOCATION and cfg.GEMINI_TTS_LOCATION != "global":
        client_options["api_endpoint"] = (
            f"{cfg.GEMINI_TTS_LOCATION}-texttospeech.googleapis.com"
        )

    client = texttospeech.TextToSpeechClient(client_options=client_options)

    if speakers:
        turns = parse_dialogue(text, [name for name, _ in speakers])
        synthesis_input = texttospeech.SynthesisInput(
            multi_speaker_markup=texttospeech.MultiSpeakerMarkup(
                turns=[
                    texttospeech.MultiSpeakerMarkup.Turn(speaker=s, text=t)
                    for s, t in turns
                ],
            ),
            prompt=prompt,
        )
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            model_name=model_name,
            multi_speaker_voice_config=texttospeech.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    texttospeech.MultispeakerPrebuiltVoice(
                        speaker_alias=name,
                        speaker_id=voice_id,
                    )
                    for name, voice_id in speakers
                ],
            ),
        )
    else:
        synthesis_input = texttospeech.SynthesisInput(text=text, prompt=prompt)
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
            model_name=model_name,
        )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        ),
    )
    return response.audio_content


def _synthesize_generate_content(
    text: str,
    prompt: str,
    model_name: str,
    voice_name: str,
    language_code: str,
    speakers: list[tuple[str, str]] | None,
) -> bytes:
    # Imported here so Cloud-TTS-only callers don't build a Gemini client.
    from google.genai import types  # pylint: disable=import-outside-toplevel

    from models.model_setup import (  # pylint: disable=import-outside-toplevel
        GeminiModelSetup,
    )

    def voice_config(name: str) -> types.VoiceConfig:
        return types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=name),
        )

    if speakers:
        speech_config = types.SpeechConfig(
            language_code=language_code or None,
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                speaker_voice_configs=[
                    types.SpeakerVoiceConfig(
                        speaker=name,
                        voice_config=voice_config(voice_id),
                    )
                    for name, voice_id in speakers
                ],
            ),
        )
    else:
        speech_config = types.SpeechConfig(
            language_code=language_code or None,
            voice_config=voice_config(voice_name),
        )

    # The style direction goes before the script, as the TTS docs show.
    contents = f"{prompt.strip()}\n\n{text}" if prompt and prompt.strip() else text

    client = GeminiModelSetup.init(location=cfg.GEMINI_TTS_LOCATION)
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_config,
        ),
    )
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if part.inline_data and part.inline_data.data:
                return _as_wav(part.inline_data.data, part.inline_data.mime_type)
    raise RuntimeError("The model returned no audio. Try a shorter or simpler script.")


def synthesize_speech(
    text: str,
    prompt: str,
    model_name: str,
    voice_name: str,
    language_code: str,
    speakers: list[tuple[str, str]] | None = None,
) -> bytes:
    """Synthesizes speech from text using a Gemini TTS model.

    Args:
        text: The text to synthesize. For a dialogue, "Name: line" lines.
        prompt: The style direction for the voice.
        model_name: The name of the TTS model to use.
        voice_name: The name of the voice to use (single speaker).
        language_code: Language code for synthesis.
        speakers: Optional [(speaker name, voice name), ...] for a dialogue.

    Returns:
        The synthesized audio in bytes (WAV).

    """
    speakers = [(n.strip(), v) for n, v in (speakers or []) if n.strip()] or None
    billing_units = {
        "characters_synthesized": len(text) if text else 0,
        "voice_name": ",".join(v for _, v in speakers) if speakers else voice_name,
        "language_code": language_code,
    }

    with track_model_call(
        model_name or "gemini-tts",
        billing_units=billing_units,
    ) as ctx:
        if gemini_tts_api(model_name) == "generate_content":
            audio_content = _synthesize_generate_content(
                text,
                prompt,
                model_name,
                voice_name,
                language_code,
                speakers,
            )
        else:
            audio_content = _synthesize_cloud_tts(
                text,
                prompt,
                model_name,
                voice_name,
                language_code,
                speakers,
            )
        ctx["billing_units"]["audio_bytes"] = len(audio_content) if audio_content else 0
        return audio_content
