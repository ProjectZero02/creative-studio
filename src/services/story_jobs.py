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

import json
import random
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace

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
    tts_voice_for,
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
                if voice:
                    s.speaker_tts_voice = tts_voice_for(voice)
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


PREVIEW_LINE = {
    "English": "Good evening everyone, and thank you so much for being here tonight.",
    "Arabic": "مساء الخير جميعاً، وشكراً جزيلاً لحضوركم الليلة.",
}


def preview_voice(story: Story, voice: str) -> str:
    """A short sample of `voice` saying the first on-camera line (or a stock
    line), delivered the way the film will deliver it."""
    from services.story_service import get_backend

    index = next(
        (i for i, sc in enumerate(story.scenes) if _is_spoken(sc)),
        0 if story.scenes else -1,
    )
    if index < 0:
        raise GenerationError("Add a scene first.")
    text = story.scenes[index].narration.strip() if _is_spoken(story.scenes[index]) else ""
    text = text or PREVIEW_LINE.get(story.language, PREVIEW_LINE["English"])
    return get_backend().generate_voiceover(
        replace(story, voice_name=voice), index, text, style="presenter"
    )


def _is_spoken(scene) -> bool:
    return bool(scene.spoken and scene.narration.strip())


def _needs_voice(story: Story, scene) -> bool:
    """A TTS line: narrated scenes with the voiceover on. On-camera lines
    are spoken by the person in the clip (the video model's own speech)."""
    if _is_spoken(scene):
        return False
    return story.voice_on and bool(scene.narration.strip())


def _voice_label(story: Story, scene) -> str:
    return "voiceover"


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

    def prepare(s: Story) -> None:
        # One seed for every clip of the film.
        if not s.seed:
            s.seed = random.randint(1, 2**31 - 1)
        # A continuous take made from an older clip of the scene before it
        # no longer matches: render it again.
        for i, sc in enumerate(s.scenes):
            prev = s.scenes[i - 1] if i else None
            if sc.clip_uri and sc.extends_from and (
                prev is None or sc.extends_from != prev.clip_uri or not s.continues_take(i)
            ):
                sc.clip_uri, sc.extends_from, sc.clip_in = "", "", 0.0

    story = mutate_story(story_id, owner, prepare)
    job = _new_job(owner, story_id, "video")
    n = len(story.scenes)
    takes = {i for i in range(n) if story.continues_take(i)}
    clip_tasks: dict[int, Task] = {}
    bridge_tasks: dict[int, Task] = {}
    for i, sc in enumerate(story.scenes):
        if sc.clip_uri:
            continue
        if story.continuity and i > 0 and i not in takes:
            bridge_tasks[i] = _add_task(
                job, f"Scene {i + 1} · last frame of scene {i}", "bridge", i
            )
        what = (
            f"continuous take from scene {i} (Veo extension)"
            if i in takes
            else "video clip with speech (Veo)"
            if _is_spoken(sc)
            else "video clip (Veo)"
        )
        clip_tasks[i] = _add_task(job, f"Scene {i + 1} · {what}", "clip", i)
    sequential = story.continuity or bool(takes & set(clip_tasks))
    # Music is kept between renders until its prompt changes.
    music_task = (
        _add_task(job, "Music · Lyria score", "music")
        if story.music_on and not story.music_uri
        else None
    )
    voice_tasks = {
        i: _add_task(job, f"Scene {i + 1} · {_voice_label(story, sc)}", "voice", i)
        for i, sc in enumerate(story.scenes)
        if _needs_voice(story, sc)
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
            i: _add_task(
                job, f"Scene {i + 1} · {alt} {_voice_label(story, sc)}", "voice_alt", i
            )
            for i, sc in enumerate(story.scenes)
            if _needs_voice(story, sc)
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
                        sc.extends_from, sc.clip_in = "", 0.0

            mutate_story(story_id, owner, apply)
            return uri

        def extend(i: int, prev_clip: str) -> str:
            """Continuous take: extend the previous clip with Veo. Falls back
            to a normal clip if the extension fails."""
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            try:
                uri, clip_in = backend.extend_clip(current, i, prev_clip)
            except Exception:
                logger.exception("Veo extension failed; making a normal clip")
                return animate(i, current.scenes[i].frame_uri)
            scene_id = current.scenes[i].id

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.clip_uri, sc.continues_from = uri, ""
                        sc.extends_from, sc.clip_in = prev_clip, clip_in

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
                if i in takes and prev_clip:
                    ok = _run_task(
                        clip_tasks[i], lambda i=i, c=prev_clip: extend(i, c)
                    )
                    prev_clip = clip_tasks[i].result_uri if ok else ""
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

        def speak(st: Story, i: int, text: str, same_language: bool) -> str:
            """The narrator's voiceover line (on-camera lines are spoken in
            the clip itself)."""
            return backend.generate_voiceover(st, i, text)

        def voice(i: int) -> str:
            uri = speak(story, i, story.scenes[i].narration, True)
            voice_uris[i] = uri
            return uri

        def voice_alt(i: int) -> str:
            text = translated.scenes[i].narration
            if not text.strip():
                raise GenerationError(f"Scene {i + 1} has no {alt} line yet.")
            uri = speak(translated, i, text, False)
            alt_voice_uris[i] = uri
            return uri

        # On-camera lines are voiced once their clip exists (they copy how the
        # person speaks in it); narration can start right away.
        after_clips = [
            (t, voice) for i, t in voice_tasks.items() if _is_spoken(story.scenes[i])
        ] + [
            (t, voice_alt)
            for i, t in alt_voice_tasks.items()
            if _is_spoken(story.scenes[i])
        ]
        held = {id(t) for t, _ in after_clips}

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
                if id(t) not in held:
                    futures.append(pool.submit(_run_task, t, lambda i=i: voice(i)))
            for i, t in alt_voice_tasks.items():
                if t.status == QUEUED and id(t) not in held:
                    futures.append(
                        pool.submit(_run_task, t, lambda i=i: voice_alt(i))
                    )
            if sequential:
                clips_continuity()
            else:
                futures.extend(clips_parallel(pool))
            for f in futures:
                f.result()
        pending_lines = [(t, fn) for t, fn in after_clips if t.status == QUEUED]
        if pending_lines:
            with ThreadPoolExecutor(max_workers=max(1, cfg.STORY_MAX_PARALLEL)) as pool:
                for f in [
                    pool.submit(_run_task, t, lambda fn=fn, i=t.scene_index: fn(i))
                    for t, fn in pending_lines
                ]:
                    f.result()
        if music_task and music_task.status == DONE:
            music_uri = music_task.result_uri
            mutate_story(story_id, owner, lambda s: setattr(s, "music_uri", music_uri))
        elif story.music_on and story.music_uri:
            music_uri = story.music_uri

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
            # With continuity, start from the last frame of the clip that
            # comes before it in the second film (that scene's own second-
            # language clip when it has one), so the joins match there too.
            # Otherwise start from the scene's storyboard frame, like the main clip.
            start_from = ""
            if sc.continues_from and i > 0:
                prev = second.scenes[i - 1]
                start_from = prev.clip_uri or sc.continues_from
            start = (
                backend.last_frame(current, start_from, i) if start_from else sc.frame_uri
            )
            uri = backend.generate_clip(second, i, start)
            scene_id, key = sc.id, sc.alt_clip_key()

            def apply(s: Story) -> None:
                for x in s.scenes:
                    if x.id == scene_id:
                        x.clip_alt_uri, x.clip_alt_key = uri, key
                        x.clip_alt_from = start_from

            mutate_story(story_id, owner, apply)
            return uri

        pending_alt = [i for i, t in alt_clip_tasks.items() if t.status == QUEUED]
        if pending_alt and story.continuity:
            # One after another: each may start from the previous one.
            for i in sorted(pending_alt):
                _run_task(alt_clip_tasks[i], lambda i=i: animate_alt(i))
        elif pending_alt:
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
        made: dict = {}

        def stitch() -> str:
            film_uri, made["timeline"] = _film_and_timeline(
                backend.stitch(final, plan, music_uri, voices)
            )
            return film_uri

        if not _run_task(stitch_task, stitch):
            for t in later[1:]:
                if t:
                    t.status = SKIPPED
            return
        film = stitch_task.result_uri

        def apply(s: Story) -> None:
            s.final_uri = film
            s.step = "video"
            if made.get("timeline"):
                s.timeline_json = json.dumps(made["timeline"])

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
            lambda: _film_and_timeline(
                backend.stitch(
                    replace(second, timeline_json=""), alt_plan, music_uri, alt_voices
                )
            )[0],
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


def _film_and_timeline(result) -> tuple[str, dict | None]:
    """A backend stitch returns (film, timeline); older ones just the film."""
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, None


def save_timeline(story_id: str, owner: str, timeline) -> Story:
    """Store the editor's timeline (validated) on the story."""
    from services.story_timeline import normalize

    clean = normalize(timeline)

    def apply(s: Story) -> None:
        s.timeline_json = json.dumps(clean)

    return mutate_story(story_id, owner, apply)


def start_export(story_id: str, owner: str) -> Job:
    """Render the edited timeline to a new film and add it to the library."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not story.timeline_json:
        raise GenerationError("Render the film once before editing it.")
    job = _new_job(owner, story_id, "export")
    render_task = _add_task(job, "Exporting your edit · video, sound and titles", "stitch")
    library_task = _add_task(job, "Saving to your library", "library")

    def work(job: Job) -> None:
        backend = get_backend()
        from services.story_timeline import normalize

        timeline = normalize(story.timeline_json)
        if not _run_task(render_task, lambda: backend.render_timeline(story, timeline)):
            library_task.status = SKIPPED
            return
        film = render_task.result_uri

        def apply(s: Story) -> None:
            s.final_uri = film

        mutate_story(story_id, owner, apply)
        _run_task(library_task, lambda: backend.save_to_library(story, film, owner))

    return _spawn(job, work)


def start_music(story_id: str, owner: str) -> Job:
    """Make the film's music with Lyria and put it on the timeline."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    job = _new_job(owner, story_id, "music")
    task = _add_task(job, "Music · Lyria score", "music")

    def work(job: Job) -> None:
        backend = get_backend()
        prompt = story.music_prompt or default_music_prompt(story)
        seconds = float(sum(s.duration for s in story.scenes)) or 30.0

        def make() -> str:
            uri = backend.generate_music(story, prompt, seconds)
            set_music(story_id, owner, uri)
            return uri

        _run_task(task, make)

    return _spawn(job, work)


def set_music(story_id: str, owner: str, uri: str) -> Story:
    """Use `uri` as the film's music: one clip across the whole timeline."""
    from services.story_timeline import duration, new_clip_id, normalize, track

    def apply(s: Story) -> None:
        s.music_uri = uri
        s.music_on = True
        if not s.timeline_json:
            return
        tl = normalize(s.timeline_json)
        old = track(tl, "music")["clips"]
        total = duration(tl)
        track(tl, "music")["clips"] = [
            {
                "id": new_clip_id(),
                "src": uri,
                "start": 0.0,
                "in": 0.0,
                "out": total,
                "gain": old[0]["gain"] if old else 0.8,
            }
        ]
        s.timeline_json = json.dumps(normalize(tl))

    return mutate_story(story_id, owner, apply)


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
    if job.kind == "export":
        return start_export(job.story_id, owner)
    if job.kind == "music":
        return start_music(job.story_id, owner)
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
