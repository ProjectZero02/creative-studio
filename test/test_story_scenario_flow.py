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

"""Story Studio Create -> Scenario -> Set hand-offs (no network)."""

from types import SimpleNamespace

from services import story_models, story_service
from services.story_models import Story
from services.story_sets import Character, StorySet


def _vertex(calls: list):
    backend = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    backend.cfg = SimpleNamespace(STORY_SCENARIO_MODEL_ID="gemini-4-neon")
    backend._set = lambda story: None

    def fake(prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return "{}"

    backend._json_text = fake
    return backend


# --- Create inputs reach the scenario writer ---------------------------------


def test_scenario_prompt_carries_the_main_character_and_photo():
    story = Story(
        idea="A baker opens a shop", character="Lina, 50s, flour on her apron"
    )
    prompt = story_models.scenario_prompt(story)
    assert "Main character (keep this look): Lina, 50s, flour on her apron" in prompt
    assert story_models.REFERENCE_PHOTO_NOTE not in prompt

    story.reference_uri = "gs://b/lina.png"
    assert story_models.REFERENCE_PHOTO_NOTE in story_models.scenario_prompt(story)


def test_saved_set_replaces_the_create_character():
    story = Story(idea="x", character="Lina", reference_uri="gs://b/lina.png")
    saved = StorySet(characters=[Character(name="Omar")])
    assert "Main character" not in story_models.scenario_prompt(story, saved)
    assert story_models.scenario_media(story, saved) == []


def test_vertex_scenario_sends_the_reference_photo():
    calls: list = []
    backend = _vertex(calls)
    backend.write_scenario(Story(idea="x", reference_uri="gs://b/lina.png"))
    backend.write_scenario(Story(idea="x"))
    assert calls[0]["media"] == ["gs://b/lina.png"]
    assert calls[1]["media"] == []


# --- Structured output, system instruction, thinking -------------------------


def test_scenario_schema_pins_scene_count_camera_and_types():
    schema = story_models.scenario_schema(Story(scene_count=5))
    scenes = schema["properties"]["scenes"]
    assert scenes["minItems"] == scenes["maxItems"] == 5
    scene = scenes["items"]["properties"]
    assert scene["camera"]["enum"] == list(story_models.CAMERA_IDS)
    assert scene["spoken"] == {"type": "boolean"}
    assert {"brief", "title", "voice", "scenes"} <= set(schema["required"])


def test_saved_set_scenario_schema_asks_for_scene_links():
    saved = StorySet(characters=[Character(name="Omar")])
    scene = story_models.scenario_schema(Story(), saved)["properties"]["scenes"][
        "items"
    ]
    assert {"cast", "location", "props", "speaker"} <= set(scene["required"])


def test_set_schema_limits_the_cast_and_voices():
    props = story_models.set_schema()["properties"]
    assert props["characters"]["maxItems"] == story_models.SET_MAX_CHARACTERS
    voice = props["characters"]["items"]["properties"]["voice"]["properties"]
    assert voice["tts_voice"]["enum"] == list(story_models.VOICES)


def test_vertex_story_calls_use_schema_system_and_thinking():
    calls: list = []
    backend = _vertex(calls)
    story = Story(idea="x", scene_count=3)
    backend.write_scenario(story)
    backend.write_set(story)
    story.scenes = [story_models.Scene(visual="v")]
    backend.rewrite_scene(story, 0)
    scen, cast, regen = calls
    assert scen["schema"] == story_models.scenario_schema(story)
    assert scen["system"] == story_models.SCENARIO_SYSTEM
    assert cast["schema"] == story_models.set_schema()
    assert cast["system"] == story_models.CASTING_SYSTEM
    assert regen["schema"]["properties"]["camera"]["enum"]
    for call in calls:
        assert call["thinking"] is True
        assert call.get("temperature") is None  # the model's own default
        assert "You are a" not in call["prompt"]  # the role is the system's


# --- The scenario call casts the film ----------------------------------------

import json  # noqa: E402

import pytest  # noqa: E402

from services import story_jobs, story_sets, story_store  # noqa: E402
from services.story_models import Scene  # noqa: E402
from services.story_sets import LocalSetStore  # noqa: E402

OWNER = "alice@example.com"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    story_store.set_store(story_store.LocalStoryStore(str(tmp_path / "stories.json")))
    story_sets.set_set_store(LocalSetStore(str(tmp_path / "sets.json")))
    backend = story_service.MockStoryBackend(speed=0)
    story_service.set_backend(backend)
    yield backend
    story_service.set_backend(None)
    story_sets.set_set_store(None)
    story_store.set_store(None)


def _run(job):
    done = story_jobs.wait(job.id, OWNER, timeout=30)
    assert done is not None and done.status != "running"
    return done


def _scenario_story(**over) -> Story:
    fields = dict(idea="A lighthouse keeper adopts a stray cat", scene_count=3)
    fields.update(over)
    story = story_store.get_store().save(Story(**fields), OWNER)
    assert _run(story_jobs.start_scenario(story.id, OWNER)).status == "done"
    return story_store.get_store().get(story.id, OWNER)


def test_plain_scenario_prompt_asks_for_the_cast_once():
    prompt = story_models.scenario_prompt(Story(idea="x"))
    assert "Cast the film too" in prompt and '"characters"' in prompt
    assert "do not describe" in prompt  # visuals name people, the cast has looks
    assert "describe it each time" not in prompt
    schema = story_models.scenario_schema(Story())
    assert {"characters", "locations", "props"} <= set(schema["required"])


def test_scenario_keeps_its_cast_until_the_set_step(stores):
    story = _scenario_story(character="Ada, 60s, white braid")
    cast = json.loads(story.cast_json)
    assert cast["characters"][0]["description"] == "Ada, 60s, white braid"
    assert set(cast["scenes"]) == {sc.id for sc in story.scenes}
    assert story.set_id == ""  # nothing in the sets library yet
    assert story_sets.get_set_store().list(OWNER) == []


def test_frames_use_the_scenario_cast_before_a_set_exists(stores):
    story = _scenario_story(character="Ada, 60s, white braid")
    name = json.loads(story.cast_json)["characters"][0]["name"]
    prompt = story_models.frame_prompt(story, story.scenes[0], False)
    assert f"On screen: {name} (Ada, 60s, white braid" in prompt
    assert "Place: " in prompt and "golden hour" in prompt
    clip = story_models.clip_prompt(story, story.scenes[0])
    assert f"On screen: {name} (Ada, 60s, white braid" in clip


def test_set_step_builds_the_set_from_the_scenario_cast(stores, monkeypatch):
    story = _scenario_story(character="Ada, 60s, white braid")
    monkeypatch.setattr(
        stores, "write_set", lambda s: pytest.fail("no second casting call")
    )
    job = _run(story_jobs.start_set(story.id, OWNER, targets=[["none", "", ""]]))
    assert job.tasks[0].label == "Building the set from the scenario"
    assert job.tasks[0].status == "done"
    story = story_store.get_store().get(story.id, OWNER)
    made = story_sets.get_set_store().get(story.set_id, OWNER)
    lead = made.on_screen()[0]
    assert lead.description == "Ada, 60s, white braid"
    assert all(sc.cast == [lead.id] for sc in story.scenes)
    assert all(sc.location_id for sc in story.scenes)
    assert story.cast_json == ""


def test_set_step_casts_again_when_scenes_changed(stores):
    story = _scenario_story()

    def add_scene(s: Story) -> None:
        s.scenes.append(Scene(visual="an extra scene", narration="More."))

    story = story_jobs.mutate_story(story.id, OWNER, add_scene)
    assert story_models.set_text_from_cast(story.cast_json, story.scenes) == ""
    job = _run(story_jobs.start_set(story.id, OWNER, targets=[["none", "", ""]]))
    assert job.tasks[0].label == "Casting with Gemini"
    assert job.tasks[0].status == "done"


def test_scenario_without_a_cast_still_works(stores, monkeypatch):
    reply = {
        "title": "T",
        "scenes": [
            {"narration": "n", "visual": f"v{i}", "camera": "static"} for i in range(3)
        ],
    }
    monkeypatch.setattr(stores, "write_scenario", lambda story: json.dumps(reply))
    story = _scenario_story()
    assert len(story.scenes) == 3 and story.cast_json == ""


def test_rewrite_moves_the_scene_in_the_stored_cast(stores, monkeypatch):
    story = _scenario_story()
    name = json.loads(story.cast_json)["characters"][0]["name"]
    assert f"Character c1: {name}" in story_models.scene_regen_prompt(story, 1)
    assert story_models.regen_links(story, None)
    new = {
        "narration": "n",
        "spoken": False,
        "visual": "v",
        "camera": "static",
        "cast": [],
        "location": "l3",
        "props": [],
        "speaker": "",
    }
    monkeypatch.setattr(stores, "rewrite_scene", lambda s, i: json.dumps(new))
    assert _run(story_jobs.start_scene_rewrite(story.id, OWNER, 1)).status == "done"
    after = story_store.get_store().get(story.id, OWNER)
    row = json.loads(after.cast_json)["scenes"][after.scenes[1].id]
    assert row == {"cast": [], "location": "l3", "props": [], "speaker": ""}
