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
"""Arabic for the demo pages (common/i18n_ar/workflows.py)."""

import re

import pytest

from common import i18n
from common.i18n_ar import workflows


def test_patterns_compile_and_fill():
    for pattern, template in workflows.PATTERNS:
        groups = re.compile(pattern).groups
        assert pattern.startswith("^") and pattern.endswith("$"), pattern
        # Every {n} in the template has a group to fill it.
        for n in re.findall(r"\{(\d+)\}", template):
            assert int(n) < groups, (pattern, template)


def test_no_arabic_keys_and_no_empty_values():
    for english, arabic in workflows.AR_TEXT.items():
        assert english and arabic
        assert not re.search(r"[؀-ۿ]", english), english
        assert re.search(r"[؀-ۿ]", arabic), english


@pytest.mark.parametrize(
    "english, arabic",
    [
        ("Try-on result 2", "نتيجة القياس 2"),
        ("Uploading 1 of 3", "جارٍ رفع 1 من 3"),
        ("Image Model: gemini-3-pro-image", "نموذج الصور: gemini-3-pro-image"),
        ("Video Duration: 8 seconds", "مدة الفيديو: 8 ث"),
        ("Making the 360 video with Veo 3.1", "إنشاء فيديو 360 باستخدام Veo 3.1"),
        ("Generating video for Kitchen...", "جارٍ إنشاء فيديو Kitchen..."),
        ("Room View: Kitchen", "عرض الغرفة: Kitchen"),
        ("Critic Retry 2: Trying on top...", "إعادة المراجعة 2: جارٍ تجربة top..."),
        ("Couldn't upload the photo. Boom", "تعذّر رفع الصورة. Boom"),
        ("Couldn't upload the photo. 404 {\n x }", "تعذّر رفع الصورة. 404 {\n x }"),
    ],
)
def test_runtime_patterns(english, arabic):
    assert i18n.tx_lang("ar", english) == arabic


def test_english_is_untouched():
    for english in list(workflows.AR_TEXT)[:50] + [
        "Try-on result 2",
        "Room View: Kitchen",
    ]:
        assert i18n.tx_lang("en", english) == english


def test_demo_labels_translate():
    for english in (
        "Choose a model",
        "Upload floor plan",
        "Get four views",
        "Create brand kit",
        "Back view",
        "Steps",
    ):
        assert i18n.tx_lang("ar", english) != english, english


def test_does_not_override_other_groups():
    """workflows.py merges last, so a shared key must not change another page's Arabic."""
    from common.i18n_ar import film, shell, studios

    for mod in (shell, studios, film):
        for english, arabic in mod.AR_TEXT.items():
            if english in workflows.AR_TEXT:
                assert workflows.AR_TEXT[english] == arabic, english
