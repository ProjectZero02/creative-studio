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
"""The Home box's type controls (services/studio_options.py) and direct jobs."""

import pytest

from services import studio_chat, studio_options
from services.live_jobs import DONE, JobLimitError, LiveJobs, RunResult

OWNER = "controls@example.com"


def test_every_kind_has_fields_with_valid_defaults():
    for kind in studio_options.KINDS:
        fields = studio_options.fields(kind)
        assert fields, kind
        for f in fields:
            values = {o["value"] for o in f["options"]}
            assert f["default"] in values, (kind, f["name"])
            for model, choice in (f.get("by_model") or {}).items():
                assert choice["default"] in {o["value"] for o in choice["options"]}, (
                    kind,
                    f["name"],
                    model,
                )


def test_clean_keeps_supported_values_and_replaces_the_rest():
    video = studio_options.fields("video")
    model = video[0]["default"]
    durations = video[2]["by_model"][model]["options"]
    pick = durations[0]["value"]
    out = studio_options.clean(
        "video", {"model": model, "duration": pick, "aspect": "7:3", "x": "y"}
    )
    assert out["duration"] == pick
    assert out["aspect"] == video[1]["by_model"][model]["default"]
    assert "x" not in out
    assert studio_options.clean("video", {"model": "nope"})["model"] == model
    assert (
        studio_options.clean("music", "not a dict")["model"]
        == studio_options.fields("music")[0]["default"]
    )


def test_summary_names_only_what_matters():
    voice = studio_options.clean("voice", {"voice": "Puck"})
    assert studio_options.summary("voice", voice) == "Puck"
    voice = studio_options.clean("voice", {"voice": "Puck", "pace": "fast"})
    assert studio_options.summary("voice", voice) == "Puck · Fast"


def instant():
    def run(job):
        return RunResult(
            f"gs://b/{job.id}.png", f"https://example.test/{job.id}", "image/png"
        )

    return {k: run for k in ("image", "video", "music", "voice")}


@pytest.fixture
def jobs(monkeypatch):
    registry = LiveJobs(instant())
    monkeypatch.setattr(studio_chat, "get_live_jobs", lambda: registry)
    studio_chat.reset(OWNER)
    yield registry
    studio_chat.reset(OWNER)


def test_make_starts_a_job_with_the_settings_and_remembers_it(jobs):
    out = studio_chat.make(OWNER, "image", "a red fox", {"aspect": "16:9"}, jobs=jobs)
    job = jobs.list(OWNER)[0]
    assert out["job"]["handle"] == "image 1" and job.aspect_ratio == "16:9"
    assert job.params["settings"]["aspect"] == "16:9"
    assert out["reply"] == "Making image 1."
    session = studio_chat.session_for(OWNER)
    assert job.id in session.job_ids
    assert [c.role for c in session.history] == ["user", "model"]


def test_make_animates_a_finished_picture(jobs):
    studio_chat.make(OWNER, "image", "a red fox", jobs=jobs)
    for _ in range(200):
        if jobs.list(OWNER)[0].status == DONE:
            break
        import time

        time.sleep(0.01)
    out = studio_chat.make(OWNER, "video", "slow push in", {}, "image 1", jobs=jobs)
    video = jobs.list(OWNER)[-1]
    assert video.kind == "video" and video.source_job == "image 1"
    assert video.source_uri.startswith("gs://")
    assert out["reply"] == "Making video 1 from image 1."


@pytest.mark.parametrize(
    "kind,prompt,source",
    [("story", "x", ""), ("image", "   ", ""), ("video", "move", "image 9")],
)
def test_make_refuses_bad_requests(jobs, kind, prompt, source):
    with pytest.raises(ValueError):
        studio_chat.make(OWNER, kind, prompt, {}, source, jobs=jobs)


def test_job_route(monkeypatch, jobs):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import chat_router

    app = FastAPI()
    app.include_router(chat_router.router)
    client = TestClient(app)
    assert set(client.get("/api/chat/options").json()["kinds"]) == set(
        studio_options.KINDS
    )
    ok = client.post("/api/chat/job", json={"kind": "music", "prompt": "lo-fi beat"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["job"]["kind"] == "music"
    assert (
        client.post("/api/chat/job", json={"kind": "story", "prompt": "x"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/chat/job", content="x", headers={"content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/chat/job",
            json={"kind": "image", "prompt": "x"},
            headers={"origin": "https://evil.test"},
        ).status_code
        == 403
    )

    def full(*_a, **_k):
        raise JobLimitError("4 jobs are already running.")

    monkeypatch.setattr(studio_chat, "make", full)
    assert (
        client.post("/api/chat/job", json={"kind": "image", "prompt": "x"}).status_code
        == 429
    )


@pytest.fixture
def film_env(tmp_path, monkeypatch):
    """Story Studio on temp stores with the fast mock backend (as test_live_story)."""
    from test_live_story import _FastMock

    from services import live_story, story_service, story_sets, story_store

    story_store.set_store(story_store.LocalStoryStore(str(tmp_path / "stories.json")))
    story_sets.set_set_store(story_sets.LocalSetStore(str(tmp_path / "sets.json")))
    story_service.set_backend(_FastMock())
    monkeypatch.setattr(live_story, "POLL_STEP_S", 0.05)
    registry = LiveJobs({"story": live_story.run_story_job})
    monkeypatch.setattr(studio_chat, "get_live_jobs", lambda: registry)
    studio_chat.reset(OWNER)
    yield registry
    studio_chat.reset(OWNER)
    story_service.set_backend(None)
    story_store.set_store(None)
    story_sets.set_set_store(None)


def _wait(registry, timeout=30.0):
    import time

    end = time.time() + timeout
    while any(j.status not in (DONE, "failed") for j in registry.list(OWNER)):
        assert time.time() < end, "film step did not finish"
        time.sleep(0.05)


def test_film_writes_the_scenario_then_runs_the_next_step(film_env):
    out = studio_chat.make(
        OWNER, "film", "A red fox explores a lantern-lit forest at dusk", {"aspect": "9:16"}, jobs=film_env
    )
    assert out["job"]["kind"] == "story"
    story_id = out["job"]["params"]["story_id"]
    assert story_id and "scenario" in out["reply"]
    _wait(film_env)
    first = film_env.list(OWNER)[0]
    assert first.status == DONE, first.error
    # Next step approves the scenario and builds the set.
    nxt = studio_chat.film_next(OWNER, story_id, jobs=film_env)
    assert nxt["job"]["params"]["story_action"] == "set"
    _wait(film_env)
    from services import story_jobs

    story = story_jobs.get_store().get(story_id, OWNER)
    assert story.approved and story.set_id and story.aspect_ratio == "9:16"


def test_film_needs_a_real_idea(film_env):
    with pytest.raises(ValueError):
        studio_chat.make(OWNER, "film", "short", {}, jobs=film_env)
    with pytest.raises(ValueError):
        studio_chat.film_next(OWNER, "", jobs=film_env)
