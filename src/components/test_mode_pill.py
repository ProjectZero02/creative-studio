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
"""The green Test Mode pill under a page title, and the shared switch.

Shown only while Test Mode is on for the signed-in person. Hovering (or
focusing) the pill opens a small card with a one-line description and the
switch to turn it off. Styles: ``.gm-testmode*`` in assets/ui/studio.src.css.
"""

from __future__ import annotations

import mesop as me

from common import test_mode
from common.i18n import tr
from common.verified_identity import AUTH_MODE_SESSION, auth_mode
from state.state import AppState


def is_admin() -> bool:
    """Admins (or everyone, without session sign-in, as in Settings)."""
    return auth_mode() != AUTH_MODE_SESSION or me.state(AppState).user_role == "admin"


def is_on() -> bool:
    return test_mode.is_on_for(me.state(AppState).user_email)


def can_switch() -> bool:
    """Only admins switch it, and never in a local mock run (always on)."""
    return is_admin() and not test_mode.forced()


def on_test_mode_toggle(e: me.SlideToggleChangeEvent):  # pylint: disable=unused-argument
    """Turn Test Mode on or off for the signed-in admin."""
    if not can_switch():
        yield
        return
    email = me.state(AppState).user_email
    test_mode.set_for(email, not test_mode.is_on_for(email))
    yield


def description() -> str:
    if test_mode.forced():
        return tr(
            "testmode.desc_local",
            "This local run never calls the cloud. Generating gives placeholder media.",
        )
    return tr(
        "testmode.desc",
        "Browse and edit as usual. Generating shows placeholders or is "
        "paused, so nothing costs money.",
    )


def test_mode_pill() -> None:
    """The pill, when Test Mode is on for this person."""
    if not is_on():
        return
    with me.box(classes="gm-testmode"):
        with me.box(classes="gm-testmode-pill"):
            me.icon("science", style=me.Style(font_size=16, width=16, height=16))
            me.text(tr("testmode.label", "Test Mode"))
        with me.box(classes="gm-testmode-card"):
            with me.box(classes="gm-testmode-desc"):
                me.text(description())
            if can_switch():
                with me.box(classes="gm-testmode-row"):
                    with me.box(classes="gm-testmode-row-label"):
                        me.text(tr("testmode.switch", "Test Mode"))
                    me.slide_toggle(
                        checked=True,
                        on_change=on_test_mode_toggle,
                        key="testmode-pill-toggle",
                    )
