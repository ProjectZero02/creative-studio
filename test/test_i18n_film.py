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
"""Arabic for the Film Studio: common/i18n_ar/film.py and the story widgets."""

import json
import re

import pytest

import common.i18n as i18n
from common.i18n import tx_lang
from common.i18n_ar import film
from components.story_studio import widgets


@pytest.mark.parametrize(
    ("english", "arabic"),
    [
        ("Edit & Export", "التحرير والتصدير"),
        ("8s", "8 ث"),
        ("≈ 30s", "≈ 30 ث"),
        ("Done · 3s", "تم · 3 ث"),
        ("Working · 1:05", "قيد العمل · 1:05"),
        ("10 of 12 steps done · 52s elapsed", "اكتملت 10 من 12 خطوات · مضى 52 ث"),
        ("10 of 12 steps done · 1:00 elapsed", "اكتملت 10 من 12 خطوات · مضى 1:00"),
        ("Updated Nov 25, 2026", "حُدّث 25 نوفمبر 2026"),
        ("Scene 3 · video clip", "المشهد 3 · مقطع فيديو"),
        ("Scene 2 · Arabic voiceover", "المشهد 2 · تعليق صوتي بالعربية"),
        ("Take 4 · start frame", "المقطع 4 · إطار البداية"),
        ("Baker · Face", "Baker · الوجه"),
        ("Narrator · voice sample", "الراوي · عينة الصوت"),
        ("1 character · 3 locations", "الشخصيات: 1 · الأماكن: 3"),
        ("My set · 2 characters · 1 prop", "My set · الشخصيات: 2 · الأغراض: 1"),
        ("8s · Wide shot · Static", "8 ث · لقطة واسعة · ثابتة"),
        ("Take 1 · 8s · 2 shots", "المقطع 1 · 8 ث · اللقطات: 2"),
        ("Kore · female", "Kore · أنثى"),
        ("Arabic version (+$12.80)", "النسخة العربية (\u2066+$12.80\u2069)"),
        ("Make English version", "إنشاء النسخة الإنجليزية"),
        (
            "Video $12.80 · Frames $0.04 · Voice <$0.01 · Music $0.06",
            "الفيديو \u2066$12.80\u2069 · الإطارات \u2066$0.04\u2069 · "
            "الصوت \u2066<$0.01\u2069 · الموسيقى \u2066$0.06\u2069",
        ),
        ("Delete “Harbour cast”?", "حذف «Harbour cast»؟"),
        ("Lock Profile", "قفل جانبي"),
        ("About 1.20 / 2.40 USD", "نحو \u20661.20 / 2.40 USD\u2069"),
        ("Trim scene 2: 1.5 s off the end", "قص المشهد 2: 1.5 ث من النهاية"),
        ("3 of 12 steps failed. Finished work is kept; press Retry to continue.",
         "فشلت 3 من 12 خطوات. حُفظ العمل المنجز؛ اضغط إعادة المحاولة للمتابعة."),
    ],
)
def test_film_patterns(english, arabic):
    assert tx_lang("ar", english) == arabic


def test_english_is_unchanged():
    for english in ("Done · 3s", "Scene 3 · video clip", "Edit & Export", "8s"):
        assert tx_lang("en", english) == english


def test_patterns_compile_and_templates_fit_groups():
    for pattern, template in film.PATTERNS:
        groups = re.compile(pattern).groups
        used = {int(n) for n in re.findall(r"\{(\d+)\}", template)}
        assert used <= set(range(groups)), (pattern, template)
        assert pattern.startswith("^") and pattern.endswith("$"), pattern


def test_no_english_words_left_in_arabic_text():
    names = {"Gemini", "Omni", "Veo", "Lyria", "SRT", "USD", "JSON", "Space",
             "Ctrl", "Shift", "Del", "Product", "Kore", "dB"}  # fmt: skip
    for english, arabic in film.AR_TEXT.items():
        if '"2 min"' in english:  # the length examples the duration box reads
            continue
        prose = re.sub(r"\]\([^)]*\)", "]", arabic)  # markdown link targets
        words = set(re.findall(r"[A-Za-z]{2,}", prose)) - names
        assert not words or arabic == english, (english, arabic)


def test_tx_dots_translates_each_part(monkeypatch):
    monkeypatch.setattr(i18n, "current_lang", lambda: "ar")
    monkeypatch.setattr(widgets, "tx", lambda s: tx_lang("ar", s))
    assert widgets.tx_dots("4 takes · 32s") == "المقاطع: 4 · 32 ث"
    assert widgets.tx_dots("1 · 8s · clip") == "1 · 8 ث · مقطع"
    assert widgets.tx_dots("") == ""


def test_tx_dots_and_strings_are_identity_in_english(monkeypatch):
    monkeypatch.setattr(widgets, "tx", lambda s: tx_lang("en", s))
    assert widgets.tx_dots("4 takes · 32s") == "4 takes · 32s"
    assert widgets.strings_json(("Play", "Scene {0}")) == "{}"


def test_strings_json_in_arabic(monkeypatch):
    monkeypatch.setattr(widgets, "tx", lambda s: tx_lang("ar", s))
    out = json.loads(widgets.strings_json(widgets._TIMELINE_TEXT))
    assert out["Scene {0}"] == "المشهد {0}"
    assert out["{0} to {1}"] == "{0} إلى {1}"
    # Every timeline, stepper and compare string has Arabic.
    texts = widgets._TIMELINE_TEXT + widgets._STEPPER_TEXT + widgets._COMPARE_TEXT
    missing = [t for t in texts if t not in json.loads(widgets.strings_json(texts))]
    assert not missing
