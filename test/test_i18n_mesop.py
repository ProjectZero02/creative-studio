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
"""The Mesop hook that routes page text through common.i18n.tx."""

import mesop as me
import pytest

import common.i18n as i18n
import common.i18n_mesop as hook
from common import i18n_ar


@pytest.fixture
def arabic(monkeypatch):
    monkeypatch.setattr(i18n, "current_lang", lambda: "ar")
    monkeypatch.setitem(i18n.AR_TEXT, "Generate", "إنشاء")
    monkeypatch.setitem(i18n.AR_TEXT, "Wide", "عريض")


def test_install_wraps_components_once():
    hook.install()
    first = me.text
    hook.install()
    assert me.text is first
    for name in ("text", "button", "input", "textarea", "select", "tooltip"):
        assert getattr(getattr(me, name), "_gm_i18n", False), name


def test_wrapper_translates_positional_and_keyword(arabic, monkeypatch):
    seen = {}

    def fake_text(text=None, **kw):
        seen["text"] = text

    def fake_input(**kw):
        seen.update(kw)

    monkeypatch.setattr(me, "text", fake_text)
    monkeypatch.setattr(me, "input", fake_input)
    hook._wrap("text", ("text",), ())
    hook._wrap("input", (), ("label", "placeholder"))
    me.text("Generate")
    assert seen["text"] == "إنشاء"
    me.input(label="Generate", placeholder="a red fox", value="Generate")
    assert seen["label"] == "إنشاء"
    assert seen["placeholder"] == "a red fox"  # unknown text passes through
    assert seen["value"] == "Generate"  # values (user content) are never touched


def test_select_translates_option_labels_not_values(arabic, monkeypatch):
    seen = {}
    monkeypatch.setattr(me, "select", lambda **kw: seen.update(kw))
    hook._wrap_select()
    me.select(label="Generate", options=[me.SelectOption(label="Wide", value="16:9")])
    assert seen["label"] == "إنشاء"
    opt = seen["options"][0]
    assert (opt.label, opt.value) == ("عريض", "16:9")


def test_english_is_untouched(monkeypatch):
    monkeypatch.setattr(i18n, "current_lang", lambda: "en")
    monkeypatch.setitem(i18n.AR_TEXT, "Generate", "إنشاء")
    assert i18n.tx("Generate") == "Generate"


def test_group_files_merge_into_ar_text():
    for mod in i18n_ar.GROUPS:
        for english, arabic in mod.AR_TEXT.items():
            assert english in i18n.AR_TEXT, english
            assert arabic.strip(), english
        for pattern, _template in mod.PATTERNS:
            body = pattern.removeprefix("(?s)")
            assert body.startswith("^") and body.endswith("$"), pattern
