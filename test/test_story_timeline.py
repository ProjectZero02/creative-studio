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
"""Story Studio timeline: validation, layout, building, rendering, export."""

import json
import shutil
import subprocess

import pytest

from services import story_jobs, story_service, story_store
from services import story_timeline as T
from services.story_models import Scene, Story, build_stitch_plan

OWNER = "owner@example.com"


def _ff() -> str:
    return T._ffmpeg()


def _clip(path, color, freq, secs=2.0):
    subprocess.run(
        [_ff(), "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c={color}:s=320x180:r=12:d={secs}", "-f", "lavfi", "-i",
         f"sine=f={freq}:d={secs}", "-shortest", "-c:v", "libx264", "-c:a", "aac",
         str(path)],
        check=True,
    )
    return str(path)


# -- normalize -----------------------------------------------------------------


def test_normalize_lays_video_end_to_end_with_crossfades():
    tl = T.empty_timeline()
    T.track(tl, "video")["clips"] = [
        {"src": "a", "in": 0, "out": 4, "start": 99},
        {"src": "b", "in": 1, "out": 5, "fade_in": 0.5},
        {"src": "c", "in": 0, "out": 2},
    ]
    out = T.normalize(tl)
    starts = [(c["start"], c["fade_in"]) for c in T.track(out, "video")["clips"]]
    assert starts == [(0.0, 0.0), (3.5, 0.5), (7.5, 0.0)]
    assert T.duration(out) == 9.5


def test_normalize_drops_bad_input_and_clamps_numbers():
    raw = {
        "width": 99999,
        "tracks": [
            {"kind": "video", "clips": [{"src": "a", "in": 0, "out": 3, "gain": 50}, {"in": 0}]},
            {"kind": "evil", "clips": [{"src": "x"}]},
            {"kind": "text", "clips": [{"text": "  ", "start": 1}, {"text": "Hi", "pos": "nowhere", "dur": -4}]},
        ],
    }
    out = T.normalize(json.dumps(raw))
    assert out["width"] == 3840
    assert [t["kind"] for t in out["tracks"]] == ["video", "voice", "music", "text"]
    vids = T.track(out, "video")["clips"]
    assert len(vids) == 1 and vids[0]["gain"] == T.MAX_GAIN
    texts = T.track(out, "text")["clips"]
    assert len(texts) == 1 and texts[0]["pos"] == "bottom" and texts[0]["dur"] == 0.2
    assert T.normalize("not json")["tracks"][0]["clips"] == []


def test_voice_tempo_changes_clip_length():
    assert T.clip_length({"in": 0, "out": 2.16, "tempo": 1.08}) == pytest.approx(2.0)


def test_gain_to_levels_loudness():
    assert T.gain_to(-20.0) == 1.0
    assert T.gain_to(-26.0) == pytest.approx(2.0, rel=0.01)
    assert T.gain_to(None) == 1.0
    assert T.gain_to(-80.0) == T.MAX_GAIN


def test_clip_gain_keeps_omni_sound_low_under_the_narrator():
    # Spoken clips: dialogue level (-20 LUFS).
    assert T.clip_gain(-20.0, spoken=True) == 1.0
    # Narrated clips: Omni's own sound stays, as an ambient bed at -30 LUFS.
    assert T.clip_gain(-14.0, spoken=False) == pytest.approx(10 ** (-16 / 20), rel=0.01)
    assert T.clip_gain(-30.0, spoken=False) == 1.0
    assert 0 < T.clip_gain(-5.0, spoken=False) < 0.1  # never muted outright
    assert T.clip_gain(None, spoken=False) == T.AMBIENT_GAIN


# -- building -------------------------------------------------------------------


def _scenes(n, spoken=()):
    return [
        Scene(
            clip_uri=f"c{i}",
            duration=4,
            narration=f"line {i}",
            spoken=i in spoken,
        )
        for i in range(n)
    ]


def test_build_timeline_keeps_speech_and_places_narration():
    scenes = _scenes(3, spoken={1})
    plan = build_stitch_plan(scenes, 0.5)
    tl = T.build_timeline(
        Story(scenes=scenes),
        plan,
        width=1280,
        height=720,
        voice_uris={0: "v0", 2: "v2"},
        voice_lengths={0: 1.5, 2: 9.0},
        clip_gains={0: 0.16, 1: 1.7},
        music_uri="m",
        music_length=30,
    )
    vids = T.track(tl, "video")["clips"]
    # Every clip keeps its own sound: narrated clips as an ambient bed (the
    # measured gain, or the default when unmeasured), the spoken one at
    # dialogue level.
    assert [c["gain"] for c in vids] == [0.16, 1.7, T.AMBIENT_GAIN]
    assert [bool(c.get("ambient")) for c in vids] == [True, False, True]
    voices = T.track(tl, "voice")["clips"]
    assert [v["src"] for v in voices] == ["v0", "v2"]
    # A long line is cut to fit its scene.
    assert T.clip_end(voices[1]) <= T.clip_end(vids[2])
    music = T.track(tl, "music")["clips"][0]
    assert music["out"] == T.duration(tl)


def test_ambient_flag_survives_normalize():
    tl = T.empty_timeline()
    T.track(tl, "video")["clips"] = [{"src": "a", "in": 0, "out": 2, "ambient": 1}, {"src": "b", "in": 0, "out": 2}]
    vids = T.track(T.normalize(tl), "video")["clips"]
    assert vids[0]["ambient"] is True and "ambient" not in vids[1]


def test_ambient_bed_neither_ducks_nor_is_ducked():
    tl = T.empty_timeline(320, 180, 12)
    T.track(tl, "video")["clips"] = [
        {"src": "a", "in": 0, "out": 2, "gain": 0.2, "ambient": True},
        {"src": "b", "in": 0, "out": 2, "gain": 1.0},
    ]
    T.track(tl, "voice")["clips"] = [{"src": "v", "in": 0, "out": 1, "start": 0.3}]
    T.track(tl, "music")["clips"] = [{"src": "m", "in": 0, "out": 4}]
    tl = T.normalize(tl)
    args = T.render_args(
        tl, {s: s for s in "abvm"}, {s: True for s in "abvm"}, {}, "out.mp4"
    )
    graph = args[args.index("-filter_complex") + 1]
    dialogue_mix = next(f for f in graph.split(";") if f.endswith("[dlg]"))
    final_mix = next(f for f in graph.split(";") if f.endswith("[mix]"))
    # The narrated clip's sound (d0) is mixed after the ducking; the spoken
    # clip (d1) and the narrator (s0) drive the music ducking.
    assert "[d0]" not in dialogue_mix and "[d1]" in dialogue_mix and "[s0]" in dialogue_mix
    assert "sidechaincompress" in graph and "[d0]" in final_mix


def test_keep_edits_carries_text_and_music_level():
    old = T.empty_timeline()
    T.track(old, "video")["clips"] = [{"src": "a", "in": 0, "out": 2}]
    T.track(old, "text")["clips"] = [{"text": "Title", "start": 0, "dur": 2}]
    T.track(old, "music")["clips"] = [{"src": "m", "in": 0, "out": 2, "gain": 0.3}]
    T.track(old, "music")["duck"] = False
    new = T.empty_timeline()
    T.track(new, "music")["clips"] = [{"src": "m2", "in": 0, "out": 2, "gain": 0.8}]
    out = T.keep_edits(new, json.dumps(old))
    assert T.track(out, "text")["clips"][0]["text"] == "Title"
    assert T.track(out, "music")["clips"][0]["gain"] == 0.3
    assert T.track(out, "music")["duck"] is False


# -- continuous takes in the stitch plan ------------------------------------


def test_extended_clip_skips_the_repeated_seconds_and_cuts():
    a = Scene(clip_uri="a", duration=8, spoken=True, narration="x")
    b = Scene(
        clip_uri="b", duration=7, spoken=True, narration="y", extends_from="a", clip_in=8.0
    )
    plan = build_stitch_plan([a, b], 0.5, clip_durations=[8.0, 15.0])
    seg = plan.segments[1]
    assert (seg.start, seg.fade_in, seg.trim_head, seg.duration) == (8.0, 0.0, 8.0, 7.0)
    assert plan.total == 15.0


def test_stale_extension_still_trims_old_seconds():
    a = Scene(clip_uri="a-new", duration=8)
    b = Scene(clip_uri="b", duration=7, extends_from="a-old", clip_in=8.0)
    plan = build_stitch_plan([a, b], 0.5, clip_durations=[8.0, 15.0])
    assert plan.segments[1].trim_head == 8.0


def test_take_is_cut_after_the_take_cap():
    """Omni continues a thread up to STORY_TAKE_MAX_SECONDS (30 s): two 15 s
    spoken scenes are one take, the third starts a new one."""
    from config.default import Default

    assert Default.__dataclass_fields__["STORY_TAKE_MAX_SECONDS"].default == 30
    s = Story(
        scenes=[Scene(spoken=True, narration=f"line {i}", duration=d) for i, d in enumerate([15, 15, 10, 10])]
    )
    assert [s.continues_take(i) for i in range(4)] == [False, True, False, True]
    assert [s.take_start(i) for i in range(4)] == [0, 0, 2, 2]


def test_clear_clip_forgets_the_omni_thread():
    sc = Scene(clip_uri="c", extends_from="b", clip_in=8.0, interaction_id="int-1")
    sc.clear_clip()
    assert (sc.clip_uri, sc.extends_from, sc.clip_in, sc.interaction_id) == ("", "", 0.0, "")


def test_continues_take_needs_two_spoken_scenes():
    s = Story(scenes=[Scene(spoken=True, narration="a"), Scene(spoken=True, narration="b")])
    assert s.continues_take(1) and not s.continues_take(0)
    s.continuous_takes = False
    assert not s.continues_take(1)
    s = Story(scenes=[Scene(spoken=True, narration="a"), Scene(narration="b")])
    assert not s.continues_take(1)


# -- rendering --------------------------------------------------------------------


def test_render_timeline_mixes_ducks_and_normalizes(tmp_path):
    a, b = _clip(tmp_path / "a.mp4", "red", 440), _clip(tmp_path / "b.mp4", "blue", 660)
    music = tmp_path / "m.wav"
    subprocess.run(
        [_ff(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=1", str(music)],
        check=True,
    )
    tl = T.empty_timeline(320, 180, 12)
    T.track(tl, "video")["clips"] = [
        {"src": a, "in": 0, "out": 2, "gain": 1},
        {"src": b, "in": 0.5, "out": 2, "gain": 1, "fade_in": 0.5},
    ]
    T.track(tl, "music")["clips"] = [{"src": str(music), "in": 0, "out": 3}]
    T.track(tl, "text")["clips"] = [{"text": "Hello", "start": 0.5, "dur": 1}]
    out = T.render_timeline(tl, lambda u, p: shutil.copyfile(u, p), str(tmp_path / "f.mp4"))
    secs, has_audio = T.probe(out)
    assert secs == pytest.approx(3.0, abs=0.15) and has_audio
    assert T.measure_lufs(out) == pytest.approx(T.MASTER_LUFS, abs=2.0)


def test_render_timeline_without_video_fails(tmp_path):
    from common.error_handling import GenerationError

    with pytest.raises(GenerationError):
        T.render_timeline(T.empty_timeline(), shutil.copyfile, str(tmp_path / "x.mp4"))


# -- jobs (demo backend, real ffmpeg) -------------------------------------------


@pytest.fixture
def demo(tmp_path, monkeypatch):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    story_store.set_store(store)
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    backend = story_service.MockStoryBackend(speed=0)
    story_service.set_backend(backend)
    yield store, backend
    story_service.set_backend(None)
    story_store.set_store(None)


def _wait(job):
    done = story_jobs.wait(job.id, OWNER, timeout=120)
    assert done is not None and done.status == "done", [(t.label, t.error) for t in done.tasks]
    return done


def test_render_writes_timeline_then_export_uses_edits(demo):
    store, backend = demo
    story = Story(idea="A presenter on stage", scene_count=2, duration=4, music_on=True)
    story = store.save(story, OWNER)
    frames = [backend.generate_frame(story, i, "") for i in range(2)]
    story.scenes = [
        Scene(narration="Hello there.", spoken=True, duration=4, frame_uri=frames[0]),
        Scene(narration="It begins.", duration=4, frame_uri=frames[1]),
    ]
    story.approved = True
    store.save(story, OWNER)

    _wait(story_jobs.start_video(story.id, OWNER))
    s = store.get(story.id, OWNER)
    assert s.final_uri and s.timeline_json and s.music_uri and s.seed
    tl = json.loads(s.timeline_json)
    assert len(T.track(tl, "video")["clips"]) == 2
    assert T.track(tl, "music")["clips"][0]["src"] == s.music_uri

    # The user adds a title and turns the music down, then exports.
    T.track(tl, "text")["clips"].append({"text": "My film", "start": 0, "dur": 2})
    T.track(tl, "music")["clips"][0]["gain"] = 0.2
    story_jobs.save_timeline(story.id, OWNER, json.dumps(tl))
    first = s.final_uri
    _wait(story_jobs.start_export(story.id, OWNER))
    s = store.get(story.id, OWNER)
    assert s.final_uri and s.final_uri != first
    assert T.probe(story_service.local_path(s.final_uri))[0] > 6

    # Rendering the scenes again keeps the user's title and music level.
    _wait(story_jobs.start_video(story.id, OWNER))
    tl = json.loads(store.get(story.id, OWNER).timeline_json)
    assert T.track(tl, "text")["clips"][0]["text"] == "My film"
    assert T.track(tl, "music")["clips"][0]["gain"] == 0.2


def test_export_needs_a_rendered_film(demo):
    store, _ = demo
    s = store.save(Story(), OWNER)
    from common.error_handling import GenerationError

    with pytest.raises(GenerationError):
        story_jobs.start_export(s.id, OWNER)


class _TakeMock(story_service.MockStoryBackend):
    def __init__(self):
        super().__init__(speed=0)
        self.extended = []

    def generate_clip(self, story, index, start_frame_uri):
        return f"local://{story.id}/clip{index}.mp4"

    def extend_clip(self, story, index, prev_clip_uri):
        self.extended.append((index, prev_clip_uri, story.scenes[index - 1].interaction_id))
        return f"local://{story.id}/take{index}.mp4", 8.0

    def interaction_of(self, clip_uri):
        return "int-" + clip_uri.rsplit("/", 1)[-1]

    def generate_voiceover(self, story, index, text):
        return f"local://v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        self.plan = plan
        return "local://film.mp4", T.empty_timeline()


def test_back_to_back_spoken_scenes_extend_the_previous_clip(demo):
    store, _ = demo
    backend = _TakeMock()
    story_service.set_backend(backend)
    scenes = [
        Scene(narration="One.", spoken=True, frame_uri="local://f0"),
        Scene(narration="Two.", spoken=True, frame_uri="local://f1"),
        Scene(narration="Three.", frame_uri="local://f2"),
    ]
    s = store.save(Story(approved=True, scenes=scenes, music_on=False), OWNER)
    job = _wait(story_jobs.start_video(s.id, OWNER))
    assert "same take as scene 1" in [t.label for t in job.tasks if t.scene_index == 1][0]
    # The continuation sees the first clip's saved Omni thread.
    assert backend.extended == [(1, f"local://{s.id}/clip0.mp4", "int-clip0.mp4")]
    s = store.get(s.id, OWNER)
    assert s.scenes[1].extends_from == s.scenes[0].clip_uri and s.scenes[1].clip_in == 8.0
    assert [sc.interaction_id for sc in s.scenes] == ["int-clip0.mp4", "int-take1.mp4", "int-clip2.mp4"]
    assert backend.plan.segments[1].trim_head == 8.0


def test_mock_backend_has_no_thread(demo):
    _, backend = demo
    assert backend.interaction_of("local://x.mp4") == ""


def test_failed_extension_falls_back_to_a_normal_clip(demo):
    store, _ = demo
    backend = _TakeMock()

    def boom(story, index, prev):
        raise RuntimeError("extension not supported")

    backend.extend_clip = boom
    story_service.set_backend(backend)
    scenes = [
        Scene(narration="One.", spoken=True, frame_uri="local://f0"),
        Scene(narration="Two.", spoken=True, frame_uri="local://f1"),
    ]
    s = store.save(Story(approved=True, scenes=scenes, music_on=False), OWNER)
    _wait(story_jobs.start_video(s.id, OWNER))
    s = store.get(s.id, OWNER)
    assert s.scenes[1].clip_uri.endswith("clip1.mp4") and not s.scenes[1].extends_from
