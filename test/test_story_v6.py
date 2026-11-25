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


# --- M2: render only what changed ------------------------------------------


class _CountingMock(_FastMock):
    def __init__(self):
        super().__init__()
        self.voiced = []
        self.stitched = 0
        self.saved = []

    def generate_voiceover(self, story, index, text, style="narrator"):
        self.voiced.append((story.language, index))
        return f"local://{story.language}-v{index}-{len(self.voiced)}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        self.stitched += 1
        return f"local://film-{story.language}-{self.stitched}.mp4"

    def save_to_library(self, story, final_uri, owner):
        self.saved.append(story.library_id)
        return story.library_id or f"item-{len(self.saved)}"


@pytest.fixture
def counting(jobs_env):
    store, _ = jobs_env
    backend = _CountingMock()
    from services import story_service

    story_service.set_backend(backend)
    yield store, backend


def _narrated(store, **kw) -> Story:
    scenes = [
        Scene(narration="The fox runs.", frame_uri="f0", duration=6),
        Scene(narration="The fox stops.", frame_uri="f1", duration=6),
    ]
    return store.save(
        Story(owner=OWNER, approved=True, music_on=False, scenes=scenes, **kw), OWNER
    )


def _chain(job):
    first = done = _run(job)
    tasks = list(done.tasks)
    while done.params.get("next_job"):
        done = _run(story_jobs.get_job(done.params["next_job"], OWNER))
        tasks += done.tasks
    return first, tasks


def test_a_second_render_reuses_every_voice_line(counting):
    store, backend = counting
    story = _narrated(store)
    first = _run(story_jobs.start_video(story.id, OWNER))
    assert first.status == "done"
    assert len(backend.voiced) == 2
    again = _run(story_jobs.start_video(story.id, OWNER))
    assert again.status == "done"
    assert len(backend.voiced) == 2  # nothing voiced again
    kinds = [t.kind for t in again.tasks]
    assert "voice" not in kinds
    assert [t.label for t in again.tasks if t.kind == "voice"] == []  # no fit step


def test_only_a_changed_line_is_voiced_again(counting):
    store, backend = counting
    story = _narrated(store)
    _run(story_jobs.start_video(story.id, OWNER))
    story_jobs.mutate_story(
        story.id, OWNER, lambda s: setattr(s.scenes[1], "narration", "It waits.")
    )
    again = _run(story_jobs.start_video(story.id, OWNER))
    voiced = [t.scene_index for t in again.tasks if t.label.endswith("voiceover")]
    assert voiced == [1]


def test_the_stitch_step_says_what_it_does(counting):
    store, backend = counting
    one = store.save(
        Story(owner=OWNER, approved=True, music_on=False, voice_on=False,
              scenes=[Scene(visual="v", frame_uri="f", duration=8)]),
        OWNER,
    )
    job = _run(story_jobs.start_video(one.id, OWNER))
    labels = [t.label for t in job.tasks]
    assert story_jobs.FINISH_LABEL in labels
    assert not any("crossfade" in lbl for lbl in labels)


def test_one_library_item_per_film(counting):
    store, backend = counting
    story = _narrated(store)
    _run(story_jobs.start_video(story.id, OWNER))
    _run(story_jobs.start_video(story.id, OWNER))
    # The first render adds the item; the second updates the same one.
    assert backend.saved == ["", "item-1"]
    assert store.get(story.id, OWNER).library_id == "item-1"


def test_second_language_film_is_its_own_job(counting):
    store, backend = counting
    story = _narrated(store, second_on=True)
    main, tasks = _chain(story_jobs.start_video(story.id, OWNER))
    assert not any(t.kind.endswith("_alt") for t in main.tasks)
    assert main.params.get("next_job")
    got = store.get(story.id, OWNER)
    film = got.final_uri
    assert film and got.final_alt_uri
    # Making only the second film again leaves the main one alone.
    stitched = backend.stitched
    alt = _run(story_jobs.start_alt_video(story.id, OWNER))
    assert alt.status == "done"
    assert backend.stitched == stitched + 1
    got = store.get(story.id, OWNER)
    assert got.final_uri == film
    # Its voice lines were reused too.
    assert sum(1 for lang, _ in backend.voiced if lang == "Arabic") == 2


def test_cancel_during_the_stitch_keeps_the_last_film(counting):
    store, backend = counting
    story = _narrated(store)
    _run(story_jobs.start_video(story.id, OWNER))
    film = store.get(story.id, OWNER).final_uri
    gate, started = threading.Event(), threading.Event()
    real = backend.stitch

    def slow(*a, **kw):
        started.set()
        gate.wait(5)
        return real(*a, **kw)

    backend.stitch = slow
    job = story_jobs.start_video(story.id, OWNER)
    assert started.wait(5)
    story_jobs.cancel_job(job.id, OWNER)
    gate.set()
    done = _run(job)
    assert done.status == "cancelled"
    assert store.get(story.id, OWNER).final_uri == film


def test_film_changes_name_what_changed():
    story = Story(scenes=[Scene(narration="Hi.", clip_uri="c")], music_on=True)
    story.final_parts_json = json.dumps(story.film_parts())
    assert story.film_changes() == []
    story.music_prompt = "Solo piano"
    story.scenes[0].narration = "Hello."
    assert story.film_changes() == ["Narration changed", "Music changed"]
    # Changing it back: the film is current again.
    story.music_prompt = ""
    story.scenes[0].narration = "Hi."
    assert story.film_changes() == []


def test_ffmpeg_stops_when_the_job_is_cancelled():
    from services import story_timeline as tl

    cancel = threading.Event()
    token = tl.CANCEL.set(cancel)
    try:
        threading.Timer(0.5, cancel.set).start()
        args = [tl._ffmpeg(), "-v", "error", "-re", "-f", "lavfi", "-i",
                "testsrc=d=30", "-f", "null", "-"]
        import time

        t = time.time()
        with pytest.raises(tl.Cancelled):
            tl.run_ffmpeg(args)
        assert time.time() - t < 10
    finally:
        tl.CANCEL.reset(token)


# --- M3: the right film type -------------------------------------------------


def test_ideas_that_ask_for_no_speech_or_one_take():
    from services import story_autoset as auto

    found = auto.infer_settings("A product montage, no voice, just music")
    assert found["speech_mode"] == "none"
    assert auto.infer_settings("one continuous shot of a city")["shots"] == "one"
    # Gemini reads any language; its answer is checked.
    got = auto.parse_live_settings('{"shots": "one", "speech_mode": "none"}')
    assert got == {"shots": "one", "speech_mode": "none"}
    assert auto.parse_live_settings('{"shots": "many"}') == {}


def test_shots_choice_beats_the_keyword_guess():
    from components.story_studio import setup_view

    s = StoryState(idea="A guy talking about our product for 30 seconds")
    assert not setup_view.one_take_of(s)
    s.shots = "one"
    assert setup_view.one_take_of(s)
    s.idea, s.shots = "one shot, no cuts", "several"
    assert not setup_view.one_take_of(s)


def test_no_speech_film_has_no_lines():
    from services.story_models import parse_scenario, scenario_prompt

    text = json.dumps(
        {"title": "T", "scenes": [{"narration": "Hello", "visual": "A city", "camera": "static"}]}
    )
    _, scenes = parse_scenario(text, 1, 6, speech_mode="none")
    assert scenes[0].narration == "" and not scenes[0].spoken
    prompt = scenario_prompt(Story(idea="City at dawn", speech_mode="none", scene_count=1))
    assert "Leave every narration empty" in prompt


def test_blueprint_matches_the_breakdown():
    from services import story_director

    narrated = story_director.setup_blueprint(32, speech_mode="narrator")
    assert narrated["takes"] == narrated["shots"]  # narrated shots never join
    silent = story_director.setup_blueprint(32, speech_mode="none", voice_on=False)
    assert silent["cost"]["voice"] == 0


def test_set_build_makes_only_the_views_frames_use():
    from services.story_sets import Character, Location, StorySet

    st = StorySet(
        characters=[Character(name="Ana")], locations=[Location(name="Stage")]
    )
    pieces = story_jobs._set_work(st, None)
    views = sorted(v for _, _, v in pieces)
    assert views == ["face", "front", "plate", "voice"]
    assert st.missing_images() == 3
    # Asking for one by hand still makes it.
    ana = st.characters[0]
    assert story_jobs._set_work(st, [("character", ana.id, "profile")]) == [
        ("character", ana.id, "profile")
    ]
