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
"""Shared pieces for the industry demo pages (Fashion, Product 360, Interiors, Brand kit).

Each demo is one simple flow: a centred hero, a numbered step indicator, the
page's own inputs in cards, and the shared progress card while a model runs.
Styles live in assets/ui/demos.css (load it with ``DEMO_STYLESHEETS``).
"""

import html
import typing

import mesop as me

from common.i18n import tx

from components.generation_progress.generation_progress import (
    generation_progress_card,
)

DEMO_STYLESHEETS = ["/ui/demos.css"]


def ctext(text: str, cls: str) -> None:
    """Text inside a box with a CSS class (leaf components take no classes)."""
    with me.box(classes=cls):
        me.text(text)


def cicon(name: str, cls: str) -> None:
    """An icon inside a box with a CSS class."""
    with me.box(classes=cls):
        me.icon(name)


def demo_card_head(number: str, title: str, hint: str = "") -> None:
    """Numbered card heading used by the workflow pages.

    ``number`` and ``hint`` may be "". Keep a hint only for what a good input
    looks like; skip it when the title already says it.
    """
    with me.box(classes="gm-demo-card-head"):
        if number:
            ctext(number, "gm-demo-card-num")
        with me.box(classes="gm-demo-card-titles"):
            ctext(title, "gm-demo-card-title")
            if hint:
                ctext(hint, "gm-demo-card-hint")


def demo_upload_button(
    label: str,
    on_upload: typing.Callable[[me.UploadEvent], typing.Any],
    *,
    key: str,
    disabled: bool = False,
    accepted_file_types: list[str] | None = None,
) -> None:
    """Upload button with an icon, the same look as ``From library``.

    Put it in a ``gm-demo-actions`` row, which gives every button there the
    same width and height (assets/ui/demos.css).
    """
    with me.content_uploader(
        on_upload=on_upload,
        accepted_file_types=accepted_file_types
        or ["image/jpeg", "image/png", "image/webp"],
        type="stroked",
        key=key,
        disabled=disabled,
    ):
        with me.box(classes="gm-btn-label"):
            me.icon("upload")
            me.text(label)


@me.component
def demo_steps(steps: list[str], current: int):
    """Numbered steps. `current` is 1-based; earlier steps show as done.

    Pass ``current=len(steps) + 1`` to show every step as done.
    """
    items = []
    for i, label in enumerate(steps, start=1):
        if i < current:
            cls, mark, note = "is-done", "&#10003;", " (done)"
        elif i == current:
            cls, mark, note = "is-current", str(i), " (current step)"
        else:
            cls, mark, note = "is-next", str(i), ""
        current_attr = ' aria-current="step"' if i == current else ""
        items.append(
            f'<li class="gm-step {cls}"{current_attr}>'
            f'<span class="gm-step-num" aria-hidden="true">{mark}</span>'
            f'<span class="gm-step-label">{html.escape(label)}'
            f'<span class="gm-sr-only">{note}</span></span></li>'
        )
    with me.box(classes="gm-steps-wrap"):
        me.html(
            '<ol class="gm-steps" aria-label="Steps">' + "".join(items) + "</ol>",
            mode="sanitized",
        )


@me.component
def demo_segmented(
    value: str,
    options: list[me.ButtonToggleButton],
    on_change: typing.Callable[[me.ButtonToggleChangeEvent], typing.Any],
    key: str = "",
):
    """A two- or three-option pill switch in the studio style."""
    with me.box(classes="gm-segmented gm-demo-switch"):
        me.button_toggle(
            key=key or None,
            value=value,
            buttons=options,
            multiple=False,
            hide_selection_indicator=True,
            on_change=on_change,
        )


@me.component
def demo_mode_switch(
    value: str,
    options: list[tuple[str, str, str]],
    on_click: typing.Callable[[me.ClickEvent], typing.Any],
    key: str,
):
    """A pill switch whose options say what they do on hover.

    `options` are (value, label, tip). Each option's key is
    f"{key}--{value}", so the page reads the picked value with
    ``mode_switch_value(e)``.
    """
    with me.box(classes="gm-seg"):
        for opt_value, label, tip in options:
            on = opt_value == value
            with me.box(classes="gm-seg-opt is-on" if on else "gm-seg-opt"):
                with me.tooltip(message=tx(tip), position="below", show_delay_ms=300):
                    me.button(tx(label), key=f"{key}--{opt_value}", on_click=on_click)


def mode_switch_value(e: me.ClickEvent) -> str:
    """The option value picked in a demo_mode_switch."""
    return (e.key or "").rsplit("--", 1)[-1]


@me.component
def demo_alert(message: str, on_dismiss: typing.Callable[[me.ClickEvent], typing.Any]):
    """A plain inline error line with a close button."""
    with me.box(classes="gm-demo-alert"):
        me.icon("error_outline")
        with me.box(classes="gm-demo-alert-text"):
            me.text(message)
        with me.content_button(type="icon", on_click=on_dismiss):
            me.icon("close")
            with me.box(classes="gm-sr-only"):
                me.text("Dismiss")


def demo_progress(
    *,
    stages: list[str],
    current: int,
    status: str,
    run_id: str,
    message: str = "",
    typical_seconds: int = 0,
    work_stage: int = -1,
    aspect: str = "1:1",
    count: int = 1,
    media_label: str = "image",
    on_retry: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    on_dismiss: typing.Callable[[me.WebEvent], typing.Any] | None = None,
):
    """The shared progress card from plain values (no progress fields needed).

    Pages whose upstream handlers only flip ``is_generating`` flags derive the
    stage list and index from those flags and call this, so the handlers stay
    untouched.
    """
    if status not in ("running", "error"):
        return
    with me.box(classes="gm-progress-slot"):
        generation_progress_card(
            key="gm_generation_progress",
            stages=list(stages),
            current=current,
            status=status,
            run_id=run_id,
            typical_seconds=typical_seconds,
            work_stage=work_stage,
            message=message,
            aspect=aspect,
            count=count,
            media_label=media_label,
            on_retry=on_retry,
            on_dismiss=on_dismiss,
        )
