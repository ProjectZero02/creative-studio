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
"""Project page (/project?id=<id>): one folder of Home chats.

The project's name (click to rename), a New chat button, its chats and
every picture, video and sound made in them. The body is <gm-project-view>
(components/project_view), which reads GET /api/projects/{id}.
"""

import mesop as me

from components.page_scaffold import page_frame, page_scaffold
from components.project_view.project_view import project_view


@me.page(
    path="/project",
    title="Project | Creative Studio",
    security_policy=me.SecurityPolicy(dangerously_disable_trusted_types=True),
)
def page():
    project_id = str(me.query_params.get("id") or "")[:64]
    with page_scaffold(page_name="project"):  # pylint: disable=not-context-manager
        with page_frame():  # pylint: disable=not-context-manager
            project_view(project_id=project_id)
