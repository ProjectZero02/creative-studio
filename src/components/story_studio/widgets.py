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


@me.web_component(path="./story_stepper.js")
def story_stepper(
    *,
    steps: list[dict],
    on_select: typing.Callable[[me.WebEvent], None],
    key: str | None = None,
):
    """Horizontal stepper. Each step: {id, label, state, enabled}."""
    return me.insert_web_component(
        key=key,
        name="story-stepper",
        properties={"stepsJson": json.dumps(steps)},
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
    key: str | None = None,
):
    """Video editor: preview plus video, voice, music and title tracks.

    `media` maps each clip's stored URI to a browser URL. `on_change` gets
    {"timeline": json} after every finished edit, `on_point` {"time": s}
    where the viewer paused or scrubbed to.
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
            "aspect": aspect,
            "busy": busy,
        },
        events=events,
    )
