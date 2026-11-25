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
"""Film Studio (/story): Films -> Setup -> Script -> Set -> Frames -> Takes ->
Music -> Edit & Export.

The page only edits small state (ids, text, URIs). Generation runs in
background jobs (services/story_jobs.py); a ticker polls them once a second so
the timeline, thumbnails and progress bar fill in live.
"""

from __future__ import annotations

import datetime
import json
import uuid

import mesop as me

from common import brand_kit
from common.analytics import get_logger
from common.notify import notify
from common.prompt_prefill import (
    is_new_prompt_arrival,
    read_prompt_param,
    take_autostart,
)
from components.dialog import dialog, dialog_actions
from components.header import header
from components.library.events import LibrarySelectionChangeEvent
from components.library.library_chooser_button import library_chooser_button
from components.page_scaffold import page_frame, page_scaffold
from components.story_studio import director_desk as desk_view
from components.story_studio import setup_view, timeline_view
from components.story_studio.set_cards import (
    SetHandlers,
    parse_key,
)
from components.story_studio.widgets import (
    film_compare,
    story_stepper,
    story_ticker,
)
from services import (
    story_autoset,
    story_director,
    story_export,
    story_fix,
    story_jobs,
    story_refs,
    story_subtitles,
    story_versions,
)
from services import story_timeline as timeline_mod
from services.story_models import (
    CAMERA_IDS,
    PACING_IDS,
    SHOT_SIZE_IDS,
    DESK_STEPS,
    STEP_IDS,
    STEPS,
    STORY_VIDEO_ENGINES,
    STYLE_BY_ID,
    SPEECH_MODES,
    STYLES,
    TRANSITION_IDS,
    VOICES,
    Scene,
    Story,
    apply_caps,
    can_enter,
    default_music_prompt,
    furthest_step,
    frame_scenes,
    frames_ready,
    scene_words,
    reachable_steps,
    resolution_options,
    take_groups,
)
from services.story_service import (
    display_url,
    get_backend,
    is_mock_mode,
)
from services.story_sets import (
    KINDS,
    Character,
    Location,
    Prop,
    StorySet,
    anchor_view,
    ensure_views,
    get_set_store,
)
from services.story_sets import duplicate as set_duplicate
from services.story_store import StoryAccessError, get_store
from state.state import AppState
from state.story_export_state import StoryExportState
from state.story_state import StoryState

logger = get_logger(__name__)

# The two audio types of a scene: a narrator over Omni's own (ambient) sound,
# or the person on screen speaking (Omni renders the speech).
AUDIO_VOICEOVER, AUDIO_ON_CAMERA = "voiceover", "camera"

STATUS_LABEL = {
    "queued": "Queued",
    "running": "Working",
    "done": "Done",
    "failed": "Failed",
    "skipped": "Skipped",
    "cancelled": "Cancelled",
}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def on_load(e: me.LoadEvent):
    s = me.state(StoryState)
    if not s.loaded:
        s.loaded = True
        _refresh_stories()
        _refresh_sets()
        story_id = me.query_params.get("id", "")
        if story_id:
            _open_story(story_id)
            step = me.query_params.get("step", "")
            if step and can_enter(step, _story()):
                s.step = step
                s.desk_tab = "set" if step == "set" else "shots"
    _refresh_brands()  # a brand made on /brand shows up on return
    filled = _prefill_idea()
    yield
    if take_autostart(filled):  # Home type chip: write the scenario now
        yield from on_generate_scenario(e)


# The step each story job shows while it runs (as the page's own buttons do).
_JOB_STEP = {
    "scenario": "scenario",
    "set": "set",
    "storyboard": "storyboard",
    "clips": "editor",
    "video": "video",
    "fix": "video",
}


def open_for_agent(story_id: str, step: str = "") -> None:
    """The voice agent opens a story at a step (also after the page loaded
    once, when on_load no longer reads ?id=). It follows the story's running
    job. Like the page's own Generate and Render buttons, a step whose job is
    running opens before it is reachable; otherwise the page falls back to the
    furthest step the story can reach."""
    s = me.state(StoryState)
    if not s.loaded:
        s.loaded = True
        _refresh_stories()
        _refresh_sets()
    _open_story(story_id)
    running = s.job_running and _JOB_STEP.get(s.job_kind) == step
    if step and (running or can_enter(step, _story())):
        s.step = step
        s.desk_tab = "set" if step == "set" else "shots"


def _prefill_idea() -> bool:
    """?prompt= (from the home page) opens Create with the idea filled in.

    Runs once per arrival. It starts a new story only from the Stories list or
    an empty idea, so an open story or a typed draft is never replaced. ?id=
    wins: a link to an existing story ignores ?prompt=.
    """
    s = me.state(StoryState)
    if me.query_params.get("id", ""):
        return False
    prompt = read_prompt_param()
    if not is_new_prompt_arrival(s, prompt):
        return False
    if s.step != "stories" and (s.idea or "").strip():
        return False
    if s.step == "stories" or s.story_id:
        _start_new_story()
    s.idea = prompt
    return True


@me.page(
    path="/story",
    title="Film Studio · Creative Studio",
    security_policy=me.SecurityPolicy(dangerously_disable_trusted_types=True),
    stylesheets=["/ui/story.css"],
    on_load=on_load,
)
def page():
    with page_scaffold(page_name="story"):
        with page_frame():
            header("Film Studio", "auto_stories", centered=True)
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
        elif step in DESK_STEPS and story:
            director_desk(story)
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
        s.error = f"Could not load your films: {exc}"
        rows = []
    s.stories_json = json.dumps(
        [
            {
                "id": r.id,
                "title": r.title
                or (r.idea[:48] + ("…" if len(r.idea) > 48 else ""))
                or "Untitled film",
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
    s.input_mode = getattr(story, "input_mode", "idea") or "idea"
    s.raw_script = getattr(story, "raw_script", "") or ""
    s.target_seconds = int(getattr(story, "target_seconds", 0) or 0)
    s.pacing = getattr(story, "pacing", "cinematic") or "cinematic"
    s.video_model = getattr(story, "video_model", "") or ""
    s.idea = story.idea
    s.character = story.character
    s.language = story.language
    s.second_on = story.second_on
    s.speech_mode = story.speech_mode
    s.shots = "one" if story.one_take else ("several" if story.scenes else "auto")
    s.brand_id = story.brand_id or ("none" if not story.brand_json else "")
    s.duration_text = (
        f"{story.target_seconds}s" if getattr(story, "target_seconds", 0) else ""
    )
    s.resolution = getattr(story, "resolution", "") or ""
    s.style_text = getattr(story, "style_prompt", "") or ""
    s.refs_json = story_refs.dump(story_refs.parse(getattr(story, "references_json", "")))
    s.ref_menu_open = False
    s.scene_count = story.scene_count
    s.duration = story.duration
    s.aspect_ratio = story.aspect_ratio
    s.style = story.style
    s.camera = story.camera
    s.reference_uri = story.reference_uri
    # A set made from Setup references is shown again as its references.
    s.create_set_id = "" if s.refs_json != "[]" else story.set_id
    s.auto_json = ""
    # Fields set by hand stay as they are when the idea is edited again.
    s.pinned_json = story.pinned_json or "[]"


def _open_story(story_id: str) -> None:
    s = me.state(StoryState)
    story = get_store().get(story_id, _owner())
    if story is None:
        s.error = "That film was not found."
        return
    try:
        story = story_jobs.ensure_set(story_id, _owner()) or story
    except Exception:  # never block opening a story on the migration
        logger.exception("Story Studio: set migration failed")
    _set_story(story)
    _load_form(story)
    _load_set(story, force=True)
    s.step = furthest_step(story)
    s.desk_tab = "set" if s.step == "set" else "shots"
    s.seq_filter = "all"
    s.animatic_index = 0
    s.expanded_shots_json = "[]"
    s.soundtrack_open = False
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
    s.job_kind = snap["kind"] if snap else ""
    s.job_misses = 0


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
    """One pill per step: Films, Setup, Script, Set, Frames, Takes, Music,
    Edit & Export. A step is done once a later one is open, and every step
    is done once the film is made."""
    s = me.state(StoryState)
    reach = reachable_steps(story)
    current = s.step if s.step in STEP_IDS else "stories"
    at = STEP_IDS.index(current)
    has_film = bool(story and story.final_uri)
    out = []
    for pos, (sid, label, _icon) in enumerate(STEPS):
        if sid == current:
            state = "current"
        elif story is not None and (pos < at or has_film):
            state = "done"
        else:
            state = "upcoming"
        out.append(
            {
                "id": sid,
                "label": label,
                "state": state,
                "enabled": sid in ("stories", "create") or sid in reach,
            }
        )
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
    elif target == "create":
        s.step = "create"
    elif can_enter(target, story):
        s.step = target
        if target in DESK_STEPS:
            s.desk_tab = "set" if target == "set" else "shots"
        if target == "set":
            _load_set(story)
    yield


# Ticks to keep checking the store after a job's snapshot goes missing.
JOB_MISS_LIMIT = 180


def _outputs_ready(story: Story | None, kind: str) -> bool:
    """The stored story already has what a job of `kind` makes."""
    if story is None:
        return True
    if kind == "storyboard":
        return frames_ready(story)
    if kind == "clips":
        return bool(story.scenes) and any(sc.clip_uri for sc in story.scenes)
    if kind in ("video", "export", "fix"):
        return bool(story.final_uri)
    if kind == "scenario":
        return bool(story.scenes)
    return False


def _on_missing_job(s: StoryState) -> None:
    """A job lives in the memory of the server instance that started it."""
    s.job_json = ""
    s.job_misses += 1
    story = _reload_story()
    if s.job_kind in ("set", "scenario"):
        _load_set(story)
    if s.job_misses >= JOB_MISS_LIMIT or _outputs_ready(story, s.job_kind):
        s.job_running = False
        s.job_misses = 0


# Jobs worth a browser notification (common/notify.py): the long ones.
NOTIFY_KINDS = (
    "scenario",
    "storyboard",
    "video",
    "export",
    "music",
    "subtitles",
    "fix",
)


def on_tick(e: me.WebEvent):
    s = me.state(StoryState)
    if not s.job_id:
        s.job_running = False
        return
    snap = story_jobs.job_snapshot(s.job_id, _owner())
    if snap is None:
        _on_missing_job(s)
        return
    s.job_misses = 0
    s.job_kind = snap["kind"]
    s.job_json = json.dumps(snap)
    finished = sum(
        1 for t in snap["tasks"] if t["status"] in ("done", "failed", "skipped")
    )
    if finished != s.job_tasks_done or snap["status"] != "running":
        s.job_tasks_done = finished
        story = _reload_story()
        if snap["kind"] in ("set", "scenario"):
            _load_set(story)
    if snap["status"] != "running" and snap.get("next_job"):
        # Setup's guided flow: the breakdown is written, then the set is
        # built and the frames paint. The page follows each job to its step.
        _watch(snap["next_job"])
        nxt = story_jobs.job_snapshot(snap["next_job"], _owner()) or {}
        if s.step in DESK_STEPS and nxt.get("kind") in _JOB_STEP:
            s.step = _JOB_STEP[nxt["kind"]]
        s.selected_shot = 0
        _reload_story()
        return
    if snap["status"] != "running":
        s.job_running = False
        story = _story()
        if snap["status"] == "cancelled":
            s.notice = "Job cancelled. Finished work was kept."
        elif (
            snap["kind"] == "video"
            and story
            and story.final_uri
            and snap["status"] == "done"
        ):
            s.notice = "Your film is ready. Edit it below, then export."
        elif snap["kind"] == "export" and snap["status"] == "done":
            s.notice = "Export finished. The new video is saved to your library."
        elif snap["kind"] == "music" and snap["status"] == "done":
            s.notice = "New music is on the timeline."
        elif snap["kind"] == "subtitles" and snap["status"] == "done":
            s.notice = "The subtitled film is ready. Download it below."
        elif snap["kind"] == "fix" and snap["status"] == "done":
            s.notice = "The fix is in the film. Play it back, or describe another fix."
        elif snap["kind"] == "set" and snap["status"] == "done":
            _refresh_sets()
        if snap["kind"] in NOTIFY_KINDS:
            if snap["status"] == "done":
                notify("Film Studio", s.notice or "Your film step is done.")
            elif snap["status"] == "failed":
                notify("Film Studio", "Something went wrong. Open the film to retry.")


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


def on_cancel_job(e: me.ClickEvent):
    s = me.state(StoryState)
    if not s.job_id:
        return
    cancel_fn = getattr(story_jobs, "cancel_job", None)
    if callable(cancel_fn):
        cancel_fn(s.job_id, _owner())
        snap = story_jobs.job_snapshot(s.job_id, _owner())
        s.job_json = json.dumps(snap) if snap else ""
        s.job_running = bool(snap and snap["status"] == "running")
        s.notice = "Cancelling current job…"


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
                    "cancelled": "Cancelled",
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
        if status == "running":
            with me.box(classes="ss-panel-foot"):
                me.text(
                    "Running in the background. You can cancel remaining tasks at any time.",
                    style=me.Style(
                        font_size=13,
                        color=me.theme_var("on-surface-variant"),
                        flex_grow=1,
                    ),
                )
                me.button(
                    "Cancel",
                    type="stroked",
                    color="warn",
                    on_click=on_cancel_job,
                    key="ss-panel-cancel",
                )
        elif status == "failed":
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
        "Your films",
        "Pick up where you left off, or start a new film from an idea or script.",
    )
    with me.box(classes="ss-stories"):
        with me.box(classes="ss-new", on_click=on_new_story):
            with me.box(classes="ss-new-icon"):
                me.icon("add", style=me.Style(font_size=28, width=28, height=28))
            me.text("Create new film", style=me.Style(font_weight=600, font_size=17))
            me.text(
                "Start a fresh film",
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
            "No films yet. Your films are saved here as you work.",
            style=me.Style(color=me.theme_var("on-surface-variant"), font_size=14),
        )
    sets_library()


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
                me.text(f"{r['scenes']} shots", style=me.Style(font_size=13))
                me.text("·", style=me.Style(font_size=13))
                me.text(
                    f"Updated {_fmt_date(r['updated'])}", style=me.Style(font_size=13)
                )
            with me.box(classes="ss-story-actions"):
                if s.confirm_delete_id == r["id"]:
                    me.text(
                        "Delete this film?", style=me.Style(font_size=14, flex_grow=1)
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
                        "Continue film",
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
    _start_new_story()


def _start_new_story() -> None:
    """Clear the draft and open the Setup step for a new story."""
    s = me.state(StoryState)
    _set_story(None)
    s.input_mode = "idea"
    s.raw_script = ""
    s.target_seconds = 0
    s.duration_text = ""
    s.pacing = "cinematic"
    s.video_model = ""
    s.resolution = ""
    s.style_text = ""
    s.idea = ""
    s.character = ""
    s.reference_uri = ""
    s.refs_json = "[]"
    s.ref_menu_open = False
    s.brand_id = ""
    s.create_set_id = ""
    s.auto_json = ""
    s.pinned_json = "[]"
    _put_set(None)
    s.job_id = ""
    s.job_json = ""
    s.job_running = False
    s.desk_tab = "shots"
    s.seq_filter = "all"
    s.soundtrack_open = False
    s.animatic_index = 0
    s.expanded_shots_json = "[]"
    s.selected_shot = 0
    s.refs_open = False
    s.preview_open = False
    s.redo_note = ""
    s.error = ""
    s.step = "create"
    _refresh_brands()


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
        s.error = "Could not delete that film."
    if s.story_id == story_id:
        _set_story(None)
    s.confirm_delete_id = ""
    _refresh_stories()


# ---------------------------------------------------------------------------
# Step 2: Setup (Create)
# ---------------------------------------------------------------------------


_SETUP_HANDLERS: setup_view.SetupHandlers | None = None


def _setup_handlers() -> setup_view.SetupHandlers:
    global _SETUP_HANDLERS
    if _SETUP_HANDLERS is None:
        _SETUP_HANDLERS = setup_view.SetupHandlers(
            on_input_mode=on_input_mode,
            on_idea_live=on_idea_live,
            on_idea_blur=on_idea_blur,
            on_script_blur=on_script_blur,
            on_duration_live=on_duration_live,
            on_duration_blur=on_duration_blur,
            on_pacing=on_pacing,
            on_shots=on_shots,
            on_speech=on_speech,
            on_video_model=on_video_model,
            on_aspect=on_aspect,
            on_language=on_language,
            on_second=on_second_setup,
            on_resolution=on_resolution,
            on_style_chip=on_style_chip,
            on_style_blur=on_style_blur,
            on_pick_set=on_pick_set,
            on_brand=on_brand,
            on_ref_menu=on_ref_menu,
            on_add_ref=on_add_ref,
            on_ref_tag=on_ref_tag,
            on_ref_role=on_ref_role,
            on_ref_voice=on_ref_voice,
            on_ref_upload=on_ref_upload,
            on_ref_mention=on_ref_mention,
            on_ref_remove=on_ref_remove,
            on_generate_scenario=on_generate_scenario,
            render_auto_note=_auto_note,
            fmt_secs=_fmt_secs,
        )
    return _SETUP_HANDLERS


def create_step(story: Story | None) -> None:
    s = me.state(StoryState)
    # No new breakdown while any step still works on this film.
    busy = _job_active_for(*desk_view.BUSY_KINDS, "music")
    setup_view.render_setup(
        s,
        story,
        busy=busy,
        set_rows=_sets_rows(),
        h=_setup_handlers(),
    )


def on_input_mode(e: me.ButtonToggleChangeEvent):
    if e.value in ("idea", "script"):
        me.state(StoryState).input_mode = e.value


def on_idea_blur(e: me.InputBlurEvent):
    me.state(StoryState).idea = e.value


def on_script_blur(e: me.InputBlurEvent):
    me.state(StoryState).raw_script = e.value


def _set_duration_text(text: str) -> None:
    s = me.state(StoryState)
    s.duration_text = " ".join(str(text or "").split())[:24]
    secs = story_director.parse_duration_text(s.duration_text)
    s.target_seconds = int(secs or 0)
    if secs:
        _pin("film_seconds")


def on_duration_live(e: me.WebEvent):
    """Typing paused in the duration box: the blueprint updates."""
    _set_duration_text(str((e.value or {}).get("value", "")))


def on_duration_blur(e: me.InputBlurEvent):
    _set_duration_text(e.value)


def on_pacing(e: me.ClickEvent):
    value = (e.key or "").split("-", 1)[-1]
    if value in PACING_IDS:
        me.state(StoryState).pacing = value
        _pin("pacing")


def on_shots(e: me.ClickEvent):
    value = (e.key or "").split("-", 1)[-1]
    if value in ("auto", "one", "several"):
        me.state(StoryState).shots = value
        if value == "auto":
            _unpin("shots")
            _reapply_auto()
        else:
            _pin("shots")


def on_speech(e: me.ClickEvent):
    value = (e.key or "").split("-", 1)[-1]
    if value in SPEECH_MODES:
        me.state(StoryState).speech_mode = value
        if value == "auto":
            _unpin("speech_mode")
            _reapply_auto()
        else:
            _pin("speech_mode")


def on_video_model(e: me.SelectSelectionChangeEvent):
    if e.value in STORY_VIDEO_ENGINES:
        s = me.state(StoryState)
        s.video_model = e.value
        if s.resolution and s.resolution not in resolution_options(e.value):
            s.resolution = ""
        _pin("video_model")


def on_resolution(e: me.SelectSelectionChangeEvent):
    s = me.state(StoryState)
    if e.value in resolution_options(setup_view.engine_of(s)):
        s.resolution = e.value


# -- Auto settings: read the film settings out of the idea while typing --


def _pinned() -> set[str]:
    try:
        return set(json.loads(me.state(StoryState).pinned_json or "[]"))
    except ValueError:
        return set()


def _unpin(field: str) -> None:
    s = me.state(StoryState)
    s.pinned_json = json.dumps(sorted(_pinned() - {field}))


def _pin(field: str) -> None:
    """The user set this field by hand: auto settings leave it alone."""
    s = me.state(StoryState)
    s.pinned_json = json.dumps(sorted(_pinned() | {field}))


def _apply_auto(found: dict) -> None:
    s = me.state(StoryState)
    current = {f: getattr(s, f) for f in story_autoset.FIELDS}
    for field, value in story_autoset.merge_settings(current, found, _pinned()).items():
        setattr(s, field, value)
    # Read from the idea, not picked: back to Auto when the idea stops
    # asking for it.
    for field in ("shots", "speech_mode"):
        if field not in found and field not in _pinned():
            setattr(s, field, "auto")
    if found.get("film_seconds"):  # the note shows the plan actually used
        found = {**found, "scene_count": s.scene_count, "duration": s.duration}
    s.auto_json = json.dumps(found) if found else ""


def on_idea_live(e: me.WebEvent):
    """Typing paused in the idea field: update the settings from it."""
    text = str((e.value or {}).get("value", ""))
    s = me.state(StoryState)
    s.live_text = text
    rules = story_autoset.infer_settings(text)
    _apply_auto(rules)
    yield
    if len(text.strip()) < 20:
        return
    try:
        refined = _live_settings(text)
    except Exception:
        logger.exception("Story Studio: live settings failed")
        return
    if s.live_text != text:
        return  # the idea changed while Gemini read it: a newer reply comes
    if refined:
        _apply_auto({**rules, **refined})
        yield


_LIVE_CACHE: dict[str, dict] = {}


def _live_settings(text: str) -> dict:
    """Gemini read of the idea, cached by its text (a pause in typing on
    the same text does not ask again)."""
    key = " ".join(text.split())
    if key not in _LIVE_CACHE:
        if len(_LIVE_CACHE) > 200:
            _LIVE_CACHE.clear()
        _LIVE_CACHE[key] = get_backend().live_settings(text) or {}
    return dict(_LIVE_CACHE[key])


def _reapply_auto() -> None:
    """Apply the last settings read from the idea again."""
    s = me.state(StoryState)
    try:
        found = json.loads(s.auto_json) if s.auto_json else {}
    except ValueError:
        found = {}
    if found.get("film_seconds"):
        found["scene_count"], found["duration"] = story_autoset.plan_length(
            found["film_seconds"]
        )
    _apply_auto(found)


def on_reset_auto(e: me.ClickEvent):
    """Let auto settings change every field again."""
    me.state(StoryState).pinned_json = "[]"
    _reapply_auto()


def _auto_note() -> None:
    s = me.state(StoryState)
    try:
        found = json.loads(s.auto_json) if s.auto_json else {}
    except ValueError:
        found = {}
    shown = {k: v for k, v in found.items() if k in _AUTO_SHOWN}
    summary = story_autoset.describe(shown)
    if not summary:
        return
    with me.box(classes="ss-auto-note", key="ss-auto-note"):
        me.icon("auto_awesome", style=me.Style(font_size=18, width=18, height=18))
        with me.box(classes="ss-auto-text"):
            me.text(f"From your idea: {summary}")
        if _pinned():
            me.button(
                "Use auto", type="stroked", on_click=on_reset_auto, key="ss-auto-reset"
            )


# What the note under the idea mentions (fields still on the Setup screen).
_AUTO_SHOWN = ("film_seconds", "aspect_ratio", "language", "style", "pacing", "video_model")


def on_pick_set(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).create_set_id = "" if e.value == "none" else e.value


def on_language(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).language = e.value
    _pin("language")


def on_second_setup(e: me.SlideToggleChangeEvent):
    s = me.state(StoryState)
    s.second_on = not s.second_on


def on_aspect(e: me.SelectSelectionChangeEvent):
    me.state(StoryState).aspect_ratio = e.value
    _pin("aspect_ratio")


def on_style_chip(e: me.ClickEvent):
    value = (e.key or "").split("-", 1)[-1]
    if value in STYLE_BY_ID:
        s = me.state(StoryState)
        s.style = value
        s.style_text = STYLE_BY_ID[value]["prompt"]
        _pin("style")


def on_style_blur(e: me.InputBlurEvent):
    s = me.state(StoryState)
    text = " ".join((e.value or "").split())[:400]
    preset = next((st["id"] for st in STYLES if st["prompt"] == text), "")
    if preset:
        s.style = preset
    s.style_text = text
    _pin("style")


# -- Brands --


def _refresh_brands() -> None:
    s = me.state(StoryState)
    try:
        s.brands_json = json.dumps(brand_kit.list_brands(_owner()))
    except Exception:
        logger.exception("Story Studio: could not list brands")
        s.brands_json = "[]"


def _brand_snapshot(owner: str, brand_id: str) -> tuple[str, str]:
    """(brand_id, snapshot JSON) for the story; ("", "") for no brand.
    "" means the owner's default brand."""
    if brand_id == "none":
        return "", ""
    brand = (
        brand_kit.get_brand(owner, brand_id)
        if brand_id
        else brand_kit.default_brand(owner)
    )
    snap = brand_kit.snapshot(brand)
    return (brand["id"], snap) if brand and snap else ("", "")


def on_brand(e: me.SelectSelectionChangeEvent):
    s = me.state(StoryState)
    if e.value == "new":
        me.navigate("/brand", query_params={"id": "new"})
        return
    s.brand_id = e.value if e.value else "none"


# -- References (services/story_refs.py) --


def _refs() -> list[dict]:
    return story_refs.parse(me.state(StoryState).refs_json)


def _put_refs(refs: list[dict]) -> None:
    me.state(StoryState).refs_json = story_refs.dump(refs)


def _ref_id(key: str) -> str:
    return (key or "").split("-", 1)[-1]


def _edit_ref(key: str, **changes) -> None:
    rid = _ref_id(key)
    _put_refs([{**r, **changes} if r["id"] == rid else r for r in _refs()])


def on_ref_menu(e: me.ClickEvent):
    s = me.state(StoryState)
    s.ref_menu_open = not s.ref_menu_open


def on_add_ref(e: me.ClickEvent):
    s = me.state(StoryState)
    kind = _ref_id(e.key)
    s.ref_menu_open = False
    if kind == "brand":
        _refresh_brands()
        try:
            rows = json.loads(s.brands_json or "[]")
        except ValueError:
            rows = []
        if not rows:
            me.navigate("/brand", query_params={"id": "new"})
            return
        if s.brand_id in ("", "none"):
            default = next((b for b in rows if b.get("is_default")), rows[0])
            s.brand_id = default["id"]
        return
    refs = _refs()
    ref = story_refs.new_ref(kind, refs)
    if ref is None:
        s.error = f"Up to {story_refs.MAX_REFS} references."
        return
    _put_refs([*refs, ref])


def on_ref_tag(e: me.InputBlurEvent):
    tag = story_refs.clean_tag(e.value)
    if tag:
        _edit_ref(e.key, tag=tag)


def on_ref_role(e: me.InputBlurEvent):
    _edit_ref(e.key, role=e.value)


def on_ref_voice(e: me.SelectSelectionChangeEvent):
    _edit_ref(e.key, voice=e.value)


def on_ref_upload(e: me.UploadEvent):
    s = me.state(StoryState)
    try:
        uri = get_backend().save_upload(e.file.getvalue(), e.file.mime_type)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _edit_ref(e.key, uri=uri)


def on_ref_mention(e: me.ClickEvent):
    s = me.state(StoryState)
    ref = next((r for r in _refs() if r["id"] == _ref_id(e.key)), None)
    if ref is None:
        return
    s.input_mode = "idea"
    s.idea = story_refs.mention(s.idea, ref["tag"])


def on_ref_remove(e: me.ClickEvent):
    rid = _ref_id(e.key)
    _put_refs([r for r in _refs() if r["id"] != rid])


def _story_set_for(owner: str, story: Story, refs: list[dict], picked: str) -> str:
    """The set id the story uses: the picked set, or a copy of it (or a new
    set) with the references added."""
    base = get_set_store().get(picked, owner) if picked else None
    if not refs:
        return base.id if base else ""
    made = story_refs.build_set(
        refs,
        base=base,
        owner=owner,
        name=f"{(story.idea or 'Story')[:40]} references" if base is None else "",
        style=story.style,
    )
    if made is None:
        return base.id if base else ""
    return get_set_store().save(made, owner).id


def setup_plan(s: StoryState) -> tuple[int, int, int]:
    """(target seconds, scene count, scene length) from the Setup screen."""
    seconds, source = setup_view.film_seconds(s)
    if s.input_mode == "script" and source == "script":
        try:
            parsed = story_director.parse_user_script(
                s.raw_script,
                language=s.language,
                speech_mode=s.speech_mode,
                pacing=s.pacing,
                target_seconds=0,
            )
            scenes = parsed.get("scenes") or []
            if scenes:
                dur = max(
                    4,
                    round(
                        sum(int(sc.get("seconds") or s.duration) for sc in scenes)
                        / len(scenes)
                    ),
                )
                return 0, len(scenes), dur
        except Exception:
            logger.exception("Story Studio: script parse failed")
    bp = story_director.plan_film_blueprint(
        seconds or story_director.DEFAULT_FILM_SECONDS,
        pacing=s.pacing,
        video_model=setup_view.engine_of(s),
        one_take=setup_view.one_take_of(s),
    )
    return int(seconds or 0), int(bp["scene_count"]), int(bp["duration"])


def on_generate_scenario(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    if s.input_mode == "script":
        raw = (s.raw_script or "").strip()
        if len(raw) < 8:
            s.error = "Paste your script or voiceover first."
            return
        idea = (s.idea or "").strip() or raw[:200]
    else:
        idea = (s.idea or "").strip()
        if len(idea) < 8:
            s.error = "Describe your idea in a sentence or two first."
            return
    if s.duration_text.strip() and story_director.parse_duration_text(s.duration_text) is None:
        s.error = 'Write a length like "30s", "2 min" or "1:30", or leave it empty.'
        return

    target, req_count, req_dur = setup_plan(s)
    caps = apply_caps(
        req_count, req_dur, resolution=s.resolution, model_id=setup_view.engine_of(s)
    )
    s.scene_count, s.duration = caps.scene_count, caps.duration
    s.target_seconds = target
    owner = _owner()
    refs = _refs()
    try:
        if s.story_id:
            story_jobs.ensure_free(s.story_id)
        existing = get_store().get(s.story_id, owner) if s.story_id else None
        story = existing or Story()
        if story.idea != idea:
            story.brief = ""  # a new idea: Gemini writes a new brief
        story.input_mode = s.input_mode if s.input_mode in ("idea", "script") else "idea"
        story.raw_script = s.raw_script if story.input_mode == "script" else ""
        story.one_take = setup_view.one_take_of(s)
        story.target_seconds = int(target or 0) or (
            story_director.DEFAULT_FILM_SECONDS if story.one_take else 0
        )
        story.pacing = s.pacing if s.pacing in PACING_IDS else "cinematic"
        story.video_model = s.video_model
        story.resolution = caps.resolution if s.resolution else ""
        story.idea = idea
        story.character = ""
        story.language = s.language
        story.second_on = s.second_on
        # Who speaks and the camera move come from the idea (read while
        # typing, story_autoset); the director reads the idea text too.
        story.speech_mode = s.speech_mode if s.speech_mode in SPEECH_MODES else "auto"
        story.pinned_json = s.pinned_json or "[]"
        story.camera = s.camera if s.camera in CAMERA_IDS else "auto"
        story.brand_id, story.brand_json = _brand_snapshot(owner, s.brand_id)
        story.scene_count = caps.scene_count
        story.duration = caps.duration
        story.aspect_ratio = s.aspect_ratio
        story.style = s.style if s.style in STYLE_BY_ID else "photographic"
        preset = STYLE_BY_ID[story.style]["prompt"]
        story.style_prompt = "" if s.style_text in ("", preset) else s.style_text
        story.reference_uri = ""
        story.references_json = story_refs.dump(refs)
        voice = story_refs.narrator_voice(refs)
        if voice:
            story.voice_name = voice
        picked = s.create_set_id
        if picked and get_set_store().get(picked, owner) is None:
            picked = ""
        story.set_id = _story_set_for(owner, story, refs, picked)
        story.set_version = 0
        story.cast_json = ""
        story.scenes = []
        story.approved = False
        story.clear_films()
        story.step = "scenario"
        story = get_store().save(story, owner)
        _set_story(story)
        _load_set(story, force=True)
        _refresh_sets()
        job = story_jobs.start_scenario(story.id, owner, then_frames=True)
    except Exception as exc:
        logger.exception("Story Studio: could not start scenario")
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)
    s.step = "scenario"
    s.desk_tab = "shots"
    s.seq_filter = "all"
    s.selected_shot = 0
    s.preview_open = False
    s.refs_open = False
    s.redo_note = ""
    s.animatic_index = 0
    yield


# ---------------------------------------------------------------------------
# Step 3: Director's Desk (Scenario, Set, Storyboard, Shots)
# ---------------------------------------------------------------------------


_DESK_HANDLERS: desk_view.DeskHandlers | None = None


def _desk_handlers() -> desk_view.DeskHandlers:
    global _DESK_HANDLERS
    if _DESK_HANDLERS is None:
        _DESK_HANDLERS = desk_view.DeskHandlers(
            on_title_blur=on_title_blur,
            on_brief_blur=on_brief_blur,
            on_visual_grammar_blur=on_visual_grammar_blur,
            on_select_shot=on_select_shot,
            on_toggle_preview=on_toggle_preview,
            on_make_set=on_make_set,
            on_paint_all_frames=on_paint_all_frames,
            on_render=on_render,
            on_to_video=on_to_video,
            on_cancel_job=on_cancel_job,
            on_rewrite_all=on_rewrite_all,
            on_rewrite_scene=on_rewrite_scene,
            on_redo_note=on_redo_note,
            on_redo_frame=on_redo_frame,
            on_redo_clip=on_redo_clip,
            on_redo_turn=on_redo_turn,
            on_add_shot=on_add_shot,
            on_move_up=on_move_up,
            on_move_down=on_move_down,
            on_remove_scene=on_remove_scene,
            on_scene_shot_size=on_scene_shot_size,
            on_scene_camera=on_scene_camera,
            on_scene_duration=on_scene_duration,
            on_scene_visual=on_scene_visual,
            on_scene_motion_prompt=on_scene_motion_prompt,
            on_scene_audio_cue=on_scene_audio_cue,
            on_scene_transition=on_scene_transition,
            on_scene_narration_alt=on_scene_narration_alt,
            on_toggle_music=on_toggle_music,
            on_music_prompt=on_music_prompt,
            on_make_music=on_make_music,
            on_add_track=on_add_track,
            on_track_take=on_track_take,
            on_track_prompt=on_track_prompt,
            on_remove_track=on_remove_track,
            on_toggle_voice=on_toggle_voice,
            on_voice=on_voice,
            on_speaker_voice=on_speaker_voice,
            on_update_set=on_update_set,
            on_save_set_as_new=on_save_set_as_new,
            on_add_asset=on_add_asset,
            on_set_field=on_set_field,
            on_animatic_prev=on_animatic_prev,
            on_animatic_next=on_animatic_next,
            on_animatic_select=on_animatic_select,
            set_handlers=_handlers,
            render_line_fields=_line_fields,
            render_media_box=_media_box,
            render_progress_panel=progress_panel,
            scene_task=_scene_task,
            job_active_for=_job_active_for,
            job_dict=_job,
            set_tasks=_set_tasks,
            fmt_secs=_fmt_secs,
            dir_class=_dir_class,
            sr=_sr,
            chip=_chip,
        )
    return _DESK_HANDLERS


def director_desk(story: Story) -> None:
    s = me.state(StoryState)
    story_set = _set()
    if story.set_id and (story_set is None or story_set.id != story.set_id):
        # Opened straight on a step (a saved story, the guided flow): read the
        # story's set without touching the page's working copy.
        story_set = get_set_store().get(story.set_id, _owner())
    desk_view.render_desk(
        s,
        story,
        story_set,
        is_demo=is_mock_mode(),
        h=_desk_handlers(),
    )


def scenario_step(story: Story) -> None:
    director_desk(story)


def set_step(story: Story) -> None:
    me.state(StoryState).desk_tab = "set"
    director_desk(story)


def storyboard_step(story: Story) -> None:
    director_desk(story)


def editor_step(story: Story) -> None:
    director_desk(story)


def _line_fields(story: Story, sc, prefix: str, disabled: bool) -> None:
    """The scene's audio type (voiceover or on camera), the line itself, and
    how many words fit."""
    with me.box(classes="gm-segmented ss-audio-type"):
        me.button_toggle(
            value=AUDIO_ON_CAMERA if sc.spoken else AUDIO_VOICEOVER,
            buttons=[
                me.ButtonToggleButton(label="Voiceover", value=AUDIO_VOICEOVER),
                me.ButtonToggleButton(label="On camera", value=AUDIO_ON_CAMERA),
            ],
            multiple=False,
            hide_selection_indicator=True,
            disabled=disabled,
            on_change=on_scene_audio,
            key=f"{prefix}spk-{sc.id}",
        )
    me.textarea(
        label="Line spoken on camera" if sc.spoken else "Narration (voiceover)",
        value=sc.narration,
        autosize=True,
        min_rows=4 if sc.duration > 10 else 2,
        max_rows=14,
        appearance="outline",
        disabled=disabled,
        on_blur=on_scene_narration,
        style=me.Style(width="100%"),
        key=f"{prefix}nar-{sc.id}",
    )
    index = next((n for n, x in enumerate(story.scenes) if x.id == sc.id), None)
    fit = scene_words(sc, story, index)
    if sc.narration.strip() and sc.line_too_long(story, index):
        me.text(
            f"Too long for {sc.duration}s: about {fit} words fit."
            + ("" if sc.spoken else " It will be shortened when voiced."),
            style=me.Style(font_size=13, color=me.theme_var("error")),
        )
    else:
        me.text(
            f"About {fit} words fit.",
            style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
        )


def _scene_id_from_key(key: str) -> str:
    return key.split("-", 1)[1]


def _same_value(old, new) -> bool:
    """True when saving a field would not really change it (a box blurred
    with no edit, or text that only differs in surrounding whitespace)."""
    if isinstance(old, str) and isinstance(new, str):
        return old.strip() == new.strip()
    return old == new


def _update_scene(
    scene_id: str, field: str, value, clear: tuple[str, ...] = ("clip_uri",)
) -> None:
    def apply(story: Story) -> None:
        for sc in story.scenes:
            if sc.id == scene_id and not _same_value(getattr(sc, field), value):
                setattr(sc, field, value)
                for c in clear:
                    if c == "clip_uri":
                        sc.clear_clip()
                    else:
                        setattr(sc, c, "")
                story.clear_films()

    _edit(apply)


def on_select_shot(e: me.ClickEvent):
    try:
        idx = int((e.key or "").split("-", 1)[1])
    except (IndexError, ValueError):
        return
    s = me.state(StoryState)
    if idx != s.selected_shot:
        s.redo_note = ""
    s.selected_shot = max(0, idx)
    s.animatic_index = s.selected_shot


def on_toggle_preview(e: me.ClickEvent):
    s = me.state(StoryState)
    s.preview_open = not s.preview_open
    s.animatic_index = s.selected_shot


def on_redo_note(e: me.InputBlurEvent):
    me.state(StoryState).redo_note = " ".join((e.value or "").split())[:400]


def _selected() -> tuple[Story | None, int]:
    s = me.state(StoryState)
    story = _story()
    if story is None or not story.scenes:
        return None, 0
    return story, max(0, min(s.selected_shot, len(story.scenes) - 1))


def on_redo_frame(e: me.ClickEvent):
    """Repaint the start frame of the selected shot's take, with the note."""
    s = me.state(StoryState)
    s.error = ""
    story, i = _selected()
    if story is None:
        return
    try:
        job = story_jobs.start_storyboard(s.story_id, _owner(), [i], note=s.redo_note)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    s.redo_note = ""
    _watch(job.id)


def redo_clip_plan(story: Story, index: int) -> tuple[list[int], bool]:
    """(scenes whose clips are made again, whole take?) for "Redo clip" on
    scene `index`: a one-shot take is remade alone; inside a longer take the
    clip and every later clip of that take are made again in order."""
    group = next((g for g in take_groups(story) if index in g), [index])
    if len(group) == 1:
        return [index], False
    return [j for j in group if j >= index], True


def on_redo_clip(e: me.ClickEvent):
    """Make the selected shot's clip again. The note goes into its Action
    text (kept, so the next redo uses it too)."""
    s = me.state(StoryState)
    s.error = ""
    story, i = _selected()
    if story is None:
        return
    redo, whole_take = redo_clip_plan(story, i)
    note = s.redo_note.strip()
    ids = {story.scenes[j].id for j in redo}
    target = story.scenes[i].id

    def apply(st: Story) -> None:
        st.approved = True
        for sc in st.scenes:
            if sc.id == target and note:
                sc.motion_prompt = f"{sc.motion_prompt.strip()} {note}".strip()[:1200]
            if sc.id in ids:
                sc.clear_clip()
        st.clear_films()

    if _edit(apply) is None:
        return
    try:
        job = (
            story_jobs.start_video(s.story_id, _owner())
            if whole_take
            else story_jobs.start_scene_clips(s.story_id, _owner(), [i])
        )
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    s.redo_note = ""
    _watch(job.id)


def on_redo_turn(e: me.ClickEvent):
    """Make one turn of a take again (key redoturn-<scene>-<turn>)."""
    s = me.state(StoryState)
    s.error = ""
    try:
        _, index, turn = (e.key or "").split("-")
        index, turn = int(index), int(turn)
    except ValueError:
        return
    try:
        job = story_jobs.start_turn_redo(s.story_id, _owner(), index, turn)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_seq_filter(e: me.ClickEvent):
    val = (e.key or "").split("|", 1)[1] if "|" in (e.key or "") else "all"
    me.state(StoryState).seq_filter = val or "all"


def on_brief_blur(e: me.InputBlurEvent):
    value = e.value.strip()[:1500]

    def apply(story: Story) -> None:
        story.brief = value

    _edit(apply)


def on_visual_grammar_blur(e: me.InputBlurEvent):
    value = e.value.strip()[:400]

    def apply(story: Story) -> None:
        story.visual_grammar = value

    _edit(apply)


def on_title_blur(e: me.InputBlurEvent):
    value = e.value.strip()[:120]

    def apply(story: Story) -> None:
        story.title = value

    _edit(apply)


def on_scene_narration(e: me.InputBlurEvent):
    scene_id = _scene_id_from_key(e.key)
    story = _story()
    spoken = bool(
        story and any(sc.id == scene_id and sc.spoken for sc in story.scenes)
    )
    clear = ("narration_alt", "clip_uri") if spoken else ("narration_alt",)
    _update_scene(scene_id, "narration", e.value.strip(), clear=clear)


def on_scene_audio(e: me.ButtonToggleChangeEvent):
    """Voiceover or on camera for one scene (the clip changes with it)."""
    if not e.value:
        return
    scene_id = _scene_id_from_key(e.key)
    spoken = e.value == AUDIO_ON_CAMERA

    def apply(story: Story) -> None:
        for sc in story.scenes:
            if sc.id == scene_id and sc.spoken != spoken:
                sc.spoken = spoken
                sc.clear_clip()
                story.clear_films()

    _edit(apply)


def on_speaker_voice(e: me.InputBlurEvent):
    value = e.value.strip()[:200]

    def apply(story: Story) -> None:
        story.speaker_voice = value

    _edit(apply)


def on_scene_narration_alt(e: me.InputBlurEvent):
    scene_id, value = _scene_id_from_key(e.key), e.value.strip()

    def apply(story: Story) -> None:
        for sc in story.scenes:
            if sc.id == scene_id and not _same_value(sc.narration_alt, value):
                sc.narration_alt = value
                story.final_alt_uri = ""

    _edit(apply)


def on_scene_visual(e: me.InputBlurEvent):
    _update_scene(_scene_id_from_key(e.key), "visual", e.value.strip())


def on_scene_motion_prompt(e: me.InputBlurEvent):
    _update_scene(_scene_id_from_key(e.key), "motion_prompt", e.value.strip())


def on_scene_audio_cue(e: me.InputBlurEvent):
    _update_scene(_scene_id_from_key(e.key), "audio_cue", e.value.strip())


def on_scene_shot_size(e: me.SelectSelectionChangeEvent):
    if e.value in SHOT_SIZE_IDS:
        _update_scene(_scene_id_from_key(e.key), "shot_size", e.value)


def on_scene_camera(e: me.SelectSelectionChangeEvent):
    _update_scene(_scene_id_from_key(e.key), "camera", e.value)


def on_scene_transition(e: me.ClickEvent):
    parts = (e.key or "").split("|")
    if len(parts) < 3:
        return
    scene_id, trans = parts[1], parts[2]
    if trans not in TRANSITION_IDS:
        return

    def apply(story: Story) -> None:
        for idx, sc in enumerate(story.scenes):
            if sc.id == scene_id and sc.transition != trans:
                sc.transition = trans
                sc.clear_clip()
                if idx > 0:
                    story.scenes[idx - 1].clear_clip()
                story.clear_films()

    _edit(apply)


def on_add_shot(e: me.ClickEvent):
    scene_id = _scene_id_from_key(e.key)

    def apply(story: Story) -> None:
        idx = next((i for i, sc in enumerate(story.scenes) if sc.id == scene_id), -1)
        if idx < 0:
            return
        ref = story.scenes[idx]
        new_sc = Scene(
            sequence=ref.sequence,
            camera=ref.camera if ref.camera in CAMERA_IDS else "static",
            duration=ref.duration,
            shot_size="medium",
            location_id=ref.location_id,
            cast=list(ref.cast),
        )
        story.scenes.insert(idx + 1, new_sc)
        story.scene_count = len(story.scenes)
        story.clear_films()

    _edit(apply)


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




def on_paint_all_frames(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    if s.set_dirty and _save_draft() is None:
        return
    story = _story()
    if story is None or not story.scenes:
        return
    if not story.approved:
        story = _edit(lambda st: setattr(st, "approved", True))
        if story is None:
            return
    # Only take starts get a frame; the rest of a take continues its clip.
    indices = None if not frames_ready(story) else frame_scenes(story)
    try:
        job = story_jobs.start_storyboard(s.story_id, _owner(), indices)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_animatic_prev(e: me.ClickEvent):
    s = me.state(StoryState)
    s.animatic_index = max(0, s.animatic_index - 1)


def on_animatic_next(e: me.ClickEvent):
    s = me.state(StoryState)
    story = _story()
    hi = max(0, len(story.scenes) - 1) if story else 0
    s.animatic_index = min(hi, s.animatic_index + 1)


def on_animatic_select(e: me.ClickEvent):
    try:
        idx = int((e.key or "").split("-", 1)[1])
    except (IndexError, ValueError):
        return
    me.state(StoryState).animatic_index = max(0, idx)


# ---------------------------------------------------------------------------
# Sets: helpers
# ---------------------------------------------------------------------------


def _set() -> StorySet | None:
    """The Set step's working copy of the story's set."""
    s = me.state(StoryState)
    if not s.set_json:
        return None
    try:
        return StorySet.from_dict(json.loads(s.set_json))
    except ValueError:
        return None


def _put_set(story_set: StorySet | None, dirty: bool = False) -> None:
    s = me.state(StoryState)
    s.set_json = json.dumps(story_set.to_dict()) if story_set else ""
    s.set_dirty = dirty if story_set else False


def _load_set(story: Story | None, force: bool = False) -> None:
    """Copy the story's stored set into the page (keeps unsaved edits)."""
    s = me.state(StoryState)
    if s.set_dirty and not force:
        return
    st = (
        get_set_store().get(story.set_id, _owner())
        if story is not None and story.set_id
        else None
    )
    _put_set(st)


def _refresh_sets() -> None:
    s = me.state(StoryState)
    try:
        rows = get_set_store().list(_owner())
    except Exception:
        logger.exception("Story Studio: could not list sets")
        rows = []
    out = []
    for r in rows:
        cover = next((u for u in r.media_uris() if not u.endswith(".wav")), "")
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "summary": r.summary(),
                "version": r.version,
                "updated": r.updated_at,
                "cover": cover,
            }
        )
    s.sets_json = json.dumps(out)


def _sets_rows() -> list[dict]:
    return json.loads(me.state(StoryState).sets_json or "[]")


def _merge_into(stored: StorySet, draft: StorySet) -> None:
    """Write the draft's text and asset list into the stored set."""
    old = {(k, a.id): a for k in KINDS for a in stored.assets(k)}
    for kind in KINDS:
        for asset in draft.assets(kind):
            before = old.get((kind, asset.id))
            if before is None:
                continue
            have = {i.view: i for i in before.images}
            for img in asset.images:
                if not img.uri and have.get(img.view) and have[img.view].uri:
                    img.uri, img.prompt = have[img.view].uri, have[img.view].prompt
                    img.locked = have[img.view].locked
            if isinstance(asset, Character) and not asset.voice.sample_uri:
                same = (
                    before.voice.tts_voice == asset.voice.tts_voice
                    and before.voice.style == asset.voice.style
                )
                if same:
                    asset.voice.sample_uri = before.voice.sample_uri
    stored.name = draft.name
    stored.style_notes = draft.style_notes
    stored.characters = draft.characters
    stored.locations = draft.locations
    stored.props = draft.props


def _save_draft() -> StorySet | None:
    """Save the Set step's edits (if any). Returns the saved set."""
    s = me.state(StoryState)
    draft = _set()
    if draft is None:
        return None
    if not s.set_dirty:
        return draft
    try:
        saved = story_jobs.mutate_set(
            draft.id, _owner(), lambda st: _merge_into(st, draft)
        )
    except StoryAccessError as exc:
        s.error = str(exc)
        return None
    _put_set(saved)
    return saved


def _edit_draft(fn) -> None:
    """Change the working copy; nothing is saved or regenerated yet."""
    draft = _set()
    if draft is None:
        return
    before = json.dumps(draft.to_dict(), sort_keys=True)
    fn(draft)
    if json.dumps(draft.to_dict(), sort_keys=True) != before:
        _put_set(draft, dirty=True)


def _set_tasks() -> dict:
    """(kind, asset id, view) -> task of the set job being watched."""
    job = _job()
    if not job or job.get("kind") != "set":
        return {}
    targets = job.get("targets") or {}
    return {
        tuple(targets[t["id"]]): t
        for t in job.get("tasks", [])
        if t["id"] in targets and t["status"] != "done"
    }


def _start_set(targets: list | None = None) -> None:
    s = me.state(StoryState)
    story = _story()
    if story is not None and not story.approved:
        _edit(lambda st: setattr(st, "approved", True))
    if _save_draft() is None and _set() is not None:
        return
    try:
        job = story_jobs.start_set(s.story_id, _owner(), targets)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


SET_HANDLERS: SetHandlers | None = None


def _handlers() -> SetHandlers:
    global SET_HANDLERS
    if SET_HANDLERS is None:
        SET_HANDLERS = SetHandlers(
            on_field=on_set_field,
            on_voice=on_set_voice,
            on_regen=on_set_regen,
            on_lock=on_set_lock,
            on_upload=on_set_upload,
            on_library=on_set_library,
            on_play=on_set_play,
            on_remove=on_set_remove,
            library_button=library_chooser_button,
        )
    return SET_HANDLERS


_TEXT_FIELDS = {"name", "description", "outfit", "time_of_day"}


def on_set_field(e: me.InputBlurEvent):
    action, kind, asset_id, _ = parse_key(e.key)
    value = (e.value or "").strip()

    def apply(draft: StorySet) -> None:
        if action == "setname":
            draft.name = value or draft.name
            return
        asset = draft.asset(kind, asset_id)
        if asset is None:
            return
        if action in _TEXT_FIELDS:
            setattr(asset, action, value)
        elif action == "style" and asset.voice.style != value:
            asset.voice.style = value
            asset.voice.sample_uri = ""
        elif action == "voice_description":
            asset.voice.description = value

    _edit_draft(apply)


def on_set_voice(e: me.SelectSelectionChangeEvent):
    _, kind, asset_id, _ = parse_key(e.key)

    def apply(draft: StorySet) -> None:
        asset = draft.asset(kind, asset_id)
        if (
            asset is not None
            and e.value in VOICES
            and asset.voice.tts_voice != e.value
        ):
            asset.voice.tts_voice = e.value
            asset.voice.sample_uri = ""

    _edit_draft(apply)


def on_set_regen(e: me.ClickEvent):
    _, kind, asset_id, view = parse_key(e.key)
    me.state(StoryState).play_sample_id = ""
    _start_set([[kind, asset_id, view]])


def _change_stored(fn) -> None:
    """Save the draft, then change the stored set (lock, uploads)."""
    s = me.state(StoryState)
    draft = _save_draft()
    if draft is None:
        return
    try:
        _put_set(story_jobs.mutate_set(draft.id, _owner(), fn))
    except StoryAccessError as exc:
        s.error = str(exc)


def on_set_lock(e: me.ClickEvent):
    _, kind, asset_id, view = parse_key(e.key)

    def apply(st: StorySet) -> None:
        asset = st.asset(kind, asset_id)
        for img in asset.images if asset else []:
            if img.view == view and img.uri:
                img.locked = not img.locked

    _change_stored(apply)


def _replace_main_image(kind: str, asset_id: str, uri: str) -> None:
    """Use the user's own picture as the asset's main image (locked)."""

    def apply(st: StorySet) -> None:
        asset = st.asset(kind, asset_id)
        if asset is None:
            return
        ensure_views(asset)
        main = anchor_view(asset) if kind != "prop" else "item"
        for img in asset.images:
            if img.view == main:
                img.uri, img.prompt, img.locked = uri, "", True

    _change_stored(apply)


def on_set_upload(e: me.UploadEvent):
    s = me.state(StoryState)
    _, kind, asset_id, _ = parse_key(e.key)
    try:
        uri = get_backend().save_upload(e.file.getvalue(), e.file.mime_type)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _replace_main_image(kind, asset_id, uri)


def on_set_library(e: LibrarySelectionChangeEvent):
    _, kind, asset_id, _ = parse_key(e.chooser_id)
    if e.gcs_uri:
        _replace_main_image(kind, asset_id, e.gcs_uri)


def on_set_play(e: me.ClickEvent):
    s = me.state(StoryState)
    _, _, asset_id, _ = parse_key(e.key)
    s.play_sample_id = "" if s.play_sample_id == asset_id else asset_id


def on_set_remove(e: me.ClickEvent):
    _, kind, asset_id, _ = parse_key(e.key)

    def apply(draft: StorySet) -> None:
        items = draft.assets(kind)
        items[:] = [a for a in items if a.id != asset_id]

    _edit_draft(apply)


def on_add_asset(e: me.ClickEvent):
    kind = e.key.split("|", 1)[1]

    def apply(draft: StorySet) -> None:
        n = len(draft.assets(kind)) + 1
        made = {
            "character": lambda: Character(name=f"Character {n}"),
            "location": lambda: Location(name=f"Location {n}"),
            "prop": lambda: Prop(name=f"Prop {n}"),
        }[kind]()
        ensure_views(made)
        draft.assets(kind).append(made)

    _edit_draft(apply)


def on_make_set(e: me.ClickEvent):
    me.state(StoryState).error = ""
    _start_set()


def on_update_set(e: me.ClickEvent):
    s = me.state(StoryState)
    if _save_draft() is not None:
        s.notice = "Set updated."
        _refresh_sets()


def on_save_set_as_new(e: me.ClickEvent):
    s = me.state(StoryState)
    draft = _set()
    if draft is None:
        return
    owner = _owner()
    try:
        current = get_set_store().get(draft.id, owner)
        name = draft.name
        if current is not None and name == current.name:
            name = f"{name} copy"
        made = get_set_store().save(set_duplicate(draft, owner, name), owner)
        story_jobs.attach_set(s.story_id, owner, made.id, keep_links=True)
    except StoryAccessError as exc:
        s.error = str(exc)
        return
    _reload_story()
    _put_set(made)
    _refresh_sets()
    s.notice = f"Saved as “{made.name}”. This film now uses it."



# ---------------------------------------------------------------------------
# Sets library (on the Stories step)
# ---------------------------------------------------------------------------


def sets_library() -> None:
    s = me.state(StoryState)
    rows = _sets_rows()
    if not rows:
        return
    _section_title("Your sets", "Reuse the same cast and places in any film.")
    with me.box(classes="ss-stories ss-sets"):
        for r in rows:
            with me.box(classes="ss-story ss-set-row"):
                with me.box(classes="ss-story-cover"):
                    if r.get("cover"):
                        me.image(
                            src=display_url(r["cover"]),
                            alt="",
                            style=me.Style(
                                width="100%", height="100%", object_fit="cover"
                            ),
                        )
                    else:
                        with me.box(classes="ss-media-overlay"):
                            me.icon("groups")
                with me.box(classes="ss-story-body"):
                    if s.rename_set_id == r["id"]:
                        me.input(
                            label="Set name",
                            value=r["name"],
                            appearance="outline",
                            on_blur=on_rename_set,
                            style=me.Style(width="100%"),
                            key=f"rename-{r['id']}",
                        )
                    else:
                        me.text(
                            r["name"],
                            style=me.Style(font_weight=600, font_size=16),
                        )
                    with me.box(classes="ss-meta"):
                        me.text(r["summary"], style=me.Style(font_size=13))
                        me.text("·", style=me.Style(font_size=13))
                        me.text(
                            f"Updated {_fmt_date(r['updated'])}",
                            style=me.Style(font_size=13),
                        )
                    with me.box(classes="ss-set-lib-tools"):
                        me.button(
                            "Rename",
                            type="stroked",
                            on_click=on_ask_rename_set,
                            key=f"rn-{r['id']}",
                        )
                        me.button(
                            "Duplicate",
                            type="stroked",
                            on_click=on_duplicate_set,
                            key=f"dup-{r['id']}",
                        )
                        me.button(
                            "Delete",
                            type="stroked",
                            on_click=on_ask_delete_set,
                            key=f"dset-{r['id']}",
                        )
    target = next((r for r in rows if r["id"] == s.confirm_delete_set_id), None)
    with dialog(is_open=target is not None, key="ss-delete-set-dialog"):  # pylint: disable=not-context-manager
        me.text(
            f"Delete “{target['name']}”?" if target else "Delete set?",
            type="headline-6",
            style=me.Style(margin=me.Margin(bottom=8)),
        )
        me.text(
            "Films that use it keep their renders, but new renders won't use it.",
            style=me.Style(font_size=14, color=me.theme_var("on-surface-variant")),
        )
        with dialog_actions():  # pylint: disable=not-context-manager
            me.button("Cancel", type="stroked", on_click=on_cancel_delete_set)
            me.button(
                "Delete", type="flat", color="warn", on_click=on_confirm_delete_set
            )


def on_ask_rename_set(e: me.ClickEvent):
    me.state(StoryState).rename_set_id = e.key.split("-", 1)[1]


def on_rename_set(e: me.InputBlurEvent):
    s = me.state(StoryState)
    set_id = e.key.split("-", 1)[1]
    name = (e.value or "").strip()
    s.rename_set_id = ""
    if name:

        def apply(st: StorySet) -> None:
            st.name = name[:60]

        try:
            saved = story_jobs.mutate_set(set_id, _owner(), apply)
        except StoryAccessError as exc:
            s.error = str(exc)
            return
        if _set() is not None and _set().id == set_id and not s.set_dirty:
            _put_set(saved)
    _refresh_sets()


def on_duplicate_set(e: me.ClickEvent):
    s = me.state(StoryState)
    owner = _owner()
    original = get_set_store().get(e.key.split("-", 1)[1], owner)
    if original is None:
        s.error = "That set was not found."
        return
    get_set_store().save(set_duplicate(original, owner), owner)
    _refresh_sets()


def on_ask_delete_set(e: me.ClickEvent):
    me.state(StoryState).confirm_delete_set_id = e.key.split("-", 1)[1]


def on_cancel_delete_set(e: me.ClickEvent):
    me.state(StoryState).confirm_delete_set_id = ""


def on_confirm_delete_set(e: me.ClickEvent):
    s = me.state(StoryState)
    set_id = s.confirm_delete_set_id
    s.confirm_delete_set_id = ""
    if not get_set_store().delete(set_id, _owner()):
        s.error = "Could not delete that set."
    if s.create_set_id == set_id:
        s.create_set_id = ""
    current = _set()
    if current is not None and current.id == set_id:
        _put_set(None)
    _refresh_sets()


# ---------------------------------------------------------------------------
# Media preview helper
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





def _move(scene_id: str, delta: int) -> None:
    def apply(story: Story) -> None:
        ids = [sc.id for sc in story.scenes]
        if scene_id not in ids:
            return
        i = ids.index(scene_id)
        j = i + delta
        if 0 <= j < len(story.scenes):
            story.scenes[i], story.scenes[j] = story.scenes[j], story.scenes[i]
            story.clear_films()
            if story.continuity:
                for sc in story.scenes[min(i, j) :]:
                    sc.clear_clip()

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
            story.clear_films()

    _edit(apply)


def on_scene_duration(e: me.SelectSelectionChangeEvent):
    _update_scene(_scene_id_from_key(e.key), "duration", int(e.value))


def _set_story_field(field: str, value) -> None:
    def apply(story: Story) -> None:
        old = getattr(story, field)
        if field == "music_prompt":
            # The box shows the default prompt when none is stored, so a blur
            # that leaves it as shown (or empty) changes nothing.
            default = default_music_prompt(story)
            if _same_value(old or default, value or default):
                return
        elif _same_value(old, value):
            return
        setattr(story, field, value)
        if field in (
            "music_on",
            "music_prompt",
            "voice_on",
            "voice_name",
            "seamless_joins",
            "color_match",
        ):
            story.clear_films()
        if field == "continuity":
            story.clear_films()
            for sc in story.scenes[1:]:
                sc.clear_clip()
        if field == "music_prompt":
            story.music_uri = ""

    _edit(apply)


def on_toggle_music(e: me.SlideToggleChangeEvent):
    story = _story()
    _set_story_field("music_on", not (story and story.music_on))


def on_toggle_voice(e: me.SlideToggleChangeEvent):
    story = _story()
    _set_story_field("voice_on", not (story and story.voice_on))


def _start_translation(force: bool) -> None:
    s = me.state(StoryState)
    s.error = ""
    try:
        job = story_jobs.start_translation(s.story_id, _owner(), force=force)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_toggle_second(e: me.SlideToggleChangeEvent):
    story = _story()
    turning_on = not (story and story.second_on)

    def apply(st: Story) -> None:
        st.second_on = turning_on
        st.final_alt_uri = ""

    story = _edit(apply)
    if turning_on and story and story.needs_translation():
        _start_translation(force=False)


def on_translate_again(e: me.ClickEvent):
    _start_translation(force=True)


def on_music_prompt(e: me.InputBlurEvent):
    _set_story_field("music_prompt", e.value.strip())


def _edit_tracks(fn) -> None:
    """Change the story's music tracks (a list of dicts) and save."""

    def apply(st: Story) -> None:
        tracks = st.music_tracks() if st.music_tracks_json else []
        fn(st, tracks)
        st.music_tracks_json = json.dumps(tracks) if tracks else ""

    _edit(apply)


def on_add_track(e: me.ClickEvent):
    """Music step: a new track, under the last take no track has yet."""

    def add(st: Story, tracks: list) -> None:
        used = {k for t in tracks for k in t.get("takes", [])}
        free = [k for k in range(len(take_groups(st))) if k not in used]
        if not free:
            return  # every take has a track
        take = free[-1]
        tracks.append({"id": uuid.uuid4().hex[:8], "takes": [take], "prompt": "", "uri": ""})

    _edit_tracks(add)


def on_track_take(e: me.ClickEvent):
    """Music step: put a track under a take, or take it off (trtake|id|k).
    A take has one track: picking it here takes it off the others."""
    try:
        _, tid, k = (e.key or "").split("|")
        k = int(k)
    except ValueError:
        return

    def toggle(st: Story, tracks: list) -> None:
        for t in tracks:
            takes = [x for x in t.get("takes", []) if x != k]
            if t.get("id") == tid and k not in t.get("takes", []):
                takes.append(k)
            if takes != t.get("takes", []):
                t["takes"] = sorted(takes)
                t["uri"] = ""  # a new length: make it again
        tracks[:] = [t for t in tracks if t.get("takes")]

    _edit_tracks(toggle)


def on_track_prompt(e: me.InputBlurEvent):
    tid = (e.key or "").split("|", 1)[-1]
    value = (e.value or "").strip()[:600]

    def set_prompt(st: Story, tracks: list) -> None:
        for t in tracks:
            if t.get("id") == tid and t.get("prompt", "") != value:
                t["prompt"], t["uri"] = value, ""

    _edit_tracks(set_prompt)


def on_remove_track(e: me.ClickEvent):
    tid = (e.key or "").split("|", 1)[-1]
    _edit_tracks(lambda st, tracks: tracks.__setitem__(
        slice(None), [t for t in tracks if t.get("id") != tid]
    ))


def on_voice(e: me.SelectSelectionChangeEvent):
    _set_story_field("voice_name", e.value)


def on_render(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    if s.set_dirty and _save_draft() is None:
        return
    story = _story()
    if story is not None and not story.approved:
        _edit(lambda st: setattr(st, "approved", True))
    try:
        job = story_jobs.start_video(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)
    s.step = "video"


def _alt_cost(story: Story) -> float:
    """What the second-language film adds (see setup_view.alt_cost)."""
    bp = story_director.setup_blueprint(
        sum(sc.duration for sc in story.scenes) or 30,
        video_model=story.video_model,
        resolution=story.resolution,
        one_take=story.one_take,
    )
    spoken = any(sc.spoken and sc.narration.strip() for sc in story.scenes)
    return round((bp["cost"]["video"] if spoken else 0.0) + bp["cost"]["voice"], 2)


# Final-quality targets for a draft film, sharpest last.
UPSCALE_TARGETS = ("720p", "1080p")


def _upscale_options(story: Story) -> list[tuple[str, float]]:
    """(resolution, about how much it costs) for each sharper version Omni
    can upscale this film's clips to."""
    from services.story_models import resolution_options, story_resolution

    order = ("360p", "720p", "1080p", "4k")
    current = story_resolution(story)
    have = order.index(current) if current in order else len(order)
    seconds = sum(sc.duration for sc in story.scenes) or 30
    out = []
    for res in UPSCALE_TARGETS:
        if order.index(res) <= have or res not in resolution_options(story.video_model):
            continue
        bp = story_director.setup_blueprint(
            seconds, video_model=story.video_model, resolution=res, one_take=story.one_take
        )
        out.append((res, bp["cost"]["video"]))
    return out


def on_upscale(e: me.ClickEvent):
    """Export: upscale the draft's clips (key ss-upscale-<resolution>) and
    make the film again from them."""
    s = me.state(StoryState)
    s.error = ""
    resolution = (e.key or "").rsplit("-", 1)[-1]
    if resolution not in UPSCALE_TARGETS:
        return
    try:
        job = story_jobs.start_upscale(s.story_id, _owner(), resolution)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_make_alt(e: me.ClickEvent):
    """Export: make the second-language film (spoken takes are made again
    saying the translated lines; narration gets a new voiceover)."""
    s = me.state(StoryState)
    s.error = ""
    if _edit(lambda st: setattr(st, "second_on", True)) is None:
        return
    try:
        job = story_jobs.start_alt_video(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_to_video(e: me.ClickEvent):
    me.state(StoryState).step = "video"


# ---------------------------------------------------------------------------
# Step 4: Timeline & Export
# ---------------------------------------------------------------------------


_TIMELINE_HANDLERS: timeline_view.TimelineHandlers | None = None


def _timeline_handlers() -> timeline_view.TimelineHandlers:
    global _TIMELINE_HANDLERS
    if _TIMELINE_HANDLERS is None:
        _TIMELINE_HANDLERS = timeline_view.TimelineHandlers(
            on_back_editor=on_back_editor,
            on_toggle_edit_music=on_toggle_edit_music,
            on_export=on_export,
            on_export_menu=on_export_menu,
            on_export_size=on_export_size,
            on_export_format=on_export_format,
            on_export_subs=on_export_subs,
            on_export_lang=on_export_lang,
            on_export_branding=on_export_branding,
            on_subtitle_style=on_subtitle_style,
            on_proxy_tick=on_proxy_tick,
            on_cancel_job=on_cancel_job,
            on_music_prompt=on_music_prompt,
            on_make_music=on_make_music,
            on_upload_music=on_upload_music,
            on_timeline_change=on_timeline_change,
            on_fix_point=on_fix_point,
            render_fix_panel=fix_panel,
            render_alt_film=_alt_film,
            on_make_alt=on_make_alt,
            alt_cost=_alt_cost,
            on_upscale=on_upscale,
            upscale_options=_upscale_options,
            render_versions_panel=versions_panel,
            render_progress_panel=progress_panel,
            media_map=_media_map,
            job_active_for=_job_active_for,
            job_dict=_job,
            scene_task=_scene_task,
            fmt_secs=_fmt_secs,
        )
    return _TIMELINE_HANDLERS


def _media_map(story: Story) -> dict[str, str]:
    """Scene thumbnails for the editor's strip (the player plays one
    rendered file, so clip URLs are not needed)."""
    media: dict[str, str] = {}
    for i, sc in enumerate(story.scenes):
        if sc.frame_uri:
            media[f"thumb:{i}"] = display_url(sc.frame_uri)
    return media


def edit_view(story: Story) -> None:
    video_step(story)


def video_step(story: Story) -> None:
    s = me.state(StoryState)
    timeline_view.render_timeline(
        s,
        story,
        _set() if story.set_id else None,
        is_demo=is_mock_mode(),
        h=_timeline_handlers(),
    )


# ---------------------------------------------------------------------------
# Edit step: film versions (compare, go back)
# ---------------------------------------------------------------------------


def versions_panel(story: Story, busy: bool) -> None:
    rows = story_versions.versions(story)
    if len(rows) < 2 and not (rows and rows[0]["uri"] != story.final_uri):
        return
    s = me.state(StoryState)
    with me.box(classes="ss-card ss-dl"):
        with me.box(classes="ss-dl-title"):
            me.text("Versions", style=me.Style(font_size=16, font_weight=600))
            me.text(
                "Earlier cuts of this film. Compare one with the current film, or "
                "bring it back with its edit (scenes and pictures stay as they are).",
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        compare = next((r for r in rows if r["uri"] == s.compare_uri), None)
        if compare and compare["uri"] != story.final_uri:
            film_compare(
                left_url=display_url(compare["uri"]),
                right_url=display_url(story.final_uri),
                left_label=f"{compare['label']} · {story_versions.ago(compare['at'])}",
                right_label="Current film",
                portrait=story.aspect_ratio == "9:16",
                key=f"ss-compare-{compare['uri'][-24:]}",
            )
        for n, row in enumerate(rows):
            current = row["uri"] == story.final_uri
            with me.box(classes="ss-dl-row"):
                with me.box(classes="ss-dl-name"):
                    me.text(row["label"])
                    me.text(
                        story_versions.ago(row["at"])
                        + (" · current" if current else ""),
                        style=me.Style(
                            font_size=12, color=me.theme_var("on-surface-variant")
                        ),
                    )
                with me.box(classes="ss-dl-actions"):
                    timeline_view.download_link(
                        "Download",
                        timeline_view.download_url(story, f"version-{n}"),
                        f"ss-vdl-{n}",
                    )
                    if not current:
                        me.button(
                            "Hide" if s.compare_uri == row["uri"] else "Compare",
                            type="stroked",
                            on_click=on_compare_version,
                            key=f"ss-vcmp-{n}",
                        )
                        me.button(
                            "Use this version",
                            type="stroked",
                            disabled=busy,
                            on_click=on_use_version,
                            key=f"ss-vuse-{n}",
                        )


def _version_at(key: str, prefix: str) -> dict | None:
    story = _story()
    if story is None:
        return None
    try:
        n = int((key or "").removeprefix(prefix))
    except ValueError:
        return None
    rows = story_versions.versions(story)
    return rows[n] if 0 <= n < len(rows) else None


def on_compare_version(e: me.ClickEvent):
    s = me.state(StoryState)
    row = _version_at(e.key, "ss-vcmp-")
    if row is not None:
        s.compare_uri = "" if s.compare_uri == row["uri"] else row["uri"]


def on_use_version(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    row = _version_at(e.key, "ss-vuse-")
    if row is None:
        return

    def apply(story: Story) -> None:
        story_versions.restore(story, row["uri"])

    try:
        story = story_jobs.mutate_story(s.story_id, _owner(), apply)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _set_story(story)
    s.compare_uri = ""
    s.notice = "That version is back, with its edit."


# ---------------------------------------------------------------------------
# Edit step: Export menu
# ---------------------------------------------------------------------------


def on_subtitle_style(e: me.ButtonToggleChangeEvent):
    if e.value in story_subtitles.STYLES:
        _set_story_field("subtitle_style", e.value)


def on_export_menu(e: me.ClickEvent):
    ex = me.state(StoryExportState)
    ex.open = not ex.open


def on_export_size(e: me.SelectSelectionChangeEvent):
    try:
        me.state(StoryExportState).short = int(e.value)
    except (TypeError, ValueError):
        pass


def on_export_format(e: me.SelectSelectionChangeEvent):
    if e.value in timeline_mod.EXPORT_FORMATS:
        me.state(StoryExportState).fmt = e.value


def on_export_subs(e: me.SelectSelectionChangeEvent):
    if e.value in story_export.SUB_MODES:
        me.state(StoryExportState).subs = e.value


def on_export_lang(e: me.SelectSelectionChangeEvent):
    if e.value in story_subtitles.VARIANTS and e.value != "none":
        me.state(StoryExportState).lang = e.value


def on_export_branding(e: me.SlideToggleChangeEvent):
    ex = me.state(StoryExportState)
    ex.branding = not ex.branding


def on_proxy_tick(e: me.WebEvent):
    """While the preview is being rendered: pick it up when it is ready
    (and start it again if nothing is rendering it, e.g. after a restart)."""
    s = me.state(StoryState)
    if not s.story_id:
        return
    story = _reload_story()
    if story is not None:
        story_jobs.ensure_proxy(story, _owner())


# ---------------------------------------------------------------------------
# Edit step: Fix with AI
# ---------------------------------------------------------------------------


def _fix_plan() -> story_fix.FixPlan | None:
    s = me.state(StoryState)
    if not s.fix_plan_json:
        return None
    try:
        return story_fix.FixPlan.from_dict(json.loads(s.fix_plan_json))
    except (ValueError, TypeError):
        return None


def parse_film_time(text: str) -> float | None:
    """'12.5', '12 s' or '0:12' -> seconds; None when empty or unreadable."""
    raw = (text or "").strip().lower().rstrip("s").strip()
    if not raw:
        return None
    try:
        if ":" in raw:
            minutes, seconds = raw.split(":", 1)
            value = int(minutes or 0) * 60 + float(seconds or 0)
        else:
            value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _fix_changes(
    story: Story, plan: story_fix.FixPlan, story_set=None
) -> list[tuple[str, str, str]]:
    """(what, now, after) rows of a fix's text changes, for the preview."""
    say = {True: "Spoken on camera", False: "Narrated over the picture"}
    rows = []
    for c in plan.changes:
        if c.action in ("rewrite_scene", "repaint_frame") and 0 <= c.scene < len(
            story.scenes
        ):
            cur = story.scenes[c.scene]
            n = f"Scene {c.scene + 1}"
            if c.narration is not None:
                rows.append((f"{n} line", cur.narration or "(none)", c.narration))
            if c.visual is not None:
                rows.append((f"{n} picture", cur.visual, c.visual))
            if c.camera is not None:
                rows.append((f"{n} camera", cur.camera, c.camera))
            if c.spoken is not None:
                rows.append((f"{n} speech", say[cur.spoken], say[c.spoken]))
        elif c.action == "set":
            asset = story_set.asset(c.asset_kind, c.asset_id) if story_set else None
            for label, new, old in (
                ("look", c.description, getattr(asset, "description", "")),
                ("outfit", c.outfit, getattr(asset, "outfit", "")),
                (
                    "voice",
                    c.voice,
                    asset.voice.description
                    if c.asset_kind == "character" and asset
                    else "",
                ),
            ):
                if new is not None:
                    rows.append((f"{c.asset_name} {label}", old or "(none)", new))
        elif c.action == "music":
            rows.append(("Music", story.music_prompt or "(default)", c.music_prompt))
        elif c.action == "scenario":
            rows.append(("Story", story.idea, c.direction))
    return rows


def fix_panel(story: Story, busy: bool) -> None:
    s = me.state(StoryState)
    plan = _fix_plan()
    locked = busy or s.fix_planning
    with me.box(classes="ss-card ss-fix"):
        with me.box(classes="ss-fix-head"):
            me.icon("auto_fix_high", style=me.Style(font_size=20, width=20, height=20))
            with me.box():
                me.text("Fix with AI", style=me.Style(font_size=16, font_weight=600))
                me.text(
                    "Say what you don't like. Gemini watches the film, picks the "
                    "smallest change (a cut, a scene, a person or place, or the "
                    "whole story) and shows it to you before anything is generated. "
                    "Pause the film to point at a moment.",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
            if story_fix.can_undo(story):
                me.button(
                    "Undo last fix",
                    type="stroked",
                    disabled=locked,
                    on_click=on_undo_fix,
                    key="ss-fix-undo",
                    style=me.Style(margin=me.Margin(left="auto"), flex_shrink=0),
                )
        me.textarea(
            label="What should change?",
            placeholder="For example: the end of scene 3 goes blank",
            value=s.fix_request,
            rows=2,
            appearance="outline",
            disabled=locked,
            on_blur=on_fix_request,
            style=me.Style(width="100%"),
            key="ss-fix-request",
        )
        with me.box(classes="ss-fix-row"):
            with me.box(classes="ss-fix-scene"):
                me.select(
                    label="Scene",
                    options=[me.SelectOption(label="Whole film", value="-1")]
                    + [
                        me.SelectOption(label=f"Scene {i + 1}", value=str(i))
                        for i in range(len(story.scenes))
                    ],
                    value=str(s.fix_scene),
                    appearance="outline",
                    disabled=locked,
                    on_selection_change=on_fix_scene,
                    style=me.Style(width="100%"),
                    key="ss-fix-scene",
                )
            with me.box(classes="ss-fix-time"):
                me.input(
                    label="At (seconds, optional)",
                    placeholder="12.5",
                    value=s.fix_time,
                    appearance="outline",
                    disabled=locked,
                    on_blur=on_fix_time,
                    style=me.Style(width="100%"),
                    key="ss-fix-time",
                )
            with me.box(classes="ss-fix-go"):
                me.button(
                    "Planning…" if s.fix_planning else "Plan the fix",
                    type="flat",
                    color="primary",
                    disabled=locked,
                    on_click=on_plan_fix,
                    key="ss-fix-plan",
                )
        if plan is not None and not s.fix_planning:
            _fix_preview(story, plan, busy)


def _fix_preview(story: Story, plan: story_fix.FixPlan, busy: bool) -> None:
    with me.box(classes="ss-fix-plan"):
        if not plan.runnable:
            with me.box(classes="ss-fix-ask"):
                me.icon(
                    "help_outline", style=me.Style(font_size=20, width=20, height=20)
                )
                me.text(
                    plan.question or plan.summary or "Gemini found nothing to change.",
                    style=me.Style(font_size=14, flex_grow=1),
                )
                me.button(
                    "Dismiss", type="stroked", on_click=on_cancel_fix, key="ss-fix-x"
                )
            return
        me.text(plan.summary or "Proposed change", style=me.Style(font_weight=600))
        if plan.reason:
            me.text(
                plan.reason,
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        story_set = story_fix.story_set_of(story)
        for name, now, after in _fix_changes(story, plan, story_set):
            with me.box(classes="ss-fix-change"):
                me.text(name, style=me.Style(font_size=13, font_weight=600))
                with me.box(classes="ss-fix-old"):
                    me.text(now)
                with me.box(classes="ss-fix-new"):
                    me.text(after)
        steps = story_fix.plan_steps(story, plan, story_set)
        with me.box(classes="ss-fix-steps"):
            for step in steps:
                with me.box(classes="ss-fix-step"):
                    me.icon(
                        "paid" if step.paid else "content_cut",
                        style=me.Style(font_size=18, width=18, height=18),
                    )
                    me.text(step.label, style=me.Style(font_size=14))
        paid = any(step.paid for step in steps)
        cost = (
            "Steps marked with a coin generate new media and cost money."
            if paid and not is_mock_mode()
            else "Demo mode: no cloud calls, no cost."
            if is_mock_mode()
            else "Only cuts what is already made. No new generation."
        )
        me.text(
            cost,
            style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
        )
        with me.box(classes="ss-fix-actions"):
            me.button(
                "Cancel",
                type="stroked",
                disabled=busy,
                on_click=on_cancel_fix,
                key="ss-fix-cancel",
            )
            me.button(
                "Apply and generate" if paid else "Apply",
                type="flat",
                color="primary",
                disabled=busy,
                on_click=on_apply_fix,
                key="ss-fix-apply",
            )


def on_fix_request(e: me.InputBlurEvent):
    me.state(StoryState).fix_request = e.value


def on_fix_scene(e: me.SelectSelectionChangeEvent):
    try:
        me.state(StoryState).fix_scene = int(e.value)
    except (TypeError, ValueError):
        me.state(StoryState).fix_scene = -1


def on_fix_time(e: me.InputBlurEvent):
    me.state(StoryState).fix_time = e.value


def on_plan_fix(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    if not s.fix_request.strip():
        s.error = "Describe what you would like to change first."
        return
    if s.fix_time.strip() and parse_film_time(s.fix_time) is None:
        s.error = "Write the time in seconds, for example 12.5 or 0:12."
        return
    s.fix_plan_json = ""
    s.fix_planning = True
    yield
    try:
        plan = story_fix.plan_fix(
            s.story_id,
            _owner(),
            s.fix_request,
            s.fix_scene,
            parse_film_time(s.fix_time),
        )
        s.fix_plan_json = json.dumps(plan.to_dict())
    except Exception as exc:
        logger.exception("Story Studio: fix planning failed")
        s.error = story_jobs.friendly_error(exc)
    s.fix_planning = False
    yield


def on_cancel_fix(e: me.ClickEvent):
    me.state(StoryState).fix_plan_json = ""


def on_fix_point(e: me.WebEvent):
    """The viewer paused the film: point the fix at that moment."""
    try:
        seconds = float((e.value or {}).get("time"))
    except (TypeError, ValueError):
        return
    if seconds >= 0:
        me.state(StoryState).fix_time = f"{seconds:g}"


def on_undo_fix(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    try:
        story = story_fix.undo_fix(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    s.fix_plan_json = ""
    _set_story(story)


def on_apply_fix(e: me.ClickEvent):
    s = me.state(StoryState)
    plan = _fix_plan()
    if plan is None:
        return
    s.error = ""
    try:
        job = story_fix.start_fix(s.story_id, _owner(), plan)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    s.fix_plan_json = ""
    s.fix_request = ""
    s.fix_time = ""
    _watch(job.id)


on_fix_plan = on_plan_fix
on_fix_apply = on_apply_fix
on_fix_undo = on_undo_fix


def on_timeline_change(e: me.WebEvent):
    s = me.state(StoryState)
    raw = (e.value or {}).get("timeline", "")
    try:
        story = story_jobs.save_timeline(s.story_id, _owner(), raw)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _set_story(story)


def on_export(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    try:
        job = story_jobs.start_export(
            s.story_id, _owner(), me.state(StoryExportState).options()
        )
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_make_music(e: me.ClickEvent):
    s = me.state(StoryState)
    s.error = ""
    try:
        job = story_jobs.start_music(s.story_id, _owner())
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _watch(job.id)


def on_upload_music(e: me.UploadEvent):
    s = me.state(StoryState)
    s.error = ""
    try:
        uri = get_backend().save_audio_upload(e.file.getvalue(), e.file.mime_type)
        story = story_jobs.set_music(s.story_id, _owner(), uri)
    except Exception as exc:
        s.error = story_jobs.friendly_error(exc)
        return
    _set_story(story)
    s.notice = "Your music is on the timeline."


def on_toggle_edit_music(e: me.ClickEvent):
    s = me.state(StoryState)
    s.edit_music_open = not s.edit_music_open


def _dir_class(language: str) -> str:
    """Right-to-left textarea text for Arabic (.ss-rtl in assets/ui/story.css)."""
    return "ss-rtl" if language == "Arabic" else ""


def _alt_film(story: Story) -> None:
    """The second-language film, under the main one."""
    me.text(
        f"{story.alt_language} version",
        style=me.Style(font_size=18, font_weight=600, margin=me.Margin(top=24)),
    )
    with me.box(
        classes="ss-media "
        + (
            "ss-ar-916 ss-player-portrait"
            if story.aspect_ratio == "9:16"
            else "ss-ar-169"
        )
    ):
        me.video(
            src=display_url(story.final_alt_uri),
            style=me.Style(width="100%", height="100%"),
        )
    with me.box(classes="ss-player-meta"):
        with me.box(classes="ss-rtl-text" if story.alt_language == "Arabic" else ""):
            me.text(
                story.title_alt or story.title or "Your film",
                style=me.Style(font_size=16, font_weight=600),
            )
        timeline_view.download_link(
            "Download", timeline_view.download_url(story, "alt"), "ss-dl-alt"
        )


def on_back_editor(e: me.ClickEvent):
    s = me.state(StoryState)
    s.step = "editor"
    s.desk_tab = "shots"
