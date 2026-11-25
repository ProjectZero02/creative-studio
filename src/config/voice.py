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
"""Settings for the Voice page (/voice): one page for every speech engine.

The engine chip lists the Gemini TTS models first (newest is the default)
and then Chirp 3 HD, which runs on Cloud Text-to-Speech.
"""

from config.gemini_tts import (
    CHIRP3_HD_LANGUAGES,
    DEFAULT_GEMINI_TTS_MODEL,
    GEMINI_TTS_ENCODINGS,
    GEMINI_TTS_LANGUAGES,
    GEMINI_TTS_MODELS,
    GEMINI_TTS_VOICES,
    supports_multi_speaker,
)

CHIRP_ENGINE = "chirp-3-hd"
CHIRP_LABEL = "Chirp 3 HD"
DEFAULT_VOICE_ENGINE = DEFAULT_GEMINI_TTS_MODEL

# Old routes -> engine to preselect on /voice.
LEGACY_ENGINE_FOR_ROUTE = {
    "/gemini-tts": DEFAULT_GEMINI_TTS_MODEL,
    "/chirp-3hd": CHIRP_ENGINE,
}

VOICES = list(GEMINI_TTS_VOICES)
DEFAULT_VOICE = "Kore"
DEFAULT_SECOND_VOICE = "Puck"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_SPEAKERS = ("Host", "Guest")

# Style presets (Gemini only). The text is the style direction sent with the script.
STYLES: list[tuple[str, str, str]] = [
    ("natural", "Natural", ""),
    ("warm", "Warm", "Say this in a warm, friendly tone:"),
    ("cheerful", "Cheerful", "Say this cheerfully, with a smile in your voice:"),
    ("calm", "Calm", "Say this in a calm, soothing voice:"),
    ("news", "Newsreader", "Read this like a confident news presenter:"),
    ("story", "Storyteller", "Tell this like an engaging storyteller:"),
    ("ad", "Advert", "Read this like an upbeat radio advert:"),
    ("whisper", "Whisper", "Whisper this softly:"),
]
DEFAULT_STYLE = "natural"

# Pace. Gemini gets it as words in the style direction; Chirp as speaking_rate.
PACES: list[tuple[str, str, float, str]] = [
    ("slow", "Slow", 0.8, "Speak slowly."),
    ("normal", "Normal pace", 1.0, ""),
    ("brisk", "Brisk", 1.15, "Speak at a brisk pace."),
    ("fast", "Fast", 1.3, "Speak quickly."),
]
DEFAULT_PACE = "normal"

ENCODINGS = GEMINI_TTS_ENCODINGS
DEFAULT_ENCODING = "PHONETIC_ENCODING_X_SAMPA"

DEFAULT_SCRIPT = (
    "Welcome to the studio. In the next two minutes, I'll show you how one "
    "script becomes a natural voice-over in any of more than a hundred languages."
)
DEFAULT_DIALOGUE = (
    "Host: Welcome back to the show! Today we're talking about AI voices.\n"
    "Guest: Thanks for having me. Honestly, they sound more human every month."
)


# Arabic site: Arabic samples and an Arabic voice language. Speaker names stay
# "Host"/"Guest" (they are the speaker ids sent to the model).
DEFAULT_SCRIPT_AR = (
    "أهلًا بكم في الاستوديو. في الدقيقتين القادمتين سأريكم كيف يتحول نص واحد "
    "إلى تعليق صوتي طبيعي بأكثر من مئة لغة."
)
DEFAULT_DIALOGUE_AR = (
    "Host: أهلًا بكم من جديد في البرنامج! نتحدث اليوم عن أصوات الذكاء الاصطناعي.\n"
    "Guest: شكرًا على الاستضافة. بصراحة، تبدو أقرب إلى صوت الإنسان كل شهر."
)
# The sample scripts count as empty: the page may swap them, never the user's own.
SAMPLE_SCRIPTS = (
    DEFAULT_SCRIPT,
    DEFAULT_DIALOGUE,
    DEFAULT_SCRIPT_AR,
    DEFAULT_DIALOGUE_AR,
)


def sample_script(lang: str, dialogue: bool) -> str:
    """The sample script for the site language."""
    if lang == "ar":
        return DEFAULT_DIALOGUE_AR if dialogue else DEFAULT_SCRIPT_AR
    return DEFAULT_DIALOGUE if dialogue else DEFAULT_SCRIPT


def is_arabic_language(code: str) -> bool:
    """True for an Arabic language code (ar-EG, ar-XA, ar-001...)."""
    return code.lower().startswith("ar")


def default_language(engine: str, lang: str = "en") -> str:
    """The voice language to start with: on the Arabic site the engine's
    first Arabic code (ar-EG for Gemini TTS, ar-XA for Chirp 3 HD, the same
    pick as models.voice.speech_language), else en-US."""
    if lang == "ar":
        for code in languages_for(engine).values():
            if is_arabic_language(code):
                return code
    return DEFAULT_LANGUAGE


def is_chirp(engine: str) -> bool:
    """True when the engine is Chirp 3 HD (Cloud Text-to-Speech voices)."""
    return engine == CHIRP_ENGINE


def engine_label(engine: str) -> str:
    """Human name for an engine."""
    if is_chirp(engine):
        return CHIRP_LABEL
    return GEMINI_TTS_MODELS.get(engine, {}).get("label", engine)


def engine_options() -> list[tuple[str, str, str]]:
    """(value, label, hint) for the model chip: Gemini models, then Chirp."""
    options = []
    for model_id, model in GEMINI_TTS_MODELS.items():
        hint = "Newest · default" if model_id == DEFAULT_GEMINI_TTS_MODEL else ""
        if not hint and supports_multi_speaker(model_id):
            hint = "Dialogue"
        options.append((model_id, model["label"], hint))
    options.append((CHIRP_ENGINE, CHIRP_LABEL, "Cloud TTS · custom pronunciations"))
    return options


def is_known_engine(engine: str) -> bool:
    """True for any engine the page can call."""
    return is_chirp(engine) or engine in GEMINI_TTS_MODELS


def engine_supports_dialogue(engine: str) -> bool:
    """Chirp voices one speaker; some Gemini models voice two."""
    return not is_chirp(engine) and supports_multi_speaker(engine)


def languages_for(engine: str) -> dict[str, str]:
    """Label -> language code for the engine."""
    return CHIRP3_HD_LANGUAGES if is_chirp(engine) else GEMINI_TTS_LANGUAGES


def language_label(engine: str, code: str) -> str:
    """Human name for a language code, or the code itself."""
    for label, value in languages_for(engine).items():
        if value == code:
            return label
    return code


def pace_rate(pace: str) -> float:
    """Chirp speaking_rate for a pace id."""
    return next((rate for value, _, rate, _ in PACES if value == pace), 1.0)


def style_direction(style: str, pace: str, extra: str = "") -> str:
    """The style prompt sent to Gemini: preset words, pace words, then the user's own."""
    parts = [text for value, _, text in STYLES if value == style and text]
    parts += [text for value, _, _, text in PACES if value == pace and text]
    if extra and extra.strip():
        parts.append(extra.strip())
    return " ".join(parts)
