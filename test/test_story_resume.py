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
"""Story Studio: Retry goes on from the turns of a long take that worked."""

import json
from types import SimpleNamespace

import pytest
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401

from common.error_handling import GenerationError
from services import story_jobs, story_service
from services.story_models import Scene, Story


def _story(narration="One line. Two line. Three line."):
    sc = Scene(narration=narration, spoken=True, duration=30, frame_uri="gs://b/f0.png")
    return Story(title="Talk", aspect_ratio="16:9", scenes=[sc])


class _Omni:
    """Fake Gemini Omni: numbered clips; fails the calls listed in `fail`."""

    def __init__(self, fail=()):
        self.calls, self.fail, self.made = [], set(fail), 0

    def __call__(self, request):
        self.calls.append(request)
        if len(self.calls) in self.fail:  # numbered within one try
            raise GenerationError("content_blocked")
        self.made += 1  # clip names run on across tries
        return f"gs://b/part{self.made}.mp4", f"turn{self.made}"


@pytest.fixture
def backend(monkeypatch):
    import models.omni as omni

    fake = _Omni()
    monkeypatch.setattr(omni, "generate_omni_video", fake)
    b = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    b.cfg = SimpleNamespace(
        STORY_VIDEO_MODEL="gemini-omni-1.2-flash", STORY_VIDEO_RESOLUTION="360p"
    )
    b._interactions = {}
    b._set = lambda s: None
    b.joined = []

    def join(story, index, pieces):
        b.joined.append(pieces)
        return "gs://b/take.mp4"

    b._join_parts = join
    b.omni = fake
    return b


def test_retry_goes_on_from_the_turns_that_worked(backend):
    story = _story()
    backend.omni.fail = {2}  # the second turn is refused
    with pytest.raises(GenerationError):
        backend.generate_clip(story, 0, "gs://b/f0.png")
    sc = story.scenes[0]
    kept = json.loads(sc.partial_turns_json)["turns"]
    assert [t["uri"] for t in kept] == ["gs://b/part1.mp4"]

    backend.omni.fail = set()
    backend.omni.calls.clear()
    uri = backend.generate_clip(story, 0, "gs://b/f0.png")
    assert uri == "gs://b/take.mp4"
    # Only turns 2 and 3 are made; turn 1 is not paid for again.
    assert [c.duration_seconds for c in backend.omni.calls] == [10, 10]
    assert backend.omni.calls[0].previous_interaction_id == "turn1"
    assert backend.joined[-1] == ["gs://b/part1.mp4", "gs://b/part2.mp4", "gs://b/part3.mp4"]
    assert [t["interaction_id"] for t in sc.turns()] == ["turn1", "turn2", "turn3"]
    assert sc.partial_turns_json == ""


def test_a_later_failure_keeps_every_turn_before_it(backend):
    story = _story()
    backend.omni.fail = {3}
    with pytest.raises(GenerationError):
        backend.generate_clip(story, 0, "gs://b/f0.png")
    kept = json.loads(story.scenes[0].partial_turns_json)["turns"]
    assert [t["interaction_id"] for t in kept] == ["turn1", "turn2"]

    backend.omni.fail = set()
    backend.omni.calls.clear()
    backend.generate_clip(story, 0, "gs://b/f0.png")
    assert [c.duration_seconds for c in backend.omni.calls] == [10]


def test_a_changed_scene_starts_the_take_again(backend):
    story = _story()
    backend.omni.fail = {2}
    with pytest.raises(GenerationError):
        backend.generate_clip(story, 0, "gs://b/f0.png")
    story.scenes[0].narration = "A different line. Said another way. And more."
    backend.omni.fail = set()
    backend.omni.calls.clear()
    backend.generate_clip(story, 0, "gs://b/f0.png")
    assert len(backend.omni.calls) == 3  # nothing kept fits the new line


class _FailsOnce(_FastMock):
    """First clip try fails after keeping a turn; the next one works."""

    def __init__(self):
        super().__init__()
        self.tries = 0
        self.seen = []

    def generate_clip(self, story, index, start_frame_uri, end_frame_uri=""):
        self.tries += 1
        sc = story.scenes[index]
        self.seen.append(sc.partial_turns_json)
        if self.tries == 1:
            sc.partial_turns_json = json.dumps({"key": "k", "turns": [{"uri": "u", "interaction_id": "i"}]})
            raise GenerationError("content_blocked")
        sc.partial_turns_json = ""
        return super().generate_clip(story, index, start_frame_uri)


def test_the_job_saves_kept_turns_and_clears_them_once_the_take_is_made(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _FailsOnce()
    story_service.set_backend(backend)
    story = store.save(
        Story(
            approved=True,
            music_on=False,
            voice_on=False,
            scenes=[Scene(duration=8, spoken=True, narration="Hi there.", frame_uri="local://f0.png")],
        ),
        OWNER,
    )
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status != "done"
    assert store.get(story.id, OWNER).scenes[0].partial_turns_json

    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert backend.seen[1]  # the retry saw the kept turns
    assert store.get(story.id, OWNER).scenes[0].partial_turns_json == ""
