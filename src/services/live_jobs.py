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

    @property
    def is_edit(self) -> bool:
        return self.kind == "image" and bool(self.source_uri)

    def public(self) -> dict:
        """What the browser and the agent see (no owner)."""
        data = asdict(self)
        data.pop("owner", None)
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
            self._jobs[job.id] = job
        self._emit(job)
        if run_async:
            threading.Thread(
                target=self._run, args=(job,), name=f"live-{job.handle}", daemon=True
            ).start()
        else:
            self._run(job)
        return job

    def _run(self, job: LiveJob) -> None:
        job.status = RUNNING
        self._emit(job)
        try:
            runner = (self._runners or default_runners())[job.kind]
            result = runner(job)
            job.gcs_uri = result.gcs_uri
            job.display_url = result.display_url
            job.mime_type = result.mime_type
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


def _story_runner(job: LiveJob) -> RunResult:
    from services.live_story import run_story_job

    return run_story_job(job)


def _mock_image(job: LiveJob) -> RunResult:
    from common.mock_generation import fake_wait, placeholder_image

    fake_wait(6 if job.is_edit else 5, job.prompt)
    label = f"{job.handle}: {job.prompt}"
    url = placeholder_image(label, job.aspect_ratio, index=int(job.handle.split()[-1]))
    return RunResult(gcs_uri="", display_url=url, mime_type="image/svg+xml")


def _mock_video(job: LiveJob) -> RunResult:
    from common.mock_generation import fake_wait, sample_video

    fake_wait(14, job.prompt)
    return RunResult(gcs_uri="", display_url=sample_video(), mime_type="video/mp4")


def _mock_music(job: LiveJob) -> RunResult:
    from common.mock_generation import fake_wait, sample_audio

    fake_wait(4, job.prompt)
    index = int(job.handle.split()[-1])
    return RunResult(
        gcs_uri="",
        display_url=sample_audio(index),
        mime_type="audio/wav",
    )


def _mock_voice(job: LiveJob) -> RunResult:
    from common.mock_generation import fake_wait, sample_audio

    fake_wait(2, job.prompt)
    index = int(job.handle.split()[-1])
    return RunResult(
        gcs_uri="",
        display_url=sample_audio(index),
        mime_type="audio/wav",
    )


def _real_image(job: LiveJob) -> RunResult:
    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from models.gemini import generate_image_from_prompt_and_images

    inputs = [job.source_uri] if job.source_uri.startswith("gs://") else []
    gcs_uris, seconds, captions, _grounding, _thoughts = (
        generate_image_from_prompt_and_images(
            prompt=job.prompt,
            images=inputs,
            aspect_ratio=job.aspect_ratio,
            gcs_folder="gemini_image_generations",
            file_prefix="live_image",
            image_size="1K",
        )
    )
    if not gcs_uris:
        raise RuntimeError("The model returned no image. Try rewording the prompt.")
    add_media_item_to_firestore(
        MediaItem(
            gcs_uris=gcs_uris,
            captions=captions,
            prompt=job.prompt,
            mime_type="image/png",
            aspect=job.aspect_ratio,
            user_email=job.owner,
            source_images_gcs=inputs,
            comment="generated by the Live agent",
            generation_time=seconds,
        )
    )
    return RunResult(
        gcs_uri=gcs_uris[0],
        display_url=create_display_url(gcs_uris[0]),
        mime_type="image/png",
    )


def _real_video(job: LiveJob) -> RunResult:
    from common.metadata import get_media_item_by_id_system
    from common.utils import create_display_url
    from config.video_studio_models import DEFAULT_STUDIO_MODEL_ID
    from models.requests import VideoGenerationRequest
    from services.veo_service import create_initial_job, process_veo_generation_task

    from_image = job.source_uri if job.source_uri.startswith("gs://") else None
    request = VideoGenerationRequest(
        prompt=job.prompt,
        duration_seconds=8,
        video_count=1,
        aspect_ratio=job.aspect_ratio
        if job.aspect_ratio in ("16:9", "9:16")
        else "16:9",
        resolution="720p",
        enhance_prompt=True,
        generate_audio=True,
        model_version_id=DEFAULT_STUDIO_MODEL_ID,  # Gemini Omni by default
        person_generation="Allow (Adults only)",
        reference_image_gcs=from_image,
        reference_image_mime_type="image/png" if from_image else None,
    )
    # The video job service saves the job to Firestore (so it shows in the Library)
    # and records failures there; run it inline in this job's thread.
    item_id = create_initial_job(request, job.owner)
    process_veo_generation_task(item_id, request, job.owner)
    item = get_media_item_by_id_system(item_id)
    uri = (item.gcs_uris[0] if item and item.gcs_uris else "") if item else ""
    if not uri:
        reason = getattr(item, "error_message", "") if item else ""
        raise RuntimeError(reason or "The video model returned no video.")
    return RunResult(
        gcs_uri=uri, display_url=create_display_url(uri), mime_type="video/mp4"
    )


def _real_music(job: LiveJob) -> RunResult:
    import datetime

    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from config.default import Default
    from models.lyria import generate_music_with_lyria

    start = time.time()
    model_name = Default().LYRIA_MODEL_VERSION
    lyrics = str(job.params.get("lyrics") or "").strip()
    gcs_uris, _c2pa, text_outputs = generate_music_with_lyria(
        prompt=job.prompt,
        model_name=model_name,
        lyrics=lyrics or None,
    )
    if not gcs_uris:
        raise RuntimeError(
            "The music model returned no audio. Try rewording the prompt."
        )
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
            comment="generated by the Live agent",
        )
    )
    return RunResult(
        gcs_uri=gcs_uris[0],
        display_url=create_display_url(gcs_uris[0]),
        mime_type="audio/wav",
    )


def _real_voice(job: LiveJob) -> RunResult:
    import datetime

    from common import storage
    from common.metadata import MediaItem, add_media_item_to_firestore
    from common.utils import create_display_url
    from config.voice import DEFAULT_LANGUAGE, DEFAULT_VOICE, DEFAULT_VOICE_ENGINE
    from models.voice import VoiceRequest, describe, synthesize_voice, validate

    request = VoiceRequest(
        engine=DEFAULT_VOICE_ENGINE,
        text=job.prompt,
        voice=str(job.params.get("voice") or DEFAULT_VOICE),
        language_code=str(job.params.get("language") or DEFAULT_LANGUAGE),
    )
    problem = validate(request)
    if problem:
        raise ValueError(problem)
    audio = synthesize_voice(request)
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
            comment=f"{describe(request)} · generated by the Live agent",
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
