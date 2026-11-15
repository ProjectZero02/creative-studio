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
"""One entry point for the Voice page: send a request to the right engine.

No API logic lives here. Gemini models go to `models.gemini_tts`, Chirp 3 HD
goes to `models.chirp_3hd`.
"""

from dataclasses import dataclass, field

from config.voice import (
    PACES,
    STYLES,
    engine_label,
    engine_supports_dialogue,
    is_chirp,
    is_known_engine,
    pace_rate,
    style_direction,
)
from models import chirp_3hd, gemini_tts


@dataclass
class VoiceRequest:
    """What the Voice page asks for."""

    engine: str
    text: str
    voice: str
    language_code: str
    style: str = "natural"
    pace: str = "normal"
    style_notes: str = ""
    multi_speaker: bool = False
    speakers: list[tuple[str, str]] = field(default_factory=list)
    # Chirp only
    pronunciations: list[dict[str, str]] = field(default_factory=list)
    phonetic_encoding: str = "PHONETIC_ENCODING_X_SAMPA"
    volume_gain_db: float = 0.0


def validate(request: VoiceRequest) -> str:
    """A plain message for a request that can't be sent, else ""."""
    if not request.text or not request.text.strip():
        return "Write a script first."
    if not is_known_engine(request.engine):
        return f"Unknown voice model: {request.engine}."
    if request.multi_speaker:
        if not engine_supports_dialogue(request.engine):
            return "This model reads one voice only. Turn off Dialogue or pick another model."
        names = [n.strip() for n, _ in request.speakers if n.strip()]
        if len(names) != 2 or names[0].lower() == names[1].lower():
            return "A dialogue needs two speakers with different names."
    return ""


def synthesize_voice(request: VoiceRequest) -> bytes:
    """Return WAV bytes for the request. Raises ValueError for a bad request."""
    problem = validate(request)
    if problem:
        raise ValueError(problem)
    if is_chirp(request.engine):
        return chirp_3hd.synthesize_chirp_speech(
            text=request.text,
            voice_name=request.voice,
            language_code=request.language_code,
            speaking_rate=pace_rate(request.pace),
            volume_gain_db=request.volume_gain_db,
            pronunciations=request.pronunciations or None,
            phonetic_encoding=request.phonetic_encoding,
        )
    return gemini_tts.synthesize_speech(
        text=request.text,
        prompt=style_direction(request.style, request.pace, request.style_notes),
        model_name=request.engine,
        voice_name=request.voice,
        language_code=request.language_code,
        speakers=list(request.speakers) if request.multi_speaker else None,
    )


def describe(request: VoiceRequest) -> str:
    """Short meta line for a result card."""
    parts = [engine_label(request.engine)]
    if request.multi_speaker and not is_chirp(request.engine):
        parts.append(" & ".join(v for _, v in request.speakers))
    else:
        parts.append(request.voice)
    parts.append(request.language_code)
    if not is_chirp(request.engine) and request.style != "natural":
        parts.append(next((lbl for v, lbl, _ in STYLES if v == request.style), ""))
    if request.pace != "normal":
        parts.append(next((lbl for v, lbl, _, _ in PACES if v == request.pace), ""))
    return " · ".join(p for p in parts if p)
