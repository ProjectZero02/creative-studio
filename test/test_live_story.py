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
"""Live agent Story Studio tools (offline mock backend, no cloud calls)."""

import asyncio
import time

import pytest

from services import live_story, story_service, story_sets, story_store
from services.live_agent import Deferred, LiveCall
from services.live_jobs import DONE, FAILED, LiveJobs

OWNER = "director@example.com"


class _FakeBrowser:
    def __init__(self):
        self.sent = []
        self.call = None

    async def send(self, message):
        self.sent.append(message)
        if message.get("type") == "ui" and message["action"] in (
            "navigate",
            "show_job",
        ):
            asyncio.get_running_loop().call_soon(
                self.call.ui_result, message["id"], {"ok": True}
            )


class _FastMock(story_service.MockStoryBackend):
    """MockStoryBackend without delays or ffmpeg media encoding."""

    def __init__(self):
        super().__init__(speed=0)

    def generate_frame(self, story, index, reference_uri):
        return f"local://{story.id}/frame{index}.png"

    def generate_clip(self, story, index, start_frame_uri):
        return f"local://{story.id}/clip{index}.mp4"

    def last_frame(self, story, clip_uri, index):
        return f"local://{story.id}/last{index}.png"

    def generate_music(self, story, prompt, seconds):
        return "local://m.wav"

    def generate_voiceover(self, story, index, text, style="narrator"):
        return f"local://v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        return "local://film.mp4"


@pytest.fixture
def story_env(tmp_path, monkeypatch):
    """Isolate Story Studio stores to tmp_path and use a fast mock backend."""
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    set_store = story_sets.LocalSetStore(str(tmp_path / "sets.json"))
    story_store.set_store(store)
    story_sets.set_set_store(set_store)
    story_service.set_backend(_FastMock())
    monkeypatch.setattr(live_story, "POLL_STEP_S", 0.05)
    yield store
    story_service.set_backend(None)
    story_store.set_store(None)
    story_sets.set_set_store(None)


def _make_call():
    browser = _FakeBrowser()
    jobs = LiveJobs({"story": live_story.run_story_job})
    call = LiveCall(OWNER, browser.send, jobs)
    browser.call = call
    return call, browser


def _wait_done(call: LiveCall, timeout: float = 30.0):
    end = time.time() + timeout
    while any(j.status not in (DONE, FAILED) for j in call.jobs.list(OWNER)):
        assert time.time() < end, "Story job did not finish in time"
        time.sleep(0.05)


def test_create_story_merges_inferred_and_explicit_settings(story_env):
    story = live_story.create_story_record(
        OWNER,
        "A vertical anime story about a baker in Tokyo, 30 seconds",
        aspect_ratio="16:9",
        style="3d",
        language="French",
    )
    assert story.aspect_ratio == "16:9"  # explicit overrides inferred vertical
    assert story.style == "3d"  # explicit overrides inferred anime
    assert story.language == "French"
    assert story.step == "scenario"
    assert story.approved is False


def test_create_story_rejects_short_idea(story_env):
    call, _ = _make_call()
    out = asyncio.run(call.run_tool("create_story", {"idea": "short"}))
    assert "error" in out
    assert "idea" in out["error"].lower()


def test_story_lifecycle_step_by_step_to_film(story_env):
    call, browser = _make_call()

    # 1. Create story -> writes scenario
    created = asyncio.run(
        call.run_tool(
            "create_story",
            {
                "idea": "A red fox explores a lantern-lit forest at dusk",
                "length": "18 seconds",
            },
        )
    )
    assert isinstance(created, Deferred)
    assert created.job.handle == "story 1"
    _wait_done(call)
    assert created.job.status == DONE, created.job.error
    res1 = LiveCall.job_result(created.job)
    assert res1["status"] == "done" and res1["story_id"]

    status1 = asyncio.run(call.run_tool("story_status", {}))
    assert status1["scene_count"] >= 3
    assert status1["approved"] is False
    assert status1["has_film"] is False
    assert status1["next_action"] == "approve"
    assert status1["job"] is not None

    # Premature render fails with plain error
    early_render = asyncio.run(call.run_tool("render_film", {}))
    assert "Approve the scenario first" in early_render["error"]

    # 2. Continue -> approve scenario
    approved = asyncio.run(call.run_tool("continue_story", {}))
    assert isinstance(approved, dict) and approved["approved"] is True
    assert approved["step"] == "set"

    # Render before storyboard frames fails with the exact plain message
    no_frames = asyncio.run(call.run_tool("render_film", {}))
    assert no_frames["error"] == "Every scene needs a storyboard frame first."

    # 3. Continue -> build set
    set_step = asyncio.run(call.run_tool("continue_story", {}))
    assert isinstance(set_step, Deferred)
    _wait_done(call)
    assert set_step.job.status == DONE, set_step.job.error

    status2 = asyncio.run(call.run_tool("story_status", {}))
    assert status2["has_set"] is True
    assert status2["next_action"] == "storyboard"

    # 4. Continue -> paint storyboard
    board_step = asyncio.run(call.run_tool("continue_story", {}))
    assert isinstance(board_step, Deferred)
    _wait_done(call)
    assert board_step.job.status == DONE, board_step.job.error

    status3 = asyncio.run(call.run_tool("story_status", {}))
    assert status3["frames_ready"] == status3["scene_count"]
    assert status3["next_action"] == "video"

    # 5. Open story by title at storyboard step
    opened = asyncio.run(
        call.run_tool("open_story", {"story": status3["title"], "step": "storyboard"})
    )
    assert opened["ok"] is True
    assert opened["url"] == f"/story?id={status3['story_id']}&step=storyboard"
    nav = [m for m in browser.sent if m.get("action") == "navigate"][-1]
    assert nav["args"]["page"] == "/story"
    assert nav["args"]["params"] == {"id": status3["story_id"], "step": "storyboard"}

    # 6. Continue (or render_film) -> render film
    render_step = asyncio.run(call.run_tool("continue_story", {}))
    assert isinstance(render_step, Deferred)
    _wait_done(call, timeout=60.0)
    assert render_step.job.status == DONE, render_step.job.error
    film_res = LiveCall.job_result(render_step.job)
    assert film_res["has_film"] is True
    assert film_res.get("film_url")

    final_status = asyncio.run(call.run_tool("story_status", {}))
    assert final_status["has_film"] is True
    assert final_status["next_action"] == "done"

    # Calling continue_story once film exists is a clean no-op
    again = asyncio.run(call.run_tool("continue_story", {}))
    assert isinstance(again, dict) and again["has_film"] is True


def test_story_tools_report_plain_errors_when_no_story(story_env):
    call, _ = _make_call()
    for tool in ("continue_story", "render_film", "story_status", "open_story"):
        out = asyncio.run(call.run_tool(tool, {}))
        assert "no story" in out["error"].lower()


def test_scripted_agent_drives_story_offline(story_env):
    from services.live_agent import ScriptedAgent

    call, _ = _make_call()
    lines = []

    async def say(text):
        lines.append(text)

    agent = ScriptedAgent(call, say)
    asyncio.run(agent.handle("make a story about a tiny lighthouse on Mars"))
    _wait_done(call)
    asyncio.run(agent.handle("story status"))
    assert any("approve" in line for line in lines)

    asyncio.run(agent.handle("next step"))  # approve
    assert any("approved" in line.lower() for line in lines)

    asyncio.run(agent.handle("render the film"))  # too early
    assert any("storyboard frame" in line.lower() for line in lines)

    asyncio.run(agent.handle("next step"))  # build set
    _wait_done(call)
    asyncio.run(agent.handle("next step"))  # paint storyboard
    _wait_done(call)
    asyncio.run(agent.handle("render the film"))  # render film
    _wait_done(call)
    asyncio.run(agent.handle("story status"))
    assert any("film ready" in line for line in lines)
