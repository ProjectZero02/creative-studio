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
"""Background jobs for Story Studio.

Long work (scenario, storyboard frames, Veo clips, music, voiceover, stitch)
runs in a background thread, never inside a Mesop event. Each job is a list
of visible tasks (queued / running / done / failed). The page polls
:func:`job_snapshot` on a short interval and draws the timeline.

Results are written to the stored story as each task finishes, so a reload
keeps finished frames and clips. Jobs live in process memory: on Cloud Run
use session affinity (already part of the deploy plan) so polls reach the
instance that runs the job.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from common.analytics import get_logger
from common.error_handling import GenerationError, classify_error
from config.default import Default
from services.story_models import (
    ScenarioError,
    Story,
    build_stitch_plan,
    default_music_prompt,
    parse_scenario,
    parse_single_scene,
)
from services.story_service import get_backend
from services.story_store import StoryAccessError, get_store

logger = get_logger(__name__)

QUEUED, RUNNING, DONE, FAILED, SKIPPED = (
    "queued",
    "running",
    "done",
    "failed",
    "skipped",
)


@dataclass
class Task:
    id: str
    label: str
    kind: str
    scene_index: int = -1
    status: str = QUEUED
    started_at: float = 0.0
    ended_at: float = 0.0
    error: str = ""
    result_uri: str = ""


@dataclass
class Job:
    id: str
    owner: str
    story_id: str
    kind: str
    tasks: list[Task] = field(default_factory=list)
    status: str = RUNNING
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    message: str = ""
    params: dict = field(default_factory=dict)


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()
_story_locks: dict[str, threading.Lock] = {}


def _story_lock(story_id: str) -> threading.Lock:
    with _jobs_lock:
        return _story_locks.setdefault(story_id, threading.Lock())


# ---------------------------------------------------------------------------
# Story mutation (shared by the UI and jobs, so neither overwrites the other)
# ---------------------------------------------------------------------------


def mutate_story(story_id: str, owner: str, fn: Callable[[Story], None]) -> Story:
    """Load, change and save a story under its lock. Owner-only."""
    with _story_lock(story_id):
        store = get_store()
        story = store.get(story_id, owner)
        if story is None:
            raise StoryAccessError("Story not found.")
        fn(story)
        return store.save(story, owner)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, (GenerationError, ScenarioError, StoryAccessError)):
        return str(exc)
    info = classify_error(exc)
    category = info.get("category", "UNKNOWN")
    plain = {
        "CAPACITY_EXHAUSTED": "The model is busy right now. Wait a moment and retry.",
        "SAFETY_FILTER": "The model declined this prompt. Edit the scene text and retry.",
        "CLIENT_TIMEOUT": "This took too long. Retry.",
        "INVALID_ARGUMENT": "The model rejected a setting. Try a different scene length or aspect ratio.",
        "AUTH_ERROR": "The app is not allowed to call this model. Check the project setup.",
        "NOT_FOUND": "A file this step needs was not found. Regenerate the previous step.",
        "UPSTREAM_FAILURE": "The model service had an error. Retry.",
    }
    return plain.get(
        category,
        "Something went wrong. Retry, and check the server log if it keeps failing.",
    )


# ---------------------------------------------------------------------------
# Job bookkeeping
# ---------------------------------------------------------------------------


def _new_job(owner: str, story_id: str, kind: str, params: dict | None = None) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        owner=owner,
        story_id=story_id,
        kind=kind,
        params=params or {},
    )
    with _jobs_lock:
        _jobs[job.id] = job
        # Keep memory bounded.
        if len(_jobs) > 300:
            for old in sorted(_jobs.values(), key=lambda j: j.created_at)[:100]:
                if old.status != RUNNING:
                    _jobs.pop(old.id, None)
    return job


def _add_task(job: Job, label: str, kind: str, scene_index: int = -1) -> Task:
    task = Task(
        id=uuid.uuid4().hex[:8], label=label, kind=kind, scene_index=scene_index
    )
    with _jobs_lock:
        job.tasks.append(task)
    return task


def _run_task(task: Task, fn: Callable[[], str]) -> bool:
    task.status = RUNNING
    task.started_at = time.time()
    try:
        task.result_uri = fn() or ""
        task.status = DONE
        return True
    except Exception as exc:
        logger.exception("Story Studio task failed: %s", task.label)
        task.error = friendly_error(exc)
        task.status = FAILED
        return False
    finally:
        task.ended_at = time.time()


def _finish(job: Job) -> None:
    failed = [t for t in job.tasks if t.status == FAILED]
    job.status = FAILED if failed else DONE
    if failed:
        job.message = (
            f"{len(failed)} of {len(job.tasks)} steps failed. Finished work is kept; "
            "press Retry to continue."
        )
    job.finished_at = time.time()


def _spawn(job: Job, target: Callable[[Job], None]) -> Job:
    def runner():
        try:
            target(job)
        except Exception as exc:
            logger.exception("Story Studio job crashed")
            job.message = friendly_error(exc)
            for t in job.tasks:
                if t.status in (QUEUED, RUNNING):
                    t.status = FAILED
                    t.error = t.error or job.message
        finally:
            if job.status == RUNNING:
                _finish(job)

    threading.Thread(target=runner, name=f"story-job-{job.id}", daemon=True).start()
    return job


def get_job(job_id: str, owner: str) -> Job | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None or job.owner != owner:
        return None
    return job


def latest_job_for(story_id: str, owner: str) -> Job | None:
    """The newest job of this story (to re-attach after a page reload)."""
    with _jobs_lock:
        jobs = [
            j for j in _jobs.values() if j.story_id == story_id and j.owner == owner
        ]
    return max(jobs, key=lambda j: j.created_at) if jobs else None


def job_snapshot(job_id: str, owner: str) -> dict | None:
    """A JSON-safe copy of the job for the UI, with elapsed seconds."""
    job = get_job(job_id, owner)
    if job is None:
        return None
    now = time.time()
    with _jobs_lock:
        tasks = []
        for t in job.tasks:
            d = asdict(t)
            if t.started_at:
                d["elapsed"] = round((t.ended_at or now) - t.started_at, 1)
            else:
                d["elapsed"] = 0.0
            tasks.append(d)
    done = sum(1 for t in tasks if t["status"] in (DONE, SKIPPED))
    running = sum(1 for t in tasks if t["status"] == RUNNING)
    total = max(1, len(tasks))
    return {
        "id": job.id,
        "kind": job.kind,
        "story_id": job.story_id,
        "status": job.status,
        "message": job.message,
        "elapsed": round((job.finished_at or now) - job.created_at, 1),
        "progress": round((done + 0.4 * running) / total, 3),
        "done": done,
        "total": len(tasks),
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def start_scenario(story_id: str, owner: str) -> Job:
    job = _new_job(owner, story_id, "scenario")
    task = _add_task(job, "Writing the scenario with Gemini", "scenario")

    def work(job: Job) -> None:
        backend = get_backend()
        story = get_store().get(story_id, owner)
        if story is None:
            raise StoryAccessError("Story not found.")

        def write() -> str:
            last: Exception | None = None
            for _ in range(2):  # one automatic retry on malformed JSON
                try:
                    title, scenes = parse_scenario(
                        backend.write_scenario(story),
                        story.scene_count,
                        story.duration,
                        story.camera,
                    )
                    break
                except ScenarioError as exc:
                    last = exc
            else:
                raise last or ScenarioError("No scenario.")

            def apply(s: Story) -> None:
                s.title = title
                s.scenes = scenes
                s.approved = False
                s.final_uri = ""
                s.step = "scenario"
                if not s.music_prompt:
                    s.music_prompt = default_music_prompt(s)

            mutate_story(story_id, owner, apply)
            return ""

        _run_task(task, write)

    return _spawn(job, work)


def start_scene_rewrite(story_id: str, owner: str, index: int) -> Job:
    job = _new_job(owner, story_id, "scene", {"index": index})
    task = _add_task(job, f"Scene {index + 1} · rewriting", "scenario", index)

    def work(job: Job) -> None:
        backend = get_backend()
        story = get_store().get(story_id, owner)
        if story is None or index >= len(story.scenes):
            raise StoryAccessError("Story not found.")

        def rewrite() -> str:
            scene = parse_single_scene(
                backend.rewrite_scene(story, index),
                story.scenes[index].duration,
                story.camera,
            )

            def apply(s: Story) -> None:
                if index < len(s.scenes):
                    cur = s.scenes[index]
                    cur.narration, cur.visual, cur.camera = (
                        scene.narration,
                        scene.visual,
                        scene.camera,
                    )
                    cur.frame_uri = cur.clip_uri = ""
                    s.final_uri = ""

            mutate_story(story_id, owner, apply)
            return ""

        _run_task(task, rewrite)

    return _spawn(job, work)


def start_storyboard(
    story_id: str, owner: str, indices: list[int] | None = None
) -> Job:
    """Paint one still per scene. Scene 1 goes first and anchors the look.

    `indices` limits the run to those scenes (regenerate); otherwise every
    scene without a frame is painted.
    """
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if indices is None:
        targets = [i for i, s in enumerate(story.scenes) if not s.frame_uri]
    else:
        targets = sorted({i for i in indices if 0 <= i < len(story.scenes)})
    job = _new_job(owner, story_id, "storyboard", {"indices": targets})
    tasks = {
        i: _add_task(job, f"Scene {i + 1} · storyboard frame", "frame", i)
        for i in targets
    }
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()

        def paint(i: int, reference: str) -> str:
            current = get_store().get(story_id, owner)
            if current is None or i >= len(current.scenes):
                raise StoryAccessError("Story not found.")
            uri = backend.generate_frame(current, i, reference)
            scene_id = current.scenes[i].id

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.frame_uri = uri
                        sc.clip_uri = ""
                s.final_uri = ""

            mutate_story(story_id, owner, apply)
            return uri

        reference = story.reference_uri
        rest = list(targets)
        if 0 in targets and not reference:
            ok = _run_task(tasks[0], lambda: paint(0, ""))
            rest.remove(0)
            reference = tasks[0].result_uri if ok else ""
        if (
            not reference
            and story.scenes
            and story.scenes[0].frame_uri
            and 0 not in targets
        ):
            reference = story.scenes[0].frame_uri
        with ThreadPoolExecutor(max_workers=max(1, cfg.STORY_MAX_PARALLEL)) as pool:
            for i in rest:
                pool.submit(_run_task, tasks[i], lambda i=i: paint(i, reference))

    return _spawn(job, work)


def start_video(story_id: str, owner: str) -> Job:
    """Animate each scene with Veo, add music and voiceover, stitch, save."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not story.scenes or not all(s.frame_uri for s in story.scenes):
        raise GenerationError("Every scene needs a storyboard frame first.")
    job = _new_job(owner, story_id, "video")
    n = len(story.scenes)
    clip_tasks: dict[int, Task] = {}
    bridge_tasks: dict[int, Task] = {}
    for i, sc in enumerate(story.scenes):
        if sc.clip_uri:
            continue
        if story.continuity and i > 0:
            bridge_tasks[i] = _add_task(
                job, f"Scene {i + 1} · last frame of scene {i}", "bridge", i
            )
        clip_tasks[i] = _add_task(job, f"Scene {i + 1} · video clip (Veo)", "clip", i)
    music_task = (
        _add_task(job, "Music · Lyria score", "music") if story.music_on else None
    )
    voice_tasks = {
        i: _add_task(job, f"Scene {i + 1} · voiceover", "voice", i)
        for i, sc in enumerate(story.scenes)
        if story.voice_on and sc.narration.strip()
    }
    stitch_task = _add_task(job, "Stitching the film · crossfades and mix", "stitch")
    library_task = _add_task(job, "Saving to your library", "library")
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()
        voice_uris: dict[int, str] = {}
        music_uri = ""

        def animate(i: int, start_frame: str) -> str:
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            uri = backend.generate_clip(current, i, start_frame)
            scene_id = current.scenes[i].id

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.clip_uri = uri

            mutate_story(story_id, owner, apply)
            return uri

        def clips_continuity() -> None:
            prev_clip = ""
            for i in range(n):
                current = get_store().get(story_id, owner)
                sc = current.scenes[i]
                if i not in clip_tasks:
                    prev_clip = sc.clip_uri
                    continue
                start = sc.frame_uri
                if i in bridge_tasks:
                    if prev_clip and _run_task(
                        bridge_tasks[i],
                        lambda i=i, c=prev_clip: backend.last_frame(current, c, i),
                    ):
                        start = bridge_tasks[i].result_uri
                    elif not prev_clip:
                        bridge_tasks[i].status = SKIPPED
                ok = _run_task(clip_tasks[i], lambda i=i, s=start: animate(i, s))
                prev_clip = clip_tasks[i].result_uri if ok else ""

        def clips_parallel(pool: ThreadPoolExecutor) -> list:
            return [
                pool.submit(
                    _run_task,
                    clip_tasks[i],
                    lambda i=i: animate(i, story.scenes[i].frame_uri),
                )
                for i in clip_tasks
            ]

        def voice(i: int) -> str:
            uri = backend.generate_voiceover(story, i, story.scenes[i].narration)
            voice_uris[i] = uri
            return uri

        with ThreadPoolExecutor(max_workers=max(2, cfg.STORY_MAX_PARALLEL)) as pool:
            futures = []
            if music_task:
                seconds = sum(s.duration for s in story.scenes)
                prompt = story.music_prompt or default_music_prompt(story)
                futures.append(
                    pool.submit(
                        _run_task,
                        music_task,
                        lambda: backend.generate_music(story, prompt, seconds),
                    )
                )
            for i, t in voice_tasks.items():
                futures.append(pool.submit(_run_task, t, lambda i=i: voice(i)))
            if story.continuity:
                clips_continuity()
            else:
                futures.extend(clips_parallel(pool))
            for f in futures:
                f.result()
        if music_task and music_task.status == DONE:
            music_uri = music_task.result_uri

        final = get_store().get(story_id, owner)
        missing = [i + 1 for i, s in enumerate(final.scenes) if not s.clip_uri]
        if missing:
            stitch_task.status = library_task.status = SKIPPED
            stitch_task.error = f"Waiting for scene {', '.join(map(str, missing))}."
            return
        plan = build_stitch_plan(final.scenes, cfg.STORY_CROSSFADE_SECONDS)
        voices = [voice_uris.get(seg.index, "") for seg in plan.segments]
        if not _run_task(
            stitch_task, lambda: backend.stitch(final, plan, music_uri, voices)
        ):
            library_task.status = SKIPPED
            return
        film = stitch_task.result_uri

        def apply(s: Story) -> None:
            s.final_uri = film
            s.step = "video"

        mutate_story(story_id, owner, apply)
        _run_task(library_task, lambda: backend.save_to_library(final, film, owner))

    return _spawn(job, work)


def retry(job_id: str, owner: str) -> Job | None:
    """Start a new job of the same kind. Finished pieces are skipped."""
    job = get_job(job_id, owner)
    if job is None:
        return None
    if job.kind == "scenario":
        return start_scenario(job.story_id, owner)
    if job.kind == "scene":
        return start_scene_rewrite(job.story_id, owner, int(job.params.get("index", 0)))
    if job.kind == "storyboard":
        failed = [t.scene_index for t in job.tasks if t.status == FAILED]
        return start_storyboard(job.story_id, owner, failed or None)
    return start_video(job.story_id, owner)


def wait(job_id: str, owner: str, timeout: float = 60.0) -> Job | None:
    """Block until a job finishes (tests and scripts)."""
    end = time.time() + timeout
    while time.time() < end:
        job = get_job(job_id, owner)
        if job is None or job.status != RUNNING:
            return job
        time.sleep(0.05)
    return get_job(job_id, owner)
