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
changes. The bridge element turns the agent's "go to page" and "fill these
fields" requests into Mesop events, because navigation and page state have to
change through Mesop. It also carries the page's fillable fields (see
:mod:`services.page_forms`) and the result of the last fill.

``live_call_button`` is the large "Talk to the studio" button on the home page.
"""

import json
import logging
import typing

import mesop as me

from common.i18n import t
from config.default import Default
from services import page_forms

logger = logging.getLogger(__name__)

ALLOWED_ROUTES = {
    "/home",
    "/nano-banana",
    "/veo",
    "/lyria",
    "/voice",
    "/story",
    "/library_v2",
}
# Deep-link params each route reads: Video Studio (pages/veo.py on_veo_load)
# and Story Studio (pages/story_studio.py on_load).
ALLOWED_PARAMS = {
    "/veo": {"veo_model", "image_path"},
    "/story": {"id", "step"},
}


@me.stateclass
class LiveFormState:
    # {"id": fill request id, "changed": {...}, "refused": {...}}
    last_fill_json: str = ""


def page_fields_json(page: str) -> str:
    """The page's fillable fields with their values, for the agent."""
    try:
        return json.dumps(page_forms.snapshot(page, me.state))
    except Exception:  # never break a page over the agent's view of it
        logger.exception("Live: could not read the fields of %s", page)
        return "[]"


def on_live_action(e: me.WebEvent):
    """Requests from the voice agent: navigate (known app routes only) or
    fill fields of the page on screen (see services.page_forms)."""
    value = e.value or {}
    if value.get("action") == "fill":
        page = str(value.get("page") or "")
        fields = value.get("fields") if isinstance(value.get("fields"), dict) else {}
        try:
            result = page_forms.fill(page, fields, me.state)
        except Exception as exc:
            logger.exception("Live: fill failed on %s", page)
            result = {"changed": {}, "refused": {}, "error": str(exc)[:200]}
        st = me.state(LiveFormState)
        st.last_fill_json = json.dumps({"id": str(value.get("id") or ""), **result})
    elif value.get("action") == "navigate":
        route = str(value.get("page") or "")
        raw = value.get("params") or {}
        allowed = ALLOWED_PARAMS.get(route, set())
        params = {
            k: str(v)[:500]
            for k, v in (raw.items() if isinstance(raw, dict) else [])
            if k in allowed and v
        }
        if route in ALLOWED_ROUTES:
            if route == "/story" and params.get("id"):
                # Story Studio reads ?id= only on its first load, so open the
                # story (and its step) in the page state directly.
                from pages import story_studio

                story_studio.open_for_agent(params["id"], params.get("step", ""))
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
        "fill": t("live.fill", "Fill only"),
        "act": t("live.act", "Do it for me"),
        "modeHint": t(
            "live.mode_hint",
            "Fill only: the agent fills the page and you press Generate. "
            "Do it for me: it also runs the jobs.",
        ),
        "avatar": t("live.avatar", "Avatar"),
        "avatarHint": t(
            "live.avatar_hint",
            "Show a talking presenter instead of voice only. Uses much more of the Live quota.",
        ),
        "avatarNoSupport": t(
            "live.avatar_no_support", "This browser cannot play the avatar, so the call is voice only."
        ),
        # Empty when the server has no avatar: the switch is then hidden.
        "avatarName": Default.LIVE_AVATAR,
    }


@me.web_component(path="./live_agent.js")
def live_agent_bridge(
    *,
    page: str = "",
    on_action: typing.Callable[[me.WebEvent], typing.Any] = on_live_action,
    key: str | None = "live-agent-bridge",
):
    """Invisible bridge, one per page (rendered by the page scaffold).
    `page` is the scaffold's page name, which picks the fillable fields."""
    return me.insert_web_component(
        key=key,
        name="live-agent-bridge",
        properties={
            "stringsJson": json.dumps(_strings()),
            "page": page,
            "fieldsJson": page_fields_json(page),
            "lastFillJson": me.state(LiveFormState).last_fill_json,
        },
        events={"actionEvent": on_action},
    )


@me.web_component(path="./live_agent.js")
def live_call_button(*, key: str | None = "live-call-button"):
    """Large call button for the home page hero."""
    return me.insert_web_component(
        key=key,
        name="live-call-button",
        properties={"stringsJson": json.dumps(_strings())},
    )
