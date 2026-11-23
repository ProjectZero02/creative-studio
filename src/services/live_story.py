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
"""Story Studio bridge for the Live voice agent.

Wraps :mod:`services.story_jobs` and :mod:`services.story_store` without
modifying Story Studio itself, so the Live agent can create a story, advance
it one step at a time, render the film, check status, and open it on screen.
"""

from __future__ import annotations

import re
import time
from typing import Any

from common.utils import create_display_url
from services import story_autoset, story_director, story_jobs
from services.live_jobs import LiveJob, RunResult
from services.story_models import (
    ASPECT_RATIOS,
    LANGUAGES,
    STEP_IDS,
    STYLES,
    Story,
    apply_caps,
    furthest_step,
)

POLL_STEP_S = 5.0
MAX_WAIT_S = 600.0

_STARTERS = {
    "scenario": story_jobs.start_scenario,
    "set": story_jobs.start_set,
    "storyboard": story_jobs.start_storyboard,
    "video": story_jobs.start_video,
    "music": story_jobs.start_music,
    "export": story_jobs.start_export,
}


def _normalize_style(value: str) -> str:
    target = (value or "").strip().lower()
    if not target:
        return ""
    for style in STYLES:
        if target in (
            style["id"].lower(),
            style["label"].lower(),
            style["chip"].lower(),
        ):
            return style["id"]
    return ""


def _normalize_language(value: str) -> str:
    target = (value or "").strip().lower()
    if not target:
        return ""
    for label, code in LANGUAGES.items():
        if target in (label.lower(), code.lower()):
            return label
    return ""


def _extract_target_seconds(length: str) -> int:
    raw = (length or "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)
    parsed = story_autoset.infer_settings(raw)
    if parsed.get("film_seconds"):
        return int(parsed["film_seconds"])

    m_min = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b", raw, re.I)
    if m_min:
        return int(round(float(m_min.group(1)) * 60))
    m_sec = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b", raw, re.I)
    if m_sec:
        return int(round(float(m_sec.group(1))))
    return 0


def _parse_length(length: str, scene_count: int | None, duration: int | None):
    raw = (length or "").strip()
    if not raw:
        return scene_count, duration
    if raw.isdigit():
        return story_autoset.plan_length(int(raw), scene_count, duration)
    parsed = story_autoset.infer_settings(raw)
    if "scene_count" in parsed or "duration" in parsed:
        return parsed.get("scene_count", scene_count), parsed.get("duration", duration)
    return scene_count, duration


def create_story_record(
    owner: str,
    idea: str,
    *,
    length: str = "",
    aspect_ratio: str = "",
    style: str = "",
    language: str = "",
) -> Story:
    """Save a new Story for ``owner``, merging inferred settings with explicit args."""
    cleaned = (idea or "").strip()
    if len(cleaned) < 8:
        raise ValueError("Describe your idea in a sentence or two first.")

    inferred = story_autoset.infer_settings(cleaned)
    pacing = inferred.get("pacing", "cinematic")
    video_model = inferred.get("video_model", "")
    target_seconds = (
        _extract_target_seconds(length)
        if length
        else int(inferred.get("film_seconds") or 0)
    )
    if target_seconds >= 90:
        bp = story_director.plan_film_blueprint(
            target_seconds, pacing=pacing, video_model=video_model
        )
        scene_count = int(bp["scene_count"])
        duration = int(bp["duration"])
    else:
        target_seconds = 0
        scene_count = inferred.get("scene_count", 4)
        duration = inferred.get("duration", 6)
        if length:
            scene_count, duration = _parse_length(length, None, None)
            scene_count = scene_count or 4
            duration = duration or 6
    caps = apply_caps(scene_count, duration, model_id=video_model)

    ar = (aspect_ratio or "").strip()
    chosen_aspect = ar if ar in ASPECT_RATIOS else inferred.get("aspect_ratio", "16:9")
    chosen_style = _normalize_style(style) or inferred.get("style", "photographic")
    chosen_language = _normalize_language(language) or inferred.get(
        "language", "English"
    )

    story = Story(
        idea=cleaned,
        language=chosen_language,
        speech_mode=inferred.get("speech_mode", "auto"),
        scene_count=caps.scene_count,
        duration=caps.duration,
        aspect_ratio=chosen_aspect,
        style=chosen_style,
        camera=inferred.get("camera", "auto"),
        target_seconds=target_seconds,
        pacing=pacing,
        video_model=video_model,
        scenes=[],
        approved=False,
        step="scenario",
    )
    return story_jobs.get_store().save(story, owner)


def resolve_story(owner: str, ref: str = "", latest_id: str = "") -> Story | None:
    """Resolve a story by id, title, or latest story of the call/owner."""
    store = story_jobs.get_store()
    text = (ref or "").strip()
    low = text.lower()
    if not low or low in ("the story", "latest", "it", "story", "this story"):
        if latest_id:
            found = store.get(latest_id, owner)
            if found is not None:
                return found
        stories = store.list(owner)
        return stories[0] if stories else None

    exact = store.get(text, owner)
    if exact is not None:
        return exact

    stories = store.list(owner)
    for story in stories:
        if story.title and story.title.lower() == low:
            return story
    for story in stories:
        if story.title and low in story.title.lower():
            return story
    if latest_id and low.startswith("story "):
        found = store.get(latest_id, owner)
        if found is not None:
            return found
    return None


def approve_story(story_id: str, owner: str) -> Story:
    """Mirror Story Studio's Approve button: mark approved and move to Set."""

    def apply(story: Story) -> None:
        story.approved = True
        story.step = "set"

    return story_jobs.mutate_story(story_id, owner, apply)


def next_step_action(story: Story) -> str:
    """Return the next action for ``continue_story``: scenario, approve, set, storyboard, video, or done."""
    if not story.scenes:
        return "scenario"
    if not story.approved:
        return "approve"
    if not story.set_id:
        return "set"
    if not all(scene.frame_uri for scene in story.scenes):
        return "storyboard"
    if not story.final_uri:
        return "video"
    return "done"


def check_render_ready(story: Story) -> str:
    """Return a plain error message if the story is not ready to render, else ''."""
    if not story.scenes:
        return "Write the scenario first before rendering the film."
    if not story.approved:
        return "Approve the scenario first before rendering the film."
    if not all(scene.frame_uri for scene in story.scenes):
        return "Every scene needs a storyboard frame first."
    return ""


def story_status_summary(story: Story, owner: str) -> dict[str, Any]:
    """Return current step, active/latest job progress, and film availability."""
    latest = story_jobs.latest_job_for(story.id, owner)
    snap = story_jobs.job_snapshot(latest.id, owner) if latest else None
    job_info = None
    if snap is not None:
        job_info = {
            "id": snap["id"],
            "kind": snap["kind"],
            "status": snap["status"],
            "progress": snap["progress"],
            "done": snap["done"],
            "total": snap["total"],
            "message": snap["message"],
        }
    return {
        "story_id": story.id,
        "title": story.title or story.idea[:60],
        "step": story.step,
        "approved": story.approved,
        "scene_count": len(story.scenes),
        "frames_ready": sum(1 for scene in story.scenes if scene.frame_uri),
        "has_set": bool(story.set_id),
        "has_film": bool(story.final_uri),
        "next_action": next_step_action(story),
        "job": job_info,
    }


def open_step_for(story: Story, requested: str = "") -> str:
    """Pick a valid step id for opening the story on screen."""
    step = (requested or "").strip().lower()
    if step in STEP_IDS:
        return step
    return story.step if story.step in STEP_IDS else furthest_step(story)


def _display_url(uri: str) -> str:
    if not uri:
        return ""
    if uri.startswith("gs://"):
        return create_display_url(uri)
    return uri


def _fix_starter(job: LiveJob):
    """A starter for a confirmed Fix with AI plan carried in the job."""
    import json

    from services import story_fix

    plan = story_fix.FixPlan.from_dict(json.loads(job.params.get("fix_plan_json") or "{}"))
    return lambda story_id, owner: story_fix.start_fix(story_id, owner, plan)


# The Story Studio page that shows each action while it runs.
_STEP_PAGE = {
    "scenario": "scenario",
    "approve": "set",
    "set": "set",
    "storyboard": "storyboard",
    "video": "video",
    "music": "video",
    "export": "video",
    "fix": "video",
}


def step_page(action: str) -> str:
    """The Story Studio step to show while `action` runs."""
    return _STEP_PAGE.get(action, "scenario")


def _run_step(job: LiveJob, story_id: str, action: str, starter) -> None:
    """Start one story_jobs step, show its page, and wait for it to finish."""
    sjob = starter(story_id, job.owner)
    job.params["story_job_id"] = sjob.id
    job.params["story_step"] = step_page(action)
    job.progress()

    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        current = story_jobs.wait(sjob.id, job.owner, timeout=POLL_STEP_S)
        if current is None or current.status != story_jobs.RUNNING:
            sjob = current
            break

    if sjob is None:
        raise RuntimeError("The story job disappeared.")
    if sjob.status == story_jobs.RUNNING:
        raise RuntimeError("The story step timed out.")
    if sjob.status == story_jobs.FAILED:
        raise RuntimeError(sjob.message or f"Story {action} failed.")


def _run_all(job: LiveJob, story_id: str) -> None:
    """Every remaining step in turn (approve, set, storyboard, film), each
    shown on its page as it runs."""
    for _ in range(len(_STARTERS) + 2):  # each pass moves at least one step
        story = story_jobs.get_store().get(story_id, job.owner)
        if story is None:
            raise RuntimeError("Story not found.")
        action = next_step_action(story)
        if action == "done":
            return
        if action == "approve":
            approve_story(story_id, job.owner)
            job.params["story_job_id"] = ""
            job.params["story_step"] = step_page(action)
            job.progress()
            continue
        _run_step(job, story_id, action, _STARTERS[action])
    raise RuntimeError("The film did not finish its steps.")


def run_story_job(job: LiveJob) -> RunResult:
    """LiveJobs runner for kind='story': runs one story_jobs step (or, for
    the action "all", every remaining step) and waits."""
    story_id = str(job.params.get("story_id") or "")
    action = str(job.params.get("story_action") or "")
    starter = _STARTERS.get(action)
    if action == "fix":
        starter = _fix_starter(job)
    if not story_id or (starter is None and action != "all"):
        raise ValueError(f"Invalid story job action: {action or 'missing'}")

    if action == "all":
        _run_all(job, story_id)
    else:
        _run_step(job, story_id, action, starter)

    story = story_jobs.get_store().get(story_id, job.owner)
    if story is None:
        raise RuntimeError("Story not found after step finished.")

    job.params["story_step"] = story.step
    job.params["story_title"] = story.title
    job.params["has_film"] = bool(story.final_uri)

    if story.final_uri:
        return RunResult(
            gcs_uri=story.final_uri if story.final_uri.startswith("gs://") else "",
            display_url=_display_url(story.final_uri),
            mime_type="video/mp4",
        )
    if story.cover_uri:
        return RunResult(
            gcs_uri="",
            display_url=_display_url(story.cover_uri),
            mime_type="image/png",
        )
    return RunResult(gcs_uri="", display_url="", mime_type="")
