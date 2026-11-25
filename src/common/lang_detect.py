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
"""Which language AI-written text should be in.

The rule everywhere: the language the person writes or speaks in wins
(Arabic in, Arabic out). With no text to go by (an empty prompt, a
"Surprise me" button, an automatic title), the site's language is used.

``detect_lang`` looks at the letters only (Arabic block vs Latin), so it is
cheap enough to call on every request and needs no model.
"""

from __future__ import annotations

import functools
import logging
import re

logger = logging.getLogger(__name__)

_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")
# Words that are often typed in English inside an Arabic sentence (model and
# app names, units), so they do not outvote a short Arabic request.
_LOANWORDS = re.compile(
    r"\b(veo|omni|lyria|imagen|gemini|nano|banana|tts|ai|4k|1080p|720p|360p|hd|mp4|png|jpg|"
    r"16:9|9:16|1:1|4:3|3:4|fps|logo)\b",
    re.I,
)

LANG_NAMES = {"ar": "Arabic", "en": "English"}
# BCP-47 codes for speech, per language.
SPEECH_CODES = {"ar": "ar-EG", "en": "en-US"}


def detect_lang(text: str | None) -> str:
    """ "ar" when the text is mostly Arabic letters, "en" when it is mostly
    Latin letters, "" when there is nothing to go by (empty, digits only)."""
    if not text:
        return ""
    sample = _LOANWORDS.sub(" ", str(text)[:4000])
    arabic = len(_ARABIC.findall(sample))
    latin = len(_LATIN.findall(sample))
    if not arabic and not latin:
        return ""
    # Arabic words are shorter in letters than their English mix-ins, so
    # Arabic wins from a third of the letters up.
    return "ar" if arabic * 2 >= latin else "en"


def ui_lang() -> str:
    """The site language inside a Mesop request, else "en"."""
    try:
        from common.i18n import current_lang  # pylint: disable=import-outside-toplevel

        lang = current_lang()
    except Exception:  # noqa: BLE001
        return "en"
    return lang if lang in LANG_NAMES else "en"


def resolve_lang(*texts: str | None, lang: str | None = None) -> str:
    """The language for AI output: the first text with letters decides;
    otherwise the given `lang` (the site language), otherwise the site
    language of the current Mesop request ("en" outside one)."""
    for text in texts:
        found = detect_lang(text)
        if found:
            return found
    if lang in LANG_NAMES:
        return str(lang)
    return ui_lang()


def lang_name(lang: str | None) -> str:
    return LANG_NAMES.get(lang or "", "English")


def speech_code(lang: str | None) -> str:
    return SPEECH_CODES.get(lang or "", SPEECH_CODES["en"])


def write_in(lang: str | None) -> str:
    """One line for a prompt: what language the output must be in."""
    if lang == "ar":
        return (
            "Write all the text you return in Arabic (Modern Standard Arabic), "
            "except names, brand names and technical ids, which stay as given."
        )
    return "Write all the text you return in English."


@functools.lru_cache(maxsize=256)
def _translate(text: str) -> str:
    from config.default import Default  # pylint: disable=import-outside-toplevel
    from common.analytics import (  # pylint: disable=import-outside-toplevel
        extract_usage_metadata,
        track_model_call,
    )
    from models.gemini import client  # pylint: disable=import-outside-toplevel

    with track_model_call(Default.MODEL_ID, task="translate") as ctx:
        response = client.models.generate_content(
            model=Default.MODEL_ID,
            contents=(
                "Translate this prompt for a media generation model into natural "
                "English. Keep names, brand names, numbers and any text that must "
                "appear on screen exactly as written (in quotes, in its own "
                "language). Reply with the translation only.\n\n" + text
            ),
        )
        ctx["billing_units"].update(extract_usage_metadata(response))
    return (response.text or "").strip()


def english_for_model(text: str) -> str:
    """`text` in English for a model that only reads English prompts (Lyria 2,
    Veo). The person still sees their own words: only the model call gets
    the translation. Non-Arabic text, mock mode and any failure return
    `text` unchanged."""
    if detect_lang(text) != "ar":
        return text
    try:
        from common.mock_generation import mock_enabled  # pylint: disable=import-outside-toplevel

        if mock_enabled():
            return text
        return _translate(text) or text
    except Exception:  # noqa: BLE001  (never block a generation over this)
        logger.warning("Could not translate a prompt for the model", exc_info=True)
        return text


def follow_user_rule(ui_language: str | None) -> str:
    """The rule for a chat or voice agent's system prompt."""
    fallback = lang_name(ui_language)
    return (
        "Language: speak and write in the language the person uses (Arabic or English). "
        "Write every field value, prompt, title, script, lyric and caption you fill in or "
        "pass to a tool in that same language, so they see their own language on screen; "
        "never translate their words into English for them. Names and the exact choices "
        f"listed for a field stay as given. If you cannot tell, use {fallback}, the language "
        "the site is set to."
    )
