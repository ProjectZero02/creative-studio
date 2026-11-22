# Copyright 2025 Google LLC
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
"""Browser-saved settings from the Settings page (pref_sync.js).

page_scaffold renders one <gm-pref> per setting, so a choice made in
Settings comes back on the next visit (like the theme and the language).
"""

import mesop as me

from state.state import AppState


@me.web_component(path="./pref_sync.js")
def _pref(*, name: str, value: str, on_load, key: str | None = None):
    return me.insert_web_component(
        key=key,
        name="gm-pref",
        properties={"name": name, "value": value},
        events={"loadEvent": on_load},
    )


def on_pref_load(e: me.WebEvent):
    """A saved value differs from this session's: use the saved one."""
    value = e.value if isinstance(e.value, dict) else {}
    s = me.state(AppState)
    if value.get("name") == "auto_enhance":
        s.auto_enhance = value.get("value") != "off"
    yield


def prefs() -> None:
    """Render the setting keepers (call once per page)."""
    s = me.state(AppState)
    _pref(
        name="auto_enhance",
        value="on" if s.auto_enhance else "off",
        on_load=on_pref_load,
        key="gm-pref-auto-enhance",
    )
