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
"""Arabic page text, one file per page group, merged into common.i18n.AR_TEXT.

shell.py      Home, nav, header, account, settings, users, projects, library,
              usage, brand, login, errors and the shared web components
studios.py    Image, Video, Voice and Music studios
film.py       Film Studio
workflows.py  Fashion, Interiors, Product 360, Brand kit and other demos

These files must not import common.i18n (it imports them).
"""

from __future__ import annotations

import re

from common.i18n_ar import film, shell, studios, workflows

GROUPS = (shell, studios, film, workflows)


def merged_text() -> dict[str, str]:
    out: dict[str, str] = {}
    for mod in GROUPS:
        out.update(mod.AR_TEXT)
    return out


def merged_patterns() -> list[tuple[re.Pattern[str], str]]:
    return [
        (re.compile(pattern), template)
        for mod in GROUPS
        for pattern, template in mod.PATTERNS
    ]
