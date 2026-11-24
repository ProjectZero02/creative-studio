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

"""Story Studio auto settings (read from the idea) and the improved brief."""

import json
from types import SimpleNamespace

import pytest

import pages.story_studio as page
from config.default import Default
from services import story_autoset as auto
from services import story_jobs, story_models, story_service, story_store
from services.story_models import Story
from state.story_state import StoryState

OWNER = "alice@example.com"


@pytest.mark.parametrize(
    "idea,expected",
    [
        (
            "I want a one minute long video that gives the entire history of the world",
            {"film_seconds": 60, "scene_count": 6, "duration": 10},
        ),
        (
            "A 30 second vertical tiktok ad, anime style",
            {"film_seconds": 30, "aspect_ratio": "9:16", "style": "anime"},
        ),
        ("Five scenes of 8 seconds each", {"scene_count": 5, "duration": 8}),
        (
            "a 45-second promo with 15 second scenes",
            {"film_seconds": 45, "scene_count": 3, "duration": 15},
        ),
        (
            "A 2 minute documentary about bees",
            {"film_seconds": 120, "speech_mode": "narrator"},
        ),
        (
            "a minute and a half claymation about a cat",
            {"film_seconds": 90, "style": "claymation"},
        ),
        (
            "Half a minute of drone shots over Petra",
            {"film_seconds": 30, "camera": "crane_up"},
        ),
        ("A presenter pitches our product to camera", {"speech_mode": "on_camera"}),
        (
            "A love story, narrated in French",
            {"language": "French", "speech_mode": "narrator"},
        ),
        ("قصة قصيرة عن صياد في الإسكندرية", {"language": "Arabic"}),
    ],
)
def test_infer_settings_reads_what_the_idea_says(idea, expected):
    found = auto.infer_settings(idea)
    for key, value in expected.items():
        assert found.get(key) == value, (key, found)


@pytest.mark.parametrize(
    "idea",
    [
        "History of music from the 1960s to the 90s",  # decades, not lengths
        "A scene where a dog runs on the beach",  # "a scene" is not a count
        "A French chef opens a bakery",  # not the film's language
        "A lighthouse keeper befriends a lost baby whale",
    ],
)
def test_infer_settings_ignores_lookalikes(idea):
    found = auto.infer_settings(idea)
    assert "film_seconds" not in found and "scene_count" not in found
    assert "language" not in found


def test_plan_length_hits_the_total_and_keeps_fixed_values():
    assert auto.plan_length(60) == (6, 10)
    n, d = auto.plan_length(60, scene_count=4)
    assert (n, d) == (4, 15)
    n, d = auto.plan_length(60, duration=20)
    assert (n, d) == (3, 20)
    n, d = auto.plan_length(15)  # short film: closest total first
    assert abs(n * d - 15) <= 1


def test_long_films_use_long_scenes():
    # 3 minutes cannot be 18 x 10 s (16 scenes max): longer scenes instead.
    n, d = auto.plan_length(180)
    assert n * d == 180 and n <= Default().STORY_MAX_SCENES


def test_merge_settings_respects_pinned_fields():
    current = {"scene_count": 4, "duration": 6, "style": "photographic"}
    found = {"scene_count": 6, "duration": 10, "style": "anime", "film_seconds": 60}
    assert auto.merge_settings(current, found, {"style"}) == {
        "scene_count": 6,
        "duration": 10,
    }


def test_parse_live_settings_validates_the_model_json():
    text = json.dumps(
        {
            "film_seconds": 60,
            "scene_count": None,
            "scene_seconds": None,
            "aspect_ratio": "9:16",
            "language": "Klingon",
            "style": "anime",
            "speech_mode": "auto",
            "camera": "dolly_in",
        }
    )
    found = auto.parse_live_settings(text)
    assert found == {
        "film_seconds": 60,
        "scene_count": 6,
        "duration": 10,
        "aspect_ratio": "9:16",
        "style": "anime",
        "camera": "dolly_in",
    }
    assert auto.parse_live_settings("not json") == {}


def test_live_settings_prompt_lists_the_choices():
    prompt = auto.live_settings_prompt("a one minute film")
    assert "film_seconds" in prompt and "claymation" in prompt and "Arabic" in prompt


def test_describe():
    found = auto.infer_settings("a one minute vertical anime film")
    assert auto.describe(found) == "1 min: 6 scenes × 10 s · Vertical 9:16 · Anime"


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _vertex(model="gemini-3.5-flash-lite"):
    backend = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    backend.cfg = SimpleNamespace(
        STORY_LIVE_SETTINGS_MODEL=model, STORY_SCENARIO_MODEL_ID="gemini-3.8-flash"
    )
    return backend


def test_vertex_live_settings_uses_the_small_model():
    backend = _vertex()
    calls = []

    def fake(prompt, temperature=0.8, task="story_scenario", model=""):
        calls.append((model, task, temperature))
        return json.dumps({"film_seconds": 60, "style": "anime"})

    backend._json_text = fake
    assert backend.live_settings("one minute anime")["style"] == "anime"
    assert calls == [("gemini-3.5-flash-lite", "story_live_settings", 0.0)]


def test_vertex_live_settings_off_or_failing_returns_nothing():
    backend = _vertex(model="")
    backend._json_text = lambda *a, **k: pytest.fail("no call when off")
    assert backend.live_settings("x") == {}
    backend = _vertex()

    def boom(*a, **k):
        raise RuntimeError("quota")

    backend._json_text = boom
    assert backend.live_settings("x") == {}


def test_live_settings_model_setting():
    assert (
        Default.__dataclass_fields__["STORY_LIVE_SETTINGS_MODEL"].default
        == "gemini-3.5-flash-lite"
    )
    assert Default.__dataclass_fields__["STORY_MAX_SCENE_SECONDS"].default == 30


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------


def test_scenario_prompt_asks_for_a_brief_and_reuses_it():
    prompt = story_models.scenario_prompt(Story(idea="a cat"))
    assert '"brief": str' in prompt and "Brief (from an earlier pass" not in prompt
    again = story_models.scenario_prompt(Story(idea="a cat", brief="A gentle film."))
    assert "A gentle film." in again


def test_parse_brief():
    assert story_models.parse_brief(json.dumps({"brief": " A film. "})) == "A film."
    assert story_models.parse_brief("{}") == "" and story_models.parse_brief("x") == ""


def test_scenario_job_stores_the_brief(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(path=str(tmp_path / "s.json"))
    monkeypatch.setattr(story_jobs, "get_store", lambda: store)
    story_service.set_backend(story_service.MockStoryBackend(speed=0))
    try:
        story = store.save(
            Story(owner=OWNER, idea="A cat learns to fly over Paris"), OWNER
        )
        job = story_jobs.start_scenario(story.id, OWNER)
        assert story_jobs.wait(job.id, OWNER, timeout=30).status == "done"
        saved = store.get(story.id, OWNER)
        assert saved.brief.startswith("A cat learns to fly over Paris.")
        assert saved.scenes
    finally:
        story_service.set_backend(None)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@pytest.fixture
def state(monkeypatch):
    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    return st


def test_typing_pause_updates_unpinned_settings(state, monkeypatch):
    monkeypatch.setattr(
        page,
        "get_backend",
        lambda: SimpleNamespace(live_settings=lambda t: {"style": "anime"}),
    )
    state.pinned_json = json.dumps(["aspect_ratio"])
    event = SimpleNamespace(
        value={"value": "A one minute vertical film about the history of the world"}
    )
    list(page.on_idea_live(event))
    assert (state.scene_count, state.duration) == (6, 10)
    assert state.aspect_ratio == "16:9"  # pinned by the user
    assert state.style == "anime"  # from the live model
    assert state.idea == ""  # the field itself is never rewritten while typing
    assert (
        "1 min" in state.auto_json or json.loads(state.auto_json)["film_seconds"] == 60
    )


def test_picking_a_value_pins_it_and_use_auto_unpins(state):
    page.on_aspect(SimpleNamespace(value="9:16"))
    assert "aspect_ratio" in json.loads(state.pinned_json)
    state.auto_json = json.dumps({"aspect_ratio": "16:9"})
    page.on_reset_auto(None)
    assert state.pinned_json == "[]" and state.aspect_ratio == "16:9"


def test_last_film_length_wins():
    found = auto.infer_settings(
        "a one minute film about bees, actually make it two minutes"
    )
    assert found["film_seconds"] == 120
    assert auto.infer_settings("half a minute, no, 45 seconds")["film_seconds"] == 45


def test_pinned_scene_length_replans_the_scene_count():
    found = auto.infer_settings("a two minute film")
    current = {"scene_count": 6, "duration": 30}
    assert auto.merge_settings(current, found, {"duration"}) == {"scene_count": 4}
    current = {"scene_count": 3, "duration": 10}
    assert auto.merge_settings(current, found, {"scene_count"}) == {"duration": 30}

