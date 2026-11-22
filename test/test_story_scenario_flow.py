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
    story = Story(idea="A baker opens a shop", character="Lina, 50s, flour on her apron")
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
