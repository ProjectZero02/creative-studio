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
"""State for the Voice page (/voice)."""

from dataclasses import field

import mesop as me

from config.voice import (
    DEFAULT_ENCODING,
    DEFAULT_LANGUAGE,
    DEFAULT_PACE,
    DEFAULT_SCRIPT,
    DEFAULT_SECOND_VOICE,
    DEFAULT_SPEAKERS,
    DEFAULT_STYLE,
    DEFAULT_VOICE,
    DEFAULT_VOICE_ENGINE,
)


@me.stateclass
class VoiceState:
    """Page state. Audio stays in GCS; only URLs live here."""

    engine: str = DEFAULT_VOICE_ENGINE
    text: str = DEFAULT_SCRIPT
    text_key: int = 0
    prompt_prefill_seen: str = ""  # last ?prompt= applied on load
    voice: str = DEFAULT_VOICE
    language: str = DEFAULT_LANGUAGE
    style: str = DEFAULT_STYLE
    pace: str = DEFAULT_PACE
    style_notes: str = ""

    # Dialogue (Gemini models that support two speakers)
    multi_speaker: bool = False
    speaker_a: str = DEFAULT_SPEAKERS[0]
    speaker_b: str = DEFAULT_SPEAKERS[1]
    voice_b: str = DEFAULT_SECOND_VOICE

    # Chirp 3 HD only
    show_pronunciations: bool = False
    encoding: str = DEFAULT_ENCODING
    pronunciations: list[dict[str, str]] = field(default_factory=list)  # pylint: disable=invalid-field-call
    phrase_input: str = ""
    pronunciation_input: str = ""
    pron_key: int = 0

    show_style_notes: bool = False

    is_generating: bool = False

    # Results this session (newest first)
    history_urls: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    history_texts: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    history_meta: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call

    # components/generation_progress fields
    progress_stages: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    progress_stage: int = 0
    progress_status: str = ""
    progress_run_id: str = ""
    progress_error: str = ""

    info_dialog_open: bool = False
