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
"""Step-by-step generation feedback, shared by any generation page.

A page keeps five plain fields in its state (see `ProgressFields`) and moves
them with the helpers below from inside its generator handler, yielding after
each call so the browser shows the new stage:

    progress_start(state, ["Preparing", "Sending to Veo", "Generating", "Saving", "Done"])
    yield
    progress_step(state, 2)
    yield
    ...
    progress_done(state)   # or progress_fail(state, "what went wrong")
    yield

`generation_progress(...)` renders the card; it only reads those fields.
"""

import json
import time
import typing

import mesop as me

from common.i18n import current_lang, t, tl, tx_lang

PROGRESS_FIELDS = (
    "progress_stages",
    "progress_stage",
    "progress_status",
    "progress_run_id",
    "progress_error",
)


class ProgressFields(typing.Protocol):
    """The state fields the helpers read and write."""

    progress_stages: list[str]
    progress_stage: int
    progress_status: str  # "" | "running" | "error" | "done"
    progress_run_id: str
    progress_error: str


def progress_start(state: ProgressFields, stages: list[str]) -> None:
    """Begin a new run at stage 0."""
    state.progress_stages = list(stages)
    state.progress_stage = 0
    state.progress_status = "running"
    state.progress_run_id = str(time.time_ns())
    state.progress_error = ""


def progress_step(state: ProgressFields, stage: int) -> None:
    """Move to `stage` (an index into the stage list)."""
    if state.progress_status == "running":
        state.progress_stage = max(0, min(stage, len(state.progress_stages) - 1))


def progress_done(state: ProgressFields) -> None:
    """Mark every stage done; the card hides itself."""
    state.progress_stage = len(state.progress_stages)
    state.progress_status = "done"


def progress_fail(state: ProgressFields, message: str) -> None:
    """Stop at the current stage and show `message`."""
    state.progress_status = "error"
    state.progress_error = message


def progress_clear(state: ProgressFields) -> None:
    """Hide the card."""
    state.progress_status = ""
    state.progress_error = ""


def friendly_error(ex: Exception | str) -> str:
    """A short, plain error line. The full detail stays in the server log."""
    text = str(ex).strip() or t("error.unknown")
    lowered = text.lower()
    if "credentials" in lowered or "default credentials" in lowered:
        return t("error.credentials")
    if "quota" in lowered or "429" in lowered or "resource exhausted" in lowered:
        return t("error.quota")
    if "safety" in lowered or "blocked" in lowered:
        return t("error.safety")
    if len(text) > 280:
        text = text[:277] + "…"
    return text


_PROGRESS_KEYS = (
    "creating",
    "failed",
    "done",
    "kept",
    "usually",
    "generic_error",
    "retry",
    "dismiss",
    "st_done",
    "st_now",
    "st_failed",
    "aria",
    "elapsed",
    "estimated",
)


def progress_labels(lang: str, media_label: str) -> str:
    """The card's text in `lang`, as JSON. {media} is already filled in."""
    media = tl(lang, f"media.{media_label}", default=media_label)
    return json.dumps(
        {k: tl(lang, f"progress.{k}", media=media, t="{t}") for k in _PROGRESS_KEYS},
        ensure_ascii=False,
    )


@me.web_component(path="./generation_progress.js")
def generation_progress_card(
    *,
    stages: list[str],
    current: int,
    status: str,
    run_id: str,
    typical_seconds: int = 0,
    work_stage: int = -1,
    message: str = "",
    heading: str = "",
    aspect: str = "1:1",
    count: int = 1,
    media_label: str = "image",
    on_retry: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    on_dismiss: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    key: str | None = None,
    labels: str = "",
):
    """Low-level wrapper for <gm-generation-progress>."""
    return me.insert_web_component(
        key=key,
        name="gm-generation-progress",
        properties={
            "stages": json.dumps(stages),
            "current": current,
            "status": status,
            "runId": run_id,
            "typicalSeconds": typical_seconds,
            "workStage": work_stage,
            "message": message,
            "heading": heading,
            "aspect": aspect,
            "count": count,
            "mediaLabel": media_label,
            "labels": labels,
        },
        events={"retryEvent": on_retry, "dismissEvent": on_dismiss},
    )


def generation_progress(
    *,
    state: ProgressFields,
    typical_seconds: int = 0,
    work_stage: int = -1,
    aspect: str = "1:1",
    count: int = 1,
    media_label: str = "image",
    on_retry: typing.Callable[[me.WebEvent], typing.Any] | None = None,
    on_dismiss: typing.Callable[[me.WebEvent], typing.Any] | None = None,
):
    """Render the progress card for a page state, or nothing when idle/done.

    A plain function (not @me.component): Mesop components must take simple
    values, and this one reads several fields off the page state.
    """
    if state.progress_status not in ("running", "error"):
        return
    lang = current_lang()
    with me.box(classes="gm-progress-slot"):
        generation_progress_card(
            key="gm_generation_progress",
            stages=[tx_lang(lang, s) for s in state.progress_stages],
            current=state.progress_stage,
            status=state.progress_status,
            run_id=state.progress_run_id,
            typical_seconds=typical_seconds,
            work_stage=work_stage,
            message=tx_lang(lang, state.progress_error),
            labels=progress_labels(lang, media_label),
            aspect=aspect,
            count=count,
            media_label=media_label,
            on_retry=on_retry,
            on_dismiss=on_dismiss,
        )
