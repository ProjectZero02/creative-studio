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
"""Translate the English text pages hand to Mesop components, in one place.

Most pages pass literal English to ``me.text``, ``me.button``, ``me.input``
and friends. Rather than wrap every call in ``tx()`` (thousands of edits that
would block upstream merges), ``install()`` wraps the Mesop components once at
startup so each user-visible string goes through ``common.i18n.tx``.

``tx`` only matches whole strings listed in ``AR_TEXT`` (or one of its
patterns) and only in Arabic, so English is untouched and user content (a
prompt, a file name) passes through unless it is exactly a known UI label.

Add a missing translation to the page group's file in ``common/i18n_ar/``.
Text built at runtime (f-strings with a number or a name) needs a pattern
there, or an explicit ``tx()``/``t()`` call in the page.
"""

from __future__ import annotations

import functools
from typing import Any

import mesop as me

from common.i18n import tx

_INSTALLED = False


def _tr(value: Any) -> Any:
    if isinstance(value, str) and value:
        return tx(value)
    return value


def _wrap(name: str, positional: tuple[str, ...], keywords: tuple[str, ...]):
    """Replace ``me.<name>`` with a version that translates the given args."""
    original = getattr(me, name, None)
    if original is None or getattr(original, "_gm_i18n", False):
        return

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        if args and positional:
            args = list(args)
            for i, _ in enumerate(positional[: len(args)]):
                args[i] = _tr(args[i])
            args = tuple(args)
        for key in positional + keywords:
            if key in kwargs:
                kwargs[key] = _tr(kwargs[key])
        return original(*args, **kwargs)

    wrapper._gm_i18n = True  # type: ignore[attr-defined]
    setattr(me, name, wrapper)


def _wrap_select() -> None:
    original = me.select
    if getattr(original, "_gm_i18n", False):
        return

    @functools.wraps(original)
    def select(*args, **kwargs):
        for key in ("label", "placeholder"):
            if key in kwargs:
                kwargs[key] = _tr(kwargs[key])
        options = kwargs.get("options")
        if options:
            kwargs["options"] = [
                me.SelectOption(label=_tr(o.label), value=o.value) for o in options
            ]
        return original(*args, **kwargs)

    select._gm_i18n = True  # type: ignore[attr-defined]
    me.select = select


def _wrap_button_toggle() -> None:
    original = getattr(me, "button_toggle", None)
    if original is None or getattr(original, "_gm_i18n", False):
        return

    @functools.wraps(original)
    def button_toggle(*args, **kwargs):
        buttons = kwargs.get("buttons")
        if buttons:
            kwargs["buttons"] = [
                me.ButtonToggleButton(label=_tr(b.label), value=b.value)
                for b in buttons
            ]
        return original(*args, **kwargs)

    button_toggle._gm_i18n = True  # type: ignore[attr-defined]
    me.button_toggle = button_toggle


def install() -> None:
    """Wrap the Mesop components once. Safe to call more than once."""
    global _INSTALLED  # pylint: disable=global-statement
    if _INSTALLED:
        return
    _INSTALLED = True
    _wrap("text", ("text",), ())
    _wrap("markdown", ("text",), ())
    _wrap("button", ("label",), ())
    _wrap("link", (), ("text",))
    _wrap("input", (), ("label", "placeholder", "hint_label"))
    _wrap("textarea", (), ("label", "placeholder", "hint_label"))
    _wrap("native_textarea", (), ("placeholder",))
    _wrap("tooltip", (), ("message",))
    _wrap("checkbox", ("label",), ())
    _wrap("slide_toggle", ("label",), ())
    _wrap("expansion_panel", (), ("title", "description"))
    _wrap("uploader", (), ("label",))
    _wrap("content_uploader", (), ("label",))
    _wrap_select()
    _wrap_button_toggle()
