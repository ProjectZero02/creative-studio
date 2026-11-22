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
"""The Home chat (services/studio_chat.py, routers/chat_router.py)."""

import time
from types import SimpleNamespace

import pytest
from google.genai import types

from services import studio_chat
from services.live_jobs import DONE, LiveJobs, RunResult

OWNER = "chat@example.com"


def instant():
    def run(job):
        ext = {"video": "mp4", "music": "wav", "voice": "wav"}.get(job.kind, "png")
        return RunResult(f"gs://b/{job.id}.{ext}", f"https://example.test/{job.id}.{ext}", "x/y")

    return {k: run for k in ("image", "video", "music", "voice")}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    jobs = LiveJobs(instant())
    monkeypatch.setattr(studio_chat, "get_live_jobs", lambda: jobs)
    studio_chat.reset(OWNER)
    yield jobs
    studio_chat.reset(OWNER)


class FakeModels:
    """Answers with the queued contents, one per generate_content call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def generate_content(self, model, contents, config):
        self.seen.append((model, list(contents), config))
        content = self.replies.pop(0)
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def call(name, **args):
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def text(value):
    return types.Content(role="model", parts=[types.Part.from_text(text=value)])


def wait_done(jobs, owner, n, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        done = [j for j in jobs.list(owner) if j.status == DONE]
        if len(done) >= n:
            return done
        time.sleep(0.02)
    raise AssertionError("jobs did not finish")


def test_tools_are_the_chat_subset():
    names = {d.name for d in studio_chat.chat_tools()[0].function_declarations}
    assert names == set(studio_chat.CHAT_TOOLS)
    assert "open_page" not in names and "download" not in names


def test_model_starts_jobs_and_replies(fresh):
    models = FakeModels(
        [
            call("generate_image", prompt="a red fox in deep snow, golden hour"),
            text("Making image 1: a red fox in deep snow."),
        ]
    )
    out = studio_chat.send(OWNER, "a fox in snow", (SimpleNamespace(models=models), "m"))
    assert out["reply"] == "Making image 1: a red fox in deep snow."
    assert [j["handle"] for j in out["jobs"]] == ["image 1"]
    assert out["offline"] is False
    # The tool answer went back to the model before its final reply.
    second_contents = models.seen[1][1]
    response = second_contents[-1].parts[0].function_response
    assert response.name == "generate_image"
    assert response.response["status"] == "started"
    wait_done(fresh, OWNER, 1)
    listed = studio_chat.chat_jobs(OWNER)
    assert listed[0]["status"] == DONE and listed[0]["display_url"].startswith("https://")


def test_text_only_answer_starts_nothing():
    models = FakeModels([text("Try: 'Fresh mornings, made simple.'")])
    out = studio_chat.send(OWNER, "a tagline for a coffee brand", (SimpleNamespace(models=models), "m"))
    assert out["jobs"] == [] and "Fresh mornings" in out["reply"]


def test_history_carries_into_the_next_message():
    models = FakeModels([text("Hi!"), text("Sure.")])
    client = (SimpleNamespace(models=models), "m")
    studio_chat.send(OWNER, "hello", client)
    studio_chat.send(OWNER, "and again", client)
    roles = [c.role for c in models.seen[1][1]]
    assert roles == ["user", "model", "user"]


def test_model_error_is_said_not_raised():
    class Broken:
        def generate_content(self, **_kw):
            raise RuntimeError("quota exceeded")

    out = studio_chat.send(OWNER, "a fox", (SimpleNamespace(models=Broken()), "m"))
    assert out["jobs"] == [] and "couldn't reach Gemini" in out["reply"]


def test_offline_agent_handles_typed_requests(fresh):
    out = studio_chat.send(OWNER, "image of a red fox", None)
    assert out["offline"] is True
    assert [j["handle"] for j in out["jobs"]] == ["image 1"]
    assert "image 1" in out["reply"]
    wait_done(fresh, OWNER, 1)


def test_empty_message_does_nothing():
    assert studio_chat.send(OWNER, "   ", None) == {"reply": "", "jobs": [], "offline": False}


def test_api_routes(monkeypatch, fresh):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import chat_router

    monkeypatch.setattr(studio_chat, "_default_client", lambda: None)
    app = FastAPI()

    @app.middleware("http")
    async def who(request, call_next):
        request.scope["MESOP_USER_EMAIL"] = OWNER
        return await call_next(request)

    app.include_router(chat_router.router)
    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "video of waves at sunset"})
    assert r.status_code == 200 and r.json()["jobs"][0]["kind"] == "video"
    wait_done(fresh, OWNER, 1)
    assert client.get("/api/chat/jobs").json()["jobs"][0]["status"] == DONE
    # Other sites can't post, and the body must be JSON.
    assert client.post("/api/chat", json={"message": "x"}, headers={"origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/chat", content="message=x", headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/api/chat/reset").json() == {"ok": True}
    assert client.get("/api/chat/jobs").json() == {"jobs": []}


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def fake_store(owner, raw, mime, data_url):
    return "gs://b/upload.png", "https://example.test/upload.png"


def test_attached_picture_becomes_the_next_image(fresh):
    job = studio_chat.attach(OWNER, PNG, "cat.png", store=fake_store)
    assert job["handle"] == "image 1"
    assert job["status"] == DONE
    assert job["gcs_uri"] == "gs://b/upload.png"
    # The agent can now edit it by its handle.
    edited = fresh.submit(OWNER, "image", "make it blue", source=fresh.resolve(OWNER, "image 1"), run_async=False)
    assert edited.source_job == "image 1"
    assert edited.source_uri == "gs://b/upload.png"
    assert edited.handle == "image 2"


@pytest.mark.parametrize(
    "data",
    ["", "hello", "data:text/plain;base64,aGk=", "data:image/gif;base64,R0lGOD", "data:image/png;base64,***"],
)
def test_attach_refuses_what_is_not_a_picture(data):
    with pytest.raises(ValueError):
        studio_chat.attach(OWNER, data, store=fake_store)


def test_attach_refuses_big_files(monkeypatch):
    monkeypatch.setattr(studio_chat, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ValueError):
        studio_chat.attach(OWNER, PNG, store=fake_store)


def test_upload_route(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import chat_router

    monkeypatch.setattr(studio_chat, "_store_upload", fake_store)
    app = FastAPI()
    app.include_router(chat_router.router)
    client = TestClient(app)
    ok = client.post("/api/chat/upload", json={"data": PNG, "name": "a.png"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["job"]["kind"] == "image"
    bad = client.post("/api/chat/upload", json={"data": "nope"})
    assert bad.status_code == 400
    wrong_type = client.post("/api/chat/upload", content="x", headers={"content-type": "text/plain"})
    assert wrong_type.status_code == 415
