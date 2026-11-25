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
"""Arabic for the Image, Video, Voice and Music studios (common/i18n_ar/studios.py)."""

import re

import pytest

from common import i18n
from common.i18n_ar import studios

ARABIC = re.compile(r"[؀-ۿ]")


@pytest.mark.parametrize(
    ("english", "arabic"),
    [
        ("First + last frame", "الإطار الأول والأخير"),
        ("Sound: always on", "الصوت: مفعّل دائمًا"),
        ("8s", "8 ث"),
        ("1 images", "صورة واحدة"),
        ("2 images", "صورتان"),
        ("4 images", "4 صور"),
        ("1 video", "فيديو واحد"),
        ("3 videos", "3 فيديوهات"),
        ("2 tracks", "مقطعان"),
        ("Usually ~30s", "عادةً ~30 ث"),
        (
            "Edit, extend, upscale · Usually ~90s",
            "تعديل وتمديد ورفع الدقة · عادةً ~90 ث",
        ),
        ("Voice for Host", "صوت Host"),
        ("Pronunciations (2)", "النطق (2)"),
        ("Generation time: 12 seconds (mock)", "مدة الإنشاء: 12 ث (تجريبي)"),
        ("Generation time: 12 seconds", "مدة الإنشاء: 12 ث"),
        ("Lyria 3 Pro · Track 2", "Lyria 3 Pro · المقطع 2"),
        ("More styles (9)", "أنماط أخرى (9)"),
        ("You can upload a maximum of 3 images.", "يمكنك رفع 3 صور كحد أقصى."),
        (
            "You can upload a maximum of 3 images. Some files were not uploaded.",
            "يمكنك رفع 3 صور كحد أقصى. لم تُرفع بعض الملفات.",
        ),
        ("English (United States)", "الإنجليزية (الولايات المتحدة)"),
    ],
)
def test_studio_text_in_arabic(english, arabic):
    assert i18n.tx_lang("ar", english) == arabic


def test_english_is_unchanged():
    for english in ("Text", "8s", "2 images", "Voice for Host", "Model: x"):
        assert i18n.tx_lang("en", english) == english


def test_every_entry_is_arabic_and_patterns_compile():
    for english, arabic in studios.AR_TEXT.items():
        assert english.strip() and arabic.strip(), english
        # Names that stay Latin (e.g. "Gemini TTS") are the only exceptions.
        if english not in {"Gemini TTS", "Chirp3 HD", "labubu"}:
            assert ARABIC.search(arabic), english
    for pattern, template in studios.PATTERNS:
        groups = re.compile(pattern).groups
        used = {int(n) for n in re.findall(r"\{(\d+)\}", template)}
        assert used <= set(range(groups)), pattern


def test_voice_languages_all_translated():
    from config.gemini_tts import CHIRP3_HD_LANGUAGES, GEMINI_TTS_LANGUAGES

    for label in set(GEMINI_TTS_LANGUAGES) | set(CHIRP3_HD_LANGUAGES):
        assert ARABIC.search(i18n.tx_lang("ar", label)), label


def test_video_modes_and_voice_options_translated():
    from config.video_studio_models import STUDIO_MODE_LABELS
    from config.voice import PACES, STYLES

    labels = list(STUDIO_MODE_LABELS.values())
    labels += [lbl for _, lbl, _ in STYLES] + [lbl for _, lbl, _, _ in PACES]
    for label in labels:
        assert ARABIC.search(i18n.tx_lang("ar", label)), label


def test_chip_wrapper_translates_text_not_values(monkeypatch):
    from components import studio_chips

    seen = {}
    monkeypatch.setattr(studio_chips, "tx", lambda s: i18n.tx_lang("ar", s))
    monkeypatch.setattr(studio_chips, "current_lang", lambda: "ar")
    monkeypatch.setattr(studio_chips, "_chip_menu", lambda **kw: seen.update(kw))

    studio_chips.chip_menu(
        label="Aspect ratio",
        value="16:9",
        options=[{"value": "16:9", "label": "16:9", "hint": "Landscape"}],
    )
    assert seen["label"] == "نسبة الأبعاد"
    assert seen["value"] == "16:9"  # selects the option: never translated
    assert seen["options"] == [{"value": "16:9", "label": "16:9", "hint": "أفقي"}]
    # The tip is looked up by the English name.
    assert seen["tip"] == "The shape: wide, square or tall"

    studio_chips.chip_menu(label="Generate audio", value="Audio", kind="toggle")
    assert seen["value"] == "الصوت"

    # "Model" is the AI model here, whatever other pages call a model.
    studio_chips.chip_menu(
        label="Model", value="m", options=[{"value": "m", "label": "M"}]
    )
    assert seen["label"] == "النموذج"


def test_studio_options_labels_follow_language(monkeypatch):
    from services import studio_options

    monkeypatch.setattr(studio_options, "tx", lambda s: i18n.tx_lang("ar", s))
    monkeypatch.setattr(studio_options, "_tr_key", lambda key, english, **fmt: english)
    assert (
        studio_options.tr("studio.input.first_frame", "First frame") == "الإطار الأول"
    )
    opts = studio_options._opts([("8", "8s"), ("16:9", "16:9")])
    assert opts == [{"value": "8", "label": "8 ث"}, {"value": "16:9", "label": "16:9"}]


def test_voice_samples_follow_site_language():
    from config import voice

    assert voice.sample_script("en", dialogue=False) == voice.DEFAULT_SCRIPT
    assert voice.sample_script("en", dialogue=True) == voice.DEFAULT_DIALOGUE
    assert voice.sample_script("ar", dialogue=False) == voice.DEFAULT_SCRIPT_AR
    assert voice.sample_script("ar", dialogue=True) == voice.DEFAULT_DIALOGUE_AR
    # The dialogue sample keeps the speaker ids the dialogue panel starts with.
    for line in voice.DEFAULT_DIALOGUE_AR.splitlines():
        assert line.split(":")[0] in voice.DEFAULT_SPEAKERS
    assert set(voice.SAMPLE_SCRIPTS) >= {voice.DEFAULT_SCRIPT, voice.DEFAULT_SCRIPT_AR}


def test_voice_default_language():
    from config import voice

    gemini = voice.DEFAULT_VOICE_ENGINE
    assert voice.default_language(gemini) == voice.DEFAULT_LANGUAGE
    assert voice.default_language(gemini, "en") == voice.DEFAULT_LANGUAGE
    ar = voice.default_language(gemini, "ar")
    assert ar.startswith("ar") and ar in voice.languages_for(gemini).values()
    chirp = voice.default_language(voice.CHIRP_ENGINE, "ar")
    assert (
        chirp.startswith("ar")
        and chirp in voice.languages_for(voice.CHIRP_ENGINE).values()
    )


def test_voice_language_follows_site_until_picked(monkeypatch):
    from types import SimpleNamespace

    from config import voice
    from pages import voice as page

    state = SimpleNamespace(
        engine=voice.DEFAULT_VOICE_ENGINE,
        language=voice.DEFAULT_LANGUAGE,
        language_picked=False,
        text=voice.DEFAULT_SCRIPT,
        text_key=0,
        multi_speaker=False,
    )
    monkeypatch.setattr(page, "current_lang", lambda: "ar")
    page._localize_language(state)
    page._localize_sample(state)
    assert state.language == "ar-EG"
    assert state.text == voice.DEFAULT_SCRIPT_AR

    # Chirp has its own Arabic code.
    page._set_engine(state, voice.CHIRP_ENGINE)
    assert state.language == "ar-XA"

    # A language the user picked, and their own script, are kept.
    state.language, state.language_picked = "fr-FR", True
    state.text = "My own words"
    monkeypatch.setattr(page, "current_lang", lambda: "en")
    page._localize_language(state)
    page._localize_sample(state)
    assert (state.language, state.text) == ("fr-FR", "My own words")
