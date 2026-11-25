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
"""Arabic for the shell pages (common/i18n_ar/shell.py) and date formatting."""

import datetime
import json
import re

import pytest

from common import i18n
from common.i18n_ar import shell


@pytest.fixture
def lang(monkeypatch):
    def _set(value: str):
        monkeypatch.setattr(i18n, "current_lang", lambda: value)

    return _set


def test_shell_text_is_arabic():
    for english, arabic in shell.AR_TEXT.items():
        assert re.search(r"[؀-ۿ]", arabic), english


def test_shell_patterns_compile_and_fill():
    for pattern, template in shell.PATTERNS:
        groups = re.compile(pattern).groups
        assert template.format(*(["x"] * groups)), pattern


@pytest.mark.parametrize(
    ("english", "arabic"),
    [
        ("Delete Acme? Films keep their copy.", "حذف Acme؟ تحتفظ الأفلام بنسختها."),
        ("Up to 5.", "حتى 5 ألوان."),
        ("Starred (3)", "المميّزة بنجمة (3)"),
        ("8 sec", "8 ث"),
        ("a@b.test is now an admin.", "أصبح a@b.test مشرفًا."),
        ("a@b.test is disabled.", "تم تعطيل a@b.test."),
        ("Use at least 12 characters.", "استخدم 12 أحرف على الأقل."),
        ('Prompt: "two\nlines"', "الوصف: «two\nlines»"),
        ("Error: boom", "خطأ: boom"),
    ],
)
def test_shell_patterns(english, arabic):
    assert i18n.tx_lang("ar", english) == arabic
    assert i18n.tx_lang("en", english) == english


def test_password_notices_keep_the_password():
    out = i18n.tx_lang(
        "ar",
        "Added a@b.test. Temporary password: Xy9-abc (shown once; share it privately).",
    )
    assert "a@b.test" in out and "Xy9-abc" in out and "تمت إضافة" in out


def test_format_date_english_is_strftime():
    day = datetime.datetime(2026, 11, 19, 8, 5)
    for fmt in ("%a %d %b", "%d %b %Y, %H:%M UTC"):
        assert i18n.format_date(day, fmt, "en") == day.strftime(fmt)


def test_format_date_arabic_names():
    day = datetime.datetime(2026, 11, 19, 8, 5)  # a Thursday
    assert i18n.format_date(day, "%a %d %b", "ar") == "الخميس 19 نوفمبر"
    assert (
        i18n.format_date(day, "%d %b %Y, %H:%M UTC", "ar")
        == "19 نوفمبر 2026، 08:05 UTC"
    )


def test_header_translates_titles_off_the_menu(lang):
    from components.header import localized_title_and_purpose

    lang("ar")
    title, purpose = localized_title_and_purpose(
        "Brands",
        "Logos, colours and tone, applied to films and images.",
        from_nav=False,
    )
    assert title == "العلامات التجارية"
    assert (
        purpose
        == shell.AR_TEXT["Logos, colours and tone, applied to films and images."]
    )
    lang("en")
    assert localized_title_and_purpose("Brands", "Own copy", from_nav=False) == (
        "Brands",
        "Own copy",
    )


def test_media_tile_pills_follow_language(lang):
    from common.metadata import MediaItem
    from components.media_tile.media_tile import get_pills_for_item

    item = MediaItem(
        gcsuri="gs://b/v.mp4", media_type="video", duration=8, aspect="16:9"
    )
    lang("en")
    english = json.loads(get_pills_for_item(item, "https://x/v.mp4"))
    assert [p["label"] for p in english] == ["Video", "t2v", "16:9", "8 sec"]
    lang("ar")
    arabic = json.loads(get_pills_for_item(item, "https://x/v.mp4"))
    assert [p["label"] for p in arabic] == [
        i18n.AR_TEXT["Video"],
        "من نص",
        "16:9",
        "8 ث",
    ]


def test_media_viewer_strings():
    from components.media_detail_viewer.media_detail_viewer import viewer_strings

    assert viewer_strings("en") == "{}"
    ar = json.loads(viewer_strings("ar"))
    assert ar["Prompt"] == "الوصف" and ar["Copy Link"] == "نسخ الرابط"
    assert all(re.search(r"[؀-ۿ]", v) for v in ar.values())


def test_home_chat_audio_and_duration_keys():
    from components.home_chat.home_chat import _STRINGS

    for name in ("audio_play", "audio_of", "secs", "mins"):
        key, english = _STRINGS[name]
        assert i18n.EN[key] == english
        assert key in i18n.AR


def test_tab_title_in_arabic():
    from components.lang_manager.lang_manager import page_title

    assert page_title("home", "en") == ""
    assert page_title("home", "ar") == i18n.AR["nav.home"] + " | Creative Studio"
    assert page_title("library", "ar").startswith(i18n.AR["nav.library_v2"])
    assert page_title("settings", "ar").startswith(i18n.AR["settings.title"])
    assert page_title("not_found", "ar").startswith("الصفحة غير موجودة")
    assert page_title("no_such_page_name", "ar") == ""


def test_360_is_isolated_in_arabic():
    # Without the isolate, RTL shows "°360".
    assert "\u2066360°\u2069" in i18n.AR["nav.object_rotation"]
