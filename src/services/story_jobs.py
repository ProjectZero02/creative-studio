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
    alt_story,
    build_stitch_plan,
    default_music_prompt,
    parse_scenario,
    parse_single_scene,
    parse_translation,
    parse_voice,
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
                    text = backend.write_scenario(story)
                    title, scenes = parse_scenario(
                        text,
                        story.scene_count,
                        story.duration,
                        story.camera,
                        story.speech_mode,
                    )
                    voice = parse_voice(text) if any(sc.spoken for sc in scenes) else ""
                    break
                except ScenarioError as exc:
                    last = exc
            else:
                raise last or ScenarioError("No scenario.")

            def apply(s: Story) -> None:
                s.title = title
                s.title_alt = ""
                s.speaker_voice = voice
                s.scenes = scenes
                s.approved = False
                s.clear_films()
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
                story.speech_mode,
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
                    cur.narration_alt = ""
                    cur.spoken = scene.spoken
                    s.clear_films()

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
                s.clear_films()

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


def _is_spoken(scene) -> bool:
    return bool(scene.spoken and scene.narration.strip())


def _translate_into(story_id: str, owner: str, force: bool = False) -> str:
    """Translate the narration into the story's second language and save it.

    Fills only missing lines (keeps the user's edits) unless `force`.
    """
    backend = get_backend()
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    last: Exception | None = None
    for _ in range(2):  # one automatic retry on malformed JSON
        try:
            title, lines = parse_translation(
                backend.translate(story), len(story.scenes)
            )
            break
        except ScenarioError as exc:
            last = exc
    else:
        raise last or ScenarioError("No translation.")
    by_id = {sc.id: line for sc, line in zip(story.scenes, lines)}

    def apply(s: Story) -> None:
        changed = False
        for sc in s.scenes:
            line = by_id.get(sc.id)
            if line is None or not sc.narration.strip():
                continue
            if force or not sc.narration_alt.strip():
                sc.narration_alt = line
                changed = True
        if title and (force or not s.title_alt):
            s.title_alt = title
        if changed:
            s.final_alt_uri = ""

    mutate_story(story_id, owner, apply)
    return ""


def start_translation(story_id: str, owner: str, force: bool = False) -> Job:
    """Translate the narration for the second-language film (reviewable)."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    job = _new_job(owner, story_id, "translate", {"force": force})
    task = _add_task(
        job, f"Translating the narration into {story.alt_language}", "translate"
    )

    def work(job: Job) -> None:
        _run_task(task, lambda: _translate_into(story_id, owner, force))

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
        what = "video clip with speech (Veo)" if _is_spoken(sc) else "video clip (Veo)"
        clip_tasks[i] = _add_task(job, f"Scene {i + 1} · {what}", "clip", i)
    music_task = (
        _add_task(job, "Music · Lyria score", "music") if story.music_on else None
    )
    voice_tasks = {
        i: _add_task(job, f"Scene {i + 1} · voiceover", "voice", i)
        for i, sc in enumerate(story.scenes)
        if story.voice_on and sc.narration.strip() and not sc.spoken
    }
    stitch_task = _add_task(job, "Stitching the film · crossfades and mix", "stitch")
    library_task = _add_task(job, "Saving to your library", "library")
    # Second-language film: same clips and music, translated voiceover.
    alt = story.alt_language
    alt_on = story.makes_alt and any(sc.narration.strip() for sc in story.scenes)
    translate_task = (
        _add_task(job, f"Translating the narration into {alt}", "translate")
        if alt_on and story.needs_translation()
        else None
    )
    alt_voice_tasks = (
        {
            i: _add_task(job, f"Scene {i + 1} · {alt} voiceover", "voice_alt", i)
            for i, sc in enumerate(story.scenes)
            if story.voice_on and sc.narration.strip() and not sc.spoken
        }
        if alt_on
        else {}
    )
    # Spoken scenes: the speech is in the video, so Veo renders the scene
    # again saying the translated line (skipped while the last one is current).
    alt_clip_tasks = (
        {
            i: _add_task(
                job, f"Scene {i + 1} · {alt} video clip with speech (Veo)", "clip_alt", i
            )
            for i, sc in enumerate(story.scenes)
            if _is_spoken(sc) and not (sc.clip_uri and sc.has_alt_clip())
        }
        if alt_on
        else {}
    )
    alt_stitch_task = (
        _add_task(job, f"Stitching the {alt} film", "stitch_alt") if alt_on else None
    )
    alt_library_task = (
        _add_task(job, f"Saving the {alt} film to your library", "library_alt")
        if alt_on
        else None
    )
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()
        voice_uris: dict[int, str] = {}
        alt_voice_uris: dict[int, str] = {}
        music_uri = ""
        if translate_task and not _run_task(
            translate_task, lambda: _translate_into(story_id, owner)
        ):
            for t in [*alt_voice_tasks.values(), *alt_clip_tasks.values()]:
                t.status = SKIPPED
        translated = alt_story(get_store().get(story_id, owner) or story)

        def animate(i: int, start_frame: str, from_clip: str = "") -> str:
            """Render scene i's clip. from_clip: the previous clip whose last
            frame is start_frame (continuity), else empty."""
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            uri = backend.generate_clip(current, i, start_frame)
            scene_id = current.scenes[i].id

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.clip_uri = uri
                        sc.continues_from = from_clip

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
                start, from_clip = sc.frame_uri, ""
                if i in bridge_tasks:
                    if prev_clip and _run_task(
                        bridge_tasks[i],
                        lambda i=i, c=prev_clip: backend.last_frame(current, c, i),
                    ):
                        start, from_clip = bridge_tasks[i].result_uri, prev_clip
                    elif not prev_clip:
                        bridge_tasks[i].status = SKIPPED
                ok = _run_task(
                    clip_tasks[i], lambda i=i, s=start, c=from_clip: animate(i, s, c)
                )
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

        def voice_alt(i: int) -> str:
            text = translated.scenes[i].narration
            if not text.strip():
                raise GenerationError(f"Scene {i + 1} has no {alt} line yet.")
            uri = backend.generate_voiceover(translated, i, text)
            alt_voice_uris[i] = uri
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
            for i, t in alt_voice_tasks.items():
                if t.status == QUEUED:
                    futures.append(
                        pool.submit(_run_task, t, lambda i=i: voice_alt(i))
                    )
            if story.continuity:
                clips_continuity()
            else:
                futures.extend(clips_parallel(pool))
            for f in futures:
                f.result()
        if music_task and music_task.status == DONE:
            music_uri = music_task.result_uri

        def animate_alt(i: int) -> str:
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            sc = current.scenes[i]
            if not sc.clip_uri:
                raise GenerationError(f"Scene {i + 1} has no clip yet.")
            second = alt_story(current)
            if not second.scenes[i].narration.strip():
                raise GenerationError(f"Scene {i + 1} has no {alt} line yet.")
            # Start where the main clip started, so both versions match.
            start = (
                backend.last_frame(current, sc.continues_from, i)
                if sc.continues_from
                else sc.frame_uri
            )
            uri = backend.generate_clip(second, i, start)
            scene_id, key = sc.id, sc.alt_clip_key()

            def apply(s: Story) -> None:
                for x in s.scenes:
                    if x.id == scene_id:
                        x.clip_alt_uri, x.clip_alt_key = uri, key

            mutate_story(story_id, owner, apply)
            return uri

        pending_alt = [i for i, t in alt_clip_tasks.items() if t.status == QUEUED]
        if pending_alt:
            with ThreadPoolExecutor(max_workers=max(1, cfg.STORY_MAX_PARALLEL)) as pool:
                for f in [
                    pool.submit(_run_task, alt_clip_tasks[i], lambda i=i: animate_alt(i))
                    for i in pending_alt
                ]:
                    f.result()

        final = get_store().get(story_id, owner)
        missing = [i + 1 for i, s in enumerate(final.scenes) if not s.clip_uri]
        later = [stitch_task, library_task, alt_stitch_task, alt_library_task]
        if missing:
            for t in later:
                if t:
                    t.status = SKIPPED
            stitch_task.error = f"Waiting for scene {', '.join(map(str, missing))}."
            return
        plan = build_stitch_plan(
            final.scenes,
            cfg.STORY_CROSSFADE_SECONDS,
            seamless=final.continuity and final.seamless_joins,
        )
        voices = [voice_uris.get(seg.index, "") for seg in plan.segments]
        if not _run_task(
            stitch_task, lambda: backend.stitch(final, plan, music_uri, voices)
        ):
            for t in later[1:]:
                if t:
                    t.status = SKIPPED
            return
        film = stitch_task.result_uri

        def apply(s: Story) -> None:
            s.final_uri = film
            s.step = "video"

        mutate_story(story_id, owner, apply)
        _run_task(library_task, lambda: backend.save_to_library(final, film, owner))
        if not alt_stitch_task:
            return
        latest = get_store().get(story_id, owner) or final
        no_speech = [
            i + 1 for i, sc in enumerate(latest.scenes)
            if _is_spoken(sc) and not sc.has_alt_clip()
        ]
        if no_speech:
            alt_stitch_task.status = alt_library_task.status = SKIPPED
            alt_stitch_task.error = (
                f"Scene {', '.join(map(str, no_speech))} has no {alt} clip."
            )
            return
        if alt_voice_tasks and not any(
            t.status == DONE for t in alt_voice_tasks.values()
        ) and not latest.has_spoken:
            alt_stitch_task.status = alt_library_task.status = SKIPPED
            alt_stitch_task.error = f"No {alt} voiceover was made."
            return
        second = alt_story(latest)
        alt_plan = build_stitch_plan(
            second.scenes,
            cfg.STORY_CROSSFADE_SECONDS,
            seamless=second.continuity and second.seamless_joins,
        )
        alt_voices = [alt_voice_uris.get(seg.index, "") for seg in alt_plan.segments]
        if not _run_task(
            alt_stitch_task,
            lambda: backend.stitch(second, alt_plan, music_uri, alt_voices),
        ):
            alt_library_task.status = SKIPPED
            return
        alt_film = alt_stitch_task.result_uri

        def apply_alt(s: Story) -> None:
            s.final_alt_uri = alt_film

        mutate_story(story_id, owner, apply_alt)
        _run_task(
            alt_library_task,
            lambda: backend.save_to_library(second, alt_film, owner),
        )

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
    if job.kind == "translate":
        return start_translation(
            job.story_id, owner, bool(job.params.get("force"))
        )
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
