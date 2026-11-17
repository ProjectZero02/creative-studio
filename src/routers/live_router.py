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
"""WebSocket bridge between the browser and a Gemini Live session.

The browser cannot call Vertex AI directly (Live ephemeral tokens are Developer
API only), so this route holds the Live session with the app's own Google
Cloud credentials and relays:

* browser -> server: ``audio`` (16 kHz PCM16, base64), ``text``, ``screen``
  (current path), ``ui_result``, ``hangup``
* server -> browser: ``audio`` (24 kHz PCM16, base64), ``transcript``,
  ``interrupted``, ``turn_complete``, ``ui`` (a screen action to run), ``job``
  (job status), ``status``, ``error``

HTTP middleware does not run for WebSockets, so this route checks identity and
origin itself.
"""

from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types
from starlette.concurrency import run_in_threadpool

from common.analytics import get_logger
from common.identity import ANONYMOUS_USER_EMAIL
from common.verified_identity import (
    AUTH_MODE_SESSION,
    auth_mode,
    get_verified_user_identity,
)
from config.default import Default
from services.live_agent import (
    SYSTEM_PROMPT,
    Deferred,
    LiveCall,
    ScriptedAgent,
    tool_declarations,
)
from services.live_jobs import DONE, FAILED, get_live_jobs

logger = get_logger(__name__)
router = APIRouter()

# Close codes the browser shows as a message.
CLOSE_FORBIDDEN = 4403
CLOSE_DISABLED = 4404


def _origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser clients (tests); cookies still gate identity
    host = ws.headers.get("x-forwarded-host") or ws.headers.get("host") or ""
    return urlparse(origin).netloc == host


async def _owner(ws: WebSocket) -> str | None:
    identity = await run_in_threadpool(get_verified_user_identity, ws.headers)
    if identity is not None:
        return identity.email
    if auth_mode() == AUTH_MODE_SESSION or Default.REQUIRE_AUTHENTICATED_USER:
        return None
    return ANONYMOUS_USER_EMAIL


def _genai_client():
    """Vertex AI with the app's own credentials (ADC / Cloud Run service account)."""
    from google import genai

    client = genai.Client(
        vertexai=True, project=Default.PROJECT_ID, location=Default.LIVE_LOCATION
    )
    return client, Default.LIVE_MODEL


def _live_config(resume_handle: str | None) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=Default.LIVE_VOICE
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=SYSTEM_PROMPT,
        tools=tool_declarations(Default.LIVE_ASYNC_TOOLS),
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
    )


class _Bridge:
    """One browser call."""

    def __init__(self, ws: WebSocket, owner: str):
        self.ws = ws
        self.owner = owner
        self.jobs = get_live_jobs()
        self._send_lock = asyncio.Lock()
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.job_events: asyncio.Queue = asyncio.Queue()
        self.call = LiveCall(owner, self.send, self.jobs)
        self.closed = False
        self.session = None
        self.session_gen = 0
        self.resume_handle: str | None = None
        self._tasks: set[asyncio.Task] = set()
        self.deferred: dict[
            str, tuple[str, str, int]
        ] = {}  # job id -> (call id, name, gen)
        self.agent: ScriptedAgent | None = None
        self.loop = asyncio.get_running_loop()

    async def send(self, message: dict) -> None:
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_text(json.dumps(message))
            except Exception:
                self.closed = True

    async def status(self, state: str, detail: str = "") -> None:
        await self.send({"type": "status", "state": state, "detail": detail})

    # -- browser reader (one task for the whole call) -----------------------

    async def read_browser(self) -> None:
        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                kind = message.get("type")
                if kind == "ui_result":
                    self.call.ui_result(
                        str(message.get("id")), message.get("result") or {}
                    )
                elif kind == "screen":
                    self.call.screen = str(message.get("path") or "/home")[:200]
                elif kind == "hangup":
                    break
                else:
                    await self.inbox.put(message)
        except WebSocketDisconnect:
            pass
        finally:
            self.closed = True
            await self.inbox.put({"type": "hangup"})

    # -- job events (one task for the whole call) ---------------------------

    def on_job(self, job) -> None:  # called from job threads
        self.loop.call_soon_threadsafe(self.job_events.put_nowait, job)

    async def pump_jobs(self) -> None:
        while not self.closed:
            job = await self.job_events.get()
            await self.send({"type": "job", "job": job.public()})
            if job.status not in (DONE, FAILED):
                continue
            if self.agent is not None:
                await self.agent.on_job_done(job)
                continue
            await self._deliver_result(job)

    async def _deliver_result(self, job) -> None:
        result = LiveCall.job_result(job)
        pending = self.deferred.pop(job.id, None)
        session = self.session
        if session is None:
            return
        try:
            if pending and pending[2] == self.session_gen and Default.LIVE_ASYNC_TOOLS:
                call_id, name, _ = pending
                await session.send_tool_response(
                    function_responses=[
                        types.FunctionResponse(
                            id=call_id,
                            name=name,
                            response=result,
                            scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
                        )
                    ]
                )
            else:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text="[job update] " + json.dumps(result))],
                    ),
                    turn_complete=True,
                )
        except Exception:
            logger.exception("Could not deliver %s result to Live", job.handle)

    # -- offline agent ------------------------------------------------------

    async def run_offline(self, reason: str = "") -> None:
        async def say(text: str) -> None:
            await self.send(
                {"type": "transcript", "who": "agent", "text": text, "final": True}
            )

        self.agent = ScriptedAgent(self.call, say)
        await self.status("offline", reason)
        await say(
            "Offline mode: type a request, for example 'image of a red fox in snow'."
        )
        while True:
            message = await self.inbox.get()
            kind = message.get("type")
            if kind == "hangup" or self.call.ended:
                return
            if kind == "text":
                text = str(message.get("text") or "")[:2000]
                await self.send(
                    {"type": "transcript", "who": "user", "text": text, "final": True}
                )
                await self.agent.handle(text)

    # -- Gemini Live ----------------------------------------------------------

    async def run_live(self) -> None:
        client, model = _genai_client()
        failures = 0
        while not self.closed and not self.call.ended:
            self.session_gen += 1
            reconnect = False
            await self.status("connecting")
            async with client.aio.live.connect(
                model=model, config=_live_config(self.resume_handle)
            ) as session:
                self.session = session
                await self.status("live")
                down = asyncio.create_task(self._downstream(session))
                up = asyncio.create_task(self._upstream(session))
                try:
                    done, _ = await asyncio.wait(
                        {down, up}, return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    up.cancel()
                    if not down.done():
                        down.cancel()
                    self.session = None
                if down in done and not down.cancelled():
                    try:
                        reconnect = down.result()
                        failures = 0
                    except Exception:
                        # Dropped without goAway: resume if we can, a few times.
                        failures += 1
                        if not self.resume_handle or failures > 3:
                            raise
                        logger.warning("Live session dropped; resuming", exc_info=True)
                        reconnect = True
            if not reconnect:
                return
            logger.info("Live session for %s reconnecting with resumption", self.owner)

    async def _upstream(self, session) -> None:
        while True:
            message = await self.inbox.get()
            kind = message.get("type")
            if kind == "hangup":
                self.closed = True
                return
            if kind == "audio":
                data = base64.b64decode(message.get("data") or "")
                if data:
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
                    )
            elif kind == "audio_end":
                await session.send_realtime_input(audio_stream_end=True)
            elif kind == "text":
                text = str(message.get("text") or "")[:2000]
                await self.send(
                    {"type": "transcript", "who": "user", "text": text, "final": True}
                )
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=text)]),
                    turn_complete=True,
                )

    async def _downstream(self, session) -> bool:
        """Relay model output. Returns True when the session should reconnect."""
        while not self.closed:
            async for msg in session.receive():
                if self.closed:
                    return False
                update = msg.session_resumption_update
                if update and update.resumable and update.new_handle:
                    self.resume_handle = update.new_handle
                if msg.go_away is not None:
                    return True
                if msg.tool_call:
                    for fc in msg.tool_call.function_calls or []:
                        task = asyncio.create_task(self._tool(session, fc))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
                content = msg.server_content
                if not content:
                    continue
                if content.interrupted:
                    await self.send({"type": "interrupted"})
                if content.model_turn:
                    for part in content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await self.send(
                                {
                                    "type": "audio",
                                    "data": base64.b64encode(
                                        part.inline_data.data
                                    ).decode(),
                                }
                            )
                if content.input_transcription and content.input_transcription.text:
                    await self.send(
                        {
                            "type": "transcript",
                            "who": "user",
                            "text": content.input_transcription.text,
                        }
                    )
                if content.output_transcription and content.output_transcription.text:
                    await self.send(
                        {
                            "type": "transcript",
                            "who": "agent",
                            "text": content.output_transcription.text,
                        }
                    )
                if content.turn_complete:
                    await self.send({"type": "turn_complete"})
                    if self.call.ended:
                        return False
        return False

    async def _tool(self, session, fc) -> None:
        await self.send({"type": "tool", "name": fc.name, "args": fc.args or {}})
        result = await self.call.run_tool(fc.name, dict(fc.args or {}))
        if isinstance(result, Deferred):
            if Default.LIVE_ASYNC_TOOLS:
                # Answered when the job finishes (pump_jobs -> WHEN_IDLE).
                self.deferred[result.job.id] = (fc.id, fc.name, self.session_gen)
                if result.job.status in (DONE, FAILED):
                    await self._deliver_result(result.job)
                return
            result = {
                "job": result.job.handle,
                "status": "started",
                "note": "Runs in the background. A [job update] message arrives when it is done.",
            }
        try:
            await session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(id=fc.id, name=fc.name, response=result)
                ]
            )
        except Exception:
            logger.exception("Could not send tool response for %s", fc.name)


@router.websocket("/api/live")
async def live_socket(ws: WebSocket):
    if not Default.LIVE_AGENT_ENABLED:
        await ws.close(code=CLOSE_DISABLED)
        return
    owner = await _owner(ws)
    if owner is None or not _origin_ok(ws):
        await ws.close(code=CLOSE_FORBIDDEN)
        return
    await ws.accept()
    bridge = _Bridge(ws, owner)
    unsubscribe = bridge.jobs.subscribe(owner, bridge.on_job)
    reader = asyncio.create_task(bridge.read_browser())
    jobs_task = asyncio.create_task(bridge.pump_jobs())
    # Show jobs from earlier calls in the tray.
    for job in bridge.jobs.list(owner):
        await bridge.send({"type": "job", "job": job.public()})
    wants_offline = ws.query_params.get("mode") == "offline"
    try:
        if Default.LIVE_AGENT_OFFLINE or wants_offline:
            await bridge.run_offline()
        else:
            try:
                await bridge.run_live()
            except Exception as exc:
                logger.exception("Live session failed")
                if not bridge.closed:
                    await bridge.send(
                        {
                            "type": "error",
                            "message": "Could not reach Gemini Live. Switched to typed offline mode.",
                        }
                    )
                    await bridge.run_offline(str(exc)[:200])
    finally:
        unsubscribe()
        bridge.closed = True
        reader.cancel()
        jobs_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass
