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
"""Python API for the <gm-chip-menu> web component (composer setting chips)."""

import json
import typing

import mesop as me

from common.i18n import tx

# What common settings do, shown when you hover or focus the chip. Labels
# that already say what they do ("Apply my brand: colours and tone") need none.
TIPS = {
    "Model": "Which Google model makes the result",
    "Aspect ratio": "The shape: wide, square or tall",
    "Resolution": "Sharper results take a little longer",
    "Image size": "Sharper results take a little longer",
    "Length": "How many seconds the video runs",
    "Number of images": "How many versions to make at once",
    "Number of videos": "How many versions to make at once",
    "Number of tracks": "How many versions to make at once",
    "Voice": "Who reads the script",
    "Pace": "How fast the voice speaks",
    "Speaking style": "The mood of the delivery",
    "Language": "The language the voice speaks",
    "Generate audio": "Add sound and speech to the video",
}


def chip_options(
    pairs: typing.Iterable[tuple[str, str] | tuple[str, str, str] | str],
) -> list[dict[str, str]]:
    """Build chip options from values, (value, label) or (value, label, hint)."""
    options = []
    for pair in pairs:
        if isinstance(pair, str):
            options.append({"value": pair, "label": pair})
        elif len(pair) == 3:
            options.append({"value": pair[0], "label": pair[1], "hint": pair[2]})
        else:
            options.append({"value": pair[0], "label": pair[1]})
    return options


def change_value(e: me.WebEvent) -> str:
    """Read the chosen value from a chip change event."""
    value = e.value
    if isinstance(value, dict):
        value = value.get("value", "")
    return str(value or "")


@me.web_component(path="./chip_menu.js")
def chip_menu(
    *,
    label: str,
    value: str,
    options: list[dict[str, str]] | None = None,
    icon: str = "",
    on_change: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    kind: str = "menu",
    checked: bool = False,
    disabled: bool = False,
    key: str | None = None,
    tip: str | None = None,
):
    """A composer chip.

    kind="menu" opens a listbox of `options`; kind="toggle" is an on/off chip
    whose change event value is "true" or "false". `label` names the setting
    for screen readers and the tooltip; the chip itself shows the value.
    `tip` says what the setting does (defaults to TIPS for common labels).
    """
    if tip is None:
        tip = TIPS.get(label, "")
    tip = tx(tip) if tip else ""
    return me.insert_web_component(
        key=key,
        name="gm-chip-menu",
        properties={
            "label": label,
            "value": value,
            "options": json.dumps(options or []),
            "icon": icon,
            "kind": kind,
            "checked": checked,
            "disabled": disabled,
            "tip": tip,
        },
        events={"changeEvent": on_change},
    )
