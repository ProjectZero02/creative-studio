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
"""Story Studio v6: do only the work the film needs (docs/STORY_STUDIO_V6_PLAN.md)."""

import json
import threading
from types import SimpleNamespace

import pytest

import pages.story_studio as page
from services import story_jobs, story_store
from services.story_models import (
    Scene,
    Story,
    default_music_prompt,
    reachable_steps,
)
from state.story_state import StoryState
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401


@pytest.fixture
def page_env(monkeypatch, tmp_path):
    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    monkeypatch.setattr(page, "_owner", lambda: OWNER)
    store = story_store.LocalStoryStore(path=str(tmp_path / "stories.json"))
    story_store.set_store(store)
    monkeypatch.setattr(page, "get_store", lambda: store)
    monkeypatch.setattr(page, "_load_set", lambda story, force=False: None)
    yield st, store
    story_store.set_store(None)


def _film(store, **kw) -> Story:
    story = Story(
        owner=OWNER,
        approved=True,
        final_uri="gs://b/film.mp4",
        music_uri="gs://b/music.mp3",
        scenes=[
            Scene(narration="  A line from the AI. ", frame_uri="f", clip_uri="c"),
        ],
        **kw,
    )
    return store.save(story, OWNER)


def _open(st, story):
    st.story_id = story.id
    st.story_json = json.dumps(story.to_dict())


# --- M1: nothing finished is thrown away by a blur ----------------------


def test_blurring_the_music_prompt_keeps_the_film_and_music(page_env):
    st, store = page_env
    story = _film(store)
    _open(st, story)
    # The box shows the default prompt when none is stored.
    shown = default_music_prompt(story)
    page.on_music_prompt(SimpleNamespace(value=shown, key="x"))
    page.on_music_prompt(SimpleNamespace(value="", key="x"))
    got = store.get(story.id, OWNER)
    assert got.final_uri == "gs://b/film.mp4"
    assert got.music_uri == "gs://b/music.mp3"
    # A real change still clears the music.
    page.on_music_prompt(SimpleNamespace(value="Solo piano, slow", key="x"))
    got = store.get(story.id, OWNER)
    assert got.music_prompt == "Solo piano, slow" and got.music_uri == ""


def test_same_voice_keeps_the_film(page_env):
    st, store = page_env
    story = _film(store, voice_name="Kore")
    _open(st, story)
    page.on_voice(SimpleNamespace(value="Kore", key="x"))
    assert store.get(story.id, OWNER).final_uri


def test_blurring_a_line_with_stray_spaces_keeps_film_and_clip(page_env):
    st, store = page_env
    story = _film(store)
    _open(st, story)
    sid = story.scenes[0].id
    page.on_scene_narration(
        SimpleNamespace(value="A line from the AI.", key=f"n-{sid}")
    )
    got = store.get(story.id, OWNER)
    assert got.final_uri and got.scenes[0].clip_uri == "c"


def test_a_take_of_several_shots_opens_edit_and_export():
    # Two on-camera shots in one take: only the first has a frame.
    story = Story(
        approved=True,
        scenes=[
            Scene(narration="One.", spoken=True, frame_uri="f", duration=8),
            Scene(narration="Two.", spoken=True, duration=8),
        ],
    )
    assert story.continues_take(1)
    assert {"editor", "music", "video"} <= reachable_steps(story)


def test_one_heavy_job_per_story(jobs_env):
    store, backend = jobs_env
    story = store.save(
        Story(owner=OWNER, scenes=[Scene(visual="v", frame_uri="f")]), OWNER
    )
    gate = threading.Event()
    real = backend.generate_clip

    def slow(*a, **kw):
        gate.wait(5)
        return real(*a, **kw)

    backend.generate_clip = slow
    first = story_jobs.start_scene_clips(story.id, OWNER, [0])
    with pytest.raises(story_jobs.JobBusyError):
        story_jobs.start_video(story.id, OWNER)
    # Nothing was changed by the refused start.
    assert store.get(story.id, OWNER).scenes[0].frame_uri == "f"
    gate.set()
    _run(first)
    # Free again once the first job is done.
    _run(story_jobs.start_scene_clips(story.id, OWNER, [0]))


def test_export_retry_keeps_its_options(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        story_jobs,
        "start_export",
        lambda sid, owner, options=None: seen.setdefault("o", options),
    )
    job = story_jobs.Job(
        id="j1",
        owner=OWNER,
        story_id="s1",
        kind="export",
        status=story_jobs.FAILED,
        params={"options": {"size": "1080p", "format": "webm"}},
    )
    story_jobs._jobs[job.id] = job
    try:
        story_jobs.retry(job.id, OWNER)
    finally:
        story_jobs._jobs.pop(job.id, None)
    assert seen["o"] == {"size": "1080p", "format": "webm"}
