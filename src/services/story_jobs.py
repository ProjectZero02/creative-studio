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

Long work (scenario, storyboard frames, Omni clips, music, voiceover, stitch)
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
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace

from common.analytics import get_logger
from common.error_handling import GenerationError, classify_error
from common import usage
from services import story_timeline, story_versions
from config.default import Default
from services.story_models import (
    NarrationTooLong,
    ScenarioError,
    Story,
    alt_story,
    build_stitch_plan,
    cast_from_scenario,
    default_music_prompt,
    frame_for,
    frame_scenes,
    frames_ready,
    parse_brief,
    parse_scenario,
    parse_scene_links,
    parse_sequences,
    parse_set_build,
    parse_single_scene,
    parse_translation,
    parse_visual_grammar,
    parse_voice,
    relink_scene,
    set_text_from_cast,
    take_groups,
)
from services.story_service import get_backend, is_mock_mode, resolve_video_engine
from services.story_store import StoryAccessError, get_store
from services.story_sets import (
    KINDS,
    VIEW_LABELS,
    StorySet,
    anchor_view,
    build_views,
    aspect_for,
    ensure_views,
    get_set_store,
    image_of,
    image_prompt,
    legacy_set,
    needs_migration,
    views_for,
)

logger = get_logger(__name__)

QUEUED, RUNNING, DONE, FAILED, SKIPPED, CANCELLED = (
    "queued",
    "running",
    "done",
    "failed",
    "skipped",
    "cancelled",
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
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()

# Jobs that change the script, set, frames, clips or film. Only one runs per
# story; a second one started from the page is refused (a job may still
# chain the next one itself, e.g. breakdown → set → frames).
HEAVY_KINDS = (
    "scenario",
    "scene",
    "set",
    "storyboard",
    "clips",
    "video",
    "translate",
    "music",
)
# The job whose thread is running (copied into its pool threads).
_current_job: contextvars.ContextVar[str] = contextvars.ContextVar(
    "story_current_job", default=""
)


class JobBusyError(Exception):
    """Another job is still working on this story."""
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


def _set_version(story: Story, owner: str) -> int:
    """The version of the story's set now (0 = no set), recorded with each
    film so the Edit step can tell when the set changed after it."""
    if not story.set_id:
        return 0
    story_set = get_set_store().get(story.set_id, owner)
    return story_set.version if story_set else 0


def ensure_set(story_id: str, owner: str) -> Story | None:
    """Give a story from before sets its one-character set (lazy migration,
    run when the story is opened). Stories with a set are left alone."""
    story = get_store().get(story_id, owner)
    if story is None or not needs_migration(story):
        return story

    def apply(s: Story) -> None:
        if not needs_migration(s):
            return
        made = get_set_store().save(legacy_set(s), owner)
        s.set_id = made.id
        # A film made before the migration was made with exactly this cast.
        s.set_version = made.version if (s.final_uri or s.final_alt_uri) else 0

    return mutate_story(story_id, owner, apply)


def friendly_error(exc: Exception) -> str:
    if isinstance(
        exc, (GenerationError, ScenarioError, StoryAccessError, JobBusyError)
    ):
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


def running_job(story_id: str) -> Job | None:
    """The heavy job still working on this story, if any."""
    with _jobs_lock:
        for j in _jobs.values():
            if j.story_id == story_id and j.status == RUNNING and j.kind in HEAVY_KINDS:
                return j
    return None


def ensure_free(story_id: str) -> None:
    """Refuse a new heavy job from the page while one runs on this story."""
    if not _current_job.get() and running_job(story_id) is not None:
        raise JobBusyError(
            "Another step is still working on this film. Wait for it to "
            "finish or cancel it first."
        )


def _new_job(owner: str, story_id: str, kind: str, params: dict | None = None) -> Job:
    if kind in HEAVY_KINDS:
        ensure_free(story_id)
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


def _insert_task(
    job: Job, before: Task, label: str, kind: str, scene_index: int = -1
) -> Task:
    """A step added while the job runs, shown before `before`."""
    task = Task(
        id=uuid.uuid4().hex[:8], label=label, kind=kind, scene_index=scene_index
    )
    with _jobs_lock:
        try:
            job.tasks.insert(job.tasks.index(before), task)
        except ValueError:
            job.tasks.append(task)
    return task


def _stitch_label(story: Story) -> str:
    """The stitch step in plain words for this film: one take is only
    finished (sound, checks), takes joined with no fade are joined, and
    only a film with fades between its shots is crossfaded."""
    if len(take_groups(story)) <= 1:
        return FINISH_LABEL
    if story.chains_takes and story.seamless_joins:
        return JOIN_LABEL
    return CROSSFADE_LABEL


FINISH_LABEL = "Finishing the film · sound and checks"
JOIN_LABEL = "Joining the takes"
CROSSFADE_LABEL = "Stitching the film · crossfades and mix"


def _plan_label(plan) -> str:
    """The stitch step's label from the real plan (once the clips exist)."""
    segs = plan.segments
    if len(segs) <= 1 or all(s.join == "extend" for s in segs[1:]):
        return FINISH_LABEL
    if all(not s.fade_in for s in segs[1:]):
        return JOIN_LABEL
    return CROSSFADE_LABEL


def _save_film_item(backend, story: Story, film: str, owner: str, alt: bool = False) -> str:
    """Keep one library item per film: update the story's item when it has
    one, else add it and remember its id."""
    field_name = "library_alt_id" if alt else "library_id"
    item_id = backend.save_to_library(
        replace(story, library_id=getattr(story, field_name)), film, owner
    )
    if item_id and item_id != getattr(story, field_name):
        mutate_story(
            story.id, owner, lambda s: setattr(s, field_name, item_id)
        )
    return ""


def _add_task(job: Job, label: str, kind: str, scene_index: int = -1) -> Task:
    task = Task(
        id=uuid.uuid4().hex[:8], label=label, kind=kind, scene_index=scene_index
    )
    with _jobs_lock:
        job.tasks.append(task)
    return task


def _run_task(
    task: Task,
    fn: Callable[[], str],
    cancel_event: threading.Event | None = None,
) -> bool:
    if (cancel_event is not None and cancel_event.is_set()) or task.status == SKIPPED:
        task.status = SKIPPED
        task.error = task.error or "Cancelled by user."
        return False
    task.status = RUNNING
    task.started_at = time.time()
    try:
        task.result_uri = fn() or ""
        task.status = DONE
        return True
    except story_timeline.Cancelled:
        task.status = SKIPPED
        task.error = "Cancelled by user."
        return False
    except Exception as exc:
        logger.exception("Story Studio task failed: %s", task.label)
        task.error = friendly_error(exc)
        task.status = FAILED
        return False
    finally:
        task.ended_at = time.time()


def _finish(job: Job) -> None:
    if job.cancel_event.is_set():
        with _jobs_lock:
            for t in job.tasks:
                if t.status == QUEUED:
                    t.status = SKIPPED
                    t.error = t.error or "Cancelled by user."
        job.status = CANCELLED
        job.message = "Cancelled by user."
        job.finished_at = time.time()
        return
    failed = [t for t in job.tasks if t.status == FAILED]
    job.status = FAILED if failed else DONE
    if failed:
        job.message = (
            f"{len(failed)} of {len(job.tasks)} steps failed. Finished work is kept; "
            "press Retry to continue."
        )
    job.finished_at = time.time()


class _Pool(ThreadPoolExecutor):
    """A thread pool whose tasks run in the caller's context, so model calls
    made in them are counted for the job's owner (common.usage)."""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)


def _spawn(job: Job, target: Callable[[Job], None]) -> Job:
    def runner():
        _current_job.set(job.id)
        story_timeline.CANCEL.set(job.cancel_event)
        try:
            with usage.acting_for(job.owner, page="story", feature="story"):
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


def cancel_job(job_id: str, owner: str) -> Job | None:
    """Request cancellation of a running job (owner-only)."""
    job = get_job(job_id, owner)
    if job is None:
        return None
    if job.status != RUNNING:
        return job
    job.cancel_event.set()
    with _jobs_lock:
        for t in job.tasks:
            if t.status == QUEUED:
                t.status = SKIPPED
                t.error = "Cancelled by user."
    return job


def latest_job_for(story_id: str, owner: str) -> Job | None:
    """The newest job of this story (to re-attach after a page reload)."""
    with _jobs_lock:
        jobs = [
            j for j in _jobs.values() if j.story_id == story_id and j.owner == owner
        ]
    return max(jobs, key=lambda j: j.created_at) if jobs else None


# How long a step usually takes, relative to the others, so the progress bar
# moves with time and not with the count of steps (a video clip is many
# times a voice line). Steps not listed weigh 1.
TASK_WEIGHT = {
    "clip": 10.0,
    "clip_alt": 10.0,
    "frame": 3.0,
    "set": 3.0,
    "scenario": 3.0,
    "music": 4.0,
    "stitch": 2.0,
    "stitch_alt": 2.0,
    "library": 0.5,
    "library_alt": 0.5,
}


def task_progress(tasks: list[dict]) -> float:
    """0..1: finished and skipped steps by weight, a running one counted at
    40 %. The one number the panel shows (bar and percent)."""
    total = sum(TASK_WEIGHT.get(t["kind"], 1.0) for t in tasks) or 1.0
    got = 0.0
    for t in tasks:
        w = TASK_WEIGHT.get(t["kind"], 1.0)
        if t["status"] in (DONE, SKIPPED):
            got += w
        elif t["status"] == RUNNING:
            got += 0.4 * w
    return round(min(1.0, got / total), 3)


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
    return {
        "id": job.id,
        "kind": job.kind,
        "story_id": job.story_id,
        "status": job.status,
        "message": job.message,
        "elapsed": round((job.finished_at or now) - job.created_at, 1),
        "progress": task_progress(tasks),
        "done": done,
        "total": len(tasks),
        "tasks": tasks,
        # Set jobs: task id -> [kind, asset id, view], so cards show progress.
        "targets": dict(job.params.get("task_targets") or {}),
        # Subtitle jobs: which download is being made.
        "params": {"variant": job.params.get("variant", "")},
        # A job this one started when it finished (Setup: breakdown, then frames).
        "next_job": job.params.get("next_job", ""),
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def start_scenario(story_id: str, owner: str, then_frames: bool = False) -> Job:
    """Write the breakdown. `then_frames`: when it is written, paint the
    start frame of every take right away (Setup's guided flow); the new job's
    id is in the snapshot as "next_job"."""
    job = _new_job(owner, story_id, "scenario", {"then_frames": then_frames})
    task = _add_task(job, "Writing the scenario with Gemini", "scenario")

    def work(job: Job) -> None:
        backend = get_backend()
        story = get_store().get(story_id, owner)
        if story is None:
            raise StoryAccessError("Story not found.")
        story_set = get_set_store().get(story.set_id, owner) if story.set_id else None

        def write() -> str:
            last: Exception | None = None
            note = ""
            for attempt in range(2):  # one retry on bad JSON or long lines
                try:
                    args = (story, story_set) if story_set is not None else (story,)
                    text = (
                        backend.write_scenario(*args, note=note)
                        if note
                        else backend.write_scenario(*args)
                    )
                    title, scenes = parse_scenario(
                        text,
                        story.scene_count,
                        story.duration,
                        story.camera,
                        story.speech_mode,
                        strict_length=attempt == 0,
                    )
                    voice = parse_voice(text) if any(sc.spoken for sc in scenes) else ""
                    brief = parse_brief(text)
                    visual_grammar = parse_visual_grammar(text)
                    sequences_json = parse_sequences(text)
                    cast_json = ""
                    if story_set is not None:
                        parse_scene_links(text, story_set, scenes)
                    else:
                        cast_json = cast_from_scenario(
                            text, Story(title=title, style=story.style, scenes=scenes)
                        )
                    break
                except NarrationTooLong as exc:
                    last, note = exc, exc.note()
                    logger.info("Story %s: %s Asking again.", story_id, exc)
                except ScenarioError as exc:
                    last = exc
            else:
                raise last or ScenarioError("No scenario.")

            def apply(s: Story) -> None:
                s.title = title
                s.title_alt = ""
                s.speaker_voice = voice
                if brief:
                    s.brief = brief
                if visual_grammar:
                    s.visual_grammar = visual_grammar
                if sequences_json:
                    s.sequences_json = sequences_json
                s.scenes = scenes
                if scenes and all(sc.spoken for sc in scenes):
                    s.voice_on = False  # all on camera: no narrator
                if s.speech_mode == "none":
                    s.voice_on = False  # music and picture only
                s.cast_json = cast_json
                s.approved = False
                s.clear_films()
                s.step = "scenario"
                if not s.music_prompt:
                    s.music_prompt = default_music_prompt(s)

            mutate_story(story_id, owner, apply)
            return ""

        if (
            _run_task(task, write, job.cancel_event)
            and then_frames
            and not job.cancel_event.is_set()
        ):
            try:
                # Always a set before any frame: a story without one gets
                # its set built (from the cast the breakdown wrote), and the
                # set job then paints the start frames from it.
                fresh = get_store().get(story_id, owner)
                if fresh is not None and not fresh.set_id:
                    job.params["next_job"] = start_set(
                        story_id, owner, then_frames=True
                    ).id
                else:
                    job.params["next_job"] = start_storyboard(story_id, owner).id
            except Exception:
                logger.exception("Story %s: could not start the set or frames", story_id)

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
            text = backend.rewrite_scene(story, index)
            scene = parse_single_scene(
                text,
                story.scenes[index].duration,
                story.camera,
                story.speech_mode,
            )
            story_set = (
                get_set_store().get(story.set_id, owner) if story.set_id else None
            )

            def apply(s: Story) -> None:
                if index < len(s.scenes):
                    cur = s.scenes[index]
                    cur.spoken = scene.spoken
                    relink_scene(s, cur, text, story_set)
                    cur.narration, cur.visual, cur.camera = (
                        scene.narration,
                        scene.visual,
                        scene.camera,
                    )
                    cur.frame_uri = ""
                    cur.clear_clip()
                    cur.narration_alt = ""
                    s.clear_films()

            mutate_story(story_id, owner, apply)
            return ""

        _run_task(task, rewrite)

    return _spawn(job, work)


def start_storyboard(
    story_id: str,
    owner: str,
    indices: list[int] | None = None,
    note: str = "",
) -> Job:
    """Paint the start frame of each take. Scene 1 goes first and anchors
    the look. Scenes that continue a take need no frame of their own: the
    take carries on from its clip (see frame_scenes).

    `indices` limits the run to those scenes (redo); a scene inside a take
    repaints its take's start frame. Otherwise every take start without a
    frame is painted. `note`: the director's "Redo with note" text.
    """
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    starts = frame_scenes(story)
    if indices is None:
        targets = [i for i in starts if not story.scenes[i].frame_uri]
    else:
        targets = sorted(
            {story.take_start(i) for i in indices if 0 <= i < len(story.scenes)}
        )
    job = _new_job(owner, story_id, "storyboard", {"indices": targets})
    tasks = {
        i: _add_task(job, f"Take {starts.index(i) + 1 if i in starts else i + 1} · start frame", "frame", i)
        for i in targets
    }
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()

        def paint(i: int, reference: str) -> str:
            current = get_store().get(story_id, owner)
            if current is None or i >= len(current.scenes):
                raise StoryAccessError("Story not found.")
            uri = (
                backend.generate_frame(current, i, reference, note=note)
                if note
                else backend.generate_frame(current, i, reference)
            )
            take = [current.scenes[j].id for g in take_groups(current) if i in g for j in g]

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == take[0]:
                        sc.frame_uri = uri
                    if sc.id in take:
                        # The take starts from this frame: its clips change.
                        sc.clear_clip()
                s.clear_films()

            mutate_story(story_id, owner, apply)
            return uri

        reference = story.reference_uri
        rest = list(targets)
        painted: dict[int, str] = {}

        def reference_for(i: int) -> str:
            # A new take in the same place as the shot before it is painted
            # from that take's frame, so a cut to a new angle keeps the venue,
            # light and people. Otherwise scene 1's frame anchors the look.
            p = same_place_source(story, i)
            if p is not None:
                uri = painted.get(p) or story.scenes[p].frame_uri
                if uri:
                    return uri
            return reference

        def run_chain(chain: list[int]) -> None:
            for i in chain:
                if job.cancel_event.is_set():
                    break
                if _run_task(tasks[i], lambda i=i: paint(i, reference_for(i)), job.cancel_event):
                    painted[i] = tasks[i].result_uri

        if 0 in targets and not reference:
            ok = _run_task(tasks[0], lambda: paint(0, ""), job.cancel_event)
            rest.remove(0)
            reference = tasks[0].result_uri if ok else ""
            if ok:
                painted[0] = reference
        if (
            not reference
            and story.scenes
            and story.scenes[0].frame_uri
            and 0 not in targets
        ):
            reference = story.scenes[0].frame_uri
        # Frames that build on one another are painted in order (one chain);
        # chains run side by side.
        chains: list[list[int]] = []
        chain_of: dict[int, list[int]] = {}
        for i in rest:
            p = same_place_source(story, i)
            chain = chain_of.get(p) if p is not None else None
            if chain is None:
                chain = []
                chains.append(chain)
            chain.append(i)
            chain_of[i] = chain
        workers = max(1, cfg.STORY_MAX_PARALLEL)
        with _Pool(max_workers=workers) as pool:
            for chain in chains:
                if job.cancel_event.is_set():
                    break
                pool.submit(run_chain, chain)

    return _spawn(job, work)


def same_place_source(story: Story, i: int) -> int | None:
    """The take start whose frame scene `i` (a take start) should be painted
    from: the take of the shot before it, when both are in the same place
    (same location, or the story has no set). None otherwise."""
    if i <= 0 or i >= len(story.scenes):
        return None
    here, before = story.scenes[i].location_id, story.scenes[i - 1].location_id
    if story.set_id and here != before:
        return None
    return story.take_start(i - 1)


def _bridge_end_frame(story: Story, i: int) -> str:
    """Target end frame when scene ``i + 1`` joins via a ``bridge`` transition."""
    if (
        i + 1 < len(story.scenes)
        and story.scenes[i + 1].transition == "bridge"
        and story.scenes[i].frame_uri
        and story.scenes[i + 1].frame_uri
        and not story.continues_take(i + 1)
    ):
        return story.scenes[i + 1].frame_uri
    return ""


def start_scene_clips(story_id: str, owner: str, indices: list[int]) -> Job:
    """Generate or regenerate specific scene clips on demand without running stitch."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    targets = sorted({i for i in indices if 0 <= i < len(story.scenes)})
    job = _new_job(owner, story_id, "clips", {"indices": targets})
    tasks = {
        i: _add_task(job, f"Scene {i + 1} · video clip", "clip", i)
        for i in targets
    }
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()

        def animate_one(i: int) -> str:
            current = get_store().get(story_id, owner)
            if current is None or i >= len(current.scenes):
                raise StoryAccessError("Story not found.")
            sc = current.scenes[i]
            start = frame_for(current, i)
            end_frame = _bridge_end_frame(current, i)
            uri = (
                backend.generate_clip(current, i, start, end_frame_uri=end_frame)
                if end_frame
                else backend.generate_clip(current, i, start)
            )
            thread = _interaction_of(backend, uri)
            scene_id = sc.id
            model_used = sc.video_model_used or resolve_video_engine(current, sc)
            turns_json = sc.turns_json

            def apply(s: Story) -> None:
                for x in s.scenes:
                    if x.id == scene_id:
                        x.turns_json = turns_json
                        x.clip_uri = uri
                        x.continues_from = ""
                        x.extends_from, x.clip_in = "", 0.0
                        x.interaction_id = thread
                        x.bridged_to = end_frame
                        x.video_model_used = model_used
                s.clear_films()

            mutate_story(story_id, owner, apply)
            return uri

        with _Pool(max_workers=max(1, cfg.STORY_MAX_PARALLEL)) as pool:
            futures = []
            for i in targets:
                if job.cancel_event.is_set():
                    break
                futures.append(
                    pool.submit(
                        _run_task,
                        tasks[i],
                        lambda i=i: animate_one(i),
                        job.cancel_event,
                    )
                )
            for f in futures:
                f.result()

    return _spawn(job, work)


def _is_spoken(scene) -> bool:
    return bool(scene.spoken and scene.narration.strip())


def _interaction_of(backend, clip_uri: str) -> str:
    """The Omni thread that made a clip ("" for backends without threads)."""
    lookup = getattr(backend, "interaction_of", None)
    return (lookup(clip_uri) or "") if callable(lookup) else ""


def _needs_voice(story: Story, scene) -> bool:
    """A TTS line: narrated scenes with the voiceover on. On-camera lines
    are spoken by the person in the clip (Gemini Omni's own speech)."""
    if _is_spoken(scene):
        return False
    return story.voice_on and bool(scene.narration.strip())


def _voice_key(story: Story, index: int, set_version: int, alt: bool = False) -> str:
    """What a narrator line is made from: its text, the voice, language and
    set (the set narrator's pinned voice), the TTS model and the scene's
    length (a line is fitted to it). Same key, same voice file."""
    import hashlib

    sc = story.scenes[index]
    text = (sc.narration_alt if alt else sc.narration).strip()
    raw = json.dumps(
        [
            text,
            story.voice_name,
            story.alt_language if alt else story.language,
            story.set_id,
            set_version,
            Default().STORY_TTS_MODEL,
            sc.duration,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _keep_voice(
    story_id: str, owner: str, scene_id: str, uri: str, key: str, alt: bool = False
) -> None:
    """Store a scene's voiced line so the next render can reuse it."""

    def apply(s: Story) -> None:
        for sc in s.scenes:
            if sc.id == scene_id:
                if alt:
                    sc.voice_alt_uri, sc.voice_alt_key = uri, key
                else:
                    sc.voice_uri, sc.voice_key = uri, key

    mutate_story(story_id, owner, apply)


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
    by_id = {sc.id: line for sc, line in zip(story.scenes, lines, strict=False)}

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
    """Animate each scene with Gemini Omni, add music and voiceover, stitch,
    save. Back-to-back spoken scenes continue one Omni thread (same voice)."""
    ensure_free(story_id)
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not frames_ready(story):
        raise GenerationError("Every take needs its start frame first.")

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
                sc.clear_clip()

    story = mutate_story(story_id, owner, prepare)
    job = _new_job(owner, story_id, "video")
    n = len(story.scenes)
    takes = {i for i in range(n) if story.continues_take(i)}
    clip_tasks: dict[int, Task] = {}
    bridge_tasks: dict[int, Task] = {}
    for i, sc in enumerate(story.scenes):
        if sc.clip_uri:
            continue
        if story.chains_takes and i > 0 and i not in takes:
            bridge_tasks[i] = _add_task(
                job, f"Scene {i + 1} · last frame of scene {i}", "bridge", i
            )
        what = (
            f"same take as scene {i}"
            if i in takes
            else "video clip with speech"
            if _is_spoken(sc)
            else "video clip"
        )
        clip_tasks[i] = _add_task(job, f"Scene {i + 1} · {what}", "clip", i)
    sequential = story.chains_takes or bool(takes & set(clip_tasks))
    # Music is kept between renders until its prompt changes.
    music_task = (
        _add_task(job, "Music · Lyria score", "music")
        if story.music_on and not story.music_uri
        else None
    )
    track_tasks = {
        t["id"]: _add_task(job, f"Music · track for takes {_takes_label(t)}", "music")
        for t in story.music_tracks()
        if story.music_on and not t.get("uri")
    }
    # Narrator lines: a line voiced before from the same text, voice and
    # length is reused; only new or changed lines go to text-to-speech.
    set_version = _set_version(story, owner)
    voice_keys = {
        i: _voice_key(story, i, set_version)
        for i, sc in enumerate(story.scenes)
        if _needs_voice(story, sc)
    }
    cached_voices = {
        i: story.scenes[i].cached_voice(key)
        for i, key in voice_keys.items()
        if story.scenes[i].cached_voice(key)
    }
    voice_tasks = {
        i: _add_task(job, f"Scene {i + 1} · voiceover", "voice", i)
        for i in voice_keys
        if i not in cached_voices
    }
    # Fitting measures and, if needed, shortens lines: only after new ones.
    fit_task = (
        _add_task(job, "Fitting the narration to its scenes", "voice")
        if voice_tasks
        else None
    )
    stitch_task = _add_task(job, _stitch_label(story), "stitch")
    library_task = _add_task(job, "Saving to your library", "library")
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()
        voice_uris: dict[int, str] = dict(cached_voices)
        music_uri = ""

        def animate(i: int, start_frame: str, from_clip: str = "") -> str:
            """Render scene i's clip. from_clip: the previous clip whose last
            frame is start_frame (continuity), else empty."""
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            end_frame = _bridge_end_frame(current, i)
            scene_obj = current.scenes[i]
            kept_before = scene_obj.partial_turns_json
            try:
                uri = (
                    backend.generate_clip(
                        current, i, start_frame, end_frame_uri=end_frame
                    )
                    if end_frame
                    else backend.generate_clip(current, i, start_frame)
                )
            except Exception:
                # A long take that failed part way keeps the turns that
                # worked, so Retry goes on from them (Scene.saved_turns).
                kept = scene_obj.partial_turns_json
                if kept != kept_before:
                    kept_id = scene_obj.id

                    def keep(s: Story, kept_id=kept_id, kept=kept) -> None:
                        for sc in s.scenes:
                            if sc.id == kept_id:
                                sc.partial_turns_json = kept

                    mutate_story(story_id, owner, keep)
                raise
            thread = _interaction_of(backend, uri)
            scene_id = scene_obj.id
            model_used = scene_obj.video_model_used or resolve_video_engine(
                current, scene_obj
            )

            turns_json = scene_obj.turns_json

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.clip_uri = uri
                        sc.continues_from = from_clip
                        sc.extends_from, sc.clip_in = "", 0.0
                        sc.interaction_id = thread
                        sc.bridged_to = end_frame
                        sc.video_model_used = model_used
                        sc.turns_json = turns_json
                        sc.partial_turns_json = ""

            mutate_story(story_id, owner, apply)
            return uri

        def extend(i: int, prev_clip: str) -> str:
            """Continuous take: continue the previous clip in its Omni thread
            (same person and voice). Falls back to a normal clip on failure."""
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            try:
                uri, clip_in = backend.extend_clip(current, i, prev_clip)
            except Exception:
                # Start the new clip on the take's last frame, not on the
                # scene's own painted frame (a different-looking place).
                logger.exception("Omni continuation failed; starting from its last frame")
                try:
                    start = backend.last_frame(current, prev_clip, i)
                except Exception:
                    logger.exception("Could not take the last frame of %s", prev_clip)
                    return animate(i, frame_for(current, i))
                return animate(i, start, prev_clip)
            thread = _interaction_of(backend, uri)
            scene_obj = current.scenes[i]
            scene_id = scene_obj.id
            model_used = scene_obj.video_model_used or resolve_video_engine(
                current, scene_obj
            )

            def apply(s: Story) -> None:
                for sc in s.scenes:
                    if sc.id == scene_id:
                        sc.clip_uri, sc.continues_from = uri, ""
                        sc.extends_from, sc.clip_in = prev_clip, clip_in
                        sc.interaction_id = thread
                        sc.turns_json = ""
                        sc.bridged_to = ""
                        sc.video_model_used = model_used

            mutate_story(story_id, owner, apply)
            return uri

        def clips_continuity() -> None:
            prev_clip = ""
            for i in range(n):
                if job.cancel_event.is_set():
                    for j in range(i, n):
                        if j in bridge_tasks and bridge_tasks[j].status == QUEUED:
                            bridge_tasks[j].status = SKIPPED
                            bridge_tasks[j].error = "Cancelled by user."
                        if j in clip_tasks and clip_tasks[j].status == QUEUED:
                            clip_tasks[j].status = SKIPPED
                            clip_tasks[j].error = "Cancelled by user."
                    break
                current = get_store().get(story_id, owner)
                sc = current.scenes[i]
                if i not in clip_tasks:
                    prev_clip = sc.clip_uri
                    continue
                if i in takes and prev_clip:
                    ok = _run_task(
                        clip_tasks[i],
                        lambda i=i, c=prev_clip: extend(i, c),
                        job.cancel_event,
                    )
                    prev_clip = clip_tasks[i].result_uri if ok else ""
                    continue
                start, from_clip = frame_for(current, i), ""
                if i in bridge_tasks:
                    if prev_clip and _run_task(
                        bridge_tasks[i],
                        lambda i=i, c=prev_clip, cur=current: backend.last_frame(cur, c, i),
                        job.cancel_event,
                    ):
                        start, from_clip = bridge_tasks[i].result_uri, prev_clip
                    elif not prev_clip:
                        bridge_tasks[i].status = SKIPPED
                ok = _run_task(
                    clip_tasks[i],
                    lambda i=i, s=start, c=from_clip: animate(i, s, c),
                    job.cancel_event,
                )
                prev_clip = clip_tasks[i].result_uri if ok else ""

        def clips_parallel(pool: ThreadPoolExecutor) -> list:
            return [
                pool.submit(
                    _run_task,
                    clip_tasks[i],
                    lambda i=i: animate(i, frame_for(story, i)),
                    job.cancel_event,
                )
                for i in clip_tasks
            ]

        def voice(i: int) -> str:
            """The narrator's line (on-camera lines are spoken in the clip)."""
            uri = backend.generate_voiceover(story, i, story.scenes[i].narration)
            voice_uris[i] = uri
            _keep_voice(story_id, owner, story.scenes[i].id, uri, voice_keys[i])
            return uri

        with _Pool(max_workers=max(2, cfg.STORY_MAX_PARALLEL)) as pool:
            futures = []
            if music_task and not job.cancel_event.is_set():
                seconds = sum(s.duration for s in story.scenes)
                prompt = story.music_prompt or default_music_prompt(story)
                futures.append(
                    pool.submit(
                        _run_task,
                        music_task,
                        lambda: backend.generate_music(story, prompt, seconds),
                        job.cancel_event,
                    )
                )
            for tid, t in track_tasks.items():
                if job.cancel_event.is_set():
                    break
                futures.append(
                    pool.submit(
                        _run_task,
                        t,
                        lambda tid=tid: _make_track(story_id, owner, backend, tid),
                        job.cancel_event,
                    )
                )
            for i, t in voice_tasks.items():
                if job.cancel_event.is_set():
                    break
                futures.append(
                    pool.submit(_run_task, t, lambda i=i: voice(i), job.cancel_event)
                )
            if sequential:
                clips_continuity()
            else:
                futures.extend(clips_parallel(pool))
            for f in futures:
                f.result()
        if job.cancel_event.is_set():
            return
        if fit_task:
            _run_task(
                fit_task,
                lambda: _fit_voice_lines(
                    story_id, owner, backend, voice_uris, set_version
                ),
                job.cancel_event,
            )
        if music_task and music_task.status == DONE:
            music_uri = music_task.result_uri
            mutate_story(story_id, owner, lambda s: setattr(s, "music_uri", music_uri))
        elif story.music_on and story.music_uri:
            music_uri = story.music_uri

        if job.cancel_event.is_set():
            return
        final = get_store().get(story_id, owner)
        missing = [i + 1 for i, s in enumerate(final.scenes) if not s.clip_uri]
        if missing:
            stitch_task.status = library_task.status = SKIPPED
            stitch_task.error = f"Waiting for scene {', '.join(map(str, missing))}."
            return
        made: dict = {}

        def stitch_now() -> str:
            plan = build_stitch_plan(
                final.scenes,
                cfg.STORY_CROSSFADE_SECONDS,
                seamless=final.chains_takes and final.seamless_joins,
            )
            voices = [voice_uris.get(seg.index, "") for seg in plan.segments]
            film_uri, made["timeline"] = _film_and_timeline(
                backend.stitch(final, plan, music_uri, voices)
            )
            return film_uri

        stitch_task.label = _plan_label(
            build_stitch_plan(
                final.scenes,
                cfg.STORY_CROSSFADE_SECONDS,
                seamless=final.chains_takes and final.seamless_joins,
            )
        )
        if not _run_task(stitch_task, stitch_now, job.cancel_event):
            library_task.status = SKIPPED
            return

        def remake(label: str, fn) -> bool:
            """A paid remake the checks asked for, shown as its own step,
            then the film stitched again."""
            nonlocal final
            task = _insert_task(job, library_task, label, "clip")
            ok = _run_task(task, fn, job.cancel_event)
            final = get_store().get(story_id, owner) or final
            again = None
            if ok:
                again = _insert_task(
                    job, library_task, "Stitching the film again", "stitch"
                )
                ok = _run_task(again, stitch_now, job.cancel_event)
            if ok:
                stitch_task.result_uri = again.result_uri
                return True
            # A failed try never fails the film: it keeps the first one.
            for t in (task, again):
                if t is not None and t.status == FAILED:
                    t.status = SKIPPED
                    t.error = "Could not improve it; the film keeps the first try."
            return False

        # A join meant to be invisible that still jumps: make the clip after
        # it again (a new take of the same prompt) and re-stitch.
        retries = 0 if is_mock_mode() else max(0, int(cfg.STORY_SEAM_RETRIES))
        for _ in range(retries):
            redo = seams_to_redo(final, (made.get("timeline") or {}).get("seams"))
            if not redo or job.cancel_event.is_set():
                break

            def smooth(redo=redo) -> str:
                for i in redo:
                    prev_clip = final.scenes[i - 1].clip_uri
                    if final.continues_take(i):
                        extend(i, prev_clip)
                    else:
                        current = get_store().get(story_id, owner) or final
                        animate(i, backend.last_frame(current, prev_clip, i), prev_clip)
                return ""

            scenes = ", ".join(str(i + 1) for i in redo)
            if not remake(f"Scene {scenes} · making a rough join again", smooth):
                break
        # A cut the video model put inside a take: make that turn again.
        for _ in range(max(0, int(getattr(cfg, "STORY_TURN_REDOS", 1)))):
            redo = turns_to_redo(final, (made.get("timeline") or {}).get("cuts"))
            if not redo or job.cancel_event.is_set():
                break

            def return_turns(redo=redo) -> str:
                for i, turn in redo:
                    _redo_turn(story_id, owner, backend, i, turn)
                return ""

            turns = ", ".join(f"scene {i + 1} turn {t + 1}" for i, t in redo)
            if not remake(f"Making {turns} again · a cut inside the take", return_turns):
                break
        if job.cancel_event.is_set():
            # Cancelled during the checks: keep the last film.
            library_task.status = SKIPPED
            return
        film = stitch_task.result_uri

        def apply(s: Story) -> None:
            s.final_uri = film
            s.final_parts_json = json.dumps(s.film_parts())
            s.film_edited = False
            s.set_version = _set_version(s, owner)
            s.step = "video"
            if made.get("timeline"):
                s.timeline_json = json.dumps(made["timeline"])
            # What the cut scan and sound checks found, shown on each take.
            cuts = (made.get("timeline") or {}).get("cuts") or []
            sound = (made.get("timeline") or {}).get("sound") or {}
            for i, sc in enumerate(s.scenes):
                mine = [
                    {"t": c.get("t", 0), "turn": c.get("turn", -1)}
                    for c in cuts
                    if c.get("scene") == i
                ]
                sc.cuts_json = json.dumps(mine) if mine else ""
                flags = sound.get(str(i)) or []
                sc.sound_json = json.dumps(flags) if flags else ""
            story_versions.remember(s, "render")

        saved = mutate_story(story_id, owner, apply)
        _run_task(
            library_task,
            lambda: _save_film_item(backend, saved, film, owner),
            job.cancel_event,
        )
        # The second-language film is its own job, after this one.
        if saved.makes_alt and not job.cancel_event.is_set():
            try:
                job.params["next_job"] = start_alt_video(story_id, owner).id
            except Exception:
                logger.exception("Could not start the second-language film")

    return _spawn(job, work)


def start_alt_video(story_id: str, owner: str) -> Job:
    """The second-language film on its own: the same clips and music, the
    narration translated and voiced again, and spoken takes made again
    saying the translated lines. The main film is left as it is."""
    ensure_free(story_id)
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not story.scenes or any(not sc.clip_uri for sc in story.scenes):
        raise GenerationError("Make the film first.")
    if not any(sc.narration.strip() for sc in story.scenes):
        raise GenerationError("There are no lines to translate.")
    alt = story.alt_language
    job = _new_job(owner, story_id, "video", {"alt": True})
    translate_task = (
        _add_task(job, f"Translating the narration into {alt}", "translate")
        if story.needs_translation()
        else None
    )
    music_task = (
        _add_task(job, "Music · Lyria score", "music")
        if story.music_on and not story.music_uri
        else None
    )
    voice_tasks = {
        i: _add_task(job, f"Scene {i + 1} · {alt} voiceover", "voice_alt", i)
        for i, sc in enumerate(story.scenes)
        if _needs_voice(story, sc)
    }
    # Spoken takes: the speech is in the picture, so the take is made again
    # saying the translated line (kept while the last one is current).
    clip_tasks = {
        i: _add_task(job, f"Scene {i + 1} · {alt} video clip with speech", "clip_alt", i)
        for i, sc in enumerate(story.scenes)
        if _is_spoken(sc) and not sc.has_alt_clip()
    }
    stitch_task = _add_task(job, f"Making the {alt} film", "stitch_alt")
    library_task = _add_task(job, f"Saving the {alt} film to your library", "library_alt")
    set_version = _set_version(story, owner)
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()
        if translate_task and not _run_task(
            translate_task, lambda: _translate_into(story_id, owner), job.cancel_event
        ):
            for t in [*voice_tasks.values(), *clip_tasks.values(), stitch_task, library_task]:
                t.status = SKIPPED
            return
        if job.cancel_event.is_set():
            return
        latest = get_store().get(story_id, owner) or story
        translated = alt_story(latest)
        voice_uris: dict[int, str] = {}

        def voice(i: int) -> str:
            sc = latest.scenes[i]
            text = translated.scenes[i].narration
            if not text.strip():
                raise GenerationError(f"Scene {i + 1} has no {alt} line yet.")
            key = _voice_key(latest, i, set_version, alt=True)
            uri = sc.cached_voice(key, alt=True)
            if not uri:
                uri = backend.generate_voiceover(translated, i, text)
                _keep_voice(story_id, owner, sc.id, uri, key, alt=True)
            voice_uris[i] = uri
            return uri

        def animate(i: int) -> str:
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            sc = current.scenes[i]
            second = alt_story(current)
            if not second.scenes[i].narration.strip():
                raise GenerationError(f"Scene {i + 1} has no {alt} line yet.")
            # With continuity, start from the last frame of the clip before it
            # in the second film, so the joins match there too; otherwise
            # from the scene's own frame, like the main clip.
            start_from = ""
            if sc.continues_from and i > 0:
                prev = second.scenes[i - 1]
                start_from = prev.clip_uri or sc.continues_from
            start = (
                backend.last_frame(current, start_from, i)
                if start_from
                else frame_for(current, i)
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

        with _Pool(max_workers=max(2, cfg.STORY_MAX_PARALLEL)) as pool:
            futures = []
            if music_task:
                seconds = sum(s.duration for s in latest.scenes)
                prompt = latest.music_prompt or default_music_prompt(latest)
                futures.append(
                    pool.submit(
                        _run_task,
                        music_task,
                        lambda: backend.generate_music(latest, prompt, seconds),
                        job.cancel_event,
                    )
                )
            for i, t in voice_tasks.items():
                futures.append(
                    pool.submit(_run_task, t, lambda i=i: voice(i), job.cancel_event)
                )
            if latest.chains_takes:
                # One after another: each may start from the one before.
                for i in sorted(clip_tasks):
                    if job.cancel_event.is_set():
                        break
                    _run_task(clip_tasks[i], lambda i=i: animate(i), job.cancel_event)
            else:
                futures.extend(
                    pool.submit(_run_task, t, lambda i=i: animate(i), job.cancel_event)
                    for i, t in clip_tasks.items()
                )
            for f in futures:
                f.result()
        if job.cancel_event.is_set():
            return
        music_uri = ""
        if music_task and music_task.status == DONE:
            music_uri = music_task.result_uri
            mutate_story(story_id, owner, lambda s: setattr(s, "music_uri", music_uri))
        elif latest.music_on:
            music_uri = latest.music_uri
        latest = get_store().get(story_id, owner) or latest
        no_speech = [
            i + 1
            for i, sc in enumerate(latest.scenes)
            if _is_spoken(sc) and not sc.has_alt_clip()
        ]
        if no_speech:
            stitch_task.status = library_task.status = SKIPPED
            stitch_task.error = f"Scene {', '.join(map(str, no_speech))} has no {alt} clip."
            return
        if voice_tasks and not voice_uris and not latest.has_spoken:
            stitch_task.status = library_task.status = SKIPPED
            stitch_task.error = f"No {alt} voiceover was made."
            return
        second = alt_story(latest)
        plan = build_stitch_plan(
            second.scenes,
            cfg.STORY_CROSSFADE_SECONDS,
            seamless=second.chains_takes and second.seamless_joins,
        )
        voices = [voice_uris.get(seg.index, "") for seg in plan.segments]
        if not _run_task(
            stitch_task,
            lambda: _film_and_timeline(
                backend.stitch(replace(second, timeline_json=""), plan, music_uri, voices)
            )[0],
            job.cancel_event,
        ) or job.cancel_event.is_set():
            library_task.status = SKIPPED
            return
        alt_film = stitch_task.result_uri
        saved = mutate_story(
            story_id, owner, lambda s: setattr(s, "final_alt_uri", alt_film)
        )
        _run_task(
            library_task,
            lambda: _save_film_item(
                backend, alt_story(saved), alt_film, owner, alt=True
            ),
            job.cancel_event,
        )

    return _spawn(job, work)


def seams_to_redo(story: Story, seams: list[dict] | None) -> list[int]:
    """Scenes to make again because the seamless join before them jumps.
    Only a scene no later scene was built on (the last of its take, or a
    clip of its own): remaking one in the middle of a take would leave the
    rest of the take continuing a clip that no longer exists."""
    out: list[int] = []
    n = len(story.scenes)
    for s in seams or []:
        i = int(s.get("scene", -1))
        if not s.get("jump") or i <= 0 or i >= n or i in out:
            continue
        if i + 1 < n and story.continues_take(i + 1):
            continue
        out.append(i)
    return out


def turns_to_redo(story: Story, cuts: list[dict] | None) -> list[tuple[int, int]]:
    """(scene, turn) to make again for each scene with a cut inside it: the
    first cut's turn. Only a scene no later scene continues (see
    `seams_to_redo`)."""
    out: list[tuple[int, int]] = []
    n = len(story.scenes)
    for c in cuts or []:
        i, turn = int(c.get("scene", -1)), int(c.get("turn", -1))
        if not 0 <= i < n or turn < 0 or any(i == j for j, _ in out):
            continue
        if i + 1 < n and story.continues_take(i + 1):
            continue
        out.append((i, turn))
    return out


def _redo_turn(story_id: str, owner: str, backend, index: int, turn: int) -> str:
    """Make turn `turn` of scene `index` again (the whole clip for the first
    turn, or when the turn can't be redone on its own) and save it."""
    current = get_store().get(story_id, owner)
    if current is None or not 0 <= index < len(current.scenes):
        raise StoryAccessError("Story not found.")
    redo = getattr(backend, "redo_turn", None)
    uri = redo(current, index, turn) if callable(redo) and turn > 0 else ""
    if not uri:
        uri = backend.generate_clip(current, index, frame_for(current, index))
    sc = current.scenes[index]
    scene_id, thread, turns_json = sc.id, _interaction_of(backend, uri), sc.turns_json
    model_used = sc.video_model_used or resolve_video_engine(current, sc)

    def apply(s: Story) -> None:
        for x in s.scenes:
            if x.id == scene_id:
                x.clip_uri, x.interaction_id = uri, thread
                x.turns_json, x.video_model_used = turns_json, model_used
                x.continues_from, x.extends_from, x.clip_in = "", "", 0.0
                x.bridged_to = ""
        s.clear_films()

    mutate_story(story_id, owner, apply)
    return uri


def start_upscale(story_id: str, owner: str, resolution: str) -> Job:
    """Final quality: upscale every clip to `resolution` with Omni, then
    make the film again from the sharper clips (same takes, music and
    voice)."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not story.scenes or not all(sc.clip_uri for sc in story.scenes):
        raise GenerationError("Make the film first, then upscale it.")
    job = _new_job(owner, story_id, "clips", {"indices": list(range(len(story.scenes)))})
    tasks = {
        i: _add_task(job, f"Take {i + 1} · upscale to {resolution}", "clip", i)
        for i in range(len(story.scenes))
    }

    def work(job: Job) -> None:
        backend = get_backend()

        def upscale(i: int) -> str:
            current = get_store().get(story_id, owner)
            if current is None:
                raise StoryAccessError("Story not found.")
            uri = backend.upscale_clip(current, i, resolution)
            scene_id = current.scenes[i].id

            def apply(s: Story) -> None:
                # Same take, sharper: the turn records and thread still hold.
                for x in s.scenes:
                    if x.id == scene_id:
                        x.clip_uri = uri

            mutate_story(story_id, owner, apply)
            return uri

        ok = True
        for i in sorted(tasks):
            if job.cancel_event.is_set():
                return
            ok = _run_task(tasks[i], lambda i=i: upscale(i), job.cancel_event) and ok
        if not ok or job.cancel_event.is_set():
            return

        def done(s: Story) -> None:
            s.resolution = resolution
            s.clear_films()

        mutate_story(story_id, owner, done)
        job.params["next_job"] = start_video(story_id, owner).id

    return _spawn(job, work)


def start_turn_redo(story_id: str, owner: str, index: int, turn: int) -> Job:
    """Make one turn of a take again ("Redo this turn")."""
    story = get_store().get(story_id, owner)
    if story is None or not 0 <= index < len(story.scenes):
        raise StoryAccessError("Story not found.")
    job = _new_job(owner, story_id, "clips", {"indices": [index]})
    task = _add_task(
        job, f"Take {index + 1} · turn {turn + 1} again", "clip", index
    )

    def work(job: Job) -> None:
        backend = get_backend()
        _run_task(
            task,
            lambda: _redo_turn(story_id, owner, backend, index, turn),
            job.cancel_event,
        )

    return _spawn(job, work)


def _film_and_timeline(result) -> tuple[str, dict | None]:
    """A backend stitch returns (film, timeline); older ones just the film."""
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, None


def film_timeline(s: Story) -> dict | None:
    """The timeline the current film was made from, or None when unknown."""
    from services.story_timeline import normalize

    if s.final_uri and s.film_timeline_uri == s.final_uri and s.film_timeline_json:
        return normalize(s.film_timeline_json)
    return None


def _mark_film_timeline(s: Story, timeline) -> None:
    from services.story_timeline import normalize

    s.film_timeline_json = json.dumps(normalize(timeline))
    s.film_timeline_uri = s.final_uri


def save_timeline(story_id: str, owner: str, timeline) -> Story:
    """Store the editor's timeline (validated, with the editor's revision
    tag so its own echo is ignored) on the story, and mark the film edited
    when the timeline differs from the one the current film was made from
    (undoing back to it clears the mark). Then start the preview render."""
    from services.story_timeline import normalize

    clean = normalize(timeline, keep_rev=True)
    plain = normalize(clean)

    def apply(s: Story) -> None:
        if s.final_uri:
            base = film_timeline(s)
            if base is None:
                # The film came from a render or a restored version: the
                # timeline before this first edit is the one it shows.
                _mark_film_timeline(s, s.timeline_json)
                base = normalize(s.film_timeline_json)
            s.film_edited = plain != base
        s.timeline_json = json.dumps(clean)

    story = mutate_story(story_id, owner, apply)
    request_proxy(story_id, owner)
    return story


# ---------------------------------------------------------------------------
# Preview proxy: one small, fast render of the current timeline
# ---------------------------------------------------------------------------

PROXY_DELAY = 0.8  # seconds of quiet after an edit before rendering
PROXY_VERSION = "p1"
# Tests turn background previews off (test/conftest.py).
PROXY_ENABLED = True
_proxy_lock = threading.Lock()
_proxy_timers: dict[str, threading.Timer] = {}
_proxy_running: set[str] = set()
_proxy_dirty: set[str] = set()
_proxy_failed: dict[str, str] = {}


def proxy_key(story: Story) -> str:
    """What the preview must show: the timeline (without the editor's
    revision tag) and the brand logo, as a short hash."""
    import hashlib

    from services.story_service import _logo_args
    from services.story_timeline import normalize

    raw = json.dumps(
        [PROXY_VERSION, normalize(story.timeline_json), _logo_args(story)], sort_keys=True
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def preview(story: Story) -> tuple[str, str]:
    """(uri, state) for the editor's player. state is "film" (the film is
    this exact edit), "ready" (an up-to-date proxy), "making" (a proxy is
    being made; uri is the last one, maybe ""), or "failed"."""
    if not story.timeline_json:
        return story.final_uri, "film"
    if story.final_uri and not story.film_edited:
        return story.final_uri, "film"
    key = proxy_key(story)
    if story.proxy_uri and story.proxy_key == key:
        return story.proxy_uri, "ready"
    last = story.proxy_uri or story.final_uri
    if _proxy_failed.get(story.id) == key:
        return last, "failed"
    return last, "making"


def proxy_busy(story_id: str) -> bool:
    with _proxy_lock:
        return story_id in _proxy_running or story_id in _proxy_timers


def request_proxy(story_id: str, owner: str, delay: float = PROXY_DELAY) -> None:
    """Render the preview proxy once edits pause for `delay` seconds. A
    request while one renders is picked up as soon as it finishes."""

    def fire() -> None:
        with _proxy_lock:
            _proxy_timers.pop(story_id, None)
            if story_id in _proxy_running:
                _proxy_dirty.add(story_id)
                return
            _proxy_running.add(story_id)
        threading.Thread(
            target=_proxy_worker, args=(story_id, owner), daemon=True, name="story-proxy"
        ).start()

    if not PROXY_ENABLED:
        return
    with _proxy_lock:
        old = _proxy_timers.pop(story_id, None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(max(0.0, delay), fire)
        timer.daemon = True
        _proxy_timers[story_id] = timer
    timer.start()


def ensure_proxy(story: Story, owner: str) -> None:
    """Start a proxy render when the preview is stale and none is under way
    (for example after a restart)."""
    _, state = preview(story)
    if state == "making" and not proxy_busy(story.id):
        request_proxy(story.id, owner, delay=0.0)


def _proxy_worker(story_id: str, owner: str) -> None:
    from services.story_timeline import (
        PROXY_CRF,
        PROXY_PRESET,
        PROXY_SHORT_SIDE,
        normalize,
    )

    try:
        while True:
            story = get_store().get(story_id, owner)
            if story is not None:
                _, state = preview(story)
                if state == "making":
                    key = proxy_key(story)
                    try:
                        uri = get_backend().render_timeline(
                            story,
                            normalize(story.timeline_json),
                            fmt="mp4",
                            short_side=PROXY_SHORT_SIDE,
                            crf=PROXY_CRF,
                            preset=PROXY_PRESET,
                            proxy=True,
                        )
                    except Exception:
                        logger.warning("Story %s: preview render failed", story_id, exc_info=True)
                        _proxy_failed[story_id] = key
                    else:
                        _proxy_failed.pop(story_id, None)

                        def apply(s: Story, uri=uri, key=key) -> None:
                            if proxy_key(s) == key:
                                s.proxy_uri, s.proxy_key = uri, key

                        mutate_story(story_id, owner, apply)
            with _proxy_lock:
                if story_id in _proxy_dirty:
                    _proxy_dirty.discard(story_id)
                    continue
                _proxy_running.discard(story_id)
                return
    except Exception:
        logger.exception("Story %s: preview worker stopped", story_id)
        with _proxy_lock:
            _proxy_running.discard(story_id)
            _proxy_dirty.discard(story_id)


def start_export(story_id: str, owner: str, options: dict | None = None) -> Job:
    """Render the edited timeline with the Export menu's options (see
    services/story_export.py): size, format, audio only, subtitles in the
    picture, logo on or off. Subtitle lines not in the story yet are
    translated first. An MP4 at the clips' own size without burned-in
    subtitles becomes the story's film (and goes to the library); every
    other export is an extra download. The file is kept in exports_json."""
    from services import story_export as ex
    from services import story_subtitles as subs
    from services.story_timeline import normalize

    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not story.timeline_json:
        raise GenerationError("Render the film once before editing it.")
    opts = ex.clean(options, normalize(story.timeline_json))
    job = _new_job(owner, story_id, "export", {"options": opts, "key": ex.key(opts)})
    missing = [c for c in ex.sub_langs(opts) if subs.lines_for(story, c) is None]
    translate_task = (
        _add_task(
            job,
            "Subtitles · translating to " + " and ".join(subs.LANGS[c] for c in missing),
            "translate",
        )
        if missing
        else None
    )
    has_logo = bool(logo_of(story))
    film = ex.makes_film(opts, has_logo)
    render_task = _add_task(
        job, "Exporting · " + ex.label(opts, normalize(story.timeline_json)), "stitch"
    )
    library_task = _add_task(job, "Saving to your library", "library") if film else None

    def work(job: Job) -> None:
        backend = get_backend()

        def translate() -> str:
            for code in missing:
                lines = backend.translate_subtitles(story, code)

                def keep(s: Story, code=code, lines=lines) -> None:
                    s.subtitle_lines_json = subs.with_cached_lines(s, code, lines)

                mutate_story(story_id, owner, keep)
            return ""

        if translate_task and not _run_task(translate_task, translate, job.cancel_event):
            render_task.status = SKIPPED
            if library_task:
                library_task.status = SKIPPED
            return
        current = get_store().get(story_id, owner) or story
        if ex.burns_subtitles(opts):
            lines = {c: subs.lines_for(current, c) for c in ex.sub_langs(opts)}
            timeline = subs.variant_timeline(current, current.timeline_json, opts["lang"], lines)
        else:
            timeline = normalize(current.timeline_json)
        made = ex.made_from(current, opts)
        if not _run_task(
            render_task,
            lambda: backend.render_timeline(
                current,
                timeline,
                fmt=opts["fmt"],
                short_side=opts["short"],
                branding=opts["branding"],
            ),
            job.cancel_event,
        ):
            if library_task:
                library_task.status = SKIPPED
            return
        uri = render_task.result_uri
        name = ex.filename(current.title, opts, timeline)

        def apply(s: Story) -> None:
            s.exports_json = ex.with_export(s, opts, uri, name, made)
            if film:
                # Same clips as the render, so set_version stays as it was.
                s.final_uri = uri
                s.film_edited = False
                _mark_film_timeline(s, current.timeline_json)
                story_versions.remember(s, "export")

        saved = mutate_story(story_id, owner, apply)
        if library_task:
            _run_task(
                library_task,
                lambda: _save_film_item(backend, saved, uri, owner),
                job.cancel_event,
            )

    return _spawn(job, work)


def logo_of(story: Story) -> str:
    from services.story_service import _logo_args

    return _logo_args(story).get("logo", "")


def start_subtitled(story_id: str, owner: str, variant: str) -> Job:
    """Make a download of the film with subtitles (`variant` is "en", "ar" or
    "en+ar", see services/story_subtitles.py): translate the lines that are
    not in the story yet (cached on the story), then render the current
    timeline with captions. The main film is left as it is."""
    from services import story_subtitles as subs

    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if variant not in subs.VARIANTS or variant == "none":
        raise GenerationError("Unknown subtitle version.")
    if not story.final_uri or not story.timeline_json:
        raise GenerationError("Render the film first.")
    job = _new_job(owner, story_id, "subtitles", {"variant": variant})
    missing = [c for c in subs.variant_langs(variant) if subs.lines_for(story, c) is None]
    words = {c: subs.LANGS[c] for c in missing}
    translate_task = (
        _add_task(job, "Subtitles · translating to " + " and ".join(words.values()), "translate")
        if missing
        else None
    )
    render_task = _add_task(job, f"Film · {subs.VARIANT_LABELS[variant].lower()}", "stitch")

    def work(job: Job) -> None:
        backend = get_backend()

        def translate() -> str:
            for code in missing:
                lines = backend.translate_subtitles(story, code)

                def keep(s: Story, code=code, lines=lines) -> None:
                    s.subtitle_lines_json = subs.with_cached_lines(s, code, lines)

                mutate_story(story_id, owner, keep)
            return ""

        if translate_task and not _run_task(translate_task, translate, job.cancel_event):
            render_task.status = SKIPPED
            return
        if job.cancel_event.is_set():
            return
        current = get_store().get(story_id, owner)
        lines = {c: subs.lines_for(current, c) for c in subs.variant_langs(variant)}
        timeline = subs.variant_timeline(current, current.timeline_json, variant, lines)
        key = subs.variant_key(current, variant, lines)
        if not _run_task(
            render_task,
            lambda: backend.render_timeline(current, timeline),
            job.cancel_event,
        ):
            return
        film = render_task.result_uri

        def apply(s: Story) -> None:
            stored = subs.variants(s)
            stored[variant] = {"uri": film, "key": key}
            s.film_variants_json = json.dumps(stored)

        mutate_story(story_id, owner, apply)

    return _spawn(job, work)


def start_music(story_id: str, owner: str) -> Job:
    """Make the film's music with Lyria (and any track still without music)
    and put it on the timeline."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    job = _new_job(owner, story_id, "music")
    task = _add_task(job, "Music · Lyria score", "music")
    track_tasks = {
        t["id"]: _add_task(job, f"Music · track for takes {_takes_label(t)}", "music")
        for t in story.music_tracks()
        if not t.get("uri")
    }

    def work(job: Job) -> None:
        backend = get_backend()
        prompt = story.music_prompt or default_music_prompt(story)
        seconds = float(sum(s.duration for s in story.scenes)) or 30.0

        def make() -> str:
            uri = backend.generate_music(story, prompt, seconds)
            set_music(story_id, owner, uri)
            return uri

        _run_task(task, make, job.cancel_event)
        for tid, t in track_tasks.items():
            if job.cancel_event.is_set():
                break
            _run_task(t, lambda tid=tid: _make_track(story_id, owner, backend, tid), job.cancel_event)
        current = get_store().get(story_id, owner)
        if current is not None and current.timeline_json:
            set_music(story_id, owner, current.music_uri)

    return _spawn(job, work)


def _takes_label(track: dict) -> str:
    return ", ".join(str(int(k) + 1) for k in sorted(track.get("takes") or []))


def _fit_voice_lines(
    story_id: str,
    owner: str,
    backend,
    voice_uris: dict[int, str],
    set_version: int = 0,
) -> str:
    """Fit the narrator's lines to their scenes, so none is cut off and all
    play at one speed: measure every voiced line, store the narrator's pace
    (Story.narrator_wps, which sets the word limits from now on), then
    rewrite each line too long for its scene to the scene's word limit at
    that pace and voice it again, once. Updates `voice_uris` in place.
    Returns "" (the task has no file); the result is logged."""
    import os
    import tempfile

    from services import story_timeline as tl_mod
    from services.story_models import (
        VO_BREATH,
        VO_LEAD,
        line_pace,
        narrator_words,
        voice_room,
    )
    from services.story_service import fetch_media

    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    narrated = [
        i
        for i, uri in sorted(voice_uris.items())
        if uri and i < len(story.scenes) and not _is_spoken(story.scenes[i])
    ]
    if not narrated:
        return ""
    with tempfile.TemporaryDirectory() as tmp:

        def speech_of(uri: str) -> float | None:
            """Seconds of speech in a voice line; None when it can't be read."""
            path = os.path.join(tmp, f"v{uuid.uuid4().hex[:8]}.wav")
            try:
                fetch_media(uri, path)
                shape = tl_mod.voice_shape(path)
            except Exception:
                logger.warning("Could not measure voice line %s", uri, exc_info=True)
                return None
            if shape["length"] <= 0:
                return None
            return max(0.0, shape["end"] - shape["lead"])

        speech = {i: speech_of(voice_uris[i]) for i in narrated}
        narrated = [i for i in narrated if speech[i] is not None]
        pace = line_pace([(story.scenes[i].narration, speech[i]) for i in narrated])
        if pace:
            mutate_story(story_id, owner, lambda s: setattr(s, "narrator_wps", pace))
            story.narrator_wps = pace
        redone = 0
        for i in narrated:
            sc = story.scenes[i]
            room = voice_room(story, i)
            if speech[i] <= room:
                continue
            words = len(sc.narration.split())
            seconds = room + VO_LEAD + VO_BREATH
            budget = min(words - 1, narrator_words(seconds, pace))
            if budget < 1:
                continue
            try:
                line = backend.shorten_line(story, i, sc.narration, budget)
            except Exception:  # a failed rewrite leaves the line as it was
                logger.exception("Shortening the line of scene %s failed", i + 1)
                continue
            if not line or len(line.split()) >= words:
                continue
            scene_id = sc.id
            sc.narration = line
            sc.narration_alt = ""  # translated from the old, longer line
            uri = backend.generate_voiceover(story, i, line)
            voice_uris[i] = uri
            key = _voice_key(story, i, set_version)
            redone += 1

            def save(s: Story, scene_id=scene_id, line=line, uri=uri, key=key) -> None:
                for x in s.scenes:
                    if x.id == scene_id:
                        x.narration = line
                        x.narration_alt = ""
                        x.voice_uri, x.voice_key = uri, key

            mutate_story(story_id, owner, save)
    logger.info(
        "Story %s: narrator pace %s words/s, %d line(s) shortened", story_id, pace, redone
    )
    return ""


def _make_track(story_id: str, owner: str, backend, track_id: str) -> str:
    """Make one music track (its takes' length) and save it on the story."""
    current = get_store().get(story_id, owner)
    if current is None:
        raise StoryAccessError("Story not found.")
    track = next((t for t in current.music_tracks() if t.get("id") == track_id), None)
    if track is None:
        raise GenerationError("That music track was removed.")
    groups = take_groups(current)
    seconds = float(
        sum(
            current.scenes[i].duration
            for k in track.get("takes") or []
            if 0 <= int(k) < len(groups)
            for i in groups[int(k)]
        )
    ) or 30.0
    prompt = (track.get("prompt") or "").strip() or (
        current.music_prompt or default_music_prompt(current)
    )
    uri = backend.generate_music(current, prompt, seconds)

    def apply(s: Story) -> None:
        tracks = s.music_tracks()
        for t in tracks:
            if t.get("id") == track_id and (t.get("prompt") or "") == (track.get("prompt") or ""):
                t["uri"] = uri
        s.music_tracks_json = json.dumps(tracks)

    mutate_story(story_id, owner, apply)
    return uri


def set_music(story_id: str, owner: str, uri: str) -> Story:
    """Use `uri` as the film's music: one clip across the whole timeline,
    or, with music tracks, wherever no track plays (story_timeline.place_music)."""
    from services.story_timeline import normalize, place_music, track

    def apply(s: Story) -> None:
        s.music_uri = uri
        s.music_on = True
        if not s.timeline_json:
            return
        tl = normalize(s.timeline_json)
        old = track(tl, "music")["clips"]
        place_music(tl, s, uri, gain=old[0]["gain"] if old else 0.8)
        s.timeline_json = json.dumps(normalize(tl))

    return mutate_story(story_id, owner, apply)


# ---------------------------------------------------------------------------
# Sets
# ---------------------------------------------------------------------------


def mutate_set(set_id: str, owner: str, fn: Callable[[StorySet], None]) -> StorySet:
    """Load, change and save a set under its lock. Owner-only."""
    with _story_lock(f"set:{set_id}"):
        store = get_set_store()
        story_set = store.get(set_id, owner)
        if story_set is None:
            raise StoryAccessError("Set not found.")
        fn(story_set)
        return store.save(story_set, owner)


def attach_set(
    story_id: str, owner: str, set_id: str, keep_links: bool = False
) -> Story:
    """Make a story use one of the owner's sets ("" = no set). The scenes'
    cast and places are cleared unless `keep_links` (a copy of the same set)."""
    if set_id and get_set_store().get(set_id, owner) is None:
        raise StoryAccessError("Set not found.")

    def apply(s: Story) -> None:
        if s.set_id != set_id:
            s.set_id = set_id
            if keep_links:
                return
            for sc in s.scenes:
                sc.cast, sc.location_id, sc.prop_ids, sc.speaker_id = [], "", [], ""

    return mutate_story(story_id, owner, apply)


def _set_work(story_set: StorySet, targets: list | None) -> list[tuple]:
    """(kind, asset id, view) pieces to make: the given targets, else every
    empty slot of the views frames use (story_sets.BUILD_VIEWS) and missing
    voice sample. Locked images never."""
    wanted = {tuple(t) for t in targets} if targets else None
    out: list[tuple] = []
    for kind in KINDS:
        for asset in story_set.assets(kind):
            ensure_views(asset)
            for img in asset.images:
                if img.view not in views_for(asset) or img.locked:
                    continue
                key = (kind, asset.id, img.view)
                build = img.view in build_views(asset) and not img.uri
                if (wanted is None and build) or (wanted and key in wanted):
                    out.append(key)
            if kind == "character":
                key = (kind, asset.id, "voice")
                if (wanted is None and not asset.voice.sample_uri) or (
                    wanted and key in wanted
                ):
                    out.append(key)
    return out


def _seed_lead(story_set: StorySet, story: Story) -> None:
    """The Create step's reference photo becomes the lead's front image
    (locked, so it is kept), the base for the lead's other views."""
    lead = next(iter(story_set.on_screen()), None)
    if lead is None or not story.reference_uri:
        return
    ensure_views(lead)
    for img in lead.images:
        if img.view == "front":
            img.uri, img.locked = story.reference_uri, True


def _set_from_scenario(story: Story) -> StorySet | None:
    """The set from the cast the scenario call already wrote (no second
    Gemini call), or None when there is none or it no longer fits the
    scenes (then the film is cast afresh)."""
    text = set_text_from_cast(story.cast_json, story.scenes)
    if not text:
        return None
    try:
        return parse_set_build(text, story)
    except ScenarioError:
        logger.warning("Story %s: stored cast unusable; casting again", story.id)
        return None


def start_set(
    story_id: str, owner: str, targets: list | None = None, then_frames: bool = False
) -> Job:
    """Make the story's set.

    A story without a set is cast first with one Gemini call (characters,
    locations, props and who is in each scene). Then every missing image is
    painted (each asset's front or wide plate first, its other views from
    it) with a voice sample per character, in parallel. `targets` limits the
    run to those (kind, asset id, view) pieces: a regenerate. Locked images
    are never replaced.
    """
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    job = _new_job(
        owner,
        story_id,
        "set",
        {"targets": targets, "task_targets": {}, "then_frames": then_frames},
    )
    cast_task = None
    if not story.set_id:
        cast_task = _add_task(
            job,
            "Building the set from the scenario"
            if set_text_from_cast(story.cast_json, story.scenes)
            else "Casting with Gemini",
            "set",
        )
    cfg = Default()

    def work(job: Job) -> None:
        backend = get_backend()
        set_id = story.set_id
        if cast_task is not None:
            holder: dict[str, StorySet] = {}

            def cast() -> str:
                current = get_store().get(story_id, owner)
                if current is None:
                    raise StoryAccessError("Story not found.")
                made = _set_from_scenario(current)
                last: Exception | None = None
                for _ in range(0 if made else 2):  # one retry on malformed JSON
                    try:
                        made = parse_set_build(backend.write_set(current), current)
                        break
                    except ScenarioError as exc:
                        last = exc
                else:
                    if made is None:
                        raise last or ScenarioError("No set.")
                _seed_lead(made, current)
                made = get_set_store().save(made, owner)
                links = {
                    sc.id: (sc.cast, sc.location_id, sc.prop_ids, sc.speaker_id)
                    for sc in current.scenes
                }

                def apply(s: Story) -> None:
                    s.set_id = made.id
                    s.cast_json = ""  # the set holds the cast now
                    for sc in s.scenes:
                        if sc.id in links:
                            sc.cast, sc.location_id, sc.prop_ids, sc.speaker_id = links[
                                sc.id
                            ]

                mutate_story(story_id, owner, apply)
                holder["set"] = made
                return ""

            if not _run_task(cast_task, cast, job.cancel_event):
                return
            set_id = holder["set"].id
        if job.cancel_event.is_set():
            return
        story_set = get_set_store().get(set_id, owner)
        if story_set is None:
            raise StoryAccessError("Set not found.")
        pieces = _set_work(story_set, targets)
        tasks: dict[tuple, Task] = {}
        for kind, aid, view in pieces:
            asset = story_set.asset(kind, aid)
            what = "voice sample" if view == "voice" else VIEW_LABELS.get(view, view)
            task = _add_task(job, f"{asset.name} · {what}", "set")
            tasks[(kind, aid, view)] = task
            job.params["task_targets"][task.id] = [kind, aid, view]

        def paint(kind: str, aid: str, view: str) -> str:
            current = get_set_store().get(set_id, owner)
            asset = current.asset(kind, aid) if current else None
            if asset is None:
                raise StoryAccessError("Set not found.")
            if view == "voice":
                uri = backend.voice_sample(current, asset)

                def apply_voice(st: StorySet) -> None:
                    a = st.asset(kind, aid)
                    if a is not None:
                        a.voice.sample_uri = uri

                mutate_set(set_id, owner, apply_voice)
                return uri
            anchor = anchor_view(asset)
            ref = image_of(asset, anchor) if view != anchor else None
            prompt = image_prompt(current, asset, view)
            uri = backend.generate_set_image(
                current, prompt, [ref.uri] if ref else [], aspect_for(asset, view)
            )

            def apply(st: StorySet) -> None:
                a = st.asset(kind, aid)
                if a is None:
                    return
                ensure_views(a)
                for img in a.images:
                    if img.view == view and not img.locked:
                        img.uri, img.prompt = uri, prompt

            mutate_set(set_id, owner, apply)
            return uri

        def chain(kind: str, aid: str, views: list[str]) -> None:
            # The anchor view goes first: the others are made from it.
            anchor_failed = False
            for view in views:
                task = tasks[(kind, aid, view)]
                if job.cancel_event.is_set():
                    if task.status == QUEUED:
                        task.status, task.error = SKIPPED, "Cancelled by user."
                    continue
                if anchor_failed and view != "voice":
                    task.status, task.error = SKIPPED, "Needs the first image."
                    continue
                ok = _run_task(
                    task, lambda v=view: paint(kind, aid, v), job.cancel_event
                )
                if not ok and view in ("front", "plate"):
                    anchor_failed = True

        by_asset: dict[tuple, list[str]] = {}
        for kind, aid, view in pieces:
            by_asset.setdefault((kind, aid), []).append(view)
        order = {"front": 0, "plate": 0, "voice": 9}
        with _Pool(max_workers=max(1, cfg.STORY_MAX_PARALLEL)) as pool:
            for (kind, aid), views in by_asset.items():
                if job.cancel_event.is_set():
                    break
                views.sort(key=lambda v: order.get(v, 1))
                pool.submit(chain, kind, aid, views)
        # Setup's guided flow: the start frames are painted from the set.
        if then_frames and not job.cancel_event.is_set():
            try:
                job.params["next_job"] = start_storyboard(story_id, owner).id
            except Exception:
                logger.exception("Story %s: could not start the frames", story_id)

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
    if job.kind == "clips":
        failed = [
            t.scene_index
            for t in job.tasks
            if t.status in (FAILED, SKIPPED) and t.scene_index >= 0
        ]
        return start_scene_clips(
            job.story_id, owner, failed or list(job.params.get("indices") or [])
        )
    if job.kind == "export":
        return start_export(job.story_id, owner, job.params.get("options"))
    if job.kind == "music":
        return start_music(job.story_id, owner)
    if job.kind == "fix":
        from services.story_fix import resume_fix

        return resume_fix(job.story_id, owner)
    if job.kind == "set":
        tt = job.params.get("task_targets") or {}
        failed = [
            tt[t.id] for t in job.tasks if t.status in (FAILED, SKIPPED) and t.id in tt
        ]
        # A failed casting call has no targets: start over from the story.
        return start_set(job.story_id, owner, failed or job.params.get("targets"))
    if job.params.get("alt"):
        return start_alt_video(job.story_id, owner)
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
