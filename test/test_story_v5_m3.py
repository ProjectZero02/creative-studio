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
"""Story Studio v5 M3: every step on top, one view per step (docs/STORY_STUDIO_V5_PLAN.md)."""

from components.story_studio import director_desk, setup_view
from services import story_jobs, story_service
from services.story_models import (
    DESK_STEPS,
    STEPS,
    Scene,
    Story,
    furthest_step,
    reachable_steps,
    record_turns,
)
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401


def test_every_step_is_on_top_in_order():
    assert [label for _, label, _ in STEPS] == [
        "Films",
        "Setup",
        "Script",
        "Set",
        "Frames",
        "Takes",
        "Music",
        "Edit & Export",
    ]
    assert set(DESK_STEPS) == {"scenario", "set", "storyboard", "editor", "music"}


def test_music_opens_with_the_takes_but_is_never_the_landing_step():
    story = Story(approved=True, scenes=[Scene(frame_uri="f.png", duration=8)])
    reach = reachable_steps(story)
    assert {"editor", "music", "video"} <= reach
    assert furthest_step(story) == "editor"
    assert "music" not in reachable_steps(Story(scenes=[Scene()]))


def test_the_old_switches_are_fixed_on_load():
    old = Story(continuous_takes=False, color_match=False, continuity=True).to_dict()
    loaded = Story.from_dict(old)
    assert loaded.continuous_takes and loaded.color_match
    # Continuity keeps what the film had; each join can still be picked.
    assert loaded.continuity


def test_script_shows_the_planned_turns_then_the_made_ones():
    sc = Scene(
        narration="First line here. Second line here. Third line here.",
        spoken=True,
        duration=30,
    )
    story = Story(video_model="gemini-omni-1.2-flash", scenes=[sc])
    rows = director_desk.turn_rows(story, 0)
    assert [(r["start"], r["end"]) for r in rows] == [(0, 10), (10, 20), (20, 30)]
    assert all(r["lines"] for r in rows)
    sc.turns_json = record_turns([12, 9, 9], ["a", "b", "c"])
    sc.cuts_json = '[{"t": 14.0, "turn": 1}]'
    rows = director_desk.turn_rows(story, 0)
    assert [(r["start"], r["end"]) for r in rows] == [(0, 12), (12, 21), (21, 30)]
    assert [bool(r["cuts"]) for r in rows] == [False, True, False]


def test_arabic_version_cost_is_a_second_render():
    bp = {"cost": {"video": 3.96, "voice": 0.01, "frames": 0.04, "music": 0.06}}
    assert setup_view.alt_cost(bp) == 3.97


class _AlwaysCut(_FastMock):
    def stitch(self, story, plan, music_uri, voice_uris):
        return f"local://{story.id}/film.mp4", {
            "cuts": [{"t": 4.0, "ratio": 80.0, "scene": 0, "turn": 0}]
        }


def test_a_render_saves_the_cuts_on_the_take(jobs_env):  # noqa: F811
    store, _ = jobs_env
    story_service.set_backend(_AlwaysCut())
    story = store.save(
        Story(
            approved=True,
            music_on=False,
            voice_on=False,
            scenes=[Scene(duration=8, frame_uri="local://f0.png")],
        ),
        OWNER,
    )
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    cuts = store.get(story.id, OWNER).scenes[0].cuts()
    assert cuts == [{"t": 4.0, "turn": 0}]
