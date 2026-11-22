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

Layout (like ChatGPT, Gemini and Claude): optional reference tiles on top, the
prompt textarea, then one row: a single "+" add menu at the bottom left
(`render_add`, usually `composer_add_menu`), the page's chips (passed as
children), and on the right Live, the dictation mic and a round send
button. See docs/COMPOSER_FORMAT_PLAN.md.

The right side holds only Live (voice), Dictate and Send. Enhance happens on
send (common/auto_enhance.py) and Up/Down recall recent prompts
(prompt_keys.js), so pages may still pass `on_enhance`, `on_clear` and
`history` without a button being drawn for them.

Enter generates, Shift+Enter adds a new line. Every icon button has a
screen-reader name and a tooltip; buttons are 44px tall on phones (CSS in
assets/ui/studio.src.css, `.gm-composer`).
"""

import typing

import mesop as me

from common.i18n import t, tx
from components.live_agent.live_agent import live_call_button
from config.default import Default

ENTER = me.Shortcut(key="Enter")


@me.web_component(path="./prompt_keys.js")
def composer_prompt_keys(*, page: str, key: str | None = None):
    """Up/Down arrows in the prompt box step through your recent prompts."""
    return me.insert_web_component(
        key=key, name="gm-prompt-keys", properties={"page": page}
    )


@me.web_component(path="./dictation.js")
def composer_dictation(*, key: str | None = None):
    """Mic button: browser speech-to-text into the composer's prompt box."""
    return me.insert_web_component(
        key=key,
        name="gm-dictation",
        properties={
            "label": t("composer.dictate"),
            "stopLabel": t("composer.dictate_stop"),
        },
    )


@me.component
def composer_add_menu(
    *,
    on_upload: typing.Callable[[me.UploadEvent], typing.Any],
    on_library_select: typing.Callable[..., typing.Any] | None = None,
    accepted_file_types: list[str] | None = None,
    multiple: bool = True,
    disabled: bool = False,
    key: str = "composer_add",
    library_media_type: list[str] | None = None,
    label: str | None = None,
):
    """One "+" button that opens Upload / Choose from library.

    The menu is pure CSS (shown while focus is inside it), so the file picker
    and the library dialog keep working without extra page state.
    """
    from components.library.library_chooser_button import (  # pylint: disable=import-outside-toplevel
        library_chooser_button,
    )

    label = tx(label) if label else t("composer.add")
    with me.box(classes="gm-add-menu" + (" gm-disabled" if disabled else "")):
        with me.box(classes="gm-composer-btn gm-add-trigger"):
            with (
                me.tooltip(message=label),
                me.content_button(type="icon", disabled=disabled, key=f"{key}_open"),
            ):
                me.icon("add")
                with me.box(classes="gm-sr-only"):
                    me.text(label)
        with me.box(classes="gm-add-pop"):
            with me.box(classes="gm-add-item"):
                with me.content_uploader(
                    on_upload=on_upload,
                    multiple=multiple,
                    accepted_file_types=accepted_file_types
                    or ["image/jpeg", "image/png", "image/webp"],
                    disabled=disabled,
                    type="flat",
                    key=f"{key}_upload",
                ):
                    with me.box(classes="gm-btn-row"):
                        me.icon("upload")
                        me.text(t("composer.upload"))
            if on_library_select:
                with me.box(classes="gm-add-item"):
                    library_chooser_button(
                        on_library_select=on_library_select,
                        button_label=t("composer.library"),
                        button_type="flat",
                        media_type=library_media_type,
                        disabled=disabled,
                        key=f"{key}_library",
                    )


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
    placeholder: str | None = None,
    on_enhance: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
    enhance_label: str | None = None,
    busy: bool = False,
    enhancing: bool = False,
    send_label: str | None = None,
    textarea_key: str = "composer_prompt",
    hint: str | None = None,
    render_top: typing.Callable[[], None] | None = None,
    render_add: typing.Callable[[], None] | None = None,
    dictation: bool = True,
    on_clear: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
    clear_label: str | None = None,
    notice: str = "",
    on_notice_undo: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
    history: str = "",
):
    """Render the composer card. Children are rendered in the chip row.

    `on_submit` receives the textarea value on Enter, so the page can store it
    and start generating in one step. `render_top` draws reference images
    above the prompt (uploads, first/last frame...). `render_add` draws the
    "+" add menu at the bottom left. `dictation` shows the mic next to send.

    Text left as None uses the shared wording in the current language; English
    text a page passes is translated when common/i18n.py knows it (`tx`).
    No hint line shows unless a page passes `hint`.

    `notice` is a one-line status under the prompt (for example the settings
    read from the typed prompt); `on_notice_undo` adds an Undo button to it.
    Both are off by default, so pages that don't pass them look the same.

    `history` is the page's key in services/page_forms.py; Up/Down in the box
    then step through your recent prompts in this studio (prompt_keys.js).
    """
    placeholder = (
        tx(placeholder) if placeholder is not None else t("composer.placeholder")
    )
    # on_enhance, enhancing, on_clear and their labels are accepted for older
    # callers; Enhance now runs on send and Clear is gone (see module doc).
    del on_enhance, enhance_label, enhancing, on_clear, clear_label
    send_label = tx(send_label) if send_label is not None else t("composer.send")
    hint = tx(hint) if hint else ""
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
            if render_add:
                with me.box(classes="gm-composer-add"):
                    render_add()
            with me.box(classes="gm-composer-tools"):
                me.slot()
            with me.box(classes="gm-composer-actions"):
                if Default.LIVE_AGENT_ENABLED:
                    with me.box(classes="gm-composer-live"):
                        live_call_button(compact=True, key="composer_live")
                if dictation:
                    with me.box(classes="gm-composer-mic"):
                        composer_dictation(key="composer_mic")
                if busy:
                    with me.box(
                        classes="gm-composer-btn gm-composer-send gm-composer-wait",
                    ):
                        me.progress_spinner(diameter=22, stroke_width=3)
                        with me.box(classes="gm-sr-only"):
                            me.text(t("composer.generating"))
                else:
                    composer_icon_button(
                        icon="arrow_upward",
                        label=send_label,
                        on_click=on_click_send,
                        primary=True,
                    )
        if history:
            composer_prompt_keys(page=history, key=f"keys-{history}")
        if notice:
            composer_notice(text=notice, on_undo=on_notice_undo)
        elif hint:
            with me.box(classes="gm-composer-hint"):
                me.text(hint)


@me.component
def composer_notice(
    *,
    text: str,
    on_undo: typing.Callable[[me.ClickEvent], typing.Any] | None = None,
):
    """A small status chip under the prompt, with an optional Undo button."""
    with me.box(classes="gm-composer-notice"):
        with me.box(classes="gm-composer-notice-icon"):
            me.icon("tune")
        with me.box(classes="gm-composer-notice-text"):
            me.text(text)
        if on_undo:
            with me.tooltip(message=t("composer.undo_hint")):
                me.button(
                    t("composer.undo"),
                    on_click=on_undo,
                    type="stroked",
                    key="composer_notice_undo",
                )


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
                        me.text(t("composer.remove", label=label))
