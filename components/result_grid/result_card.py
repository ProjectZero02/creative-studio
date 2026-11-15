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
"""Python API for <gm-result-card> and a simple results grid wrapper."""

import typing

import mesop as me


def card_action(e: me.WebEvent) -> tuple[str, str]:
    """Return (action, src) from a result card event."""
    value = e.value if isinstance(e.value, dict) else {}
    return str(value.get("action", "")), str(value.get("src", ""))


@me.web_component(path="./result_card.js")
def result_card(
    *,
    src: str,
    kind: str = "image",
    prompt: str = "",
    meta: str = "",
    aspect: str = "1:1",
    actions: str = "open,download,reuse",
    selected: bool = False,
    on_action: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    key: str | None = None,
):
    """One generated item. `actions` is a comma list of:
    open, download, reuse, edit, video (image to video), extend (video),
    edit_video and upscale (video, Gemini Omni).
    """
    return me.insert_web_component(
        key=key,
        name="gm-result-card",
        properties={
            "mediaUrl": src,
            "kind": kind,
            "prompt": prompt,
            "meta": meta,
            "aspect": aspect,
            "actions": actions,
            "selected": selected,
        },
        events={"actionEvent": on_action},
    )


@me.component
def empty_results(icon: str, title: str, body: str = ""):
    """A calm empty state for the results area."""
    with me.box(classes="gm-empty"):
        with me.box(classes="gm-empty-icon"):
            me.icon(icon)
        me.text(title, style=me.Style(font_size=16, font_weight=500))
        if body:
            me.text(
                body,
                style=me.Style(font_size=14, color=me.theme_var("on-surface-variant")),
            )


@me.content_component
def result_grid(*, title: str = "Recent", count: int = 0, wide: bool = False):
    """A titled responsive grid; put result_card(...) calls inside."""
    with me.box(classes="gm-results"):
        with me.box(classes="gm-results-head"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## " + title)
            if count:
                me.text(
                    f"{count} item{'s' if count != 1 else ''} this session",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
        with me.box(classes="gm-results-grid" + (" gm-wide" if wide else "")):
            me.slot()
