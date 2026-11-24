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
"""Page not found: shown for any path that is not a page (common/not_found.py)."""

import mesop as me

from common.not_found import NOT_FOUND_PATH
from components.page_scaffold import page_frame, page_scaffold


def on_home(e: me.ClickEvent) -> None:  # pylint: disable=unused-argument
    me.navigate("/home")


def on_library(e: me.ClickEvent) -> None:  # pylint: disable=unused-argument
    me.navigate("/library_v2")


@me.page(path=NOT_FOUND_PATH, title="Page not found | Creative Studio")
def page() -> None:
    with page_scaffold(page_name="not_found"):  # pylint: disable=not-context-manager
        with page_frame():  # pylint: disable=not-context-manager
            with me.box(classes="gm-empty gm-not-found"):
                with me.box(classes="gm-empty-icon"):
                    me.icon("explore_off")
                with me.box(classes="gm-not-found-title"):
                    me.text("Page not found")
                with me.box(classes="gm-not-found-text"):
                    me.text("This link doesn't lead to a page.")
                with me.box(classes="gm-not-found-actions"):
                    me.button("Go home", type="flat", on_click=on_home)
                    me.button("Library", on_click=on_library)
