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
