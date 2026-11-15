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
"""Story Studio (/story): idea -> scenario -> storyboard -> editor -> film.

The page only edits small state (ids, text, URIs). Generation runs in
background jobs (services/story_jobs.py); a ticker polls them once a second so
the timeline, thumbnails and progress bar fill in live.
"""

from __future__ import annotations

import datetime
import json

import mesop as me

from common.analytics import get_logger
from components.header import header
from components.page_scaffold import page_frame, page_scaffold
from components.story_studio.widgets import (
    story_stepper,
    story_style_picker,
    story_ticker,
)
from config.default import Default
from services import story_jobs
from services.story_models import (
    ASPECT_RATIOS,
    CAMERA_IDS,
    CAMERA_PRESETS,
    LANGUAGES,
    STEP_IDS,
    STEPS,
    STYLE_BY_ID,
    STYLES,
    VOICES,
    Story,
    apply_caps,
    can_enter,
    default_music_prompt,
    furthest_step,
    reachable_steps,
    supported_durations,
)
from services.story_service import display_url, get_backend, is_mock_mode
from services.story_store import StoryAccessError, get_store
from state.state import AppState
from state.story_state import StoryState

logger = get_logger(__name__)

EXAMPLE_IDEAS = [
    "A lighthouse keeper befriends a lost baby whale and helps it find its family.",
    "A tiny robot opens a coffee shop on Mars and its first customer is a dust storm.",
    "A grandmother's recipe book comes alive the night before the village festival.",
]
EXAMPLE_LABELS = [
    "Lighthouse and whale",
    "Robot café on Mars",
    "The living recipe book",
]

STATUS_LABEL = {
    "queued": "Queued",
    "running": "Working",
    "done": "Done",
    "failed": "Failed",
    "skipped": "Skipped",
}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def on_load(e: me.LoadEvent):
    s = me.state(StoryState)
    if not s.loaded:
        s.loaded = True
        _refresh_stories()
        story_id = me.query_params.get("id", "")
        if story_id:
            _open_story(story_id)
            step = me.query_params.get("step", "")
            if step and can_enter(step, _story()):
                s.step = step
    yield


@me.page(
    path="/story",
    title="Story Studio · GenMedia Studio",
    security_policy=me.SecurityPolicy(dangerously_disable_trusted_types=True),
    stylesheets=["/ui/story.css"],
    on_load=on_load,
)
def page():
    with page_scaffold(page_name="story"):
        with page_frame():
            header("Story Studio", "auto_stories")
            story_studio_content()


def story_studio_content():
    s = me.state(StoryState)
    story = _story()
    story_ticker(
        active=s.job_running, on_tick=on_tick, interval_ms=1000, key="ss-ticker"
    )

    with me.box(classes="ss-root"):
        if is_mock_mode():
            with me.box(classes="ss-demo"):
                me.icon("science", style=me.Style(font_size=18, width=18, height=18))
                me.text("Demo mode: placeholder media, no cloud calls, no cost.")
        with me.box(classes="ss-stepper"):
            story_stepper(
                steps=_stepper_steps(story), on_select=on_step_select, key="ss-steps"
            )

        if s.error:
            with me.box(classes="ss-alert ss-alert-error"):
                me.icon(
                    "error_outline", style=me.Style(width=20, height=20, font_size=20)
                )
                me.text(s.error, style=me.Style(flex_grow=1))
                me.button("Dismiss", on_click=on_dismiss_error, type="stroked")
        if s.notice:
            with me.box(classes="ss-alert ss-alert-info"):
                me.icon("info", style=me.Style(width=20, height=20, font_size=20))
                me.text(s.notice, style=me.Style(flex_grow=1))
                me.button("OK", on_click=on_dismiss_notice, type="stroked")

        step = s.step if s.step in STEP_IDS else "stories"
        if step == "stories":
            stories_step()
        elif step == "create":
            create_step(story)
        elif step == "scenario" and story:
            scenario_step(story)
        elif step == "storyboard" and story:
            storyboard_step(story)
        elif step == "editor" and story:
            editor_step(story)
        elif step == "video" and story:
            video_step(story)
        else:
            stories_step()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner() -> str:
    return me.state(AppState).user_email


def _story() -> Story | None:
    s = me.state(StoryState)
    if not s.story_json:
        return None
    try:
        return Story.from_dict(json.loads(s.story_json))
    except ValueError:
        return None


def _set_story(story: Story | None) -> None:
    s = me.state(StoryState)
    if story is None:
        s.story_id = ""
        s.story_json = ""
        return
    s.story_id = story.id
    s.story_json = json.dumps(story.to_dict())


def _job() -> dict | None:
    s = me.state(StoryState)
    if not s.job_json:
        return None
    try:
        return json.loads(s.job_json)
    except ValueError:
        return None


def _refresh_stories() -> None:
    s = me.state(StoryState)
    try:
        rows = get_store().list(_owner())
    except Exception as exc:
        logger.exception("Story Studio: could not list stories")
        s.error = f"Could not load your stories: {exc}"
        rows = []
    s.stories_json = json.dumps(
        [
            {
                "id": r.id,
                "title": r.title
                or (r.idea[:48] + ("…" if len(r.idea) > 48 else ""))
                or "Untitled story",
                "style": r.style,
                "scenes": len(r.scenes) or r.scene_count,
                "updated": r.updated_at,
                "cover": r.cover_uri,
                "has_film": bool(r.final_uri),
            }
            for r in rows
        ]
    )


def _load_form(story: Story) -> None:
    s = me.state(StoryState)
    s.idea = story.idea
    s.character = story.character
    s.language = story.language
    s.scene_count = story.scene_count
    s.duration = story.duration
    s.aspect_ratio = story.aspect_ratio
    s.style = story.style
    s.camera = story.camera
    s.reference_uri = story.reference_uri


def _open_story(story_id: str) -> None:
    s = me.state(StoryState)
    story = get_store().get(story_id, _owner())
    if story is None:
        s.error = "That story was not found."
        return
    _set_story(story)
    _load_form(story)
    s.step = furthest_step(story)
    job = story_jobs.latest_job_for(story.id, _owner())
    if job is not None:
        _watch(job.id)
    else:
        s.job_id = ""
        s.job_json = ""
        s.job_running = False


def _reload_story() -> Story | None:
    s = me.state(StoryState)
    if not s.story_id:
        return None
    story = get_store().get(s.story_id, _owner())
    if story is not None:
        _set_story(story)
    return story


def _watch(job_id: str) -> None:
    s = me.state(StoryState)
    s.job_id = job_id
    snap = story_jobs.job_snapshot(job_id, _owner())
    s.job_json = json.dumps(snap) if snap else ""
    s.job_running = bool(snap and snap["status"] == "running")
    s.job_tasks_done = 0


def _edit(fn, clear_media: bool = False) -> Story | None:
    """Change the stored story (owner-only) and refresh the render copy."""
    s = me.state(StoryState)
    try:
        story = story_jobs.mutate_story(s.story_id, _owner(), fn)
    except StoryAccessError as exc:
        s.error = str(exc)
        return None
    _set_story(story)
    return story


def _fmt_secs(secs: float) -> str:
    secs = int(round(secs or 0))
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}:{secs % 60:02d}"


def _fmt_date(iso: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except TypeError, ValueError:
        return ""
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _job_active_for(*kinds: str) -> bool:
    s = me.state(StoryState)
    job = _job()
    return bool(s.job_running and job and job.get("kind") in kinds)


def _scene_task(kind: str, index: int) -> dict | None:
    job = _job()
    if not job:
        return None
    for t in job.get("tasks", []):
        if t["kind"] == kind and t["scene_index"] == index:
            return t
    return None


def _stepper_steps(story: Story | None) -> list[dict]:
    s = me.state(StoryState)
    reach = reachable_steps(story)
    current = s.step if s.step in STEP_IDS else "stories"
    furthest = furthest_step(story) if story else "stories"
    cur_i = STEP_IDS.index(current)
    far_i = max(STEP_IDS.index(furthest), cur_i)
    out = []
    for i, (sid, label, _icon) in enumerate(STEPS):
        if sid == current:
            state = "current"
        elif (i < far_i and sid in reach) or (
            sid == "video" and story and story.final_uri
        ):
            state = "done"
        else:
            state = "upcoming"
        out.append({"id": sid, "label": label, "state": state, "enabled": sid in reach})
    return out


def _section_title(title: str, subtitle: str = "") -> None:
    with me.box(classes="ss-section-title"):
        me.text(
            title,
            type="headline-6",
            style=me.Style(margin=me.Margin.all(0), font_weight=600),
        )
        if subtitle:
            me.text(
                subtitle,
                style=me.Style(color=me.theme_var("on-surface-variant"), font_size=14),
            )


def _chip(label: str, tone: str = "") -> None:
    with me.box(classes=f"ss-chip {tone}".strip()):
        me.text(label)


def _sr(text: str) -> None:
    with me.box(classes="gm-sr-only"):
        me.text(text)


# ---------------------------------------------------------------------------
# Events: navigation and polling
# ---------------------------------------------------------------------------


def on_step_select(e: me.WebEvent):
    s = me.state(StoryState)
    target = (e.value or {}).get("id", "")
    story = _story()
    if target == "stories":
        _refresh_stories()
        s.step = "stories"
    elif target == "create" or can_enter(target, story):
        s.step = target
    yield


def on_tick(e: me.WebEvent):
    s = me.state(StoryState)
    if not s.job_id:
        s.job_running = False
        return
    snap = story_jobs.job_snapshot(s.job_id, _owner())
    if snap is None:
        s.job_running = False
        s.job_json = ""
        return
    s.job_json = json.dumps(snap)
    finished = sum(
        1 for t in snap["tasks"] if t["status"] in ("done", "failed", "skipped")
    )
    if finished != s.job_tasks_done or snap["status"] != "running":
        s.job_tasks_done = finished
        _reload_story()
    if snap["status"] != "running":
        s.job_running = False
        story = _story()
        if (
            snap["kind"] == "video"
            and story
            and story.final_uri
            and snap["status"] == "done"
        ):
            s.notice = "Your film is ready."


def on_dismiss_error(e: me.ClickEvent):
    me.state(StoryState).error = ""


def on_dismiss_notice(e: me.ClickEvent):
    me.state(StoryState).notice = ""


def on_retry_job(e: me.ClickEvent):
    s = me.state(StoryState)
    try:
        job = story_jobs.retry(s.job_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    if job:
        _watch(job.id)


# ---------------------------------------------------------------------------
# Progress panel
# ---------------------------------------------------------------------------

TASK_ICON = {
    "queued": "schedule",
    "done": "check_circle",
    "failed": "error",
    "skipped": "remove_circle_outline",
}


def progress_panel(title: str, kinds: tuple[str, ...]) -> None:
    job = _job()
    if not job or job.get("kind") not in kinds:
        return
    status = job["status"]
    pct = (
        int(round(job["progress"] * 100))
        if status == "running"
        else (100 if status == "done" else int(round(job["progress"] * 100)))
    )
    with me.box(classes=f"ss-panel ss-panel-{status}"):
        with me.box(classes="ss-panel-head"):
            with me.box(classes="ss-panel-title"):
                me.text(title, style=me.Style(font_weight=600, font_size=16))
                me.text(
                    f"{job['done']} of {job['total']} steps done · {_fmt_secs(job['elapsed'])} elapsed",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
            _chip(
                {
                    "running": "In progress",
                    "done": "Complete",
                    "failed": "Needs attention",
                }.get(status, status),
                f"ss-chip-{status}",
            )
        with me.box(classes="ss-bar"):
            me.box(classes="ss-bar-fill", style=me.Style(width=f"{max(3, pct)}%"))
        _sr(f"{pct} percent complete")
        with me.box(classes="ss-tasks"):
            for t in job["tasks"]:
                with me.box(classes=f"ss-task ss-task-{t['status']}"):
                    if t["status"] == "running":
                        me.box(classes="ss-spinner")
                    else:
                        me.icon(
                            TASK_ICON.get(t["status"], "schedule"),
                            style=me.Style(font_size=20, width=20, height=20),
                        )
                    with me.box(classes="ss-task-body"):
                        me.text(t["label"], style=me.Style(font_size=14))
                        if t["status"] == "failed" and t.get("error"):
                            me.text(
                                t["error"],
                                style=me.Style(
                                    font_size=13, color=me.theme_var("error")
                                ),
                            )
                        elif t["status"] == "skipped" and t.get("error"):
                            me.text(
                                t["error"],
                                style=me.Style(
                                    font_size=13,
                                    color=me.theme_var("on-surface-variant"),
                                ),
                            )
                    me.text(
                        f"{STATUS_LABEL.get(t['status'], t['status'])}"
                        + (f" · {_fmt_secs(t['elapsed'])}" if t["elapsed"] else ""),
                        style=me.Style(
                            font_size=13,
                            color=me.theme_var("on-surface-variant"),
                            white_space="nowrap",
                        ),
                    )
        if status == "failed":
            with me.box(classes="ss-panel-foot"):
                me.text(
                    job.get("message") or "Some steps failed.",
                    style=me.Style(font_size=14, flex_grow=1),
                )
                with me.content_button(
                    type="flat", color="primary", on_click=on_retry_job
                ):
                    with me.box(classes="ss-btn-inner"):
                        me.icon(
                            "refresh", style=me.Style(font_size=18, width=18, height=18)
                        )
                        me.text("Retry")


# ---------------------------------------------------------------------------
# Step 1: Stories
# ---------------------------------------------------------------------------


def stories_step() -> None:
    s = me.state(StoryState)
    rows = json.loads(s.stories_json or "[]")
    _section_title(
        "Your stories",
        "Pick up where you left off, or start a new film from one idea.",
    )
    with me.box(classes="ss-stories"):
        with me.box(classes="ss-new", on_click=on_new_story):
            with me.box(classes="ss-new-icon"):
                me.icon("add", style=me.Style(font_size=28, width=28, height=28))
            me.text("Create new story", style=me.Style(font_weight=600, font_size=17))
            me.text(
                "Start a fresh story",
                style=me.Style(font_size=14, color=me.theme_var("on-surface-variant")),
            )
            me.button(
                "Get started",
                type="flat",
                color="primary",
                on_click=on_new_story,
                key="ss-new-btn",
            )
        for r in rows:
            story_card(r)
    if not rows:
        me.text(
            "No stories yet. Your stories are saved here as you work.",
            style=me.Style(color=me.theme_var("on-surface-variant"), font_size=14),
        )


def story_card(r: dict) -> None:
    s = me.state(StoryState)
    style = STYLE_BY_ID.get(r["style"], STYLES[0])
    with me.box(classes="ss-story"):
        with me.box(classes="ss-story-cover"):
            if r.get("cover"):
                me.image(
                    src=display_url(r["cover"]),
                    alt="",
                    style=me.Style(width="100%", height="100%", object_fit="cover"),
                )
            else:
                me.image(
                    src=f"/ui/story/{style['id']}.svg",
                    alt="",
                    style=me.Style(width="100%", height="100%", object_fit="cover"),
                )
            if r.get("has_film"):
                with me.box(classes="ss-story-badge"):
                    me.icon("movie", style=me.Style(font_size=14, width=14, height=14))
                    me.text("Film ready")
        with me.box(classes="ss-story-body"):
            me.text(
                r["title"],
                style=me.Style(font_weight=600, font_size=16, line_height="1.3"),
            )
            with me.box(classes="ss-meta"):
                _chip(style["chip"])
                me.text(f"{r['scenes']} scenes", style=me.Style(font_size=13))
                me.text("·", style=me.Style(font_size=13))
                me.text(
                    f"Updated {_fmt_date(r['updated'])}", style=me.Style(font_size=13)
                )
            with me.box(classes="ss-story-actions"):
                if s.confirm_delete_id == r["id"]:
                    me.text(
                        "Delete this story?", style=me.Style(font_size=14, flex_grow=1)
                    )
                    me.button(
                        "Cancel",
                        type="stroked",
                        on_click=on_cancel_delete,
                        key=f"cancel-{r['id']}",
                    )
                    me.button(
                        "Delete",
                        type="flat",
                        color="warn",
                        on_click=on_confirm_delete,
                        key=f"del-{r['id']}",
                    )
                else:
                    me.button(
                        "Continue story",
                        type="stroked",
                        on_click=on_continue_story,
                        key=f"open-{r['id']}",
                    )
                    with me.content_button(
                        type="icon", on_click=on_ask_delete, key=f"ask-{r['id']}"
                    ):
                        me.icon("delete_outline")
                        _sr(f"Delete {r['title']}")


def on_new_story(e: me.ClickEvent):
    s = me.state(StoryState)
    _set_story(None)
    s.idea = ""
    s.character = ""
    s.reference_uri = ""
    s.job_id = ""
    s.job_json = ""
    s.job_running = False
    s.error = ""
    s.step = "create"


def on_continue_story(e: me.ClickEvent):
    _open_story(e.key.split("-", 1)[1])


def on_ask_delete(e: me.ClickEvent):
    me.state(StoryState).confirm_delete_id = e.key.split("-", 1)[1]


def on_cancel_delete(e: me.ClickEvent):
    me.state(StoryState).confirm_delete_id = ""


def on_confirm_delete(e: me.ClickEvent):
    s = me.state(StoryState)
    story_id = e.key.split("-", 1)[1]
    if not get_store().delete(story_id, _owner()):
        s.error = "Could not delete that story."
    if s.story_id == story_id:
        _set_story(None)
    s.confirm_delete_id = ""
    _refresh_stories()


# ---------------------------------------------------------------------------
# Step 2: Create
# ---------------------------------------------------------------------------


def create_step(story: Story | None) -> None:
    s = me.state(StoryState)
    caps = apply_caps(s.scene_count, s.duration)
    busy = _job_active_for("scenario")
    with me.box(classes="ss-create"):
        with me.box(classes="ss-card ss-create-main"):
            _section_title(
                "What's your story?",
                "One or two sentences is enough. Gemini writes the scenes.",
            )
            me.textarea(
                label="Your idea",
                value=s.idea,
                rows=4,
                appearance="outline",
                placeholder="A lighthouse keeper befriends a lost baby whale…",
                on_blur=on_idea_blur,
                style=me.Style(width="100%"),
                key="ss-idea",
            )
            with me.box(classes="ss-examples"):
                me.text(
                    "Try:",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
                for i, idea in enumerate(EXAMPLE_IDEAS):
                    me.button(
                        EXAMPLE_LABELS[i],
                        type="stroked",
                        on_click=on_example,
                        key=f"ex-{i}",
                    )
            me.input(
                label="Main character (optional)",
                value=s.character,
                appearance="outline",
                placeholder="e.g. an old keeper with a grey beard and a yellow raincoat",
                on_blur=on_character_blur,
                style=me.Style(width="100%"),
                key="ss-character",
            )
            with me.box(classes="ss-fields"):
                me.select(
                    label="Language",
                    options=[me.SelectOption(label=k, value=k) for k in LANGUAGES],
                    value=s.language,
                    appearance="outline",
                    on_selection_change=on_language,
                    key="ss-lang",
                )
                cfg = Default()
                me.select(
                    label="Scenes",
                    options=[
                        me.SelectOption(label=f"{n} scenes", value=str(n))
                        for n in range(cfg.STORY_MIN_SCENES, cfg.STORY_MAX_SCENES + 1)
                    ],
                    value=str(s.scene_count),
                    appearance="outline",
                    on_selection_change=on_scene_count,
                    key="ss-count",
                )
                me.select(
                    label="Scene length",
                    options=[
                        me.SelectOption(label=f"{d} seconds", value=str(d))
                        for d in supported_durations()
                    ],
                    value=str(s.duration),
                    appearance="outline",
                    on_selection_change=on_duration,
                    key="ss-dur",
                )
                me.select(
                    label="Aspect ratio",
                    options=[
                        me.SelectOption(
                            label=f"{a} {'landscape' if a == '16:9' else 'portrait'}",
                            value=a,
                        )
                        for a in ASPECT_RATIOS
                    ],
                    value=s.aspect_ratio,
                    appearance="outline",
                    on_selection_change=on_aspect,
                    key="ss-aspect",
                )
                me.select(
                    label="Camera motion",
                    options=[
                        me.SelectOption(label=v["label"], value=k)
                        for k, v in CAMERA_PRESETS.items()
                    ],
                    value=s.camera,
                    appearance="outline",
                    on_selection_change=on_camera,
                    key="ss-camera",
                )
            story_style_picker(
                options=[
                    {
                        "id": st["id"],
                        "label": st["label"],
                        "src": f"/ui/story/{st['id']}.svg",
                    }
                    for st in STYLES
                ],
                value=s.style,
                label="Style",
                on_change=on_style,
                key="ss-style",
            )
            with me.box(classes="ss-ref"):
                with me.box(classes="ss-ref-text"):
                    me.text(
                        "Character reference (optional)",
                        style=me.Style(font_weight=600, font_size=14),
                    )
                    me.text(
                        "Upload a photo or drawing to keep the same look in every frame.",
                        style=me.Style(
                            font_size=13, color=me.theme_var("on-surface-variant")
                        ),
                    )
                if s.reference_uri:
                    me.image(
                        src=display_url(s.reference_uri),
                        alt="Character reference",
                        style=me.Style(
                            width=72, height=72, object_fit="cover", border_radius=10
                        ),
                    )
                    me.button("Remove", type="stroked", on_click=on_remove_reference)
                else:
                    me.uploader(
                        label="Upload image",
                        accepted_file_types=["image/png", "image/jpeg", "image/webp"],
                        type="stroked",
                        on_upload=on_upload_reference,
                        key="ss-upload",
                    )

        with me.box(classes="ss-card ss-summary"):
            me.text(
                "Your film",
                style=me.Style(
                    font_size=14,
                    font_weight=600,
                    color=me.theme_var("on-surface-variant"),
                ),
            )
            me.text(
                f"≈ {caps.scene_count * caps.duration}s",
                style=me.Style(font_size=40, font_weight=700, line_height="1.1"),
            )
            with me.box(classes="ss-summary-lines"):
                me.text(f"{caps.scene_count} scenes × {caps.duration}s")
                me.text(
                    f"{s.aspect_ratio} · {caps.resolution} · {STYLE_BY_ID.get(s.style, STYLES[0])['label']}"
                )
                me.text(
                    f"Camera: {CAMERA_PRESETS.get(s.camera, CAMERA_PRESETS['auto'])['label']}"
                )
            for note in caps.notes:
                me.text(
                    note,
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
            with me.box(classes="ss-next"):
                me.text(
                    "What happens next", style=me.Style(font_size=13, font_weight=600)
                )
                for icon, line in [
                    ("description", "Gemini writes the scenes. You edit and approve."),
                    (
                        "view_carousel",
                        "One still per scene, same character throughout.",
                    ),
                    (
                        "movie",
                        "Veo animates each still, then we add music and voice and stitch the film.",
                    ),
                ]:
                    with me.box(classes="ss-next-row"):
                        me.icon(
                            icon,
                            style=me.Style(
                                font_size=18, width=18, height=18, flex_shrink=0
                            ),
                        )
                        me.text(line, style=me.Style(font_size=13))
            if story and story.scenes and not busy:
                me.text(
                    "This writes a new scenario and replaces the current scenes.",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
            me.button(
                "Writing scenario…" if busy else "Generate scenario",
                type="flat",
                color="primary",
                disabled=busy,
                on_click=on_generate_scenario,
                style=me.Style(width="100%", height=48, font_size=15),
                key="ss-generate",
            )


def on_idea_blur(e: me.InputBlurEvent):
    me.state(StoryState).idea = e.value


def on_character_blur(e: me.InputBlurEvent):
    me.state(StoryState).character = e.value


def on_example(e: me.ClickEvent):
    me.state(StoryState).idea = EXAMPLE_IDEAS[int(e.key.split("-")[1])]


def on_language(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).language = e.value


def on_scene_count(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).scene_count = int(e.value)


def on_duration(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).duration = int(e.value)


def on_aspect(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).aspect_ratio = e.value


def on_camera(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).camera = e.value


def on_style(e: me.WebEvent):
    value = (e.value or {}).get("value", "")
    if value in STYLE_BY_ID:
        me.state(StoryState).style = value


def on_upload_reference(e: me.UploadEvent):
    s = me.state(StoryState)
    try:
        s.reference_uri = get_backend().save_upload(e.file.getvalue(), e.file.mime_type)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)


def on_remove_reference(e: me.ClickEvent):
    me.state(StoryState).reference_uri = ""


def on_generate_scenario(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    idea = (s.idea or "").strip()
    if len(idea) < 8:
        s.error = "Describe your idea in a sentence or two first."
        return
    caps = apply_caps(s.scene_count, s.duration)
    s.scene_count, s.duration = caps.scene_count, caps.duration
    owner = _owner()
    try:
        existing = get_store().get(s.story_id, owner) if s.story_id else None
        story = existing or Story()
        story.idea = idea
        story.character = s.character.strip()
        story.language = s.language
        story.scene_count = caps.scene_count
        story.duration = caps.duration
        story.aspect_ratio = s.aspect_ratio
        story.style = s.style
        story.camera = s.camera
        story.reference_uri = s.reference_uri
        story.scenes = []
        story.approved = False
        story.final_uri = ""
        story.step = "scenario"
        story = get_store().save(story, owner)
        _set_story(story)
        job = story_jobs.start_scenario(story.id, owner)
    except Exception as exc:
        logger.exception("Story Studio: could not start scenario")
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)
    s.step = "scenario"
    yield


# ---------------------------------------------------------------------------
# Step 3: Scenario
# ---------------------------------------------------------------------------


def scenario_step(story: Story) -> None:
    busy_all = _job_active_for("scenario")
    busy_any = _job_active_for("scenario", "scene", "storyboard")
    progress_panel("Writing your scenario", ("scenario", "scene"))
    if busy_all or not story.scenes:
        with me.box(classes="ss-scenes"):
            for i in range(story.scene_count):
                with me.box(classes="ss-card ss-scene ss-skeleton-card"):
                    me.text(f"Scene {i + 1}", style=me.Style(font_weight=600))
                    me.box(classes="ss-skel ss-skel-line")
                    me.box(classes="ss-skel ss-skel-line short")
                    me.box(classes="ss-skel ss-skel-block")
        return

    with me.box(classes="ss-card ss-title-row"):
        with me.box(classes="ss-grow"):
            me.input(
                label="Film title",
                value=story.title,
                appearance="outline",
                on_blur=on_title_blur,
                style=me.Style(width="100%"),
                key=f"title-{story.id}",
            )
        with me.content_button(
            type="stroked", on_click=on_rewrite_all, disabled=busy_any
        ):
            with me.box(classes="ss-btn-inner"):
                me.icon("autorenew", style=me.Style(font_size=18, width=18, height=18))
                me.text("Rewrite all scenes")

    with me.box(classes="ss-scenes"):
        for i, sc in enumerate(story.scenes):
            rewriting = _job_active_for("scene") and (
                _scene_task("scenario", i) or {}
            ).get("status") in ("queued", "running")
            with me.box(classes="ss-card ss-scene" + (" is-busy" if rewriting else "")):
                with me.box(classes="ss-scene-head"):
                    with me.box(classes="ss-badge"):
                        me.text(f"Scene {i + 1}")
                    with me.box(classes="ss-grow"):
                        me.select(
                            label="Camera",
                            options=[
                                me.SelectOption(
                                    label=CAMERA_PRESETS[c]["label"], value=c
                                )
                                for c in CAMERA_IDS
                            ],
                            value=sc.camera,
                            appearance="outline",
                            on_selection_change=on_scene_camera,
                            style=me.Style(width="100%"),
                            key=f"cam-{sc.id}",
                        )
                    with me.content_button(
                        type="stroked",
                        on_click=on_rewrite_scene,
                        disabled=busy_any,
                        key=f"rw-{i}",
                    ):
                        with me.box(classes="ss-btn-inner"):
                            me.icon(
                                "refresh",
                                style=me.Style(font_size=18, width=18, height=18),
                            )
                            me.text("Regenerate")
                if rewriting:
                    with me.box(classes="ss-busy-line"):
                        me.box(classes="ss-spinner")
                        me.text("Rewriting this scene…", style=me.Style(font_size=13))
                me.textarea(
                    label="Narration (voiceover)",
                    value=sc.narration,
                    rows=2,
                    appearance="outline",
                    on_blur=on_scene_narration,
                    style=me.Style(width="100%"),
                    key=f"nar-{sc.id}",
                )
                me.textarea(
                    label="What we see",
                    value=sc.visual,
                    rows=4,
                    appearance="outline",
                    on_blur=on_scene_visual,
                    style=me.Style(width="100%"),
                    key=f"vis-{sc.id}",
                )

    with me.box(classes="ss-actions"):
        me.button("Back to idea", type="stroked", on_click=on_back_create)
        me.button(
            "Approve and paint storyboard",
            type="flat",
            color="primary",
            disabled=busy_any,
            on_click=on_approve,
            style=me.Style(height=44),
        )


def _scene_id_from_key(key: str) -> str:
    return key.split("-", 1)[1]


def _update_scene(
    scene_id: str, field: str, value, clear: tuple[str, ...] = ("clip_uri",)
) -> None:
    def apply(story: Story) -> None:
        for sc in story.scenes:
            if sc.id == scene_id and getattr(sc, field) != value:
                setattr(sc, field, value)
                for c in clear:
                    setattr(sc, c, "")
                story.final_uri = ""

    _edit(apply)


def on_title_blur(e: me.InputBlurEvent):
    value = e.value.strip()[:120]

    def apply(story: Story) -> None:
        story.title = value

    _edit(apply)


def on_scene_narration(e: me.InputBlurEvent):
    _update_scene(_scene_id_from_key(e.key), "narration", e.value.strip(), clear=())


def on_scene_visual(e: me.InputBlurEvent):
    _update_scene(_scene_id_from_key(e.key), "visual", e.value.strip())


def on_scene_camera(e: me.SelectSelectionChangeEvent):
    _update_scene(_scene_id_from_key(e.key), "camera", e.value)


def on_rewrite_scene(e: me.ClickEvent):
    s = me.state(StoryState)
    try:
        job = story_jobs.start_scene_rewrite(
            s.story_id, _owner(), int(e.key.split("-")[1])
        )
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_rewrite_all(e: me.ClickEvent):
    s = me.state(StoryState)
    try:
        job = story_jobs.start_scenario(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_back_create(e: me.ClickEvent):
    me.state(StoryState).step = "create"


def on_approve(e: me.ClickEvent):
    s = me.state(StoryState)

    def apply(story: Story) -> None:
        story.approved = True
        story.step = "storyboard"

    story = _edit(apply)
    if story is None:
        return
    s.step = "storyboard"
    if any(not sc.frame_uri for sc in story.scenes):
        try:
            job = story_jobs.start_storyboard(story.id, _owner())
        except Exception as exc:
            s.error = story_jobs.friendly_error(exc)
            return
        _watch(job.id)


# ---------------------------------------------------------------------------
# Step 4: Storyboard
# ---------------------------------------------------------------------------


def _media_box(
    uri: str, aspect: str, task: dict | None, alt: str, video: bool = False
) -> None:
    ar = "ss-ar-916" if aspect == "9:16" else "ss-ar-169"
    status = (task or {}).get("status", "")
    with me.box(classes=f"ss-media {ar}"):
        if uri and status not in ("running",):
            if video:
                me.video(
                    src=display_url(uri), style=me.Style(width="100%", height="100%")
                )
            else:
                me.image(
                    src=display_url(uri),
                    alt=alt,
                    style=me.Style(width="100%", height="100%", object_fit="cover"),
                )
        elif status == "running":
            me.box(classes="ss-skel ss-skel-fill")
            with me.box(classes="ss-media-overlay"):
                me.box(classes="ss-spinner")
                me.text(
                    f"Generating… {_fmt_secs(task.get('elapsed', 0))}",
                    style=me.Style(font_size=13),
                )
        elif status == "failed":
            with me.box(classes="ss-media-overlay ss-failed"):
                me.icon("error", style=me.Style(font_size=22, width=22, height=22))
                me.text(
                    task.get("error") or "Failed",
                    style=me.Style(font_size=13, text_align="center"),
                )
        elif status == "queued":
            me.box(classes="ss-skel ss-skel-fill is-idle")
            with me.box(classes="ss-media-overlay"):
                me.icon("schedule", style=me.Style(font_size=20, width=20, height=20))
                me.text("Queued", style=me.Style(font_size=13))
        else:
            with me.box(classes="ss-media-overlay"):
                me.icon("image", style=me.Style(font_size=22, width=22, height=22))
                me.text("No frame yet", style=me.Style(font_size=13))


def storyboard_step(story: Story) -> None:
    busy = _job_active_for("storyboard")
    progress_panel("Painting your storyboard", ("storyboard",))
    with me.box(
        classes="ss-frames" + (" is-portrait" if story.aspect_ratio == "9:16" else "")
    ):
        for i, sc in enumerate(story.scenes):
            task = (
                _scene_task("frame", i)
                if busy or (_job() or {}).get("kind") == "storyboard"
                else None
            )
            if task and task["status"] == "done":
                task = None
            with me.box(classes="ss-card ss-frame"):
                _media_box(
                    sc.frame_uri,
                    story.aspect_ratio,
                    task,
                    f"Storyboard frame for scene {i + 1}",
                )
                with me.box(classes="ss-frame-body"):
                    with me.box(classes="ss-frame-head"):
                        me.text(
                            f"Scene {i + 1}",
                            style=me.Style(font_weight=600, font_size=14),
                        )
                        _chip(
                            CAMERA_PRESETS.get(sc.camera, CAMERA_PRESETS["static"])[
                                "label"
                            ]
                        )
                    me.text(
                        sc.narration or sc.visual[:90],
                        style=me.Style(
                            font_size=13,
                            color=me.theme_var("on-surface-variant"),
                            line_height="1.4",
                        ),
                    )
                    with me.content_button(
                        type="stroked",
                        disabled=busy,
                        on_click=on_regen_frame,
                        key=f"rf-{i}",
                    ):
                        with me.box(classes="ss-btn-inner"):
                            me.icon(
                                "refresh",
                                style=me.Style(font_size=18, width=18, height=18),
                            )
                            me.text("Regenerate frame")
    ready = bool(story.scenes) and all(sc.frame_uri for sc in story.scenes)
    with me.box(classes="ss-actions"):
        me.button("Back to scenario", type="stroked", on_click=on_back_scenario)
        me.button(
            "Continue to editor",
            type="flat",
            color="primary",
            disabled=busy or not ready,
            on_click=on_to_editor,
            style=me.Style(height=44),
        )


def on_regen_frame(e: me.ClickEvent):
    s = me.state(StoryState)
    try:
        job = story_jobs.start_storyboard(
            s.story_id, _owner(), [int(e.key.split("-")[1])]
        )
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_back_scenario(e: me.ClickEvent):
    me.state(StoryState).step = "scenario"


def on_to_editor(e: me.ClickEvent):
    s = me.state(StoryState)

    def apply(story: Story) -> None:
        story.step = "editor"
        if not story.music_prompt:
            story.music_prompt = default_music_prompt(story)

    if _edit(apply):
        s.step = "editor"


# ---------------------------------------------------------------------------
# Step 5: Editor
# ---------------------------------------------------------------------------


def editor_step(story: Story) -> None:
    busy = _job_active_for("video", "storyboard", "scene")
    total = sum(sc.duration for sc in story.scenes)
    xf = Default().STORY_CROSSFADE_SECONDS
    film_len = max(0.0, total - xf * max(0, len(story.scenes) - 1))
    to_render = sum(1 for sc in story.scenes if not sc.clip_uri)
    with me.box(classes="ss-editor"):
        with me.box(classes="ss-editor-list"):
            for i, sc in enumerate(story.scenes):
                with me.box(classes="ss-card ss-row"):
                    with me.box(classes="ss-row-media"):
                        _media_box(
                            sc.frame_uri, story.aspect_ratio, None, f"Scene {i + 1}"
                        )
                        if sc.clip_uri:
                            _chip("Clip ready", "ss-chip-done")
                    with me.box(classes="ss-row-body"):
                        with me.box(classes="ss-row-head"):
                            with me.box(classes="ss-badge"):
                                me.text(f"Scene {i + 1}")
                            me.select(
                                label="Length",
                                options=[
                                    me.SelectOption(label=f"{d}s", value=str(d))
                                    for d in supported_durations()
                                ],
                                value=str(sc.duration),
                                appearance="outline",
                                disabled=busy,
                                on_selection_change=on_scene_duration,
                                style=me.Style(width=110),
                                key=f"dur-{sc.id}",
                            )
                            me.select(
                                label="Camera",
                                options=[
                                    me.SelectOption(
                                        label=CAMERA_PRESETS[c]["label"], value=c
                                    )
                                    for c in CAMERA_IDS
                                ],
                                value=sc.camera,
                                appearance="outline",
                                disabled=busy,
                                on_selection_change=on_scene_camera,
                                style=me.Style(width=160),
                                key=f"ecam-{sc.id}",
                            )
                            with me.box(classes="ss-row-tools"):
                                for icon, label, handler, dis in [
                                    (
                                        "arrow_upward",
                                        "Move up",
                                        on_move_up,
                                        busy or i == 0,
                                    ),
                                    (
                                        "arrow_downward",
                                        "Move down",
                                        on_move_down,
                                        busy or i == len(story.scenes) - 1,
                                    ),
                                    (
                                        "delete_outline",
                                        "Remove scene",
                                        on_remove_scene,
                                        busy or len(story.scenes) <= 1,
                                    ),
                                ]:
                                    with me.tooltip(message=label):
                                        with me.content_button(
                                            type="icon",
                                            disabled=dis,
                                            on_click=handler,
                                            key=f"{label.split()[0].lower()}{label.split()[-1].lower()}-{sc.id}",
                                        ):
                                            me.icon(icon)
                                            _sr(f"{label}: scene {i + 1}")
                        me.textarea(
                            label="Narration (voiceover)",
                            value=sc.narration,
                            rows=2,
                            appearance="outline",
                            disabled=busy,
                            on_blur=on_scene_narration,
                            style=me.Style(width="100%"),
                            key=f"enar-{sc.id}",
                        )
                        me.textarea(
                            label="Video prompt",
                            value=sc.visual,
                            rows=3,
                            appearance="outline",
                            disabled=busy,
                            on_blur=on_scene_visual,
                            style=me.Style(width="100%"),
                            key=f"evis-{sc.id}",
                        )

        with me.box(classes="ss-card ss-summary ss-sound"):
            me.text("Soundtrack", style=me.Style(font_size=16, font_weight=600))
            me.slide_toggle(
                "Music (Lyria)",
                checked=story.music_on,
                disabled=busy,
                on_change=on_toggle_music,
                key="ss-music-on",
            )
            if story.music_on:
                me.textarea(
                    label="Music prompt",
                    value=story.music_prompt or default_music_prompt(story),
                    rows=3,
                    appearance="outline",
                    disabled=busy,
                    on_blur=on_music_prompt,
                    style=me.Style(width="100%"),
                    key="ss-music",
                )
            me.slide_toggle(
                "Voiceover (Gemini TTS)",
                checked=story.voice_on,
                disabled=busy,
                on_change=on_toggle_voice,
                key="ss-voice-on",
            )
            if story.voice_on:
                me.select(
                    label="Voice",
                    options=[me.SelectOption(label=v, value=v) for v in VOICES],
                    value=story.voice_name,
                    appearance="outline",
                    disabled=busy,
                    on_selection_change=on_voice,
                    style=me.Style(width="100%"),
                    key="ss-voice",
                )
            me.slide_toggle(
                "Continuity: start each clip from the last frame of the one before",
                checked=story.continuity,
                disabled=busy,
                on_change=on_toggle_continuity,
                key="ss-continuity",
            )
            me.text(
                "Smoother cuts, but clips render one after another (slower).",
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
            with me.box(classes="ss-summary-lines"):
                me.text(f"Film length ≈ {_fmt_secs(film_len)} with {xf:g}s crossfades")
                me.text(f"Veo clips to render: {to_render} of {len(story.scenes)}")
            me.button(
                "Rendering…" if _job_active_for("video") else "Render film",
                type="flat",
                color="primary",
                disabled=busy,
                on_click=on_render,
                style=me.Style(width="100%", height=48, font_size=15),
                key="ss-render",
            )
            if story.final_uri:
                me.button(
                    "View current film",
                    type="stroked",
                    on_click=on_to_video,
                    style=me.Style(width="100%"),
                )


def _move(scene_id: str, delta: int) -> None:
    def apply(story: Story) -> None:
        ids = [sc.id for sc in story.scenes]
        if scene_id not in ids:
            return
        i = ids.index(scene_id)
        j = i + delta
        if 0 <= j < len(story.scenes):
            story.scenes[i], story.scenes[j] = story.scenes[j], story.scenes[i]
            story.final_uri = ""
            if story.continuity:
                for sc in story.scenes[min(i, j) :]:
                    sc.clip_uri = ""

    _edit(apply)


def on_move_up(e: me.ClickEvent):
    _move(_scene_id_from_key(e.key), -1)


def on_move_down(e: me.ClickEvent):
    _move(_scene_id_from_key(e.key), 1)


def on_remove_scene(e: me.ClickEvent):
    scene_id = _scene_id_from_key(e.key)

    def apply(story: Story) -> None:
        if len(story.scenes) > 1:
            story.scenes = [sc for sc in story.scenes if sc.id != scene_id]
            story.scene_count = len(story.scenes)
            story.final_uri = ""

    _edit(apply)


def on_scene_duration(e: me.SelectSelectionChangeEvent):
    _update_scene(_scene_id_from_key(e.key), "duration", int(e.value))


def _set_story_field(field: str, value) -> None:
    def apply(story: Story) -> None:
        setattr(story, field, value)
        if field in ("music_on", "music_prompt", "voice_on", "voice_name"):
            story.final_uri = ""
        if field == "continuity":
            story.final_uri = ""
            for sc in story.scenes[1:]:
                sc.clip_uri = ""

    _edit(apply)


def on_toggle_music(e: me.SlideToggleChangeEvent):
    story = _story()
    _set_story_field("music_on", not (story and story.music_on))


def on_toggle_voice(e: me.SlideToggleChangeEvent):
    story = _story()
    _set_story_field("voice_on", not (story and story.voice_on))


def on_toggle_continuity(e: me.SlideToggleChangeEvent):
    story = _story()
    _set_story_field("continuity", not (story and story.continuity))


def on_music_prompt(e: me.InputBlurEvent):
    _set_story_field("music_prompt", e.value.strip())


def on_voice(e: me.SelectSelectionChangeEvent):
    _set_story_field("voice_name", e.value)


def on_render(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    try:
        job = story_jobs.start_video(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)
    s.step = "video"


def on_to_video(e: me.ClickEvent):
    me.state(StoryState).step = "video"


# ---------------------------------------------------------------------------
# Step 6: Video
# ---------------------------------------------------------------------------


def video_step(story: Story) -> None:
    job = _job()
    rendering = _job_active_for("video")
    with me.box(classes="ss-video"):
        with me.box(classes="ss-card ss-player"):
            if story.final_uri and not rendering:
                with me.box(
                    classes="ss-media "
                    + (
                        "ss-ar-916 ss-player-portrait"
                        if story.aspect_ratio == "9:16"
                        else "ss-ar-169"
                    )
                ):
                    me.video(
                        src=display_url(story.final_uri),
                        style=me.Style(width="100%", height="100%"),
                    )
                with me.box(classes="ss-player-meta"):
                    with me.box():
                        me.text(
                            story.title or "Your film",
                            style=me.Style(font_size=20, font_weight=600),
                        )
                        me.text(
                            f"{len(story.scenes)} scenes · {STYLE_BY_ID.get(story.style, STYLES[0])['label']} · {story.aspect_ratio}",
                            style=me.Style(
                                font_size=14, color=me.theme_var("on-surface-variant")
                            ),
                        )
                    with me.box(classes="ss-player-actions"):
                        me.markdown(f"[Download MP4]({display_url(story.final_uri)})")
                        if not is_mock_mode():
                            me.markdown("[Open library](/library)")
                        me.button(
                            "Edit and re-render",
                            type="stroked",
                            on_click=on_back_editor,
                        )
            else:
                with me.box(classes="ss-media ss-ar-169 ss-player-wait"):
                    if rendering:
                        me.box(classes="ss-spinner ss-spinner-lg")
                        me.text(
                            "Making your film…",
                            style=me.Style(font_size=18, font_weight=600),
                        )
                        me.text(
                            "Clips, music and voiceover are generated in parallel, then stitched.",
                            style=me.Style(
                                font_size=14,
                                color=me.theme_var("on-surface-variant"),
                                text_align="center",
                            ),
                        )
                    else:
                        me.icon(
                            "movie", style=me.Style(font_size=36, width=36, height=36)
                        )
                        me.text(
                            "No film yet. Render it from the Editor.",
                            style=me.Style(font_size=15),
                        )
                        me.button(
                            "Go to editor",
                            type="flat",
                            color="primary",
                            on_click=on_back_editor,
                        )

        with me.box(classes="ss-filmstrip", key="ss-strip"):
            for i, sc in enumerate(story.scenes):
                task = (
                    _scene_task("clip", i)
                    if job and job.get("kind") == "video"
                    else None
                )
                status = (task or {}).get("status") or ("done" if sc.clip_uri else "")
                with me.box(classes=f"ss-strip-item ss-strip-{status or 'idle'}"):
                    with me.box(
                        classes="ss-media "
                        + ("ss-ar-916" if story.aspect_ratio == "9:16" else "ss-ar-169")
                    ):
                        if sc.frame_uri:
                            me.image(
                                src=display_url(sc.frame_uri),
                                alt=f"Scene {i + 1}",
                                style=me.Style(
                                    width="100%", height="100%", object_fit="cover"
                                ),
                            )
                        if status == "running":
                            with me.box(classes="ss-media-overlay"):
                                me.box(classes="ss-spinner")
                                me.text(
                                    _fmt_secs(task.get("elapsed", 0)),
                                    style=me.Style(font_size=12),
                                )
                    with me.box(classes="ss-strip-label"):
                        me.text(
                            f"Scene {i + 1}",
                            style=me.Style(font_size=12, font_weight=600),
                        )
                        me.text(
                            {
                                "done": "Clip ready",
                                "running": "Animating",
                                "queued": "Queued",
                                "failed": "Failed",
                            }.get(status, "Waiting"),
                            style=me.Style(font_size=12),
                        )
        progress_panel("Rendering your film", ("video",))


def on_back_editor(e: me.ClickEvent):
    me.state(StoryState).step = "editor"
