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
"""Python API for the Story Studio web components."""

import json
import typing

import mesop as me

from common.i18n import tx

# English text the web components show, sent to them translated (see _T in
# each .js file). Templates use {0}, {1} for numbers and names.
_STEPPER_TEXT = ("Film steps", "Step {0}: {1}", "Step {0}: {1} (done)")
_COMPARE_TEXT = ("Pause both", "Play both", "Position")
_TIMELINE_TEXT = (
    "Video", "Voice", "Music", "Titles", "Title", "Clip", "Scene {0}",
    "New title", "{0} to {1}", "{0} speech", "{0} speech (muted)",
    "Speech recorded in {0}. It moves with the shot; select it to change its volume.",
    "Clip settings", "Select a clip to edit it", "{0} s", "Text", "Position",
    "Top", "Center", "Bottom", "Size", "Small", "Medium", "Large", "Huge",
    "Volume", "Clip sound", "Transition in", "Cut", "Crossfade 0.25 s",
    "Crossfade 0.5 s", "Crossfade 1 s", "Dip to black", "Earlier", "Later",
    "Lower under speech", "Updating preview", "Preview not updated",
    "No timeline yet.", "Preview", "Back to start", "Pause", "Play",
    "Play or pause (Space)", "Exit full screen", "Full screen", "Full screen (F)",
    "Edit", "Split at playhead (S)", "Split", "Delete (Del)", "Delete",
    "Add a title at the playhead", "Add title", "Undo (Ctrl+Z)", "Undo",
    "Redo (Ctrl+Shift+Z)", "Redo", "Zoom out", "Zoom", "Zoom in", "Timeline",
    "Video track", "Voice track", "Music track", "Titles track",
)


def strings_json(texts: typing.Iterable[str]) -> str:
    """{english: translation} for the texts that change in the current
    language ("{}" in English), for a web component's stringsJson."""
    out = {}
    for text in texts:
        local = tx(text)
        if local != text:
            out[text] = local
    return json.dumps(out, ensure_ascii=False)


def tx_dots(text: str) -> str:
    """tx() for a line of parts joined by " · " ("4 takes · 32s"): the whole
    line if it has a translation, else each part on its own."""
    if not text:
        return text
    local = tx(text)
    if local != text or " · " not in text:
        return local
    return " · ".join(tx(part) for part in text.split(" · "))


@me.web_component(path="./film_compare.js")
def film_compare(
    *,
    left_url: str,
    right_url: str,
    left_label: str = "Before",
    right_label: str = "Now",
    portrait: bool = False,
    key: str | None = None,
):
    """Two films side by side, played and scrubbed together."""
    return me.insert_web_component(
        key=key,
        name="gm-film-compare",
        properties={
            "leftUrl": left_url,
            "rightUrl": right_url,
            "leftLabel": tx_dots(left_label),
            "rightLabel": tx(right_label),
            "portrait": portrait,
            "stringsJson": strings_json(_COMPARE_TEXT),
        },
    )


@me.web_component(path="./story_stepper.js")
def story_stepper(
    *,
    steps: list[dict],
    on_select: typing.Callable[[me.WebEvent], None],
    key: str | None = None,
):
    """Horizontal stepper. Each step: {id, label, state, enabled}."""
    steps = [{**step, "label": tx(step.get("label", ""))} for step in steps]
    return me.insert_web_component(
        key=key,
        name="story-stepper",
        properties={
            "stepsJson": json.dumps(steps, ensure_ascii=False),
            "stringsJson": strings_json(_STEPPER_TEXT),
        },
        events={"selectEvent": on_select},
    )


@me.web_component(path="./story_style_picker.js")
def story_style_picker(
    *,
    options: list[dict],
    value: str,
    on_change: typing.Callable[[me.WebEvent], None],
    label: str = "Style",
    key: str | None = None,
):
    """Image-tile radio group. Each option: {id, label, src}."""
    return me.insert_web_component(
        key=key,
        name="story-style-picker",
        properties={"optionsJson": json.dumps(options), "value": value, "label": label},
        events={"changeEvent": on_change},
    )


@me.web_component(path="./story_idea_watch.js")
def story_idea_watch(
    *,
    on_idea: typing.Callable[[me.WebEvent], None],
    selector: str = ".ss-idea-field",
    delay_ms: int = 700,
    key: str | None = None,
):
    """Invisible: fires `on_idea` ({value}) when typing pauses in the field
    inside `selector`."""
    return me.insert_web_component(
        key=key,
        name="story-idea-watch",
        properties={"selector": selector, "delay": delay_ms},
        events={"ideaEvent": on_idea},
    )


@me.web_component(path="./story_ticker.js")
def story_ticker(
    *,
    active: bool,
    on_tick: typing.Callable[[me.WebEvent], None],
    interval_ms: int = 1000,
    key: str | None = None,
):
    """Invisible poller that fires `on_tick` while `active`."""
    return me.insert_web_component(
        key=key,
        name="story-ticker",
        properties={"active": active, "interval": interval_ms},
        events={"tickEvent": on_tick},
    )


@me.web_component(path="./story_timeline.js")
def story_timeline(
    *,
    timeline_json: str,
    media: dict[str, str],
    aspect: str,
    busy: bool,
    on_change: typing.Callable[[me.WebEvent], None],
    on_point: typing.Callable[[me.WebEvent], None] | None = None,
    preview_url: str = "",
    preview_state: str = "film",
    key: str | None = None,
):
    """Video editor: a player for the rendered preview, plus video, voice,
    music and title tracks.

    `media` maps "thumb:<scene>" to a browser URL of that scene's frame.
    `preview_url` is the rendered film or proxy of this exact timeline;
    `preview_state` is "film", "ready", "making" or "failed" (see
    story_jobs.preview). `on_change` gets {"timeline": json} after every
    finished edit, `on_point` {"time": s} where the viewer paused or
    scrubbed to.
    """
    events = {"changeEvent": on_change}
    if on_point is not None:
        events["pointEvent"] = on_point
    return me.insert_web_component(
        key=key,
        name="story-timeline",
        properties={
            "timelineJson": timeline_json,
            "mediaJson": json.dumps(media),
            "previewUrl": preview_url,
            "previewState": preview_state,
            "aspect": aspect,
            "busy": busy,
            "stringsJson": strings_json(_TIMELINE_TEXT),
        },
        events=events,
    )
