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
"""Composer chips for the studio pages, with their text in the page language.

The studio pages pass English to ``components.composer.chip_menu``: the
setting's name (``label``, also the chip's accessible name), option labels
and hints, and the text of toggle chips. A web component's properties are
not reached by the Mesop text hook (common/i18n_mesop.py), so this wrapper
runs them through ``common.i18n.tx`` (Arabic in common/i18n_ar/studios.py).

Option values, and the value of a menu chip (it selects the option), are
passed unchanged, so change events and saved settings are the same in every
language. English output is unchanged.
"""

from __future__ import annotations

from typing import Any

from common.i18n import current_lang, tx
from common.i18n_ar import studios as _studios
from components.composer.chip_menu import TIPS, change_value, chip_options
from components.composer.chip_menu import chip_menu as _chip_menu

__all__ = [
    "change_value",
    "chip_menu",
    "chip_options",
    "localize_options",
    "studio_text",
]


def studio_text(english: str) -> str:
    """Translate, preferring the studios' own Arabic.

    One-word names like "Model" mean something else on other pages (a
    fashion model), and the merged dictionary keeps only one meaning.
    """
    if current_lang() == "ar" and english in _studios.AR_TEXT:
        return _studios.AR_TEXT[english]
    return tx(english)


def localize_options(options: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Option dicts with their label and hint translated (values kept)."""
    out = []
    for option in options or []:
        item = dict(option)
        if item.get("label"):
            item["label"] = studio_text(str(item["label"]))
        if item.get("hint"):
            item["hint"] = studio_text(str(item["hint"]))
        out.append(item)
    return out


def chip_menu(
    *,
    label: str,
    value: str,
    options: list[dict[str, str]] | None = None,
    kind: str = "menu",
    tip: str | None = None,
    **kwargs: Any,  # noqa: ANN401
) -> Any:  # noqa: ANN401
    """``components.composer.chip_menu.chip_menu`` with translated text."""
    if tip is None:
        # Look the tip up by the English name before the name is translated.
        tip = TIPS.get(label, "")
    if kind == "toggle" or not options:
        # The chip shows this text; a toggle's change event is "true"/"false".
        value = studio_text(value) if value else value
    return _chip_menu(
        label=studio_text(label),
        value=value,
        options=localize_options(options),
        kind=kind,
        tip=tip,
        **kwargs,
    )
