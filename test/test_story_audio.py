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
"""Story Studio audio: a natural ending, and narrator lines that fit."""

import json
import math
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401

from services import story_jobs, story_service
from services import story_timeline as T
from services.story_models import (
    END_BREATH,
    Scene,
    Story,
    clip_prompt,
    line_pace,
    narrator_words,
    scene_words,
    split_narration_parts,
    voice_room,
)


def _ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _clip(path, seconds, speech_until):
    """A small video whose sound is a tone (speech) until `speech_until`,
    then near silence (room tone)."""
    audio = (
        f"aevalsrc='0.3*sin(2*PI*300*t)*lt(t,{speech_until})+0.0005*sin(2*PI*90*t)'"
        f":s=48000:d={seconds}"
    )
    subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=s=320x180:r=24:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            audio,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            path,
        ],
        check=True,
    )
    return path


def _music(path, seconds):
    subprocess.run(
        [
            _ffmpeg(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='0.2*sin(2*PI*440*t)':s=48000:d={seconds}",
            path,
        ],
        check=True,
    )
    return path


def _film(clip, music, length, duck=True):
    tl = T.empty_timeline(320, 180, 24)
    T.track(tl, "video")["clips"].append(
        {
            "id": "v",
            "src": "clip",
            "start": 0.0,
            "in": 0.0,
            "out": float(length),
            "gain": 1.0,
            "fade_in": 0.0,
            "join": "cut",
            "scene": 0,
            "src_max": float(length),
        }
    )
    m = T.track(tl, "music")
    m["clips"].append(
        {
            "id": "m",
            "src": "music",
            "start": 0.0,
            "in": 0.0,
            "out": float(length),
            "gain": 0.8,
            "src_max": float(length) + 2,
        }
    )
    m["duck"] = duck
    files = {"clip": clip, "music": music}
    return tl, lambda uri, dest: shutil.copyfile(files[uri], dest)


def _last_sound(path):
    levels = T.audio_levels(path, 0.05)
    loud = [i for i, v in enumerate(levels) if v > -45]
    return (loud[-1] + 1) * 0.05 if loud else 0.0


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("audio")
    return {
        "early": _clip(str(d / "early.mp4"), 6, 4.5),
        "late": _clip(str(d / "late.mp4"), 6, 6),
        "music": _music(str(d / "music.wav"), 8),
        "dir": d,
    }


def test_ducked_music_plays_to_the_end_every_time(media):
    # The ducking filter used to drop the music at a random point up to a
    # second before the end (heard as an abrupt stop).
    for k in range(4):
        tl, fetch = _film(media["early"], media["music"], 6)
        out = str(media["dir"] / f"duck{k}.wav")
        T.render_timeline(tl, fetch, out, fmt="wav")
        assert _last_sound(out) >= 5.6, k


def test_the_end_music_fades_out_over_the_outro():
    tl, _ = _film("a.mp4", "m.wav", 10)
    args = T.render_args(
        T.normalize(tl),
        {"clip": "a.mp4", "music": "m.wav"},
        {"clip": True, "music": True},
        {},
        "out.mp4",
    )
    graph = args[args.index("-filter_complex") + 1]
    assert f"afade=t=out:st={10 - T.MUSIC_OUTRO:.3f}:d={T.MUSIC_OUTRO:.3f}" in graph
    # The last clip's own sound eases out too.
    assert f"d={T.END_SOUND_FADE:.3f}" in graph


def test_speech_up_to_the_end_holds_the_last_frame(media):
    tl, fetch = _film(media["late"], media["music"], 6)
    out = str(media["dir"] / "hold.mp4")
    T.render_timeline(tl, fetch, out)
    length, _ = T.probe(out)
    assert abs(length - (6 + T.END_HOLD)) < 0.1


def test_a_natural_ending_is_not_held(media):
    tl, fetch = _film(media["early"], media["music"], 6)
    out = str(media["dir"] / "nohold.mp4")
    T.render_timeline(tl, fetch, out)
    assert abs(T.probe(out)[0] - 6) < 0.1


def test_the_last_turn_gets_fewer_words_and_ends_on_a_breath():
    text = " ".join(f"w{i}" for i in range(60))
    even = split_narration_parts(text, [10, 10, 10])
    ending = split_narration_parts(text, [10, 10, 10], end_breath=END_BREATH)
    assert len(ending[-1].split()) < len(even[-1].split())
    assert " ".join(ending).split() == text.split()

    story = Story(
        language="English", scenes=[Scene(duration=10, spoken=True, narration="Hi.")]
    )
    assert "end of the film" in clip_prompt(story, story.scenes[0], ends_film=True)
    assert "end of the film" not in clip_prompt(story, story.scenes[0])


def test_narrator_word_limits_follow_the_measured_pace():
    # 1.8 words a second, less the lead-in and the breath.
    assert [narrator_words(d) for d in (4, 6, 10)] == [5, 8, 15]
    assert narrator_words(6, 2.4) > narrator_words(6)
    story = Story(
        scenes=[
            Scene(duration=6, narration="x"),
            Scene(duration=6, spoken=True, narration="x"),
        ],
        narrator_wps=2.0,
    )
    assert scene_words(story.scenes[0], story, 0) == narrator_words(6, 2.0)
    # The last scene ends on a breath: fewer words.
    assert scene_words(story.scenes[1], story, 1) < scene_words(story.scenes[1])
    assert voice_room(story, 0) == pytest.approx(6 - 0.75)


def test_line_pace_is_the_median_of_real_lines():
    lines = [
        ("one two three four", 2.0),
        ("a b c d e f", 3.0),
        ("x y z", 3.0),
        ("hi", 9.0),
    ]
    assert line_pace(lines) == 2.0
    assert line_pace([("too short", 1.0)]) == 0.0


def test_one_speed_for_every_line():
    assert T.film_tempo([(3.0, 4.0), (2.0, 4.0)]) == 1.0
    assert T.film_tempo([(4.2, 4.0), (2.0, 4.0)]) == pytest.approx(1.05)
    assert T.film_tempo([(6.0, 4.0)]) == T.MAX_FILM_TEMPO


def _plan(durations):
    segs, start = [], 0.0
    for i, d in enumerate(durations):
        segs.append(
            SimpleNamespace(
                index=i,
                start=start,
                duration=float(d),
                fade_in=0.0,
                clip_uri=f"c{i}.mp4",
                trim_head=0.0,
                join="cut",
                spoken=False,
            )
        )
        start += d
    return SimpleNamespace(segments=segs, total=start)


def _story(durations, lines):
    return Story(
        scenes=[
            Scene(duration=d, narration=t)
            for d, t in zip(durations, lines, strict=True)
        ]
    )


def test_lines_play_at_one_speed_and_never_overlap():
    durations = [4, 4, 4]
    story = _story(durations, ["a b c", "d e f", "g h i"])
    info = {
        0: {"length": 3.0, "lead": 0.26, "end": 2.9, "pauses": [1.5]},
        1: {"length": 3.5, "lead": 0.26, "end": 3.4, "pauses": [1.8]},
        2: {"length": 2.0, "lead": 0.26, "end": 1.9, "pauses": []},
    }
    tl = T.build_timeline(
        story,
        _plan(durations),
        width=320,
        height=180,
        clip_lengths={i: 4.0 for i in range(3)},
        voice_uris={i: f"v{i}.wav" for i in range(3)},
        voice_lengths={i: info[i]["length"] for i in range(3)},
        voice_info=info,
    )
    lines = T.track(tl, "voice")["clips"]
    assert len({c["tempo"] for c in lines}) == 1
    # The leading silence is trimmed: speech starts just after the lead-in.
    assert lines[0]["in"] == pytest.approx(0.21)
    for a, b in zip(lines, lines[1:], strict=False):
        assert T.clip_end(a) <= b["start"] + 1e-6


def test_a_line_too_long_ends_at_its_last_pause():
    durations = [4, 4]
    story = _story(durations, ["long " * 12, "next"])
    info = {
        0: {"length": 6.0, "lead": 0.2, "end": 5.9, "pauses": [1.6, 2.9, 5.0]},
        1: {"length": 1.0, "lead": 0.2, "end": 0.9, "pauses": []},
    }
    tl = T.build_timeline(
        story,
        _plan(durations),
        width=320,
        height=180,
        clip_lengths={0: 4.0, 1: 4.0},
        voice_uris={0: "v0.wav", 1: "v1.wav"},
        voice_lengths={0: 6.0, 1: 1.0},
        voice_info=info,
    )
    first = T.track(tl, "voice")["clips"][0]
    assert first["out"] == 2.9  # the last pause before the next line


def test_a_long_line_may_run_into_a_silent_next_scene():
    durations = [4, 4]
    story = _story(durations, ["long " * 9, ""])
    info = {0: {"length": 4.3, "lead": 0.2, "end": 4.2, "pauses": [2.0]}}
    tl = T.build_timeline(
        story,
        _plan(durations),
        width=320,
        height=180,
        clip_lengths={0: 4.0, 1: 4.0},
        voice_uris={0: "v0.wav"},
        voice_lengths={0: 4.3},
        voice_info=info,
    )
    (line,) = T.track(tl, "voice")["clips"]
    assert "cut" not in line
    assert T.clip_end(line) > 4.0  # past its own scene, into the quiet one


def test_voice_shape_finds_lead_end_and_pauses(tmp_path):
    rate = 16000
    t = np.arange(int(rate * 3.0)) / rate
    on = ((t > 0.3) & (t < 1.2)) | ((t > 1.5) & (t < 2.6))
    tone = 0.3 * np.sin(2 * math.pi * 300 * t) * on
    path = str(tmp_path / "line.wav")
    story_service._write_wav(path, tone, rate)
    shape = T.voice_shape(path)
    assert shape["lead"] == pytest.approx(0.3, abs=0.03)
    assert shape["end"] == pytest.approx(2.6, abs=0.03)
    assert len(shape["pauses"]) == 1 and 1.2 < shape["pauses"][0] < 1.5


class _VoiceMock(_FastMock):
    """Real voice files at the narrator's pace; records shortened lines."""

    def __init__(self):
        super().__init__()
        self.shortened = []

    def generate_voiceover(self, story, index, text, voice=None):
        return story_service.MockStoryBackend.generate_voiceover(
            self, story, index, text
        )

    def shorten_line(self, story, index, text, words):
        self.shortened.append((index, words))
        return story_service.MockStoryBackend.shorten_line(
            self, story, index, text, words
        )


def test_a_line_too_long_is_shortened_and_voiced_again(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _VoiceMock()
    story_service.set_backend(backend)
    long_line = " ".join(["word"] * 14)  # 14 words: about 8 s at 1.8 a second
    story = store.save(
        Story(
            approved=True,
            music_on=False,
            voice_on=True,
            speech_mode="narrator",
            scenes=[
                Scene(duration=4, narration=long_line, frame_uri="local://f0.png"),
                Scene(
                    duration=6,
                    narration="A short closing line here.",
                    frame_uri="local://f1.png",
                ),
            ],
        ),
        OWNER,
    )
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert [i for i, _ in backend.shortened] == [0]
    saved = store.get(story.id, OWNER)
    assert len(saved.scenes[0].narration.split()) <= narrator_words(
        4, saved.narrator_wps
    )
    assert saved.narrator_wps > 0
    fit = next(t for t in job.tasks if t.label.startswith("Fitting"))
    assert fit.status == "done"


def test_the_writer_is_told_the_narrator_limits():
    from services.story_models import scenario_prompt

    story = Story(
        idea="A city at dawn", speech_mode="narrator", duration=24, scene_count=4
    )
    prompt = scenario_prompt(story)
    assert f"{narrator_words(4)} for 4s" in prompt
    data = json.dumps({"ok": True})
    assert data
