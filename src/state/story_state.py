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
"""Story Studio page state.

Small on purpose: Mesop sends the whole state on every event. Only ids, text
and media URIs (gs:// or local://) live here, never image or video bytes.
The full story is the stored record; `story_json` is a render copy of it.
"""

from dataclasses import dataclass

import mesop as me


@me.stateclass
@dataclass
class StoryState:
    step: str = "stories"
    story_id: str = ""
    story_json: str = ""
    stories_json: str = ""
    loaded: bool = False

    # Create form draft (copied into the story on "Generate scenario").
    idea: str = ""
    character: str = ""
    language: str = "English"
    speech_mode: str = "auto"
    scene_count: int = 4
    duration: int = 6
    aspect_ratio: str = "16:9"
    style: str = "photographic"
    camera: str = "auto"
    reference_uri: str = ""
    prompt_prefill_seen: str = ""  # last ?prompt= applied on load

    # Background job being watched.
    job_id: str = ""
    job_json: str = ""
    job_running: bool = False
    job_tasks_done: int = 0

    error: str = ""
    notice: str = ""
    confirm_delete_id: str = ""
