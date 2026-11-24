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
"""Story Studio v5 M2: make one turn of a take again (docs/STORY_STUDIO_V5_PLAN.md)."""

import json
from types import SimpleNamespace

from services import story_jobs, story_service
from services.story_models import Scene, Story, record_turns
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401


def _take(**kw):
    sc = Scene(
        narration="One. Two. Three.",
        spoken=True,
        duration=30,
        frame_uri="gs://b/f0.png",
        clip_uri="gs://b/joined.mp4",
        turns_json=record_turns(
            [10, 10, 10],
            ["One.", "Two.", "Three."],
            ["first prompt", "second prompt", "third prompt"],
            ["turn1", "turn2", "turn3"],
            ["gs://b/part1.mp4", "gs://b/part2.mp4", "gs://b/part3.mp4"],
        ),
    )
    return Story(title="Talk", aspect_ratio="16:9", scenes=[sc], **kw)


def test_the_cut_turn_is_picked_once_per_scene():
    story = _take()
    cuts = [{"t": 24.3, "scene": 0, "turn": 2}, {"t": 28.0, "scene": 0, "turn": 2}]
    assert story_jobs.turns_to_redo(story, cuts) == [(0, 2)]
    assert story_jobs.turns_to_redo(story, [{"t": 1.0}]) == []
    assert story_jobs.turns_to_redo(story, None) == []


def test_a_scene_another_take_continues_is_not_redone():
    story = Story(
        scenes=[Scene(spoken=True, narration="a", duration=8), Scene(spoken=True, narration="b", duration=8)]
    )
    assert story.continues_take(1)
    assert story_jobs.turns_to_redo(story, [{"scene": 0, "turn": 1}]) == []
    assert story_jobs.turns_to_redo(story, [{"scene": 1, "turn": 0}]) == [(1, 0)]


def test_redo_turn_continues_from_the_turn_before(monkeypatch):
    import models.omni as omni

    calls = []

    def fake_omni(request):
        calls.append(request)
        return f"gs://b/new{len(calls)}.mp4", f"new{len(calls)}"

    monkeypatch.setattr(omni, "generate_omni_video", fake_omni)
    backend = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    backend.cfg = SimpleNamespace(
        STORY_VIDEO_MODEL="gemini-omni-1.2-flash", STORY_VIDEO_RESOLUTION="360p"
    )
    backend._interactions = {}
    backend._set = lambda s: None
    joined = {}

    def fake_join(st, index, pieces):
        joined["pieces"] = pieces
        return "gs://b/redone.mp4"

    backend._join_parts = fake_join
    story = _take()
    uri = backend.redo_turn(story, 0, 1)
    assert uri == "gs://b/redone.mp4"
    # Turns 2 and 3 are made again, from turn 1's interaction.
    assert [c.duration_seconds for c in calls] == [10, 10]
    assert calls[0].previous_interaction_id == "turn1"
    history = json.loads(calls[0].chat_history_json)
    assert history[1]["content"][0]["gcs_uri"] == "gs://b/part1.mp4"
    assert calls[1].previous_interaction_id == "new1"
    assert joined["pieces"] == ["gs://b/part1.mp4", "gs://b/new1.mp4", "gs://b/new2.mp4"]
    turns = story.scenes[0].turns()
    assert [t["interaction_id"] for t in turns] == ["turn1", "new1", "new2"]
    assert [t["uri"] for t in turns] == ["gs://b/part1.mp4", "gs://b/new1.mp4", "gs://b/new2.mp4"]
    assert turns[0]["prompt"] == "first prompt" and turns[2]["lines"] == "Three."


def test_the_first_turn_or_a_missing_record_means_a_new_clip():
    backend = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    backend.cfg = SimpleNamespace(STORY_VIDEO_MODEL="gemini-omni-1.2-flash")
    story = _take()
    assert backend.redo_turn(story, 0, 0) == ""
    story.scenes[0].turns_json = ""
    assert backend.redo_turn(story, 0, 1) == ""


class _TurnMock(_FastMock):
    def __init__(self):
        super().__init__()
        self.redone = []

    def redo_turn(self, story, index, turn):
        self.redone.append((index, turn))
        return f"local://{story.id}/redo{index}-{turn}.mp4"


def test_redo_this_turn_saves_the_new_take(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _TurnMock()
    story_service.set_backend(backend)
    story = store.save(_take(), OWNER)
    job = _run(story_jobs.start_turn_redo(story.id, OWNER, 0, 2))
    assert job.status == "done"
    assert backend.redone == [(0, 2)]
    saved = store.get(story.id, OWNER).scenes[0]
    assert saved.clip_uri.endswith("redo0-2.mp4")
    # Redoing the first turn makes the whole clip again.
    job = _run(story_jobs.start_turn_redo(story.id, OWNER, 0, 0))
    assert job.status == "done" and backend.redone == [(0, 2)]
    assert store.get(story.id, OWNER).scenes[0].clip_uri.endswith("clip0.mp4")


class _CutMock(_TurnMock):
    """The first film has a cut inside take 1's second turn; later ones don't."""

    def __init__(self):
        super().__init__()
        self.stitches = 0

    def generate_clip(self, story, index, start_frame_uri, end_frame_uri=""):
        story.scenes[index].turns_json = record_turns([10, 10, 10])
        return super().generate_clip(story, index, start_frame_uri, end_frame_uri)

    def stitch(self, story, plan, music_uri, voice_uris):
        self.stitches += 1
        cuts = [{"t": 14.0, "ratio": 90.0, "scene": 0, "turn": 1}] if self.stitches == 1 else []
        return f"local://{story.id}/film{self.stitches}.mp4", {"cuts": cuts}


def test_a_cut_in_a_take_is_redone_once(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _CutMock()
    story_service.set_backend(backend)
    story = _take(music_on=False, voice_on=False)
    story.scenes[0].clip_uri = ""
    story = store.save(story, OWNER)
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert backend.redone == [(0, 1)]
    assert backend.stitches == 2
    saved = store.get(story.id, OWNER)
    assert saved.scenes[0].clip_uri.endswith("redo0-1.mp4")
    assert saved.scenes[0].turns()  # the turn records were saved
