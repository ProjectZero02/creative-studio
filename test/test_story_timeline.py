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
    """Omni returns up to 40 s but reads only the last 30 s of its input: a
    take grows while it is at most 30 s long and stays within 40 s."""
    from config.default import Default

    fields = Default.__dataclass_fields__
    assert fields["STORY_TAKE_MAX_SECONDS"].default == 40
    assert fields["STORY_TAKE_CONTEXT_SECONDS"].default == 30
    s = Story(
        scenes=[Scene(spoken=True, narration=f"line {i}", duration=d) for i, d in enumerate([15, 15, 10, 15])]
    )
    # The 4th scene is too long for one rolling extension (10 s of new
    # seconds on top of the 30 s the model reads): a new take.
    assert [s.continues_take(i) for i in range(4)] == [False, True, True, False]
    assert [s.take_start(i) for i in range(4)] == [0, 0, 0, 3]
    # A 10 s scene rolls the take on past 40 s.
    s.scenes[3].duration = 10
    assert s.continues_take(3)
    # The live test: four 8 s shots are one 32 s take (24 s before the last).
    s = Story(scenes=[Scene(spoken=True, narration=f"l{i}", duration=8) for i in range(4)])
    assert [s.continues_take(i) for i in range(4)] == [False, True, True, True]


def test_join_picker_decides_the_take():
    """Extend joins even without speech; Cut, Bridge, Dissolve and Fade
    black always start a new shot; Auto joins two spoken scenes."""
    s = Story(scenes=[Scene(duration=8), Scene(duration=8, transition="extend")])
    assert s.continues_take(1)
    for t in ("cut", "bridge", "dissolve", "fade_black"):
        s = Story(
            scenes=[
                Scene(spoken=True, narration="a", duration=8),
                Scene(spoken=True, narration="b", duration=8, transition=t),
            ]
        )
        assert not s.continues_take(1), t


def test_a_take_is_cut_from_its_last_file():
    """Each extension returns the whole take so far: every scene of the take
    is cut from the last file at its own offset, so nothing switches files."""
    a = Scene(clip_uri="c1", duration=8)
    b = Scene(clip_uri="c2", duration=8, extends_from="c1", clip_in=8.0)
    c = Scene(clip_uri="c3", duration=8, extends_from="c2", clip_in=16.0)
    d = Scene(clip_uri="c4", duration=8)
    plan = build_stitch_plan([a, b, c, d], 0.0, seamless=True)
    assert [s.clip_uri for s in plan.segments] == ["c3", "c3", "c3", "c4"]
    assert [s.trim_head for s in plan.segments[:3]] == [0.0, 8.0, 16.0]
    assert [s.start for s in plan.segments] == [0.0, 8.0, 16.0, 24.0]
    # A scene only set to Extend, but made as its own clip, keeps its file.
    e = Scene(clip_uri="c5", duration=8, transition="extend")
    plan = build_stitch_plan([d, e], 0.0, seamless=True)
    assert [s.clip_uri for s in plan.segments] == ["c4", "c5"]


def test_a_rolling_take_uses_the_newest_file_that_holds_each_scene():
    """Past the model's 30 s context, an extension returns the last 30 s
    plus the new seconds. Five 8 s scenes: file 4 holds 0-32 s (one file so
    far); file 5 holds 2-40 s. Scenes 1-4 come from file 4, and the film
    crossfades into file 5 for scene 5, inside the overlap where both files
    show the same moment: one change of file in the whole take."""
    from config.default import Default

    xf = Default.__dataclass_fields__["STORY_ROLL_CROSSFADE"].default
    scenes = [Scene(clip_uri="c1", duration=8)]
    scenes += [
        Scene(clip_uri=f"c{k}", duration=8, extends_from=f"c{k - 1}", clip_in=float(8 * (k - 1)))
        for k in (2, 3, 4)
    ]
    # File 5 holds 30 s of the take (2-32 s) before its new seconds.
    scenes.append(Scene(clip_uri="c5", duration=8, extends_from="c4", clip_in=30.0))
    plan = build_stitch_plan(scenes, 0.0, seamless=True)
    segs = plan.segments
    assert [s.clip_uri for s in segs] == ["c4", "c4", "c4", "c4", "c5"]
    assert [s.trim_head for s in segs[:4]] == [0.0, 8.0, 16.0, 24.0]
    assert segs[4].start == round(32.0 - xf, 3)
    assert segs[4].trim_head == round(30.0 - xf, 4) and segs[4].fade_in == xf
    assert plan.total == 40.0


def test_extension_offset_finds_the_new_seconds():
    from services.story_service import extension_offset

    # Whole input returned plus 8 new seconds.
    assert extension_offset(24.0, 32.0, 8.0) == 24.0
    # A 38 s input: the model keeps its last 30 s and adds 8.
    assert extension_offset(38.0, 38.04, 8.0) == 30.0
    # Only the new seconds came back.
    assert extension_offset(24.0, 8.0, 8.0) == 0.0


def test_only_seamless_joins_count_as_jumps(monkeypatch):
    from services import story_timeline

    changes = [(k / 24, 0.001) for k in range(240)]
    changes[96] = (4.0, 0.2)  # a jump at 4 s
    changes[192] = (8.0, 0.3)  # a planned cut at 8 s
    monkeypatch.setattr(story_timeline, "frame_changes", lambda path: changes)
    report = story_timeline.seam_check(
        "film.mp4",
        [
            {"t": 4.0, "scene": 1, "seamless": True},
            {"t": 8.0, "scene": 2, "seamless": False},
        ],
    )
    assert [(r["scene"], r["jump"]) for r in report] == [(1, True), (2, False)]


def test_seams_to_redo_only_remakes_the_end_of_a_take():
    from services.story_jobs import seams_to_redo

    s = Story(scenes=[Scene(spoken=True, narration=f"l{i}", duration=8) for i in range(4)])
    s.scenes[3].transition = "cut"
    seams = [{"scene": 1, "jump": True}, {"scene": 2, "jump": True}, {"scene": 3, "jump": False}]
    # Scene 2 is the take's last; scene 1 has scene 2 built on it.
    assert seams_to_redo(s, seams) == [2]


def test_sound_crosses_at_a_cut():
    """The outgoing clip's sound runs JOIN_FADE past the cut, under the
    incoming one, instead of both fading to a dip."""
    from services import story_timeline as st

    tl = st.empty_timeline()
    st.track(tl, "video")["clips"] = [
        {"id": "a", "src": "a", "start": 0.0, "in": 0.0, "out": 8.0, "src_max": 9.0, "gain": 1.0, "fade_in": 0, "join": "cut"},
        {"id": "b", "src": "b", "start": 8.0, "in": 0.0, "out": 8.0, "src_max": 8.0, "gain": 1.0, "fade_in": 0, "join": "cut"},
    ]
    args = st.render_args(tl, {"a": "a.mp4", "b": "b.mp4"}, {"a": True, "b": True}, {}, "out.mp4")
    graph = args[args.index("-filter_complex") + 1]
    assert f"atrim=start=0.000:end={8.0 + st.JOIN_FADE:.3f}" in graph
    assert "atrim=start=0.000:end=8.000" in graph  # the last clip has no tail


def test_render_plays_a_take_straight_through():
    """Back-to-back pieces of one file render as one piece (one trim, one
    sound chain), so nothing is cut or faded at the join."""
    from services.story_timeline import merge_runs

    clips = [
        {"src": "t", "start": 0.0, "in": 0.0, "out": 8.0, "gain": 1.0, "fade_in": 0},
        {"src": "t", "start": 8.0, "in": 8.0, "out": 16.0, "gain": 1.0, "fade_in": 0},
        {"src": "t", "start": 16.0, "in": 16.04, "out": 24.0, "gain": 1.0, "fade_in": 0},
        {"src": "u", "start": 24.0, "in": 0.0, "out": 8.0, "gain": 1.0, "fade_in": 0},
        {"src": "u", "start": 32.0, "in": 3.0, "out": 5.0, "gain": 1.0, "fade_in": 0},
    ]
    runs = merge_runs(clips, 24)
    assert [(r["src"], r["in"], r["out"]) for r in runs] == [
        ("t", 0.0, 24.0),
        ("u", 0.0, 8.0),
        ("u", 3.0, 5.0),
    ]


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
    assert store.get(story.id, OWNER).film_edited  # Download is the old film
    first = s.final_uri
    _wait(story_jobs.start_export(story.id, OWNER))
    s = store.get(story.id, OWNER)
    assert s.final_uri and s.final_uri != first
    assert not s.film_edited
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


# -- voice lines and music follow the scenes -----------------------------------


def _scenes_tl():
    """Three 6 s scenes, a line in each (0.5 s in), music over the film."""
    tl = T.empty_timeline()
    T.track(tl, "video")["clips"] = [
        {
            "id": f"v{i}",
            "src": f"c{i}",
            "in": 0,
            "out": 6,
            "src_max": 6,
            "scene": i,
            "label": f"Scene {i + 1}",
        }
        for i in range(3)
    ]
    T.track(tl, "voice")["clips"] = [
        {
            "id": f"a{i}",
            "src": f"n{i}",
            "start": i * 6 + 0.5,
            "in": 0,
            "out": 3,
            "scene": i,
        }
        for i in range(3)
    ]
    T.track(tl, "music")["clips"] = [
        {"id": "m", "src": "m", "start": 0, "in": 0, "out": 18}
    ]
    return T.normalize(tl)


def _starts(tl, kind):
    return {c.get("scene", c["id"]): c["start"] for c in T.track(tl, kind)["clips"]}


def test_lines_move_with_reordered_scenes():
    prev = _scenes_tl()
    cur = json.loads(json.dumps(prev))
    v = T.track(cur, "video")["clips"]
    v[1], v[2] = v[2], v[1]
    T._layout_video(v)
    T.follow_scenes(prev, cur)
    assert _starts(cur, "voice") == {0: 0.5, 2: 6.5, 1: 12.5}


def test_a_deleted_scene_takes_its_line_and_music_fits():
    prev = _scenes_tl()
    cur = json.loads(json.dumps(prev))
    T.track(cur, "video")["clips"].pop(1)
    T._layout_video(T.track(cur, "video")["clips"])
    T.follow_scenes(prev, cur)
    assert _starts(cur, "voice") == {0: 0.5, 2: 6.5}
    music = T.track(cur, "music")["clips"][0]
    assert T.clip_end(music) == T.duration(cur) == 12


def test_trimming_a_scene_head_keeps_its_line_on_the_picture():
    prev = _scenes_tl()
    cur = json.loads(json.dumps(prev))
    T.track(cur, "video")["clips"][1]["in"] = 2.0  # cut 2 s off scene 2's start
    T._layout_video(T.track(cur, "video")["clips"])
    T.follow_scenes(prev, cur)
    # Scene 2's line started 0.5 s into its clip; that moment is now 1.5 s
    # before the trimmed clip starts. Scene 3 moves 2 s earlier with its line.
    assert _starts(cur, "voice") == {0: 0.5, 1: 4.5, 2: 10.5}


def test_lines_without_a_scene_are_linked_by_where_they_sit():
    prev = _scenes_tl()
    for c in T.track(prev, "voice")["clips"]:
        c.pop("scene")
    cur = json.loads(json.dumps(prev))
    v = T.track(cur, "video")["clips"]
    v[0], v[2] = v[2], v[0]
    T._layout_video(v)
    T.follow_scenes(prev, cur)
    assert sorted(c["scene"] for c in T.track(cur, "voice")["clips"]) == [0, 1, 2]
    assert _starts(cur, "voice")[0] == 12.5


def test_normalize_keeps_a_lines_scene_and_build_sets_it():
    out = T.normalize(_scenes_tl())
    assert [c["scene"] for c in T.track(out, "voice")["clips"]] == [0, 1, 2]


def test_rerender_keeps_order_trims_and_transitions():
    old = _scenes_tl()
    v = T.track(old, "video")["clips"]
    v[0], v[2] = v[2], v[0]  # scene 3 first
    v[1]["out"] = 4.0  # scene 2 trimmed to 4 s
    v[1]["fade_in"], v[2]["fade_in"] = 0.5, 0.0
    v[1]["gain"] = 0.4
    # The editor moves each line with its scene, as it does on every edit.
    old = T.follow_scenes(_scenes_tl(), T.normalize(old))
    new = _scenes_tl()  # a fresh render in story order, same clips
    out = T.keep_edits(new, json.dumps(old))
    vids = T.track(out, "video")["clips"]
    assert [c["scene"] for c in vids] == [2, 1, 0]
    assert vids[1]["out"] == 4.0 and vids[1]["gain"] == 0.4
    assert [c["fade_in"] for c in vids] == [0.0, 0.5, 0.0]
    # Each line follows its scene into the new order.
    starts = _starts(out, "voice")
    assert starts[2] == 0.5 and starts[0] == vids[2]["start"] + 0.5


def test_rerender_with_a_remade_clip_starts_that_scene_fresh():
    old = _scenes_tl()
    T.track(old, "video")["clips"][1]["out"] = 3.0
    new = _scenes_tl()
    T.track(new, "video")["clips"][1]["src"] = "c1-new"
    out = T.keep_edits(new, json.dumps(T.normalize(old)))
    assert T.track(out, "video")["clips"][1]["out"] == 6


# -- clean cuts: picture length, frozen edges, no black frames ------------------


def _still_then_moving(path, still=1.0, moving=3.0, sound=None):
    """A clip whose first ``still`` seconds are one frozen frame, then
    movement; its sound runs ``sound`` seconds (longer than the picture)."""
    sound = sound or still + moving
    subprocess.run(
        [
            _ff(),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:d={sound}",
            "-filter_complex",
            f"color=c=red:s=320x180:r=12:d={still}[a];"
            f"testsrc=s=320x180:r=12:d={moving}[b];[a][b]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return str(path)


def test_clip_edges_measures_the_picture_and_its_frozen_head(tmp_path):
    path = _still_then_moving(tmp_path / "c.mp4", still=1.0, moving=3.0, sound=5.0)
    assert T.probe(path)[0] == pytest.approx(5.0, abs=0.1)  # the file, with its sound
    length, head, tail = T.clip_edges(path)
    assert length == pytest.approx(4.0, abs=0.1)  # the picture alone
    assert head == pytest.approx(1.0, abs=0.15) and tail == 0


def test_clip_edges_never_cuts_into_speech(tmp_path):
    # Spoken clip: sound plays over the frozen head, so it stays.
    path = _still_then_moving(tmp_path / "c.mp4", still=1.0, moving=3.0)
    assert T.clip_edges(path, spoken=True)[1] == 0


def test_clip_edges_caps_the_trim_and_keeps_enough_clip(tmp_path):
    path = _still_then_moving(tmp_path / "c.mp4", still=2.0, moving=1.5)
    length, head, _ = T.clip_edges(path)
    assert head <= T.STILL_CAP and length - head >= T.MIN_KEEP - 0.01


def test_build_timeline_trims_frozen_heads_and_tails():
    plan = build_stitch_plan(_scenes(2), 0.0)
    tl = T.build_timeline(
        Story(scenes=_scenes(2)),
        plan,
        width=1280,
        height=720,
        clip_lengths={0: 4.0, 1: 4.0},
        clip_stills={0: (0.8, 0.0), 1: (0.0, 0.5)},
    )
    first, second = T.track(tl, "video")["clips"]
    assert (first["in"], first["out"]) == (0.8, 4.0)
    assert (second["in"], second["out"]) == (0.0, 3.5)


def test_a_clip_shorter_than_its_slot_holds_its_last_frame(tmp_path):
    # Picture 1.5 s, sound 2.5 s: the slot asks for 2.5 s of picture. The
    # gap must hold the last frame, not show the black canvas.
    a = _still_then_moving(tmp_path / "a.mp4", still=0.5, moving=1.0, sound=2.5)
    b = _clip(tmp_path / "b.mp4", "blue", 660)
    tl = T.empty_timeline(320, 180, 12)
    T.track(tl, "video")["clips"] = [
        {"src": a, "in": 0, "out": 2.5, "gain": 1},
        {"src": b, "in": 0, "out": 2, "gain": 1},
    ]
    out = T.render_timeline(
        tl, lambda u, p: shutil.copyfile(u, p), str(tmp_path / "f.mp4")
    )
    err = subprocess.run(
        [
            _ff(),
            "-hide_banner",
            "-i",
            out,
            "-vf",
            "blackdetect=d=0.04:pix_th=0.05",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    assert "black_start" not in err


def test_clip_sound_eases_in_and_out_at_cuts():
    tl = T.empty_timeline(320, 180, 12)
    T.track(tl, "video")["clips"] = [
        {"src": "a", "in": 0, "out": 2, "gain": 1.0},
        {"src": "b", "in": 0, "out": 2, "gain": 1.0},
    ]
    args = T.render_args(
        T.normalize(tl), {"a": "a", "b": "b"}, {"a": True, "b": True}, {}, "o.mp4"
    )
    graph = args[args.index("-filter_complex") + 1]
    assert f"afade=t=in:st=0:d={T.JOIN_FADE:.3f}" in graph
    assert "tpad=stop_mode=clone" in graph


def _dark_frames(path):
    import re

    err = subprocess.run(
        [
            _ff(),
            "-hide_banner",
            "-i",
            path,
            "-vf",
            "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stderr
    values = [float(v) for v in re.findall(r"YAVG=([\d.]+)", err)]
    return sum(1 for v in values if v < 25), len(values)


def test_joins_between_frames_never_show_black(tmp_path):
    # A continuous take's offsets (6.04, 12.03) put cuts between two frames
    # at 24 fps (11.96 s). Every output frame must still show a clip,
    # including the last one.
    a = _clip(tmp_path / "a.mp4", "red", 440, secs=6.0)
    b = _clip(tmp_path / "b.mp4", "blue", 660, secs=12.0)
    c = _clip(tmp_path / "c.mp4", "green", 550, secs=18.0)
    tl = T.empty_timeline(320, 180, 24)
    T.track(tl, "video")["clips"] = [
        {"src": a, "in": 0, "out": 6.0, "gain": 0},
        {"src": b, "in": 6.04, "out": 12.0, "gain": 0},
        {"src": c, "in": 12.03, "out": 18.0, "gain": 0},
    ]
    out = T.render_timeline(
        tl, lambda u, p: shutil.copyfile(u, p), str(tmp_path / "f.mp4")
    )
    dark, total = _dark_frames(out)
    assert total == round(17.93 * 24) and dark == 0
