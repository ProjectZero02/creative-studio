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
"""The composer's optional notice chip and its translated wording."""

import inspect
import pathlib
import re

from common import i18n


def test_notice_is_off_by_default():
    from components.composer import composer as comp

    params = inspect.signature(comp.composer).parameters
    assert params["notice"].default == ""
    assert params["on_notice_undo"].default is None


def test_undo_strings_exist_in_both_languages():
    for key in ("composer.undo", "composer.undo_hint", "settings.undone"):
        assert i18n.EN[key] and i18n.AR[key]


def test_prompt_settings_english_matches_i18n():
    """Each notice string the parser writes has the same English in i18n."""
    import common.prompt_settings as ps

    source = pathlib.Path(ps.__file__).read_text(encoding="utf-8")
    pairs = re.findall(r'"(settings\.[a-z_.]+)",\s*"([^"]+)"', source)
    assert len(pairs) >= 8
    for key, english in pairs:
        assert i18n.EN.get(key) == english, key
        assert key in i18n.AR, key
