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
"""Tell the person a generation finished, even from another tab.

:func:`notify` bumps a small state the page scaffold hands to the
``<gm-notify>`` web component (components/notify/notify.js). The browser
shows a system notification only when the person switched it on in the
avatar menu, allowed notifications, and the tab is in the background; the
switch lives in the browser (localStorage), not on the server.

It must run in a page handler (it uses Mesop state). Background jobs are
reported from the page's poll (Story Studio's on_tick).
"""

from __future__ import annotations

import logging
import time

import mesop as me

logger = logging.getLogger(__name__)

# page_name (page_scaffold) -> what was made
KINDS = {
    "veo": "video",
    "gemini-omni": "video",
    "gemini_image_generation": "image",
    "banana-studio": "image",
    "fashion": "image",
    "starter-pack": "image",
    "vto": "image",
    "lyria": "music",
    "voice": "audio",
    "gemini-tts": "audio",
    "chirp_3hd": "audio",
    "story": "film",
}


def notify(title: str, body: str = "") -> None:
    try:
        from state.notify_state import NotifyState

        s = me.state(NotifyState)
        # A time stamp, not a counter: it keeps going up after a page reload.
        s.seq = max(s.seq + 1, time.time_ns() // 1_000_000)
        s.title = title[:80]
        s.body = body[:200]
    except Exception:  # never break a generation over a notification
        logger.debug("notify: no page state here", exc_info=True)


def _kind() -> str:
    try:
        from state.state import AppState

        return KINDS.get(me.state(AppState).current_page, "")
    except Exception:
        return ""


def generation_done() -> None:
    kind = _kind()
    notify("Ready", f"Your {kind} is ready." if kind else "Your generation is ready.")


def generation_failed(message: str = "") -> None:
    kind = _kind()
    notify(
        "Something went wrong",
        message or (f"Your {kind} could not be made." if kind else "The generation failed."),
    )
