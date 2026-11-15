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
"""Python API for the <capability-card> web component (home page cards)."""

import typing

import mesop as me


@me.web_component(path="./capability_card.js")
def capability_card(
    *,
    label: str,
    route: str,
    description: str = "",
    icon: str = "",
    icon_family: str = "",
    mode: str = "",
    video_url: str = "",
    video_object_position: str = "center",
    size: str = "media",
    on_click: typing.Callable[[me.WebEvent], None] | None = None,
    key: str | None = None,
):
    """A card that links to one capability. `size` is "media" or "compact"."""
    return me.insert_web_component(
        key=key,
        name="capability-card",
        properties={
            "label": label,
            "route": route,
            "description": description,
            "icon": icon,
            "iconFamily": icon_family,
            "mode": mode,
            "videoUrl": video_url,
            "videoObjectPosition": video_object_position,
            "size": size,
        },
        events={"clickEvent": on_click},
    )
