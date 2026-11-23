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
"""Story Studio Export menu state: whether it is open and the choices.

Kept apart from StoryState so the Timeline & Export view owns it. The values
are checked again by services/story_export.clean before an export runs.
"""

from dataclasses import dataclass

import mesop as me


@me.stateclass
@dataclass
class StoryExportState:
    open: bool = False
    short: int = 0  # 0 = the clips' own size
    fmt: str = "mp4"
    subs: str = "none"  # "none" | "burn" | "srt"
    lang: str = "en"  # "en" | "ar" | "en+ar"
    branding: bool = True

    def options(self) -> dict:
        return {
            "short": self.short,
            "fmt": self.fmt,
            "subs": self.subs,
            "lang": self.lang,
            "branding": self.branding,
        }
