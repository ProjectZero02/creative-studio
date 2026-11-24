# Copyright 2024 Google LLC
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
"""Home: one chat that makes anything.

The headline, a line whose media words open each studio, and one prompt box
(components/home_chat). Whatever you type goes to the studio chat
(services/studio_chat.py), which answers in text or starts the right jobs
(image, video, music, voice, film) and shows the results in the thread.
The studios stay one click away in the side menu.
"""

import mesop as me

from components.home_chat.home_chat import home_chat
from components.page_scaffold import page_frame, page_scaffold
from config.default import Default
from state.state import AppState


@me.page(
    path="/home",
    title="Creative Studio · Google Cloud",
    security_policy=me.SecurityPolicy(
        dangerously_disable_trusted_types=True,
    ),
)
def page():
    """Main Page."""
    state = me.state(AppState)
    with page_scaffold(page_name="home"):  # pylint: disable=E1129:not-context-manager
        with page_frame():  # pylint: disable=E1129:not-context-manager
            home_page_content(state)


def home_page_content(app_state: me.state):  # pylint: disable=unused-argument
    """Home page body."""
    with me.box(classes="gm-home gm-home-chat"):
        home_chat(live=Default.LIVE_AGENT_ENABLED)
