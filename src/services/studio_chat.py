# Copyright 2025 Google LLC
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
"""The Home chat: one prompt box that does everything.

A typed version of the Live voice agent. Each message goes to Gemini with
the same job tools (services.live_agent): images, edits, video, music,
voice and Story Studio films. Jobs run in the background in
services.live_jobs, so the chat answers at once and the results appear in
the conversation when they finish (the page polls ``/api/chat/jobs``). Plain
questions get a text answer.

Without a model (mock generation or LIVE_AGENT_OFFLINE) the offline
ScriptedAgent answers simple typed requests, so the page demos at no cost.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from google.genai import types

from common.analytics import extract_usage_metadata, track_model_call
from services.live_agent import (
    ACT,
    Deferred,
    LiveCall,
    ScriptedAgent,
    _all_declarations,
)
from services.live_jobs import LiveJob, LiveJobs, get_live_jobs

logger = logging.getLogger(__name__)

# Tools the chat may call. Screen tools (open_page, show_job, download,
# read_page, fill_fields, open_story, end_call) need the voice call's
# browser link, so the chat shows results inline instead.
CHAT_TOOLS = (
    "generate_image",
    "edit_image",
    "generate_video",
    "generate_music",
    "generate_voice",
    "create_story",
    "continue_story",
    "render_film",
    "story_status",
    "plan_film_fix",
    "run_film_fix",
    "list_jobs",
)
MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 30  # contents kept per conversation
MAX_MESSAGE = 4000

CHAT_PROMPT = """You are Creative Studio, a studio built on Google's media models (Nano Banana for images, Gemini Omni and Veo for video, Lyria for music, Gemini TTS for voice, and Film Studio for short films). People type what they want and you make it.

How you work:
- Decide from the request what to make and call the right tool right away: generate_image, edit_image, generate_video, generate_music, generate_voice, or create_story for a short film. Several things at once are fine.
- Write rich prompts for the models from their words: subject, style, lighting, camera, or genre, instruments, mood, tempo. Keep their intent and any names or text exactly.
- generate_voice speaks the script exactly as given: pass their words unchanged.
- Jobs run in the background and appear in this chat when they are ready. Do not wait for them and do not invent results or links.
- "The image" or "it" means the latest one; jobs have names like "image 1" and "video 2".
- A message may start with "[Attached: image 3]": the person added that picture. Use it as the image to edit (edit_image) or animate (generate_video with from_image), or as the subject they describe.
- Films: create_story only writes the scenario (cheap). Before each costly step (continue_story builds the set and paints the storyboard; render_film renders the videos), say what it will do and ask for a yes, unless they already said to go all the way.
- If they ask a question, want ideas, copy or a script, answer in text without a tool.

How you write:
- Short and warm: one or two sentences. Say what you started, e.g. "Making image 1: a red fox in deep snow at golden hour."
- Plain words, no markdown headings, no URLs or ids.
- Reply in the language the person writes in (for example Arabic or English); prompts for the models may stay in English.
- Only creative and media work. Politely decline anything else."""


def chat_tools() -> list[types.Tool]:
    """The chat's function declarations (blocking style, for generate_content)."""
    decls = _all_declarations(async_tools=False)[0].function_declarations
    return [types.Tool(function_declarations=[d for d in decls if d.name in CHAT_TOOLS])]


async def _no_screen(_message: dict) -> None:
    """The chat has no voice-call browser link; UI hints are dropped."""


@dataclass
class ChatSession:
    owner: str
    call: LiveCall
    history: list[types.Content] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    touched: float = field(default_factory=time.time)


_sessions: dict[str, ChatSession] = {}
_sessions_lock = threading.Lock()


def session_for(owner: str, jobs: LiveJobs | None = None) -> ChatSession:
    with _sessions_lock:
        s = _sessions.get(owner)
        if s is None:
            call = LiveCall(owner, _no_screen, jobs or get_live_jobs(), mode=ACT)
            s = _sessions[owner] = ChatSession(owner=owner, call=call)
        s.touched = time.time()
        return s


def reset(owner: str) -> None:
    with _sessions_lock:
        _sessions.pop(owner, None)


def load_history(
    owner: str,
    messages: list[dict],
    job_ids: list[str] | None = None,
    jobs: LiveJobs | None = None,
) -> int:
    """Start a fresh session that remembers a saved chat's earlier turns.

    ``messages`` are ``{"role": "user"|"assistant", "text"}``; the last
    MAX_HISTORY with text become the model's history, so a reopened chat can
    still say "make a video from image 1". ``job_ids`` are the chat's jobs, so
    any still running keep reporting. Returns how many turns were kept.
    """
    reset(owner)
    s = session_for(owner, jobs)
    history: list[types.Content] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        text = str(m.get("text") or "").strip()[:MAX_MESSAGE]
        if not text:
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        history.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))
    with s.lock:
        s.history = history[-MAX_HISTORY:]
        s.job_ids = [str(j)[:64] for j in (job_ids or []) if j][-500:]
    return len(s.history)


def make(
    owner: str,
    kind: str,
    prompt: str,
    settings: Any = None,
    source: str = "",
    jobs: LiveJobs | None = None,
    inputs: Any = None,
) -> dict:
    """Start one job straight from the Home box's type controls.

    No model call: the person picked Image, Video, Music, Voice or Film and
    its settings, so the job starts with exactly those (checked by
    services.studio_options). ``source`` is the handle of a finished picture
    ("image 2") to edit or animate. ``inputs`` fills the type's file slots:
    ``{"first_frame": ["image 2"], "references": [...], "video": ["video 1"]}``
    (see studio_options.inputs). The exchange is added to the chat's
    history so later messages can say "animate it". Returns {"reply", "job",
    "settings", "summary", "trace"}. Raises ValueError for a bad request and
    live_jobs.JobLimitError when too many jobs run.
    """
    from common.i18n import tr
    from services.live_jobs import LiveJob, video_missing_media
    from services.studio_options import KINDS, clean, summary

    if kind not in KINDS:
        raise ValueError("Pick Image, Video, Music, Voice or Film.")
    picked = clean(kind, settings)
    prompt = (prompt or "").strip()[:MAX_MESSAGE]
    auto_prompt = False
    if not prompt and kind == "video" and picked.get("mode") == "upscale":
        # Upscale sends no prompt (as Video Studio); the thread still needs a line.
        prompt, auto_prompt = f"Upscale to {picked.get('resolution', '')}".strip(), True
    if not prompt:
        raise ValueError(tr("home.chat.need_prompt", "Write what to make first."))
    s = session_for(owner, jobs)
    line = summary(kind, picked)
    trace = [_step(*_picked_label(kind, picked))]
    if line:
        trace.append(_step(tr("home.trace.settings", "Settings: {line}").format(line=line)))
    if kind == "film":
        out = _start_film(s, prompt, picked, line)
        trace.append(_step(_started_label(out["job"]["handle"])))
        return {**out, "trace": trace}
    slots, src = _resolve_inputs(s, kind, inputs, source)
    for slot, items in slots.items():
        trace.append(
            _step(
                tr("home.trace.using", "Using {items} as {slot}").format(
                    items=", ".join(i["handle"] for i in items), slot=_slot_label(kind, slot)
                )
            )
        )
    params: dict[str, Any] = {"settings": picked, "from": "controls"}
    if slots:
        params["inputs"] = slots
    if auto_prompt:
        params["auto_prompt"] = True
    if kind == "video":
        probe = LiveJob(
            id="",
            owner=owner,
            kind=kind,
            handle="",
            prompt=prompt,
            source_uri=(src.gcs_uri or src.display_url) if src else "",
            params=params,
        )
        problem = video_missing_media(probe, picked)
        if problem:
            raise ValueError(problem)
    job = s.call.jobs.submit(
        owner,
        kind,
        prompt,
        aspect_ratio=picked.get("aspect", ""),
        source=src,
        params=params,
    )
    trace.append(_step(_started_label(job.handle)))
    reply = tr("home.chat.making_job", "Making {job}.").format(job=job.handle)
    if src is not None:
        reply = tr("home.chat.making_from", "Making {job} from {source}.").format(
            job=job.handle, source=src.handle
        )
    said = f"[{kind}{': ' + line if line else ''}{', from ' + src.handle if src else ''}] {prompt}"
    with s.lock:
        s.job_ids.append(job.id)
        s.history = (
            s.history
            + [
                types.Content(role="user", parts=[types.Part.from_text(text=said)]),
                types.Content(role="model", parts=[types.Part.from_text(text=reply)]),
            ]
        )[-MAX_HISTORY:]
    return {
        "reply": reply,
        "job": job.public(),
        "settings": picked,
        "summary": line,
        "trace": trace,
    }


MAX_INPUT_HANDLES = 20


def _resolve_inputs(
    s: ChatSession, kind: str, raw: Any, source: str
) -> tuple[dict[str, list[dict]], LiveJob | None]:
    """Turn ``{slot: [handle, ...]}`` into ``{slot: [{"handle", "uri", "mime"}]}``.

    A handle names a finished picture or video of this person ("image 2",
    "video 1", or a job id). ``source`` (the older single picture) fills the
    references (image) or the first frame (video). Returns the slots and the
    job to record as the source (the first picture used), or raises
    ValueError when a slot or handle is unknown.
    """
    from common.i18n import tr
    from services.studio_options import inputs as slot_list

    slots = {sl["name"]: sl for sl in slot_list(kind)}
    raw = dict(raw) if isinstance(raw, dict) else {}
    if source and kind in ("image", "video"):
        key = "references" if kind == "image" else "first_frame"
        if not raw.get(key):
            raw[key] = [source]
    mine = s.call.jobs.list(s.owner)
    out: dict[str, list[dict]] = {}
    first: LiveJob | None = None
    for name, handles in raw.items():
        if not handles:
            continue
        slot = slots.get(str(name))
        if slot is None:
            raise ValueError(f"{kind.title()} has no '{name}' input.")
        if isinstance(handles, str):
            handles = [handles]
        want = "video" if slot["accept"].startswith("video") else "image"
        items = []
        for handle in list(handles)[:MAX_INPUT_HANDLES][: int(slot["max"])]:
            text = str(handle).strip().lower()
            job = next(
                (
                    j
                    for j in mine
                    if (j.handle == text or j.id == text)
                    and j.kind == want
                    and j.status == "done"
                    and (j.gcs_uri or j.display_url)
                ),
                None,
            )
            if job is None:
                gone = (
                    "That video is gone. Add it again."
                    if want == "video"
                    else "That picture is gone. Add it again."
                )
                raise ValueError(tr(f"home.chat.{want}_gone", gone))
            items.append(
                {
                    "handle": job.handle,
                    "uri": job.gcs_uri or job.display_url,
                    "mime": job.mime_type,
                }
            )
            if first is None and want == "image":
                first = job
        if items:
            out[slot["name"]] = items
    return out, first


_KIND_LABELS = {
    "image": "Image",
    "video": "Video",
    "music": "Music",
    "voice": "Voice",
    "film": "Film",
    "story": "Film",
}


def _step(label: str, detail: str = "") -> dict:
    return {"type": "step", "label": label, "detail": detail}


def _picked_label(kind: str, settings: dict[str, str]) -> tuple[str, str]:
    """("Picked Image · Nano Banana 2.1 · 16:9", why) for a type and its settings."""
    from common.i18n import tr
    from services.studio_options import option_label, summary

    kind = "film" if kind == "story" else kind
    parts = [tr(f"home.kind.{kind}", _KIND_LABELS.get(kind, kind.title()))]
    if settings.get("model"):
        parts.append(option_label(kind, "model", settings))
    if settings.get("aspect") and settings["aspect"] != "auto":
        parts.append(settings["aspect"])
    detail = summary(kind, settings) if settings else ""
    return tr("home.trace.picked", "Picked {what}").format(what=" · ".join(parts)), detail


def _started_label(handle: str) -> str:
    from common.i18n import tr

    return tr("home.trace.started", "Started {job}").format(job=handle)


def _slot_label(kind: str, slot: str) -> str:
    from services.studio_options import inputs as slot_list

    for sl in slot_list(kind):
        if sl["name"] == slot:
            return str(sl["label"]).lower()
    return slot


def _job_steps(job: LiveJob) -> list[dict]:
    """The trace for a job the chat started: what, the prompt, started."""
    from common.i18n import tr
    from services.live_jobs import job_settings

    settings = job_settings(job) if job.kind != "story" else {}
    label, detail = _picked_label(job.kind, settings)
    return [
        _step(label, detail),
        _step(tr("home.trace.prompt", "Wrote the prompt"), job.prompt),
        _step(_started_label(job.handle)),
    ]


_TYPED = (
    (r"\b(\d{1,2}:\d{1,2})\b", "{}"),
    (r"\b(4k|2k|1k|720p|1080p)\b", "{}"),
    (r"\b(\d{1,3})\s*(?:s|sec|secs|seconds?)\b", "{}s"),
    (r"\b(\d{1,2})\s*(?:min|mins|minutes?)\b", "{}m"),
)


def typed_settings(message: str) -> list[str]:
    """Settings written in the message ("16:9", "4K", "8 seconds"), for the trace."""
    import re

    found = []
    for pattern, fmt in _TYPED:
        for match in re.finditer(pattern, message or "", re.I):
            value = fmt.format(match.group(1).upper() if "k" in match.group(1).lower() else match.group(1))
            if value not in found:
                found.append(value)
    return found[:6]


class _Trace:
    """Collects the chat's steps and hands each to ``on_step`` as it happens."""

    def __init__(self, on_step: Any = None):
        self.steps: list[dict] = []
        self._on_step = on_step

    def step(self, label: str, detail: str = "") -> None:
        item = _step(label, detail)
        self.steps.append(item)
        if self._on_step is not None:
            try:
                self._on_step(item)
            except Exception:  # pylint: disable=broad-except
                logger.exception("Studio chat: a trace listener failed")

    def jobs(self, started: list[LiveJob]) -> None:
        for job in started:
            for item in _job_steps(job):
                self.step(item["label"], item["detail"])


def _remember(s: ChatSession, said: str, reply: str, job: LiveJob | None) -> None:
    with s.lock:
        if job is not None:
            s.job_ids.append(job.id)
        s.history = (
            s.history
            + [
                types.Content(role="user", parts=[types.Part.from_text(text=said)]),
                types.Content(role="model", parts=[types.Part.from_text(text=reply)]),
            ]
        )[-MAX_HISTORY:]


def _start_film(s: ChatSession, idea: str, picked: dict, line: str) -> dict:
    """Film: write the scenario (the cheap first step) of a new Story Studio story."""
    from common.i18n import tr

    args: dict[str, Any] = {"idea": idea}
    for key, arg in (
        ("length", "length"),
        ("aspect", "aspect_ratio"),
        ("style", "style"),
        ("language", "language"),
        ("engine", "video_model"),
        ("pacing", "pacing"),
        ("speech", "speech_mode"),
        ("camera", "camera"),
    ):
        if picked.get(key, "auto") != "auto":
            args[arg] = picked[key]
    for key, arg in (("scenes", "scene_count"), ("scene_length", "scene_seconds")):
        if str(picked.get(key, "auto")).isdigit():
            args[arg] = int(picked[key])
    if picked.get("source") == "script":
        # From a script: the text is the script; the idea is its opening.
        args["script"] = idea
        args["idea"] = " ".join(idea.split())[:400]
    out = asyncio.run(s.call.run_tool("create_story", args))
    if not isinstance(out, Deferred):
        raise ValueError(str((out or {}).get("error") or "The film could not start."))
    job = out.job
    reply = tr(
        "home.chat.film_started",
        "Writing the scenario for {job}. Check it, then go to the next step.",
    ).format(job=job.handle)
    _remember(s, f"[film{': ' + line if line else ''}] {idea}", reply, job)
    return {"reply": reply, "job": job.public(), "settings": picked, "summary": line}


def film_next(owner: str, story_id: str, all_steps: bool = False, jobs: LiveJobs | None = None) -> dict:
    """Run a film's next step (approving the scenario first), or all of them.

    Returns {"reply", "job"}; job is None when the film is already done.
    """
    from common.i18n import tr

    s = session_for(owner, jobs)
    story_id = str(story_id or "").strip()[:64]
    if not story_id:
        raise ValueError("Which film?")
    args = {"story": story_id, "all_steps": bool(all_steps)}
    out = asyncio.run(s.call.run_tool("continue_story", args))
    if isinstance(out, dict) and out.get("approved"):
        # The scenario is approved; go straight on to building the set.
        out = asyncio.run(s.call.run_tool("continue_story", {"story": story_id}))
    if isinstance(out, Deferred):
        job = out.job
        key = "home.chat.film_all" if all_steps else "home.chat.film_next"
        english = "Making the whole film: {job}." if all_steps else "Next step started: {job}."
        reply = tr(key, english).format(job=job.handle)
        _remember(s, "[film] whole film" if all_steps else "[film] next step", reply, job)
        return {"reply": reply, "job": job.public()}
    out = out if isinstance(out, dict) else {}
    if out.get("error"):
        raise ValueError(str(out["error"]))
    return {"reply": tr("home.chat.film_done", "The film is already finished."), "job": None}


def chat_jobs(owner: str, jobs: LiveJobs | None = None) -> list[dict]:
    """The jobs this person started from the chat, oldest first."""
    s = _sessions.get(owner)
    if s is None:
        return []
    wanted = set(s.job_ids)
    return [j.public() for j in (jobs or s.call.jobs).list(owner) if j.id in wanted]


def _tool_response(out: dict | Deferred) -> tuple[dict, LiveJob | None]:
    if isinstance(out, Deferred):
        job = out.job
        return (
            {
                "job": job.handle,
                "status": "started",
                "note": "Running in the background; it shows in the chat when ready.",
            },
            job,
        )
    return (out if isinstance(out, dict) else {"result": str(out)}), None


def _offline_reply(
    s: ChatSession, message: str, trace: _Trace | None = None
) -> tuple[str, list[LiveJob]]:
    said: list[str] = []
    before = {j.id for j in s.call.jobs.list(s.owner)}

    async def say(text: str) -> None:
        said.append(text)

    asyncio.run(ScriptedAgent(s.call, say).handle(message))
    started = [j for j in s.call.jobs.list(s.owner) if j.id not in before]
    if trace is not None:
        trace.jobs(started)
        if not started:
            trace.step("Wrote the reply")
    return " ".join(said) or "Done.", started


_TOOL_STEPS = {
    "list_jobs": "Checked your jobs",
    "story_status": "Checked the film",
    "plan_film_fix": "Planned the fix",
    "continue_story": "Moved the film on",
}


def _model_reply(
    s: ChatSession,
    message: str,
    client: Any,
    model: str,
    trace: _Trace | None = None,
) -> tuple[str, list[LiveJob]]:
    trace = trace or _Trace()
    contents = list(s.history) + [
        types.Content(role="user", parts=[types.Part.from_text(text=message)])
    ]
    config = types.GenerateContentConfig(
        system_instruction=CHAT_PROMPT,
        tools=chat_tools(),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.6,
    )
    started: list[LiveJob] = []
    text = ""
    for _ in range(MAX_TOOL_ROUNDS):
        with track_model_call(model_name=model, task="studio_chat") as ctx:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            ctx["billing_units"].update(extract_usage_metadata(response))
        candidate = (response.candidates or [None])[0]
        content = candidate.content if candidate and candidate.content else None
        if content is None:
            break
        contents.append(content)
        calls = [p.function_call for p in (content.parts or []) if p.function_call]
        text = "".join(p.text or "" for p in (content.parts or []) if p.text).strip()
        if not calls:
            break
        replies = []
        for fc in calls:
            out = asyncio.run(s.call.run_tool(fc.name or "", dict(fc.args or {})))
            payload, job = _tool_response(out)
            if job is not None:
                started.append(job)
                trace.jobs([job])
            elif isinstance(payload, dict) and payload.get("error"):
                trace.step("Could not do that", str(payload["error"])[:300])
            else:
                trace.step(_TOOL_STEPS.get(fc.name or "", f"Used {fc.name}"))
            replies.append(types.Part.from_function_response(name=fc.name or "", response=payload))
        contents.append(types.Content(role="user", parts=replies))
    s.history = contents[-MAX_HISTORY:]
    if text and not started:
        trace.step("Wrote the reply")
    if not text:
        text = "On it." if started else "Sorry, I could not answer that. Try again?"
    return text, started


def _default_client() -> tuple[Any, str] | None:
    """The app's Gemini client and chat model, or None to use the offline agent."""
    from common.mock_generation import mock_enabled
    from config.default import Default

    if mock_enabled() or Default.LIVE_AGENT_OFFLINE:
        return None
    from models.gemini import client

    return client, Default.MODEL_ID


UPLOAD_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 40 * 1024 * 1024


def attach(owner: str, data_url: str, name: str = "", *, store: Any = None) -> dict:
    """Keep a picture the person attached to the chat; returns its job.

    The picture becomes "image N", so the next message can say "edit image N"
    or "make a video from image N". It is stored in Cloud Storage (or kept as
    a data URL in mock mode). ``store`` replaces the upload, for tests.
    """
    import base64
    import re

    match = re.match(r"^data:((?:image|video)/[a-z0-9.+-]+);base64,(.+)$", data_url or "", re.S)
    if not match or match.group(1) not in UPLOAD_TYPES:
        raise ValueError("Attach a PNG, JPEG or WebP picture, or an MP4, WebM or MOV video.")
    mime = match.group(1)
    is_video = mime.startswith("video/")
    # Check the size before decoding (base64 is 4/3 of the bytes).
    limit = MAX_VIDEO_UPLOAD_BYTES if is_video else MAX_UPLOAD_BYTES
    if len(match.group(2)) * 3 // 4 > limit + 3:
        raise ValueError("Videos can be up to 40 MB." if is_video else "Pictures can be up to 10 MB.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        what = "video" if is_video else "picture"
        raise ValueError(f"That {what} could not be read.") from exc
    if len(raw) > limit:
        raise ValueError("Videos can be up to 40 MB." if is_video else "Pictures can be up to 10 MB.")
    clean_name = re.sub(r"[^\w.\- ]", "", name or "")[:60]
    if store is None:
        store = _store_upload
    uri, display_url = store(owner, raw, mime, data_url)
    jobs = session_for(owner).call.jobs
    job = jobs.add_upload(
        owner,
        uri=uri,
        display_url=display_url,
        mime_type=mime,
        name=clean_name,
        kind="video" if is_video else "image",
    )
    return job.public()


def _store_upload(owner: str, raw: bytes, mime: str, data_url: str) -> tuple[str, str]:
    """(uri, display_url) for an attached picture."""
    import uuid

    from common.mock_generation import mock_enabled

    if mock_enabled():
        return data_url, data_url
    from common.storage import store_to_gcs
    from common.utils import create_display_url

    del owner
    uri = store_to_gcs(
        "chat_uploads", f"{uuid.uuid4().hex}.{UPLOAD_TYPES[mime]}", mime, raw
    )
    return uri, create_display_url(uri)


def send(
    owner: str,
    message: str,
    client_and_model: tuple[Any, str] | None | bool = True,
    on_step: Any = None,
) -> dict:
    """Handle one chat message. Returns {"reply", "jobs", "offline", "trace"}.

    ``client_and_model``: True picks the app's client (or offline in mock
    mode); None forces the offline agent; a (client, model) pair is used as is.
    ``on_step`` gets each trace step ({"type": "step", "label", "detail"}) as
    it happens (it runs on this thread); ``trace`` lists them all.
    """
    message = (message or "").strip()[:MAX_MESSAGE]
    if not message:
        return {"reply": "", "jobs": [], "offline": False, "trace": []}
    trace = _Trace(on_step)
    s = session_for(owner)
    picked = _default_client() if client_and_model is True else client_and_model
    offline = picked is None
    trace.step(
        "Reading your message",
        "Offline helper" if offline else f"Gemini · {picked[1]}",
    )
    found = typed_settings(message)
    if found:
        trace.step("Found settings in your message", " · ".join(found))
    with s.lock:
        try:
            if offline:
                reply, started = _offline_reply(s, message, trace)
            else:
                reply, started = _model_reply(s, message, *picked, trace=trace)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Studio chat: the model call failed")
            reply = (
                "I couldn't reach Gemini just now, so nothing was started. "
                f"Please try again. ({str(exc)[:120]})"
            )
            started = []
            trace.step("Could not reach Gemini", str(exc)[:200])
        s.job_ids.extend(j.id for j in started)
    return {
        "reply": reply,
        "jobs": [j.public() for j in started],
        "offline": offline,
        "trace": trace.steps,
    }
