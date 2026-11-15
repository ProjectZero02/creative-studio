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
"""English / Arabic text layer (common/i18n.py) and the language switch."""

import json
import re
import string
from types import SimpleNamespace

import pytest

from common import i18n


@pytest.fixture
def lang(monkeypatch):
    """Set the language t() sees, without a Mesop request."""

    def _set(value: str):
        monkeypatch.setattr(i18n, "current_lang", lambda: value)

    return _set


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_langs():
    assert i18n.LANGS == ("en", "ar")


def test_every_ar_key_exists_in_en():
    missing = sorted(set(i18n.AR) - set(i18n.EN))
    assert not missing, f"Arabic keys with no English: {missing}"


def test_every_en_key_has_arabic():
    # Not required by the fallback, but the shared chrome should be complete.
    missing = sorted(set(i18n.EN) - set(i18n.AR))
    assert not missing, f"English keys with no Arabic: {missing}"


def test_placeholders_match():
    for key, ar in i18n.AR.items():
        assert _fields(ar) <= _fields(i18n.EN[key]), key


def test_arabic_values_are_arabic_or_names():
    arabic = re.compile(r"[؀-ۿ]")
    names_only = {
        "lang.name.en",
        "home.eyebrow",
        "nav.gemini_omni",
        "nav.gemini_tts",
        "nav.gemini_writers_workshop",
        "nav.chirp_3hd",
        "nav.pixie_compositor",
    }
    for key, value in i18n.AR.items():
        assert value.strip(), key
        if key not in names_only:
            assert arabic.search(value), f"{key} has no Arabic: {value!r}"


def test_product_names_stay_latin():
    for name in ("Nano Banana", "Gemini Omni", "Veo", "Vertex AI", "Google Cloud"):
        en_hits = [k for k, v in i18n.EN.items() if name in v]
        for key in en_hits:
            assert name in i18n.AR.get(key, name), f"{key} lost {name!r}"


def test_t_reads_current_language(lang):
    lang("en")
    assert i18n.t("nav.veo") == "Video Studio"
    lang("ar")
    assert i18n.t("nav.veo") == "استوديو الفيديو"


def test_t_falls_back_to_english(lang, monkeypatch):
    monkeypatch.setitem(i18n.EN, "test.only_en", "Only English {n}")
    lang("ar")
    assert "test.only_en" not in i18n.AR
    assert i18n.t("test.only_en", n=3) == "Only English 3"


def test_t_unknown_key_uses_default_then_key(lang):
    lang("ar")
    assert i18n.t("no.such.key", default="Fallback") == "Fallback"
    assert i18n.t("no.such.key") == "no.such.key"


def test_t_outside_mesop_is_english():
    # No Mesop request in tests: current_lang() must not raise.
    assert i18n.current_lang() == "en"
    assert i18n.t("menu.sign_out") == "Sign out"


def test_tr_keeps_page_english_and_translates_arabic(lang):
    lang("en")
    assert i18n.tr("page.veo.purpose", "Page's own copy.") == "Page's own copy."
    lang("ar")
    assert (
        i18n.tr("page.veo.purpose", "Page's own copy.") == i18n.AR["page.veo.purpose"]
    )
    assert i18n.tr("page.unknown.purpose", "Kept") == "Kept"


def test_tx_phrases_and_patterns(lang):
    lang("ar")
    assert i18n.tx("Saving to library") == "الحفظ في المكتبة"
    assert i18n.tx("Sending to Gemini Omni") == "الإرسال إلى Gemini Omni"
    assert i18n.tx("Not a known phrase") == "Not a known phrase"
    lang("en")
    assert i18n.tx("Saving to library") == "Saving to library"


def test_plural(lang):
    lang("en")
    assert i18n.plural("results.count", 1) == "1 item this session"
    assert i18n.plural("results.count", 4) == "4 items this session"


def test_normalize_and_accept_language():
    assert i18n.normalize_lang("ar-QA") == "ar"
    assert i18n.normalize_lang("EN_us") == "en"
    assert i18n.normalize_lang("fr") == "en"
    assert i18n.normalize_lang(None) == "en"
    assert i18n.lang_from_accept_language("ar-QA,ar;q=0.9,en;q=0.8") == "ar"
    assert i18n.lang_from_accept_language("en-GB,ar;q=0.5") == "en"
    assert i18n.lang_from_accept_language("") == "en"


def test_route_key():
    assert i18n.route_key("/nano-banana") == "nano_banana"
    assert i18n.route_key("/library_v2") == "library_v2"


def test_every_nav_route_has_a_title_key():
    with open("config/navigation.json", encoding="utf-8") as f:
        pages = json.load(f)["pages"]
    for page in pages:
        key = f"nav.{i18n.route_key(page['route'])}"
        assert i18n.EN.get(key) == page["display"], key
        assert key in i18n.AR, key


def test_apply_lang_sets_state():
    state = SimpleNamespace(lang="en", lang_chosen=False)
    assert i18n.apply_lang(state, "ar") == "ar"
    assert state.lang == "ar" and state.lang_chosen is True
    i18n.apply_lang(state, "xx", chosen=False)
    assert state.lang == "en"


def _patch_state(monkeypatch, module, state):
    monkeypatch.setattr(module.me, "state", lambda cls: state)


def test_language_switch_handler_sets_state(monkeypatch):
    from components.user_menu import user_menu

    state = SimpleNamespace(lang="en", lang_chosen=False)
    _patch_state(monkeypatch, user_menu, state)

    list(user_menu.on_lang(SimpleNamespace(value={"lang": "ar"})))
    assert state.lang == "ar" and state.lang_chosen is True

    # No language in the event: toggle to the other one.
    list(user_menu.on_lang(SimpleNamespace(value={})))
    assert state.lang == "en" and state.lang_chosen is True


def test_lang_load_handler_keeps_browser_default_unchosen(monkeypatch):
    from components.lang_manager import lang_manager

    state = SimpleNamespace(lang="en", lang_chosen=False)
    _patch_state(monkeypatch, lang_manager, state)

    list(
        lang_manager.on_lang_load(
            SimpleNamespace(value={"lang": "ar", "chosen": False})
        )
    )
    assert state.lang == "ar" and state.lang_chosen is False

    list(
        lang_manager.on_lang_load(SimpleNamespace(value={"lang": "en", "chosen": True}))
    )
    assert state.lang == "en" and state.lang_chosen is True


def test_menu_labels_json():
    from components.user_menu.user_menu import menu_labels

    ar = json.loads(menu_labels("ar"))
    en = json.loads(menu_labels("en"))
    assert en["sign_out"] == "Sign out" and ar["sign_out"] == "تسجيل الخروج"
    # The switch is labelled in the other language.
    assert ar["name.en"] == "English" and en["name.ar"] == "العربية"


def test_header_localizes_title_and_purpose(lang):
    from components.header import localized_title_and_purpose

    lang("ar")
    title, purpose = localized_title_and_purpose(
        "Video Studio", "English copy", from_nav=False
    )
    assert title == "استوديو الفيديو"
    assert purpose == i18n.AR["page.veo.purpose"]
    title, purpose = localized_title_and_purpose("Library", "x", from_nav=True)
    assert title == "المكتبة" and purpose == i18n.AR["nav.library_v2.desc"]
    lang("en")
    assert localized_title_and_purpose("Video Studio", "Own", from_nav=False) == (
        "Video Studio",
        "Own",
    )


def test_progress_labels_fill_media():
    from components.generation_progress.generation_progress import progress_labels

    ar = json.loads(progress_labels("ar", "video"))
    assert ar["creating"] == "جارٍ إنشاء الفيديو"
    assert "{t}" in ar["usually"]
    en = json.loads(progress_labels("en", "image"))
    assert en["creating"] == "Creating your image"


def test_login_page_renders_both_languages():
    from routers import auth_router

    en = auth_router.render_login_page(csrf="c", next_path="/home")
    assert 'lang="en" dir="ltr"' in en and "Welcome back" in en
    assert 'data-lang="ar"' in en and "العربية" in en
    ar = auth_router.render_login_page(csrf="c", next_path="/home", lang="ar")
    assert 'lang="ar" dir="rtl"' in ar and "مرحبًا بعودتك" in ar
    assert 'data-lang="en"' in ar
