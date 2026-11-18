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
"""Live voice agent: job service, tool handling and offline agent (no network)."""

import asyncio
import threading
import time

import pytest
from google.genai import types

from services import live_agent
from services.live_agent import Deferred, LiveCall, ScriptedAgent, tool_declarations
from services.live_jobs import (
    DONE,
    FAILED,
    MAX_RUNNING_PER_OWNER,
    JobLimitError,
    LiveJobs,
    RunResult,
)

OWNER = "presenter@example.com"


def instant_runners(delay: float = 0.0, fail_on: str = ""):
    def run(job):
        if delay:
            time.sleep(delay)
        if fail_on and fail_on in job.prompt:
            raise RuntimeError("boom")
        ext = "mp4" if job.kind == "video" else "png"
        return RunResult(
            gcs_uri=f"gs://bucket/{job.handle.replace(' ', '_')}.{ext}",
            display_url=f"https://example.test/{job.id}.{ext}",
            mime_type="video/mp4" if job.kind == "video" else "image/png",
        )

    return {"image": run, "video": run}


# --- job service -----------------------------------------------------------


def test_handles_count_per_kind_and_owner():
    jobs = LiveJobs(instant_runners())
    a = jobs.submit(OWNER, "image", "fox", run_async=False)
    b = jobs.submit(OWNER, "video", "waves", run_async=False)
    c = jobs.submit(OWNER, "image", "owl", run_async=False)
    other = jobs.submit("someone@example.com", "image", "cat", run_async=False)
    assert [a.handle, b.handle, c.handle, other.handle] == [
        "image 1",
        "video 1",
        "image 2",
        "image 1",
    ]
    assert a.status == DONE and a.gcs_uri.startswith("gs://")
    assert [j.handle for j in jobs.list(OWNER)] == ["image 1", "video 1", "image 2"]


def test_jobs_run_in_parallel():
    jobs = LiveJobs(instant_runners(delay=0.4))
    start = time.time()
    for prompt in ("a", "b", "c"):
        jobs.submit(OWNER, "image", prompt)
    while any(j.status != DONE for j in jobs.list(OWNER)):
        assert time.time() - start < 3
        time.sleep(0.02)
    # Three 0.4 s jobs in well under 1.2 s means they overlapped.
    assert time.time() - start < 1.0


def test_running_cap():
    release = threading.Event()

    def slow(job):
        release.wait(2)
        return RunResult("", "data:,", "image/png")

    jobs = LiveJobs({"image": slow, "video": slow})
    for i in range(MAX_RUNNING_PER_OWNER):
        jobs.submit(OWNER, "image", f"p{i}")
    with pytest.raises(JobLimitError):
        jobs.submit(OWNER, "image", "one too many")
    release.set()


def test_failure_is_reported_not_raised():
    jobs = LiveJobs(instant_runners(fail_on="bad"))
    job = jobs.submit(OWNER, "image", "a bad prompt", run_async=False)
    assert job.status == FAILED
    assert job.error


def test_empty_prompt_and_unknown_kind_rejected():
    jobs = LiveJobs(instant_runners())
    with pytest.raises(ValueError):
        jobs.submit(OWNER, "image", "  ")
    with pytest.raises(ValueError):
        jobs.submit(OWNER, "music", "song")


def test_resolve_by_what_people_say():
    jobs = LiveJobs(instant_runners())
    img1 = jobs.submit(OWNER, "image", "fox", run_async=False)
    vid1 = jobs.submit(OWNER, "video", "waves", run_async=False)
    img2 = jobs.submit(OWNER, "image", "owl", run_async=False)
    assert jobs.resolve(OWNER, "image 1") is img1
    assert jobs.resolve(OWNER, "the video") is vid1
    assert jobs.resolve(OWNER, "", kind="image") is img2
    assert jobs.resolve(OWNER, "video 1") is vid1
    assert jobs.resolve(OWNER, img1.id) is img1
    assert jobs.resolve("nobody@example.com", "image 1") is None


def test_listeners_see_every_status_change():
    jobs = LiveJobs(instant_runners())
    seen = []
    unsubscribe = jobs.subscribe(OWNER, lambda j: seen.append(j.status))
    jobs.submit(OWNER, "image", "fox", run_async=False)
    unsubscribe()
    jobs.submit(OWNER, "image", "owl", run_async=False)
    assert seen == ["queued", "running", "done"]


def test_edit_links_to_its_source():
    jobs = LiveJobs(instant_runners())
    src = jobs.submit(OWNER, "image", "fox", run_async=False)
    edit = jobs.submit(OWNER, "image", "make it night", source=src, run_async=False)
    assert edit.is_edit and edit.source_job == "image 1"
    assert edit.source_uri == src.gcs_uri
    assert edit.public()["is_edit"] is True
    assert "owner" not in edit.public()


def test_default_runners_follow_mock_mode(monkeypatch):
    from services import live_jobs

    monkeypatch.setenv("GENMEDIA_MOCK_GENERATION", "true")
    monkeypatch.setenv("APP_ENV", "local")
    assert live_jobs.default_runners()["image"] is live_jobs._mock_image
    monkeypatch.setenv("GENMEDIA_MOCK_GENERATION", "false")
    assert live_jobs.default_runners()["image"] is live_jobs._real_image


# --- tool declarations ----------------------------------------------------


def test_tool_declarations_mark_job_tools_non_blocking():
    decls = {d.name: d for d in tool_declarations(True)[0].function_declarations}
    assert set(decls) == {
        "generate_image",
        "edit_image",
        "generate_video",
        "list_jobs",
        "show_job",
        "open_page",
        "download",
        "end_call",
    }
    for name in ("generate_image", "edit_image", "generate_video"):
        assert decls[name].behavior == types.Behavior.NON_BLOCKING
    assert decls["show_job"].behavior == types.Behavior.BLOCKING
    blocking_only = {
        d.name: d for d in tool_declarations(False)[0].function_declarations
    }
    assert blocking_only["generate_image"].behavior is None


# --- LiveCall ---------------------------------------------------------------


class FakeBrowser:
    """Answers every screen action like the real page would."""

    def __init__(self):
        self.sent = []
        self.call = None

    async def send(self, message):
        self.sent.append(message)
        if message.get("type") == "ui" and message["action"] not in (
            "compose",
            "end_call",
        ):
            asyncio.get_running_loop().call_soon(
                self.call.ui_result, message["id"], {"ok": True}
            )

    def actions(self):
        return [m["action"] for m in self.sent if m.get("type") == "ui"]


def make_call(runners=None):
    browser = FakeBrowser()
    call = LiveCall(OWNER, browser.send, LiveJobs(runners or instant_runners()))
    browser.call = call
    return call, browser


def run(coro):
    return asyncio.run(coro)


def wait_done(call):
    end = time.time() + 3
    while any(j.status not in (DONE, FAILED) for j in call.jobs.list(OWNER)):
        assert time.time() < end
        time.sleep(0.02)


def test_generate_image_defers_and_drives_the_screen():
    call, browser = make_call()

    async def go():
        return await call.run_tool(
            "generate_image", {"prompt": "a red fox", "aspect_ratio": "16:9"}
        )

    out = run(go())
    assert isinstance(out, Deferred)
    assert out.job.handle == "image 1" and out.job.aspect_ratio == "16:9"
    compose = [m for m in browser.sent if m.get("action") == "compose"][0]
    assert compose["args"]["page"] == "/nano-banana"
    assert compose["args"]["prompt"] == "a red fox"
    assert call.screen == "/nano-banana"
    wait_done(call)
    result = LiveCall.job_result(out.job)
    assert result["status"] == "done" and result["job"] == "image 1"


def test_edit_waits_for_a_finished_image():
    release = threading.Event()

    def slow(job):
        release.wait(2)
        return RunResult("gs://b/x.png", "https://example.test/x.png", "image/png")

    call, _ = make_call({"image": slow, "video": slow})

    async def go():
        await call.run_tool("generate_image", {"prompt": "fox"})
        early = await call.run_tool("edit_image", {"instruction": "night"})
        release.set()
        return early

    early = run(go())
    assert "still" in early["error"]
    wait_done(call)
    out = run(
        call.run_tool(
            "edit_image", {"instruction": "make it night", "image": "image 1"}
        )
    )
    assert isinstance(out, Deferred)
    assert out.job.source_job == "image 1" and out.job.handle == "image 2"


def test_edit_without_any_image():
    call, _ = make_call()
    out = run(call.run_tool("edit_image", {"instruction": "night"}))
    assert "no image" in out["error"].lower()


def test_video_from_image_and_screen_tools():
    call, browser = make_call()
    run(call.run_tool("generate_image", {"prompt": "fox"}))
    wait_done(call)

    async def go():
        video = await call.run_tool(
            "generate_video", {"prompt": "fox runs", "from_image": "image 1"}
        )
        shown = await call.run_tool("show_job", {"job": "image 1"})
        opened = await call.run_tool("open_page", {"page": "Library"})
        bad = await call.run_tool("open_page", {"page": "settings"})
        dl = await call.run_tool("download", {"job": "image 1"})
        listed = await call.run_tool("list_jobs", {})
        return video, shown, opened, bad, dl, listed

    video, shown, opened, bad, dl, listed = run(go())
    assert isinstance(video, Deferred) and video.job.source_job == "image 1"
    assert shown["shown"] is True and shown["job"] == "image 1"
    assert opened["ok"] is True and call.screen == "/library_v2"
    assert "No page" in bad["error"]
    assert dl["downloaded"] == "image 1"
    assert [j["job"] for j in listed["jobs"]] == ["image 1", "video 1"]
    assert "download" in browser.actions() and "show_job" in browser.actions()


def test_download_needs_a_finished_job():
    release = threading.Event()

    def slow(job):
        release.wait(2)
        return RunResult("", "data:,", "image/png")

    call, _ = make_call({"image": slow, "video": slow})

    async def go():
        await call.run_tool("generate_image", {"prompt": "fox"})
        return await call.run_tool("download", {})

    out = run(go())
    release.set()
    assert "not finished" in out["error"]


def test_ui_timeout_does_not_hang(monkeypatch):
    monkeypatch.setattr(live_agent, "UI_TIMEOUT_S", 0.05)

    async def silent(message):
        return None

    call = LiveCall(OWNER, silent, LiveJobs(instant_runners()))
    out = run(call.run_tool("open_page", {"page": "video"}))
    assert out["ok"] is False


def test_unknown_tool_and_bad_args():
    call, _ = make_call()
    assert "Unknown tool" in run(call.run_tool("delete_everything", {}))["error"]
    assert "Bad arguments" in run(call.run_tool("open_page", {"nope": 1}))["error"]


def test_job_limit_becomes_a_spoken_error():
    release = threading.Event()

    def slow(job):
        release.wait(2)
        return RunResult("", "data:,", "image/png")

    call, _ = make_call({"image": slow, "video": slow})

    async def go():
        for i in range(MAX_RUNNING_PER_OWNER):
            await call.run_tool("generate_image", {"prompt": f"p{i}"})
        return await call.run_tool("generate_image", {"prompt": "extra"})

    out = run(go())
    release.set()
    assert "already running" in out["error"]


# --- offline agent ----------------------------------------------------------


def test_scripted_agent_runs_the_demo():
    call, browser = make_call()
    lines = []

    async def say(text):
        lines.append(text)

    agent = ScriptedAgent(call, say)

    async def go():
        await agent.handle("Make an image of a red fox in snow")
        await agent.handle("while that runs, a video of waves at sunset")
        await asyncio.sleep(0.1)
        await agent.handle("show image 1")
        await agent.handle("edit it so it is night with northern lights")
        await asyncio.sleep(0.1)
        await agent.handle("download image 2")
        await agent.handle("bye")

    run(go())
    handles = [j.handle for j in call.jobs.list(OWNER)]
    assert handles == ["image 1", "video 1", "image 2"]
    assert call.jobs.resolve(OWNER, "image 1").prompt == "a red fox in snow"
    assert call.jobs.resolve(OWNER, "image 2").source_job == "image 1"
    assert "Starting the image: image 1." in lines
    assert any(line.startswith("Downloading image 2") for line in lines)
    assert call.ended is True


# --- WebSocket route (offline agent, no model) ------------------------------


def test_websocket_offline_flow(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import live_router

    jobs = LiveJobs(instant_runners(delay=0.05))
    monkeypatch.setattr(live_router, "get_live_jobs", lambda: jobs)
    monkeypatch.setattr(live_router, "_owner", _fake_owner)
    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_OFFLINE", True)

    app = FastAPI()
    app.include_router(live_router.router)
    with TestClient(app).websocket_connect("/api/live") as ws:
        assert ws.receive_json() == {"type": "status", "state": "offline", "detail": ""}
        ws.receive_json()  # offline greeting
        ws.send_json({"type": "screen", "path": "/home"})
        ws.send_json({"type": "text", "text": "image of a red fox"})
        seen = []
        for _ in range(30):
            message = ws.receive_json()
            seen.append(message)
            if message["type"] == "ui" and message["action"] == "compose":
                assert message["args"]["prompt"] == "a red fox"
            if message["type"] == "transcript" and "is ready" in message["text"]:
                break
        kinds = [m["type"] for m in seen]
        assert "ui" in kinds and "job" in kinds
        done = [
            m["job"]
            for m in seen
            if m["type"] == "job" and m["job"]["status"] == "done"
        ]
        assert done and done[0]["handle"] == "image 1"
        ws.send_json({"type": "hangup"})


def test_websocket_rejects_when_disabled_or_unauthorised(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from routers import live_router

    app = FastAPI()
    app.include_router(live_router.router)
    client = TestClient(app)

    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_ENABLED", False)
    with pytest.raises(WebSocketDisconnect) as off:
        with client.websocket_connect("/api/live"):
            pass
    assert off.value.code == live_router.CLOSE_DISABLED

    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_ENABLED", True)

    async def nobody(ws):
        return None

    monkeypatch.setattr(live_router, "_owner", nobody)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("/api/live"):
            pass
    assert denied.value.code == live_router.CLOSE_FORBIDDEN

    monkeypatch.setattr(live_router, "_owner", _fake_owner)
    with pytest.raises(WebSocketDisconnect) as cross_site:
        with client.websocket_connect(
            "/api/live", headers={"origin": "https://evil.example"}
        ):
            pass
    assert cross_site.value.code == live_router.CLOSE_FORBIDDEN


async def _fake_owner(ws):
    return OWNER


# --- WebSocket route against a fake Gemini Live session --------------------


class _FakeSession:
    """Plays a scripted model turn, then idles like a quiet live session."""

    def __init__(self, script):
        self.script = list(script)
        self.tool_responses = []
        self.audio_chunks = 0
        self.texts = []

    async def receive(self):
        while self.script:
            yield self.script.pop(0)
        await asyncio.sleep(3600)  # idle until cancelled
        yield None  # pragma: no cover

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def send_realtime_input(self, audio=None, audio_stream_end=None, text=None):
        if audio is not None:
            self.audio_chunks += 1

    async def send_client_content(self, turns=None, turn_complete=None):
        self.texts.append(turns.parts[0].text)


class _FakeLive:
    def __init__(self, session):
        self.session = session
        self.configs = []

    def connect(self, model, config):
        live = self

        class _Ctx:
            async def __aenter__(self_inner):
                live.configs.append(config)
                return live.session

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def test_websocket_live_flow_with_fake_session(monkeypatch):
    import base64

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import live_router

    script = [
        types.LiveServerMessage(
            session_resumption_update=types.LiveServerSessionResumptionUpdate(
                new_handle="h1", resumable=True
            )
        ),
        types.LiveServerMessage(
            tool_call=types.LiveServerToolCall(
                function_calls=[
                    types.FunctionCall(
                        id="call-1", name="generate_image", args={"prompt": "a red fox"}
                    )
                ]
            )
        ),
        types.LiveServerMessage(
            server_content=types.LiveServerContent(
                model_turn=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=b"\x01\x00" * 8, mime_type="audio/pcm"
                            )
                        )
                    ],
                ),
                output_transcription=types.Transcription(text="On it."),
                turn_complete=True,
            )
        ),
    ]
    session = _FakeSession(script)
    fake_live = _FakeLive(session)

    class _Client:
        class aio:  # noqa: N801
            live = fake_live

    jobs = LiveJobs(instant_runners(delay=0.1))
    monkeypatch.setattr(live_router, "get_live_jobs", lambda: jobs)
    monkeypatch.setattr(live_router, "_owner", _fake_owner)
    monkeypatch.setattr(live_router, "_genai_client", lambda: (_Client(), "fake-live"))
    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_ENABLED", True)
    monkeypatch.setattr(live_router.Default, "LIVE_AGENT_OFFLINE", False)
    monkeypatch.setattr(live_router.Default, "LIVE_ASYNC_TOOLS", True)

    app = FastAPI()
    app.include_router(live_router.router)
    with TestClient(app).websocket_connect("/api/live") as ws:
        ws.send_json(
            {"type": "audio", "data": base64.b64encode(b"\x00\x00" * 160).decode()}
        )
        seen = []
        for _ in range(40):
            message = ws.receive_json()
            seen.append(message)
            if message["type"] == "job" and message["job"]["status"] == "done":
                break
        kinds = [m["type"] for m in seen]
        assert {"status", "audio", "transcript", "turn_complete", "ui", "job"} <= set(
            kinds
        )
        for _ in range(50):
            if session.tool_responses:
                break
            time.sleep(0.02)
        ws.send_json({"type": "hangup"})

    # The job result went back as the answer to the original call, at the next pause.
    assert len(session.tool_responses) == 1
    response = session.tool_responses[0]
    assert response.id == "call-1" and response.name == "generate_image"
    assert response.scheduling == types.FunctionResponseScheduling.WHEN_IDLE
    assert response.response["status"] == "done"
    assert session.audio_chunks >= 1
    config = fake_live.configs[0]
    assert config.system_instruction and config.tools


def test_video_jobs_open_video_studio_on_omni():
    from config.video_studio_models import DEFAULT_STUDIO_MODEL_ID
    from services.live_agent import page_params

    jobs = LiveJobs(instant_runners())
    img = jobs.submit(OWNER, "image", "fox", run_async=False)
    vid = jobs.submit(OWNER, "video", "fox runs", source=img, run_async=False)
    assert page_params(img) == {}
    assert page_params(vid) == {
        "veo_model": DEFAULT_STUDIO_MODEL_ID,
        "image_path": img.gcs_uri,
    }


def test_navigation_handler_only_allows_known_routes_and_params(monkeypatch):
    from components.live_agent import live_agent as bridge

    calls = []
    monkeypatch.setattr(
        bridge.me,
        "navigate",
        lambda url, query_params=None: calls.append((url, query_params)),
    )

    def fire(value):
        list(bridge.on_live_action(type("E", (), {"value": value})()))

    fire(
        {
            "action": "navigate",
            "page": "/veo",
            "params": {"veo_model": "3.1-fast", "evil": "x"},
        }
    )
    fire({"action": "navigate", "page": "https://evil.example"})
    fire({"action": "navigate", "page": "/home"})
    assert calls == [("/veo", {"veo_model": "3.1-fast"}), ("/home", None)]
