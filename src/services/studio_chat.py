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

CHAT_PROMPT = """You are GenMedia Studio, a creative studio built on Google's media models (Nano Banana for images, Gemini Omni and Veo for video, Lyria for music, Gemini TTS for voice, and Story Studio for short films). People type what they want and you make it.

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
) -> dict:
    """Start one job straight from the Home box's type controls.

    No model call: the person picked Image, Video, Music or Voice and its
    settings, so the job starts with exactly those (checked by
    services.studio_options). ``source`` is the handle of a finished picture
    ("image 2") to edit or animate. The exchange is added to the chat's
    history so later messages can say "animate it". Returns {"reply", "job",
    "settings", "summary"}. Raises ValueError for a bad request and
    live_jobs.JobLimitError when too many jobs run.
    """
    from common.i18n import tr
    from services.studio_options import KINDS, clean, summary

    if kind not in KINDS:
        raise ValueError("Pick Image, Video, Music or Voice.")
    prompt = (prompt or "").strip()[:MAX_MESSAGE]
    if not prompt:
        raise ValueError(tr("home.chat.need_prompt", "Write what to make first."))
    s = session_for(owner, jobs)
    picked = clean(kind, settings)
    src = None
    if source and kind in ("image", "video"):
        handle = str(source).strip().lower()
        src = next(
            (
                j
                for j in s.call.jobs.list(owner)
                if j.handle == handle and j.kind == "image" and j.status == "done"
            ),
            None,
        )
        if src is None:
            raise ValueError(tr("home.chat.source_gone", "That picture is gone. Add it again."))
    job = s.call.jobs.submit(
        owner,
        kind,
        prompt,
        aspect_ratio=picked.get("aspect", ""),
        source=src,
        params={"settings": picked, "from": "controls"},
    )
    line = summary(kind, picked)
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
    return {"reply": reply, "job": job.public(), "settings": picked, "summary": line}


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


def _offline_reply(s: ChatSession, message: str) -> tuple[str, list[LiveJob]]:
    said: list[str] = []
    before = {j.id for j in s.call.jobs.list(s.owner)}

    async def say(text: str) -> None:
        said.append(text)

    asyncio.run(ScriptedAgent(s.call, say).handle(message))
    started = [j for j in s.call.jobs.list(s.owner) if j.id not in before]
    return " ".join(said) or "Done.", started


def _model_reply(s: ChatSession, message: str, client: Any, model: str) -> tuple[str, list[LiveJob]]:
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
        response = client.models.generate_content(model=model, contents=contents, config=config)
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
            replies.append(types.Part.from_function_response(name=fc.name or "", response=payload))
        contents.append(types.Content(role="user", parts=replies))
    s.history = contents[-MAX_HISTORY:]
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


UPLOAD_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def attach(owner: str, data_url: str, name: str = "", *, store: Any = None) -> dict:
    """Keep a picture the person attached to the chat; returns its job.

    The picture becomes "image N", so the next message can say "edit image N"
    or "make a video from image N". It is stored in Cloud Storage (or kept as
    a data URL in mock mode). ``store`` replaces the upload, for tests.
    """
    import base64
    import re

    match = re.match(r"^data:(image/[a-z]+);base64,(.+)$", data_url or "", re.S)
    if not match or match.group(1) not in UPLOAD_TYPES:
        raise ValueError("Attach a PNG, JPEG or WebP picture.")
    mime = match.group(1)
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("That picture could not be read.") from exc
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Pictures can be up to 10 MB.")
    clean_name = re.sub(r"[^\w.\- ]", "", name or "")[:60]
    if store is None:
        store = _store_upload
    uri, display_url = store(owner, raw, mime, data_url)
    jobs = session_for(owner).call.jobs
    job = jobs.add_upload(owner, uri=uri, display_url=display_url, mime_type=mime, name=clean_name)
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


def send(owner: str, message: str, client_and_model: tuple[Any, str] | None | bool = True) -> dict:
    """Handle one chat message. Returns {"reply", "jobs", "offline"}.

    ``client_and_model``: True picks the app's client (or offline in mock
    mode); None forces the offline agent; a (client, model) pair is used as is.
    """
    message = (message or "").strip()[:MAX_MESSAGE]
    if not message:
        return {"reply": "", "jobs": [], "offline": False}
    s = session_for(owner)
    picked = _default_client() if client_and_model is True else client_and_model
    with s.lock:
        offline = picked is None
        try:
            if offline:
                reply, started = _offline_reply(s, message)
            else:
                reply, started = _model_reply(s, message, *picked)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Studio chat: the model call failed")
            reply = (
                "I couldn't reach Gemini just now, so nothing was started. "
                f"Please try again. ({str(exc)[:120]})"
            )
            started = []
        s.job_ids.extend(j.id for j in started)
    return {"reply": reply, "jobs": [j.public() for j in started], "offline": offline}
