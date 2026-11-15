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
"""Prompt composer: a big rounded prompt card with settings chips inside it.

Layout (like Krea, Google Flow and Firefly): optional reference tiles on top,
the prompt textarea, then one row with the page's chips on the left (passed as
children) and the enhance + send buttons on the right.

Enter generates, Shift+Enter adds a new line. Every icon button has a
screen-reader name and a tooltip; buttons are 44px tall on phones (CSS in
assets/ui/studio.src.css, `.gm-composer`).
"""

import typing

import mesop as me

ENTER = me.Shortcut(key="Enter")


@me.component
def composer_icon_button(
    *,
    icon: str,
    label: str,
    on_click: typing.Callable[[me.ClickEvent], typing.Any],
    disabled: bool = False,
    key: str | None = None,
    primary: bool = False,
):
    """A round icon button with a tooltip and a screen-reader name."""
    with me.box(
        classes="gm-composer-btn gm-composer-send" if primary else "gm-composer-btn"
    ):
        with (
            me.tooltip(message=label),
            me.content_button(
                type="icon",
                on_click=on_click,
                disabled=disabled,
                key=key,
            ),
        ):
            me.icon(icon)
            with me.box(classes="gm-sr-only"):
                me.text(label)


@me.content_component
def composer(
    *,
    value: str,
    on_blur: typing.Callable[[me.InputBlurEvent], typing.Any],
    on_submit: typing.Callable[[me.TextareaShortcutEvent], typing.Any],
    on_click_send: typing.Callable[[me.ClickEvent], typing.Any],
    placeholder: str = "Describe what you want to create…",
    on_enhance: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
    enhance_label: str = "Enhance prompt",
    busy: bool = False,
    enhancing: bool = False,
    send_label: str = "Generate",
    textarea_key: str = "composer_prompt",
    hint: str = "Enter to generate · Shift+Enter for a new line",
    render_top: typing.Callable[[], None] | None = None,
    on_clear: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
    clear_label: str = "Clear prompt and results",
):
    """Render the composer card. Children are rendered in the chip row.

    `on_submit` receives the textarea value on Enter, so the page can store it
    and start generating in one step. `render_top` draws reference images
    above the prompt (uploads, first/last frame...).
    """
    with me.box(classes="gm-composer" + (" gm-busy" if busy else "")):
        if render_top:
            render_top()
        with me.box(classes="gm-composer-field"):
            me.native_textarea(
                key=textarea_key,
                value=value,
                placeholder=placeholder,
                autosize=True,
                min_rows=3,
                max_rows=12,
                on_blur=on_blur,
                shortcuts={ENTER: on_submit},
                style=me.Style(
                    width="100%",
                    border=me.Border.all(me.BorderSide(style="none")),
                    outline="none",
                    background="transparent",
                    color=me.theme_var("on-surface"),
                    font_size=17,
                    line_height="1.55",
                    padding=me.Padding(top=4, bottom=4, left=0, right=0),
                ),
            )
        with me.box(classes="gm-composer-bar"):
            with me.box(classes="gm-composer-tools"):
                me.slot()
            with me.box(classes="gm-composer-actions"):
                if on_clear:
                    composer_icon_button(
                        icon="restart_alt",
                        label=clear_label,
                        on_click=on_clear,
                        disabled=busy,
                    )
                if on_enhance:
                    if enhancing:
                        with me.box(
                            classes="gm-composer-btn",
                            style=me.Style(
                                display="flex",
                                align_items="center",
                                justify_content="center",
                                width=40,
                                height=40,
                            ),
                        ):
                            me.progress_spinner(diameter=20, stroke_width=3)
                    else:
                        composer_icon_button(
                            icon="auto_awesome",
                            label=enhance_label,
                            on_click=on_enhance,
                            disabled=busy,
                        )
                if busy:
                    with me.box(
                        classes="gm-composer-btn gm-composer-send gm-composer-wait",
                    ):
                        me.progress_spinner(diameter=22, stroke_width=3)
                        with me.box(classes="gm-sr-only"):
                            me.text("Generating")
                else:
                    composer_icon_button(
                        icon="arrow_upward",
                        label=send_label,
                        on_click=on_click_send,
                        primary=True,
                    )
        if hint:
            with me.box(classes="gm-composer-hint"):
                me.text(hint)


@me.component
def composer_attachment(
    *,
    src: str,
    label: str,
    index: int,
    on_remove: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
):
    """A small reference thumbnail inside the composer, with a remove button."""
    with me.box(classes="gm-attach"):
        me.image(src=src, alt=label, style=me.Style(width=64, height=64))
        if on_remove:
            with me.box(classes="gm-attach-remove"):
                with me.content_button(type="icon", on_click=on_remove, key=str(index)):
                    me.icon("close")
                    with me.box(classes="gm-sr-only"):
                        me.text(f"Remove {label}")
