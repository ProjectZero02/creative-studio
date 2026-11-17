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
"""Live voice agent: the browser side.

``live_agent_bridge`` sits in the page scaffold (every page). Its JavaScript
creates one ``window.gmLive`` controller attached to ``document.body``, outside
Mesop's render tree, so the call, the job tray and the overlays survive page
changes. The bridge element only turns the agent's "go to page" requests into a
Mesop event, because navigation has to happen through ``me.navigate``.

``live_call_button`` is the large "Talk to the studio" button on the home page.
"""

import typing

import mesop as me

from common.i18n import t

ALLOWED_ROUTES = {
    "/home",
    "/nano-banana",
    "/veo",
    "/lyria",
    "/voice",
    "/story",
    "/library_v2",
}
# Video Studio deep-link params (pages/veo.py on_veo_load).
ALLOWED_PARAMS = {"veo_model", "image_path"}


def on_live_action(e: me.WebEvent):
    """Navigation requested by the voice agent (only known app routes)."""
    value = e.value or {}
    if value.get("action") == "navigate":
        route = str(value.get("page") or "")
        raw = value.get("params") or {}
        params = {
            k: str(v)[:500]
            for k, v in (raw.items() if isinstance(raw, dict) else [])
            if k in ALLOWED_PARAMS and v
        }
        if route in ALLOWED_ROUTES:
            me.navigate(route, query_params=params or None)
    yield


def _strings() -> dict:
    return {
        "talk": t("live.talk", "Talk to the studio"),
        "hint": t(
            "live.hint", "Ask for images and videos by voice. Jobs run side by side."
        ),
        "connecting": t("live.connecting", "Connecting…"),
        "listening": t("live.listening", "Listening"),
        "speaking": t("live.speaking", "Speaking"),
        "offline": t("live.offline", "Offline mode (typed)"),
        "type": t("live.type", "Type a request…"),
        "mute": t("live.mute", "Mute microphone"),
        "unmute": t("live.unmute", "Unmute microphone"),
        "hangup": t("live.hangup", "End call"),
        "jobs": t("live.jobs", "Jobs"),
        "download": t("live.download", "Download"),
        "close": t("live.close", "Close"),
        "nomic": t("live.nomic", "No microphone access. You can still type."),
    }


@me.web_component(path="./live_agent.js")
def live_agent_bridge(
    *,
    on_action: typing.Callable[[me.WebEvent], typing.Any] = on_live_action,
    key: str | None = "live-agent-bridge",
):
    """Invisible bridge, one per page (rendered by the page scaffold)."""
    import json

    return me.insert_web_component(
        key=key,
        name="live-agent-bridge",
        properties={"stringsJson": json.dumps(_strings())},
        events={"actionEvent": on_action},
    )


@me.web_component(path="./live_agent.js")
def live_call_button(*, key: str | None = "live-call-button"):
    """Large call button for the home page hero."""
    import json

    return me.insert_web_component(
        key=key,
        name="live-call-button",
        properties={"stringsJson": json.dumps(_strings())},
    )
