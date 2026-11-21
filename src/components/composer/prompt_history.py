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
"""The composer's history button: pick one of your recent prompts.

The composer shows the button when a page passes ``history=<page key>``.
Picking a prompt puts it back in the page's prompt field through
``services.page_forms.fill``, the same path the Live agent uses, so the
textarea re-mounts with the text.
"""

from __future__ import annotations

import json

import mesop as me

from common import prompt_history
from state.state import AppState


@me.stateclass
class PromptHistoryState:
    open_for: str = ""  # page key whose list is open
    prompts_json: str = "[]"


def _prompts(s: PromptHistoryState) -> list[str]:
    try:
        return list(json.loads(s.prompts_json or "[]"))
    except ValueError:
        return []


def on_history_click(e: me.ClickEvent):
    s = me.state(PromptHistoryState)
    page = e.key or ""
    if s.open_for == page:
        s.open_for = ""
        return
    owner = me.state(AppState).user_email
    s.prompts_json = json.dumps(prompt_history.recent(owner, page))
    s.open_for = page


def on_history_close(e: me.ClickEvent):  # pylint: disable=unused-argument
    me.state(PromptHistoryState).open_for = ""


def on_history_pick(e: me.ClickEvent):
    from services import page_forms

    s = me.state(PromptHistoryState)
    page = s.open_for
    try:
        index = int(e.key.rsplit("-", 1)[-1])
        text = _prompts(s)[index]
    except (ValueError, IndexError):
        return
    page_forms.fill(page, {prompt_history.field_for(page): text}, me.state)
    s.open_for = ""


def history_panel(page: str) -> None:
    """The list under the prompt, shown while it is open for this page."""
    s = me.state(PromptHistoryState)
    if s.open_for != page:
        return
    prompts = _prompts(s)
    with me.box(classes="gm-history"):
        with me.box(classes="gm-history-head"):
            me.text("Recent prompts")
            me.button("Close", on_click=on_history_close, key=f"hist-close-{page}")
        if not prompts:
            me.text("Nothing yet. Your prompts show up here after you generate.",
                    classes="gm-history-empty")
        for i, text in enumerate(prompts):
            with me.box(
                classes="gm-history-item",
                on_click=on_history_pick,
                key=f"hist-{page}-{i}",
            ):
                me.text(text)
