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
"""Background media jobs for the Live voice agent.

Every job runs in its own thread, so several images and videos can render at
once and none of them stops when the page changes. Jobs live in process memory
(one worker per container, plus Cloud Run session affinity), keyed by owner.
Results are saved to GCS and the Library exactly as the studio pages save them.

Each job gets a short spoken handle ("image 1", "video 2") so the agent and the
presenter can refer to it.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from common.analytics import get_logger

logger = get_logger(__name__)

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
KINDS = ("image", "video", "music", "voice", "story")
MAX_RUNNING_PER_OWNER = 4


class JobLimitError(Exception):
    """Too many jobs running for one person."""


@dataclass
class LiveJob:
    id: str
    owner: str
    kind: str  # "image" or "video"
    handle: str  # "image 1"
    prompt: str
    aspect_ratio: str = ""
    source_job: str = ""  # handle of the image this one edits or animates
    source_uri: str = ""
    status: str = QUEUED
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    error: str = ""
    gcs_uri: str = ""
    display_url: str = ""
    mime_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    # Visible steps, as the studio pages show them: the stage names, the
    # index of the current one, when the run began and a rough length.
    stages: list[str] = field(default_factory=list)
    stage: int = 0
    started_at: float = 0.0
    typical_seconds: int = 0
    # Story jobs: Story Studio's own task list [{"label", "status"}].
    tasks: list[dict] = field(default_factory=list)
    # Set by LiveJobs.submit: tells listeners the job moved on while running.
    on_progress: Callable[[], None] | None = field(
        default=None, repr=False, compare=False
    )

    def progress(self, stage: int | None = None) -> None:
        """Report a change while running: a new stage index, or a story step."""
        if stage is not None and self.stages:
            self.stage = max(0, min(int(stage), len(self.stages) - 1))
        if self.on_progress is not None:
            self.on_progress()

    @property
    def is_edit(self) -> bool:
        return self.kind == "image" and bool(self.source_uri)

    def public(self) -> dict:
        """What the browser and the agent see (no owner)."""
        if self.kind == "story":
            _refresh_story_tasks(self)
        data = asdict(self)
        data.pop("owner", None)
        data.pop("on_progress", None)
        data["is_edit"] = self.is_edit
        data["seconds"] = round((self.finished_at or time.time()) - self.created_at, 1)
        return data


@dataclass
class RunResult:
    gcs_uri: str
    display_url: str
    mime_type: str


Runner = Callable[[LiveJob], RunResult]
Listener = Callable[[LiveJob], None]


class LiveJobs:
    """Per-owner job registry. Thread-safe."""

    def __init__(self, runners: dict[str, Runner] | None = None):
        self._runners = runners
        self._jobs: dict[str, LiveJob] = {}
        self._counters: dict[tuple[str, str], int] = {}
        self._listeners: dict[str, list[Listener]] = {}
        self._lock = threading.Lock()

    # -- queries ---------------------------------------------------------

    def list(self, owner: str) -> list[LiveJob]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.owner == owner]
        return sorted(jobs, key=lambda j: j.created_at)

    def resolve(self, owner: str, ref: str = "", kind: str = "") -> LiveJob | None:
        """Find a job from what someone might say.

        Accepts a job id, "image 2", "video", "2", "latest", or "" (the latest
        job of ``kind``, preferring finished ones).
        """
        jobs = self.list(owner)
        if not jobs:
            return None
        text = (ref or "").strip().lower()
        for job in jobs:
            if text and job.id == text:
                return job
        match = re.search(
            r"(image|picture|photo|video|clip|music|track|song|voice|speech|story)?\s*#?\s*(\d+)",
            text,
        )
        want = kind
        if "video" in text or "clip" in text:
            want = "video"
        elif any(w in text for w in ("music", "track", "song")):
            want = "music"
        elif any(w in text for w in ("voice", "speech", "narration")):
            want = "voice"
        elif "story" in text:
            want = "story"
        elif any(w in text for w in ("image", "picture", "photo", "edit")):
            want = "image"
        if match:
            number = match.group(2)
            for job in jobs:
                if job.handle.endswith(f" {number}") and (not want or job.kind == want):
                    return job
        pool = [j for j in jobs if not want or j.kind == want]
        if not pool:
            return None
        done = [j for j in pool if j.status == DONE]
        return (done or pool)[-1]

    # -- events ----------------------------------------------------------

    def subscribe(self, owner: str, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.setdefault(owner, []).append(listener)

        def unsubscribe() -> None:
            with self._lock:
                items = self._listeners.get(owner, [])
                if listener in items:
                    items.remove(listener)

        return unsubscribe

    def _emit(self, job: LiveJob) -> None:
        with self._lock:
            listeners = list(self._listeners.get(job.owner, []))
        for listener in listeners:
            try:
                listener(job)
            except Exception:  # a broken listener must not kill the job
                logger.exception("Live job listener failed")

    # -- submit ----------------------------------------------------------

    def submit(
        self,
        owner: str,
        kind: str,
        prompt: str,
        *,
        aspect_ratio: str = "",
        source: LiveJob | None = None,
        params: dict[str, Any] | None = None,
        run_async: bool = True,
    ) -> LiveJob:
        if kind not in KINDS:
            raise ValueError(f"Unknown job kind: {kind}")
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("A prompt is needed.")
        with self._lock:
            running = sum(
                1
                for j in self._jobs.values()
                if j.owner == owner and j.status in (QUEUED, RUNNING)
            )
            if running >= MAX_RUNNING_PER_OWNER:
                raise JobLimitError(
                    f"{running} jobs are already running. Wait for one to finish."
                )
            number = self._counters.get((owner, kind), 0) + 1
            self._counters[(owner, kind)] = number
            default_aspect = {"video": "16:9", "image": "1:1"}.get(kind, "")
            job = LiveJob(
                id=uuid.uuid4().hex[:12],
                owner=owner,
                kind=kind,
                handle=f"{kind} {number}",
                prompt=prompt,
                aspect_ratio=aspect_ratio or default_aspect,
                source_job=source.handle if source else "",
                source_uri=(source.gcs_uri or source.display_url) if source else "",
                params=dict(params or {}),
            )
            job.on_progress = lambda: self._emit(job)
            try:
                job.stages, job.typical_seconds = plan_stages(job)
            except Exception:  # stages are a nicety; never block a job on them
                logger.exception("Could not plan the stages of %s", job.handle)
            self._jobs[job.id] = job
        self._emit(job)
        if run_async:
            threading.Thread(
                target=self._run, args=(job,), name=f"live-{job.handle}", daemon=True
            ).start()
        else:
            self._run(job)
        return job

    def add_upload(
        self,
        owner: str,
        *,
        uri: str,
        display_url: str,
        mime_type: str,
        name: str = "",
        kind: str = "image",
    ) -> LiveJob:
        """Register a picture (or video) the person attached as a finished job.

        It gets the next "image N" handle, so the agent can edit or animate it
        like any image it made ("edit image 3", "make a video from image 3").
        """
        kind = kind if kind in ("image", "video") else "image"
        what = "Picture" if kind == "image" else "Video"
        with self._lock:
            number = self._counters.get((owner, kind), 0) + 1
            self._counters[(owner, kind)] = number
            job = LiveJob(
                id=uuid.uuid4().hex[:12],
                owner=owner,
                kind=kind,
                handle=f"{kind} {number}",
                prompt=f"{what} you attached{f' ({name})' if name else ''}",
                status=DONE,
                finished_at=time.time(),
                gcs_uri=uri if uri.startswith("gs://") else "",
                display_url=display_url,
                mime_type=mime_type,
                params={"uploaded": True},
            )
            self._jobs[job.id] = job
        self._emit(job)
        return job

    def _run(self, job: LiveJob) -> None:
        job.status = RUNNING
        job.started_at = time.time()
        self._emit(job)
        try:
            from common import usage

            runner = (self._runners or default_runners())[job.kind]
            with usage.acting_for(job.owner):
                result = runner(job)
            job.gcs_uri = result.gcs_uri
            job.display_url = result.display_url
            job.mime_type = result.mime_type
            if job.stages:
                job.stage = len(job.stages) - 1
            job.status = DONE
        except Exception as exc:  # reported to the agent, which says it aloud
            logger.exception("Live job %s failed", job.handle)
            job.error = _friendly(exc)
            job.status = FAILED
        job.finished_at = time.time()
        self._emit(job)


_PLAIN_ERRORS = {
    "CAPACITY_EXHAUSTED": "The model is busy right now. Try again in a moment.",
    "SAFETY_FILTER": "The model declined this prompt. Try different wording.",
    "CLIENT_TIMEOUT": "This took too long. Try again.",
    "AUTH_ERROR": "The app is not allowed to call this model. Check the project setup.",
    "UPSTREAM_FAILURE": "The model service had an error. Try again.",
}


def _friendly(exc: Exception) -> str:
    try:
        from common.error_handling import GenerationError, classify_error

        if isinstance(exc, GenerationError):
            return str(exc)
        category = classify_error(exc).get("category", "")
        return _PLAIN_ERRORS.get(category) or str(exc)[:300]
    except Exception:
        return str(exc)[:300] or exc.__class__.__name__


# ---------------------------------------------------------------------------
# Runners: mock (local demo, no cloud) and real (Vertex, GCS, Firestore)
# ---------------------------------------------------------------------------


def default_runners() -> dict[str, Runner]:
    from common.mock_generation import mock_enabled

    if mock_enabled():
        return {
            "image": _mock_image,
            "video": _mock_video,
            "music": _mock_music,
            "voice": _mock_voice,
            "story": _story_runner,
        }
    return {
        "image": _real_image,
        "video": _real_video,
        "music": _real_music,
        "voice": _real_voice,
        "story": _story_runner,
    }


# ---------------------------------------------------------------------------
# Settings, inputs and stages
# ---------------------------------------------------------------------------

# LiveJob kinds to the Home box's types (services/studio_options.py).
_OPTION_KIND = {"image": "image", "video": "video", "music": "music", "voice": "voice"}


def _raw_settings(job: LiveJob) -> dict[str, str]:
    raw = job.params.get("settings") if isinstance(job.params, dict) else None
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def job_settings(job: LiveJob) -> dict[str, str]:
    """Every setting for this job, checked against the model.

    Jobs from the Home box carry ``params["settings"]``; the agent's jobs
    carry a few loose params (voice, language, lyrics) and an aspect ratio,
    which are folded in so both get the studio's defaults for the rest.
    """
    kind = _OPTION_KIND.get(job.kind)
    raw = _raw_settings(job)
    if not kind:
        return raw
    legacy: dict[str, str] = {}
    params = job.params if isinstance(job.params, dict) else {}
    if kind == "voice":
        for key in ("voice", "language"):
            if params.get(key):
                legacy[key] = str(params[key])
    if kind == "music" and str(params.get("lyrics") or "").strip():
        legacy["lyrics"] = "on"
        legacy["lyrics_text"] = str(params["lyrics"])
    if job.aspect_ratio and kind in ("image", "video"):
        legacy["aspect"] = job.aspect_ratio
    try:
        from services.studio_options import clean

        return clean(kind, {**legacy, **raw})
    except Exception:  # the registries failed to load; run with what we have
        logger.exception("Could not read the settings of %s", job.handle)
        return {**legacy, **raw}


# Kept for callers that only want the raw Home box settings.
_settings = _raw_settings


def job_inputs(job: LiveJob, slot: str) -> list[str]:
    """URIs attached to an input slot (first_frame, references, video...)."""
    slots = job.params.get("inputs") if isinstance(job.params, dict) else None
    items = (slots or {}).get(slot) if isinstance(slots, dict) else None
    out = []
    for item in items or []:
        uri = item.get("uri") if isinstance(item, dict) else item
        if uri:
            out.append(str(uri))
    return out


def _gcs(uris: list[str]) -> list[str]:
    return [u for u in uris if u.startswith("gs://")]


def _mime(uri: str, default: str = "image/png") -> str:
    low = (uri or "").lower().split("?")[0]
    for ext, mime in (
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".png", "image/png"),
        (".mp4", "video/mp4"),
        (".mov", "video/quicktime"),
        (".webm", "video/webm"),
    ):
        if low.endswith(ext):
            return mime
    return default


def _image_refs(job: LiveJob) -> list[str]:
    refs = job_inputs(job, "references")
    if job.source_uri and job.source_uri not in refs:
        refs.insert(0, job.source_uri)
    return refs


def _video_mode(job: LiveJob, settings: dict[str, str]) -> str:
    """The studio mode; a text job with a picture becomes image-to-video."""
    mode = settings.get("mode") or "t2v"
    if mode == "t2v" and (job_inputs(job, "first_frame") or job.source_uri):
        return "i2v"
    return mode


def _first_frame(job: LiveJob) -> str:
    frames = job_inputs(job, "first_frame")
    return frames[0] if frames else job.source_uri


_VIDEO_WORK = {
    "edit": "Editing video",
    "extend": "Extending video",
    "upscale": "Upscaling video",
}


def _veo_enhancing(model_id: str, settings: dict[str, str]) -> bool:
    from config.veo_models import get_veo_model_config

    cfg = get_veo_model_config(model_id)
    if not cfg or not cfg.supports_prompt_enhancement:
        return False
    return cfg.requires_prompt_enhancement or settings.get("enhance", "on") != "off"


def plan_stages(job: LiveJob) -> tuple[list[str], int]:
    """The job's stage names and rough seconds, worded as the studios word them."""
    settings = job_settings(job)
    if job.kind == "image":
        from config.gemini_image_models import get_gemini_image_model_config

        cfg = get_gemini_image_model_config(settings.get("model") or "")
        first = "Reading your references" if _image_refs(job) else "Preparing prompt"
        seconds = cfg.typical_generation_seconds if cfg else 15
        return [
            first,
            "Sending to Gemini",
            "Generating image",
            "Saving to library",
            "Done",
        ], seconds
    if job.kind == "video":
        from config.video_studio_models import engine_name, is_omni, typical_seconds

        model = settings.get("model") or ""
        mode = _video_mode(job, settings)
        if mode == "extend":
            first = "Preparing the clip"
        elif not is_omni(model) and _veo_enhancing(model, settings):
            first = "Enhancing prompt"
        else:
            first = "Preparing request"
        work = _VIDEO_WORK.get(mode, "Generating video")
        return (
            [
                first,
                f"Sending to {engine_name(model)}",
                work,
                "Saving to library",
                "Done",
            ],
            typical_seconds(model),
        )
    if job.kind == "music":
        return [
            "Preparing",
            "Sending to Lyria",
            "Composing",
            "Saving to library",
            "Done",
        ], 30
    if job.kind == "voice":
        from config.voice import engine_label

        engine = engine_label(settings.get("model") or "")
        return [
            "Preparing",
            f"Sending to {engine}",
            "Speaking",
            "Saving to library",
            "Done",
        ], 8
    if job.kind == "story":
        return [], 60
    return [], 0


def _refresh_story_tasks(job: LiveJob) -> None:
    """Copy Story Studio's task list (story_jobs.job_snapshot) onto the job."""
    story_job_id = str(job.params.get("story_job_id") or "")
    if not story_job_id:
        return
    try:
        from services import story_jobs

        snap = story_jobs.job_snapshot(story_job_id, job.owner)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Could not read story job %s", story_job_id)
        return
    if not snap:
        return
    job.tasks = [
        {"label": str(t.get("label") or ""), "status": str(t.get("status") or "")}
        for t in snap.get("tasks") or []
    ]
    job.stages = [t["label"] for t in job.tasks]
    running = next((i for i, t in enumerate(job.tasks) if t["status"] == "running"), -1)
    if running < 0:
        running = sum(1 for t in job.tasks if t["status"] in ("done", "skipped"))
    job.stage = max(0, min(running, len(job.stages) - 1)) if job.stages else 0


def _story_runner(job: LiveJob) -> RunResult:
    from services.live_story import run_story_job

    return run_story_job(job)


# ---------------------------------------------------------------------------
# Mock runners: the same stages with fake waits, so the demo shows motion
# ---------------------------------------------------------------------------


def _walk_stages(job: LiveJob, total_seconds: float) -> None:
    """Step through every stage but "Done", sharing ``total_seconds``."""
    from common.mock_generation import fake_wait

    steps = max(1, len(job.stages) - 1)
    for i in range(steps):
        job.progress(i)
        fake_wait(total_seconds / steps, job.prompt)


def _mock_image(job: LiveJob) -> RunResult:
    from common.mock_generation import placeholder_image

    settings = job_settings(job)
    _walk_stages(job, 6 if job.is_edit else 5)
    label = f"{job.handle}: {job.prompt}"
    aspect = settings.get("aspect") or job.aspect_ratio
    index = int(job.handle.split()[-1])
    count = max(1, int(settings.get("count") or 1))
    urls = [placeholder_image(label, aspect, index=index + i) for i in range(count)]
    job.params["results"] = [{"gcs_uri": "", "display_url": u} for u in urls]
    return RunResult(gcs_uri="", display_url=urls[0], mime_type="image/svg+xml")


def _mock_video(job: LiveJob) -> RunResult:
    from common.mock_generation import sample_video

    job_settings(job)  # every setting is read, as the real runner does
    _walk_stages(job, 14)
    return RunResult(gcs_uri="", display_url=sample_video(), mime_type="video/mp4")


def _mock_music(job: LiveJob) -> RunResult:
    from common.mock_generation import sample_audio

    settings = job_settings(job)
    _walk_stages(job, 4)
    index = int(job.handle.split()[-1])
    count = max(1, int(settings.get("count") or 1))
    urls = [sample_audio(index + i) for i in range(count)]
    job.params["results"] = [{"gcs_uri": "", "display_url": u} for u in urls]
    return RunResult(gcs_uri="", display_url=urls[0], mime_type="audio/wav")


def _mock_voice(job: LiveJob) -> RunResult:
    from common.mock_generation import sample_audio

    _voice_request(job)  # checks the settings like the real runner
    _walk_stages(job, 2)
    index = int(job.handle.split()[-1])
    return RunResult(gcs_uri="", display_url=sample_audio(index), mime_type="audio/wav")


# ---------------------------------------------------------------------------
# Real runners (Vertex, GCS, Firestore), mirroring the studio pages
# ---------------------------------------------------------------------------


def _with_count(prompt: str, count: int) -> str:
    """The image studio's "Give me N images." suffix."""
    if count <= 1:
        return prompt
    sep = " " if prompt.endswith((".", "!", "?")) else ". "
    return f"{prompt}{sep}Give me {count} images."


def _brand_prompt(job: LiveJob, prompt: str) -> str:
    from common import brand_kit

    line = brand_kit.prompt_line(brand_kit.load(job.owner))
    return f"{prompt}\n\n{line}" if line else prompt


def _real_image(job: LiveJob) -> RunResult:
    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from config.gemini_image_models import get_gemini_image_model_config
    from models.gemini import generate_image_from_prompt_and_images

    settings = job_settings(job)
    job.progress(0)
    model = settings.get("model") or None
    cfg = get_gemini_image_model_config(model or "")
    inputs = _gcs(_image_refs(job))
    if cfg:
        inputs = inputs[: cfg.max_input_images]
    count = max(1, int(settings.get("count") or 1))
    prompt = job.prompt
    if settings.get("brand") == "on":
        prompt = _brand_prompt(job, prompt)
    prompt = _with_count(prompt, count)
    aspect = settings.get("aspect") or job.aspect_ratio
    job.progress(1)
    job.progress(2)
    gcs_uris, seconds, captions, grounding, _thoughts = (
        generate_image_from_prompt_and_images(
            prompt=prompt,
            images=inputs,
            aspect_ratio=aspect,
            gcs_folder="gemini_image_generations",
            file_prefix="live_image",
            candidate_count=1,
            image_size=settings.get("size") or "1K",
            use_search=settings.get("search", "on") == "on"
            and bool(cfg and cfg.supports_search),
            thinking_level=(settings.get("thinking") or "HIGH")
            if cfg and cfg.supports_thinking
            else None,
            model_name=model,
        )
    )
    if not gcs_uris:
        raise RuntimeError("The model returned no image. Try rewording the prompt.")
    if count and len(gcs_uris) > count:
        gcs_uris, captions = gcs_uris[-count:], list(captions)[-count:]
    job.progress(3)
    import json

    add_media_item_to_firestore(
        MediaItem(
            gcs_uris=gcs_uris,
            captions=captions,
            prompt=job.prompt,
            mime_type="image/png",
            aspect=aspect,
            model=model or "",
            user_email=job.owner,
            source_images_gcs=inputs,
            comment="generated from Home",
            generation_time=seconds,
            grounding_info=json.dumps(grounding) if grounding else "",
        )
    )
    job.params["results"] = [
        {"gcs_uri": u, "display_url": create_display_url(u)} for u in gcs_uris
    ]
    return RunResult(
        gcs_uri=gcs_uris[0],
        display_url=create_display_url(gcs_uris[0]),
        mime_type="image/png",
    )


def video_missing_media(job: LiveJob, settings: dict[str, str] | None = None) -> str:
    """What the chosen video mode still needs, or "" (checked before a run)."""
    from config.video_studio_models import is_omni, omni_mode

    settings = settings or job_settings(job)
    mode = _video_mode(job, settings)
    has_image = bool(_first_frame(job))
    has_last = bool(job_inputs(job, "last_frame"))
    refs = len(job_inputs(job, "references"))
    has_video = bool(job_inputs(job, "video"))
    if is_omni(settings.get("model") or ""):
        from models.omni import find_missing_required_media

        return (
            find_missing_required_media(
                omni_mode(mode),
                has_image=has_image,
                has_video=has_video,
                reference_count=refs,
                has_last_image=has_last,
            )
            or ""
        )
    if mode == "i2v" and not has_image:
        return "Image to video needs a first frame."
    if mode == "interpolation" and not (has_image and has_last):
        return "First + last frame needs both pictures."
    if mode == "r2v" and not (refs or job_inputs(job, "style")):
        return "References mode needs at least one reference picture."
    if mode == "extend" and not has_video:
        return "Extend needs a video."
    return ""


def _real_video(job: LiveJob) -> RunResult:
    from config.video_studio_models import is_omni

    settings = job_settings(job)
    job.progress(0)
    problem = video_missing_media(job, settings)
    if problem:
        raise ValueError(problem)
    if is_omni(settings.get("model") or ""):
        return _real_omni(job, settings)
    return _real_veo(job, settings)


def _real_omni(job: LiveJob, settings: dict[str, str]) -> RunResult:
    """Gemini Omni in every mode, as pages/veo.py build_omni_request does."""
    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from config.omni_models import get_omni_model_config
    from config.video_studio_models import (
        STUDIO_MODE_LABELS,
        VIDEO_INPUT_MODES,
        omni_mode,
    )
    from models.omni import generate_omni_video
    from models.requests import APIReferenceImage, OmniVideoGenerationRequest

    mode = _video_mode(job, settings)
    omni = omni_mode(mode)
    model = settings.get("model") or ""
    first = _first_frame(job) if omni in ("i2v", "first_last", "edit") else ""
    last = (job_inputs(job, "last_frame") or [""])[0] if omni == "first_last" else ""
    video = (job_inputs(job, "video") or [""])[0] if mode in VIDEO_INPUT_MODES else ""
    refs = job_inputs(job, "references") if omni == "ref2v" else []
    prompt = "" if job.params.get("auto_prompt") else job.prompt
    request = OmniVideoGenerationRequest(
        prompt=prompt,
        duration_seconds=int(settings.get("duration") or 8),
        aspect_ratio=settings.get("aspect") or job.aspect_ratio or "16:9",
        resolution=settings.get("resolution") or "720p",
        omni_mode=omni,
        model_version_id=model,
        reference_image_gcs=first or None,
        reference_image_mime_type=_mime(first) if first else None,
        last_reference_image_gcs=last or None,
        last_reference_image_mime_type=_mime(last) if last else None,
        reference_video_gcs=video or None,
        reference_video_mime_type=_mime(video, "video/mp4") if video else None,
        r2v_references=[APIReferenceImage(gcs_uri=u, mime_type=_mime(u)) for u in refs]
        or None,
    )
    job.progress(1)
    job.progress(2)
    gcs_uri, _interaction = generate_omni_video(request)
    if not gcs_uri:
        raise RuntimeError("The video model returned no video.")
    job.progress(3)
    cfg = get_omni_model_config(model)
    try:
        add_media_item_to_firestore(
            MediaItem(
                gcs_uris=[gcs_uri],
                prompt=job.prompt
                or f"{STUDIO_MODE_LABELS.get(mode)} to {request.resolution}",
                mime_type="video/mp4",
                aspect=request.aspect_ratio,
                resolution=request.resolution,
                duration=float(request.duration_seconds)
                if mode not in VIDEO_INPUT_MODES
                else None,
                user_email=job.owner,
                model=cfg.model_name if cfg else model,
                mode=mode,
                comment=f"Generated from Home via Gemini Omni mode: {omni}",
            )
        )
    except Exception:  # the clip is in GCS; show it even if the Library write fails
        logger.exception("Could not save %s to the Library", job.handle)
    return RunResult(
        gcs_uri=gcs_uri, display_url=create_display_url(gcs_uri), mime_type="video/mp4"
    )


def _real_veo(job: LiveJob, settings: dict[str, str]) -> RunResult:
    """Veo, as pages/veo.py on_click_veo / on_click_extend_video build it."""
    from common.metadata import get_media_item_by_id_system
    from common.utils import create_display_url
    from config.veo_models import get_veo_model_config
    from models.requests import APIReferenceImage, VideoGenerationRequest
    from services.studio_options import PEOPLE
    from services.veo_service import create_initial_job, process_veo_generation_task

    mode = _video_mode(job, settings)
    model = settings.get("model") or ""
    cfg = get_veo_model_config(model)
    first = _first_frame(job) if mode in ("i2v", "interpolation", "r2v") else ""
    last = (job_inputs(job, "last_frame") or [""])[0] if mode == "interpolation" else ""
    refs = job_inputs(job, "references") if mode == "r2v" else []
    style = (job_inputs(job, "style") or [""])[0] if mode == "r2v" else ""
    video = (job_inputs(job, "video") or [""])[0] if mode == "extend" else ""
    seed = int(settings.get("seed") or 0)
    count = max(1, int(settings.get("count") or 1))
    if cfg:
        count = min(count, cfg.max_samples)
    request = VideoGenerationRequest(
        prompt=job.prompt,
        negative_prompt=settings.get("negative_prompt") or None,
        duration_seconds=int(settings.get("duration") or 8),
        video_count=count,
        aspect_ratio=settings.get("aspect") or job.aspect_ratio or "16:9",
        resolution=settings.get("resolution") or "720p",
        enhance_prompt=_veo_enhancing(model, settings),
        seed=seed if seed > 0 else None,
        generate_audio=settings.get("audio", "on") != "off",
        model_version_id=model,
        person_generation=PEOPLE.get(
            settings.get("people") or "", PEOPLE["allow_adult"]
        ),
        reference_image_gcs=first or None,
        reference_image_mime_type=_mime(first) if first else None,
        last_reference_image_gcs=last or None,
        last_reference_image_mime_type=_mime(last) if last else None,
        r2v_references=[APIReferenceImage(gcs_uri=u, mime_type=_mime(u)) for u in refs]
        or None,
        r2v_style_image=APIReferenceImage(gcs_uri=style, mime_type=_mime(style))
        if style
        else None,
        video_input_gcs=video or None,
        video_input_mime_type=_mime(video, "video/mp4") if video else None,
    )
    job.progress(1)
    # The video job service saves the job to Firestore (so it shows in the
    # Library) and records failures there; run it inline in this job's thread.
    item_id = create_initial_job(request, job.owner)
    job.progress(2)
    process_veo_generation_task(item_id, request, job.owner)
    job.progress(3)
    item = get_media_item_by_id_system(item_id)
    uris = list(item.gcs_uris or []) if item else []
    if not uris:
        reason = getattr(item, "error_message", "") if item else ""
        raise RuntimeError(reason or "The video model returned no video.")
    job.params["results"] = [
        {"gcs_uri": u, "display_url": create_display_url(u)} for u in uris
    ]
    return RunResult(
        gcs_uri=uris[0], display_url=create_display_url(uris[0]), mime_type="video/mp4"
    )


def _real_music(job: LiveJob) -> RunResult:
    import datetime

    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from config.lyria_models import get_lyria_model_config
    from models.lyria import generate_music_with_lyria
    from services.studio_options import default_music_model

    start = time.time()
    settings = job_settings(job)
    job.progress(0)
    model_name = settings.get("model") or default_music_model()
    cfg = get_lyria_model_config(model_name)
    prompt = job.prompt
    lyrics = ""
    instrumental = settings.get("instrumental") == "on"
    if (
        cfg
        and cfg.supports_lyrics
        and not instrumental
        and settings.get("lyrics") == "on"
    ):
        lyrics = (settings.get("lyrics_text") or "").strip()
    if instrumental and "instrumental" not in prompt.lower():
        # Lyria hears "instrumental" only from the prompt (as the studio does).
        prompt = f"{prompt.rstrip('. ')}. Instrumental."
    image = ""
    if cfg and cfg.supports_images:
        image = (_gcs(job_inputs(job, "image")) or [""])[0]
    count = max(1, int(settings.get("count") or 1))
    if cfg:
        count = min(count, cfg.max_samples)
    job.progress(1)
    job.progress(2)
    gcs_uris, _c2pa, text_outputs = generate_music_with_lyria(
        prompt=prompt,
        model_name=model_name,
        lyrics=lyrics or None,
        image_gcs_uri=image or None,
        image_mime_type=_mime(image, "image/jpeg") if image else "image/jpeg",
        sample_count=count,
    )
    if not gcs_uris:
        raise RuntimeError(
            "The music model returned no audio. Try rewording the prompt."
        )
    job.progress(3)
    add_media_item_to_firestore(
        MediaItem(
            user_email=job.owner,
            timestamp=datetime.datetime.now(datetime.UTC),
            prompt=job.prompt,
            original_prompt=job.prompt,
            model=model_name,
            mime_type="audio/wav",
            generation_time=time.time() - start,
            gcs_uris=gcs_uris,
            generated_text=list(text_outputs or []),
            comment="generated from Home",
        )
    )
    job.params["results"] = [
        {"gcs_uri": u, "display_url": create_display_url(u)} for u in gcs_uris
    ]
    return RunResult(
        gcs_uri=gcs_uris[0],
        display_url=create_display_url(gcs_uris[0]),
        mime_type="audio/wav",
    )


def parse_pronunciations(text: str) -> list[dict[str, str]]:
    """ "word=how to say it" lines to Chirp's [{"phrase", "pronunciation"}]."""
    out = []
    for line in (text or "").splitlines():
        phrase, sep, say = line.partition("=")
        if sep and phrase.strip() and say.strip():
            out.append(
                {"phrase": phrase.strip()[:100], "pronunciation": say.strip()[:200]}
            )
    return out[:50]


def speech_language(engine: str, text: str, code: str) -> str:
    """See models.voice.speech_language."""
    from models.voice import speech_language as pick

    return pick(engine, text, code)


def _voice_request(job: LiveJob):
    """The VoiceRequest for a job (model, voices, dialogue, direction...)."""
    from config.voice import (
        DEFAULT_LANGUAGE,
        DEFAULT_VOICE,
        DEFAULT_VOICE_ENGINE,
        engine_supports_dialogue,
        is_chirp,
    )
    from models.voice import VoiceRequest, validate

    settings = job_settings(job)
    engine = settings.get("model") or DEFAULT_VOICE_ENGINE
    voice = settings.get("voice") or DEFAULT_VOICE
    dialogue = settings.get("dialogue") == "on" and engine_supports_dialogue(engine)
    request = VoiceRequest(
        engine=engine,
        text=job.prompt,
        voice=voice,
        language_code=speech_language(
            engine, job.prompt, settings.get("language") or DEFAULT_LANGUAGE
        ),
        style=settings.get("style") or "natural",
        pace=settings.get("pace") or "normal",
        style_notes="" if is_chirp(engine) else settings.get("direction", ""),
        multi_speaker=dialogue,
        speakers=[
            (settings.get("speaker_a") or "Host", voice),
            (settings.get("speaker_b") or "Guest", settings.get("voice_b") or voice),
        ]
        if dialogue
        else [],
        pronunciations=parse_pronunciations(settings.get("pronunciations", ""))
        if is_chirp(engine)
        else [],
    )
    problem = validate(request)
    if problem:
        raise ValueError(problem)
    return request


def _real_voice(job: LiveJob) -> RunResult:
    import datetime

    from common import storage
    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from models.voice import describe, synthesize_voice

    job.progress(0)
    request = _voice_request(job)
    job.progress(1)
    job.progress(2)
    audio = synthesize_voice(request)
    job.progress(3)
    gcs_uri = storage.store_to_gcs(
        folder="voice-audio",
        file_name=f"voice-{uuid.uuid4()}.wav",
        mime_type="audio/wav",
        contents=audio,
    )
    add_media_item_to_firestore(
        MediaItem(
            user_email=job.owner,
            timestamp=datetime.datetime.now(datetime.UTC),
            prompt=request.text,
            comment=f"{describe(request)} · generated from Home",
            model=request.engine,
            mime_type="audio/wav",
            gcsuri=gcs_uri,
            voice=request.voice,
            language_code=request.language_code,
        )
    )
    return RunResult(
        gcs_uri=gcs_uri,
        display_url=create_display_url(gcs_uri),
        mime_type="audio/wav",
    )


_registry: LiveJobs | None = None
_registry_lock = threading.Lock()


def get_live_jobs() -> LiveJobs:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = LiveJobs()
        return _registry
