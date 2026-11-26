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

"""A lightbox-style dialog component."""

import mesop as me
import typing


@me.content_component
def lightbox_dialog(
    *,
    is_open: bool,
    on_close: typing.Callable[[me.ClickEvent], typing.Any],
    key: str | None = None,
):
    """Render a lightbox-style dialog that covers most of the screen."""

    # gm-lightbox lifts the page layer that holds it above the side menu
    # (extras.css); the panel and close button are styled there too.
    with me.box(
        key=key,
        classes="gm-lightbox" if is_open else "",
        style=me.Style(
            background="rgba(0, 0, 0, 0.7)",
            display="flex" if is_open else "none",
            align_items="center",
            justify_content="center",
            height="100%",
            left=0,
            top=0,
            position="fixed",
            width="100%",
            z_index=1000,
        ),
    ):
        with me.box(classes="gm-lightbox-panel"):
            with me.box(classes="gm-lightbox-close"):
                with me.content_button(on_click=on_close, type="icon"):
                    me.icon("close")

            # Slot for the main content, with padding and scrolling
            with me.box(classes="gm-lightbox-body"):
                me.slot()
