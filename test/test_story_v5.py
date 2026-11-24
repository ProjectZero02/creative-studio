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
"""Story Studio v5 M1: one continuous take that works (docs/STORY_STUDIO_V5_PLAN.md)."""

import os
import subprocess

import pytest

from services import story_director, story_timeline
from services.story_models import (
    ONE_TAKE_RULES,
    Scene,
    Story,
    clip_parts,
    clip_prompt,
    scenario_prompt,
)

TEST_PROMPT = (
    "i want one shot, with the character talking, one guy on a stage talking "
    "about Gemini enterprise for 30 seconds. the camera pans from left to right "
    "slowly throughout that time"
)


def test_one_take_is_read_from_the_idea():
    assert story_director.is_one_take(TEST_PROMPT)
    assert story_director.is_one_take("a single-take tour of the kitchen")
    assert story_director.is_one_take("no cuts, just him talking")
    assert not story_director.is_one_take("a short film about a cat")
    assert not story_director.is_one_take("a man throughout history")


def test_a_one_shot_is_one_take_of_the_asked_length():
    assert story_director.plan_one_take(30) == (1, 30)
    plan = story_director.plan_film_blueprint(30, one_take=True)
    assert (plan["scene_count"], plan["duration"]) == (1, 30)
    bp = story_director.setup_blueprint(30, one_take=True)
    assert bp["seconds"] == 30
    assert bp["takes"] == 1 and bp["cuts"] == 0
    assert bp["turns"] == [10, 10, 10]


def test_long_continuous_scenes_use_as_few_takes_as_fit():
    assert story_director.plan_one_take(45) == (2, 25)
    assert story_director.plan_one_take(300) == (10, 30)
    bp = story_director.setup_blueprint(300, one_take=True)
    assert bp["cuts"] == 0


def test_turns_are_even_and_within_omni_limits():
    assert clip_parts(30, 15) == [10, 10, 10]
    assert clip_parts(20, 15) == [10, 10]
    assert clip_parts(15, 15) == [15]
    assert clip_parts(16, 15) == [8, 8]
    for secs in range(16, 31):
        parts = clip_parts(secs, 15)
        assert sum(parts) == secs
        assert all(3 <= p <= 10 for p in parts)
    assert all(p <= 8 for p in clip_parts(30, 8))  # Veo's 8 s first clip


def _story(**kw):
    sc = Scene(
        visual="Arthur stands on the left side of the stage under a blue spotlight.",
        narration="Welcome everyone. Today we explore Gemini Enterprise.",
        spoken=True,
        camera="pan_right",
        duration=30,
    )
    base = dict(idea=TEST_PROMPT, scenes=[sc], scene_count=1, duration=30,
                speech_mode="on_camera", speaker_voice="a calm male voice")
    base.update(kw)
    return Story(**base), sc


def test_a_later_turn_of_the_take_does_not_resend_the_framing():
    story, sc = _story(character="a man in a navy blazer")
    later = clip_prompt(story, sc, continuing=True, part_narration="and so on.")
    assert "left side of the stage" not in later
    assert "blue spotlight" not in later
    assert "for the whole clip" not in later
    assert "stopping or reversing" not in later
    assert "( )" not in later and "()" not in later
    assert "no cuts" in later.lower()
    first = clip_prompt(story, sc, continuing=False)
    assert "left side of the stage" in first


def test_a_moving_camera_keeps_the_person_in_frame():
    story, sc = _story(character="a man in a navy blazer")
    prompt = clip_prompt(story, sc, continuing=False)
    assert "in frame" in prompt


def test_spoken_clips_ask_for_clean_sound():
    story, sc = _story()
    prompt = clip_prompt(story, sc, continuing=False)
    assert "applause" in prompt and "hiss" in prompt


def test_the_breakdown_prompt_asks_for_one_take():
    story, _ = _story(one_take=True, target_seconds=30, scenes=[])
    text = scenario_prompt(story)
    assert "ONE CONTINUOUS TAKE of 30 seconds" in text
    assert ONE_TAKE_RULES.strip()[:20] in text
    plain, _ = _story(one_take=False, scenes=[], scene_count=4, duration=8)
    assert "ONE CONTINUOUS TAKE" not in scenario_prompt(plain)


def test_trim_lands_on_the_asked_length():
    tl = story_timeline.empty_timeline(1280, 720, 24)
    story_timeline.track(tl, "video")["clips"].append(
        {"id": "a", "src": "x.mp4", "start": 0.0, "in": 0.0, "out": 32.0}
    )
    story_timeline.track(tl, "music")["clips"].append(
        {"id": "m", "src": "m.wav", "start": 0.0, "in": 0.0, "out": 32.0}
    )
    story_timeline.trim_to(tl, 30)
    assert story_timeline.duration(tl) == 30.0
    assert story_timeline.track(tl, "music")["clips"][0]["out"] == 30.0


def test_spoken_gain_is_capped():
    assert story_timeline.clip_gain(-30.0, spoken=True) <= story_timeline.SPOKEN_GAIN_MAX


def _ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture
def cut_clip(tmp_path):
    """3 s of a slowly moving picture with a hard cut to another at 1.5 s."""
    out = os.path.join(tmp_path, "cut.mp4")
    subprocess.run(
        [
            _ffmpeg(), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1.5",
            "-f", "lavfi", "-i", "mandelbrot=size=320x180:rate=24",
            "-filter_complex",
            "[1:v]trim=duration=1.5,setpts=PTS-STARTPTS[b];[0:v][b]concat=n=2:v=1[v]",
            "-map", "[v]", "-pix_fmt", "yuv420p", out,
        ],
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture
def clean_clip(tmp_path):
    out = os.path.join(tmp_path, "clean.mp4")
    subprocess.run(
        [
            _ffmpeg(), "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=3",
            "-pix_fmt", "yuv420p", out,
        ],
        check=True,
        capture_output=True,
    )
    return out


def test_the_cut_scan_finds_a_cut_inside_a_take(cut_clip, clean_clip):
    cuts = story_timeline.take_cuts(cut_clip)
    assert len(cuts) == 1 and abs(cuts[0]["t"] - 1.5) < 0.1
    assert story_timeline.take_cuts(clean_clip) == []


def test_turn_records_map_a_time_to_its_turn():
    from services.story_models import record_turns

    sc = Scene(duration=30)
    sc.turns_json = record_turns([10, 10, 10], ["a.", "b.", "c."], ids=["t1", "t2", "t3"])
    turns = sc.turns()
    assert [t["start"] for t in turns] == [0, 10, 20]
    assert turns[1]["lines"] == "b." and turns[2]["interaction_id"] == "t3"
    assert sc.turn_at(8.42) == 0 and sc.turn_at(24.33) == 2
    sc.clear_clip()
    assert sc.turns() == []
    assert Scene(turns_json="not json").turns() == []


def test_a_cut_is_located_in_its_scene_clip():
    tl = story_timeline.empty_timeline(1280, 720, 24)
    story_timeline.track(tl, "video")["clips"] += [
        {"id": "a", "src": "a.mp4", "scene": 0, "start": 0.0, "in": 0.0, "out": 8.0},
        {"id": "b", "src": "b.mp4", "scene": 1, "start": 8.0, "in": 2.0, "out": 32.0},
    ]
    assert story_timeline.locate(tl, 3.0) == (0, 3.0)
    assert story_timeline.locate(tl, 20.0) == (1, 14.0)
    assert story_timeline.locate(tl, 99.0) == (-1, 0.0)
