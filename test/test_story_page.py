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

"""Story Studio page handlers that don't need a browser."""

import json

import pytest

import pages.story_studio as page
from services import story_store
from services.story_models import Scene, Story
from state.story_state import StoryState

OWNER = "alice@example.com"


@pytest.fixture
def state(monkeypatch, tmp_path):
    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    monkeypatch.setattr(page, "_owner", lambda: OWNER)
    store = story_store.LocalStoryStore(path=str(tmp_path / "stories.json"))
    monkeypatch.setattr(page, "get_store", lambda: store)
    monkeypatch.setattr(page, "_load_set", lambda story, force=False: None)
    return st, store


def _story(store, frames: int) -> Story:
    story = Story(owner=OWNER, scenes=[Scene(visual=f"v{i}") for i in range(4)])
    for sc in story.scenes[:frames]:
        sc.frame_uri = "gs://b/f.png"
    return store.save(story, OWNER)


def _watching(st, story, kind="storyboard"):
    st.story_id = story.id
    st.story_json = json.dumps(story.to_dict())
    st.job_id = "gone"
    st.job_kind = kind
    st.job_running = True
    st.job_json = json.dumps({"kind": kind, "status": "running", "tasks": []})


def test_missing_job_reloads_the_story_and_stops_when_done(state, monkeypatch):
    st, store = state
    story = _story(store, frames=1)
    _watching(st, story)
    monkeypatch.setattr(page.story_jobs, "job_snapshot", lambda job_id, owner: None)

    # The job ran on another instance and finished: every frame is stored.
    def finish(s):
        for sc in s.scenes:
            sc.frame_uri = "gs://b/f.png"

    stored = store.get(story.id, OWNER)
    finish(stored)
    store.save(stored, OWNER)
    page.on_tick(None)
    shown = Story.from_dict(json.loads(st.story_json))
    assert all(sc.frame_uri for sc in shown.scenes)
    assert st.job_running is False and st.job_json == ""


def test_missing_job_keeps_checking_while_outputs_are_missing(state, monkeypatch):
    st, store = state
    _watching(st, _story(store, frames=1))
    monkeypatch.setattr(page.story_jobs, "job_snapshot", lambda job_id, owner: None)
    page.on_tick(None)
    assert st.job_running is True and st.job_misses == 1
    assert st.job_json == ""  # no stale "running" tasks hiding stored frames
    st.job_misses = page.JOB_MISS_LIMIT - 1
    page.on_tick(None)
    assert st.job_running is False  # gives up after the limit
