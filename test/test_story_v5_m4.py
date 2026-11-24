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
"""Story Studio v5 M4: music tracks, sound checks, long takes, final quality."""

import json
import os
import subprocess

import pytest
from test_story_setup_v4 import OWNER, _FastMock, _run, jobs_env  # noqa: F401

from common.error_handling import GenerationError
from services import story_jobs, story_service
from services import story_timeline as T
from services.story_models import Scene, Story, record_turns


def _tl_with_takes(lengths):
    tl = T.empty_timeline(1280, 720, 24)
    start = 0.0
    for i, n in enumerate(lengths):
        T.track(tl, "video")["clips"].append(
            {"id": f"v{i}", "src": f"c{i}.mp4", "scene": i, "start": start, "in": 0.0, "out": n}
        )
        start += n
    return tl


def _cut_story(n):
    # Cuts between the scenes: one take each.
    return Story(scenes=[Scene(duration=10, transition="cut") for _ in range(n)])


def test_film_music_plays_under_every_take_without_tracks():
    tl = _tl_with_takes([10, 10, 10])
    T.place_music(tl, _cut_story(3), "m.wav", total=30.0)
    (clip,) = T.track(tl, "music")["clips"]
    assert (clip["start"], clip["in"], clip["out"]) == (0.0, 0.0, 30.0)


def test_a_track_plays_under_its_takes_and_the_film_music_around_it():
    story = _cut_story(3)
    story.music_tracks_json = json.dumps(
        [{"id": "t1", "takes": [1], "prompt": "drums", "uri": "drums.wav"}]
    )
    tl = _tl_with_takes([10, 10, 10])
    T.place_music(tl, story, "m.wav", total=30.0)
    clips = T.track(tl, "music")["clips"]
    spans = [(c["src"], c["start"], c["start"] + c["out"] - c["in"]) for c in clips]
    assert spans == [("m.wav", 0.0, 10.5), ("drums.wav", 9.5, 20.5), ("m.wav", 19.5, 30.0)]
    # The film music picks up where it would have been.
    assert clips[2]["in"] == 19.5


def test_tracks_without_music_are_not_listed():
    story = Story(music_tracks_json='[{"id": "a", "takes": []}, {"id": "b", "takes": [0]}, 3]')
    assert [t["id"] for t in story.music_tracks()] == ["b"]
    assert Story(music_tracks_json="nope").music_tracks() == []


class _MusicMock(_FastMock):
    def __init__(self):
        super().__init__()
        self.music = []

    def generate_music(self, story, prompt, seconds):
        self.music.append((prompt, seconds))
        return f"local://m{len(self.music)}.wav"


def test_make_music_makes_the_tracks_too(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _MusicMock()
    story_service.set_backend(backend)
    story = _cut_story(3)
    story.music_tracks_json = json.dumps(
        [{"id": "t1", "takes": [1, 2], "prompt": "drums", "uri": ""}]
    )
    story = store.save(story, OWNER)
    job = _run(story_jobs.start_music(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert ("drums", 20.0) in backend.music
    saved = store.get(story.id, OWNER)
    assert saved.music_tracks()[0]["uri"].startswith("local://m")


def _ffmpeg():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _speech_like(path, volumes, noise=0.0):
    """A 1 kHz tone, on for 0.6 s of every second, at one volume per 10 s."""
    parts = []
    for k, v in enumerate(volumes):
        parts.append(
            f"aevalsrc='{v}*sin(2*PI*1000*t)*lt(mod(t,1),0.6)':s=16000:d=10[s{k}]"
        )
    concat = "".join(f"[s{k}]" for k in range(len(volumes)))
    graph = ";".join(parts) + f";{concat}concat=n={len(volumes)}:v=0:a=1[tone]"
    if noise:
        graph += f";anoisesrc=d={10 * len(volumes)}:a={noise}[n];[tone][n]amix=inputs=2:normalize=0[a]"
    else:
        graph += ";[tone]anull[a]"
    subprocess.run(
        [_ffmpeg(), "-v", "error", "-y", "-filter_complex", graph, "-map", "[a]", path],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture
def turns3():
    return json.loads(record_turns([10, 10, 10]))


def test_even_speech_passes_the_sound_checks(tmp_path, turns3):
    path = _speech_like(os.path.join(tmp_path, "even.wav"), [0.3, 0.3, 0.3])
    assert T.sound_flags(path, turns3) == []


def test_a_quiet_turn_is_flagged(tmp_path, turns3):
    path = _speech_like(os.path.join(tmp_path, "quiet.wav"), [0.3, 0.08, 0.3])
    (flag,) = T.sound_flags(path, turns3)
    assert flag["kind"] == "level" and flag["turn"] == 1 and flag["db"] < -4


def test_background_noise_is_flagged(tmp_path, turns3):
    path = _speech_like(os.path.join(tmp_path, "hiss.wav"), [0.3, 0.3, 0.3], noise=0.05)
    assert [f["kind"] for f in T.sound_flags(path, turns3)] == ["noise"]


class _ChainMock(_FastMock):
    def __init__(self):
        super().__init__()
        self.last_frames = []

    def last_frame(self, story, clip_uri, index):
        self.last_frames.append(index)
        return super().last_frame(story, clip_uri, index)


def test_a_long_continuous_scene_starts_each_take_from_the_last_frame(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _ChainMock()
    story_service.set_backend(backend)
    scenes = [
        Scene(duration=30, narration=f"Part {i}.", spoken=True, frame_uri=f"local://f{i}.png")
        for i in range(3)
    ]
    story = store.save(
        Story(approved=True, one_take=True, music_on=False, voice_on=False, scenes=scenes),
        OWNER,
    )
    assert story.chains_takes and not story.continuity
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert backend.last_frames[:2] == [1, 2]
    saved = store.get(story.id, OWNER)
    assert [bool(sc.continues_from) for sc in saved.scenes] == [False, True, True]


class _UpscaleMock(_FastMock):
    def __init__(self):
        super().__init__()
        self.upscaled = []

    def upscale_clip(self, story, index, resolution):
        self.upscaled.append((index, resolution))
        return f"local://{story.id}/up{index}-{resolution}.mp4"


def test_upscale_makes_every_clip_sharper_then_the_film(jobs_env):  # noqa: F811
    store, _ = jobs_env
    backend = _UpscaleMock()
    story_service.set_backend(backend)
    story = store.save(
        Story(
            approved=True,
            resolution="360p",
            video_model="gemini-omni-1.2-flash",
            music_on=False,
            voice_on=False,
            scenes=[
                Scene(duration=8, frame_uri="local://f.png", clip_uri="local://c.mp4",
                      turns_json=record_turns([8]))
            ],
        ),
        OWNER,
    )
    job = _run(story_jobs.start_upscale(story.id, OWNER, "720p"))
    assert job.status == "done", [t.error for t in job.tasks]
    assert backend.upscaled == [(0, "720p")]
    saved = store.get(story.id, OWNER)
    assert saved.resolution == "720p"
    assert saved.scenes[0].clip_uri.endswith("up0-720p.mp4")
    assert saved.scenes[0].turns()  # same take: the records stay
    snap = story_jobs.job_snapshot(job.id, OWNER)
    film = _run(story_jobs.get_job(snap["next_job"], OWNER))
    assert film.kind == "video" and film.status == "done"


def test_a_film_without_clips_cannot_be_upscaled(jobs_env):  # noqa: F811
    store, _ = jobs_env
    story = store.save(Story(scenes=[Scene(duration=8)]), OWNER)
    with pytest.raises(GenerationError):
        story_jobs.start_upscale(story.id, OWNER, "720p")


def test_a_draft_offers_sharper_versions():
    import pages.story_studio as page

    draft = Story(resolution="360p", video_model="gemini-omni-1.2-flash",
                  scenes=[Scene(duration=30)])
    assert [r for r, _ in page._upscale_options(draft)] == ["720p", "1080p"]
    sharp = Story(resolution="1080p", video_model="gemini-omni-1.2-flash",
                  scenes=[Scene(duration=30)])
    assert page._upscale_options(sharp) == []


def test_a_take_has_one_track():
    story = Story(
        music_tracks_json=json.dumps(
            [{"id": "a", "takes": [0, 1]}, {"id": "b", "takes": [1]}, {"id": "c", "takes": [1, 2]}]
        )
    )
    assert [(t["id"], t["takes"]) for t in story.music_tracks()] == [("a", [0, 1]), ("c", [2])]
