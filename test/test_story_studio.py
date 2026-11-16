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
"""Story Studio: scenario parsing, caps, steps, stitching, owner-only access, jobs."""

import json
from types import SimpleNamespace

import pytest

from services import story_jobs, story_models, story_service, story_store
from services.story_models import (
    ScenarioError,
    Scene,
    Story,
    apply_caps,
    build_stitch_plan,
    can_enter,
    furthest_step,
    normalize_camera,
    parse_scenario,
    parse_single_scene,
    reachable_steps,
)

OWNER = "alice@example.com"
OTHER = "mallory@example.com"


def _caps_cfg(**over):
    base = dict(
        STORY_MIN_SCENES=3,
        STORY_MAX_SCENES=8,
        STORY_MAX_FILM_SECONDS=64,
        STORY_VIDEO_RESOLUTION="720p",
        STORY_VEO_MODEL_VERSION="3.1-fast",
    )
    base.update(over)
    return lambda: SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Scenario parsing
# ---------------------------------------------------------------------------


def _scenario(n=3, **scene_over):
    scenes = [
        {
            "narration": f"Line {i}",
            "visual": f"Visual {i}",
            "camera": "dolly in",
            **scene_over,
        }
        for i in range(n)
    ]
    return json.dumps({"title": "The Whale", "scenes": scenes})


def test_parse_scenario_valid():
    title, scenes = parse_scenario(_scenario(3), 3, 6)
    assert title == "The Whale"
    assert [s.narration for s in scenes] == ["Line 0", "Line 1", "Line 2"]
    assert all(s.camera == "dolly_in" and s.duration == 6 for s in scenes)
    assert len({s.id for s in scenes}) == 3


def test_parse_scenario_strips_code_fences_and_drops_extra_scenes():
    text = "Here you go:\n```json\n" + _scenario(5) + "\n```"
    _, scenes = parse_scenario(text, 3, 4)
    assert len(scenes) == 3


def test_parse_scenario_fixed_camera_preset_overrides():
    _, scenes = parse_scenario(_scenario(3), 3, 6, camera_preset="orbit")
    assert {s.camera for s in scenes} == {"orbit"}


@pytest.mark.parametrize(
    "text, msg",
    [
        ("not json", "not valid JSON"),
        ("[1, 2]", "JSON object"),
        (json.dumps({"title": "x", "scenes": []}), "no scenes"),
        (_scenario(2), "Expected 3 scenes"),
        (_scenario(3, visual=""), "no visual"),
    ],
)
def test_parse_scenario_rejects_bad_output(text, msg):
    with pytest.raises(ScenarioError, match=msg):
        parse_scenario(text, 3, 6)


def test_parse_scenario_accepts_alternate_keys_and_default_title():
    text = json.dumps(
        {
            "scenes": [
                {"voiceover": "v", "visual_description": "d", "camera_move": "Crane-up"}
            ]
            * 3
        }
    )
    title, scenes = parse_scenario(text, 3, 6)
    assert title == "Untitled story"
    assert scenes[0].narration == "v" and scenes[0].visual == "d"
    assert scenes[0].camera == "crane_up"


def test_parse_single_scene():
    sc = parse_single_scene(
        '{"narration": "n", "visual": "v", "camera": "handheld"}', 8
    )
    assert (sc.narration, sc.visual, sc.camera, sc.duration) == (
        "n",
        "v",
        "handheld",
        8,
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Dolly In", "dolly_in"),
        ("slow orbit around", "orbit"),
        ("", "static"),
        ("weird", "static"),
    ],
)
def test_normalize_camera(raw, expected):
    assert normalize_camera(raw) == expected


# ---------------------------------------------------------------------------
# Cost caps
# ---------------------------------------------------------------------------


def test_caps_clamp_scene_count(monkeypatch):
    monkeypatch.setattr(story_models, "Default", _caps_cfg())
    assert apply_caps(20, 4).scene_count == 8
    assert apply_caps(1, 4).scene_count == 3


def test_caps_snap_duration_to_veo_values(monkeypatch):
    monkeypatch.setattr(story_models, "Default", _caps_cfg())
    caps = apply_caps(4, 5)
    assert caps.duration in (4, 6)
    assert any("supported by Veo" in n for n in caps.notes)
    assert apply_caps(4, 30).duration == 8


def test_caps_total_film_length(monkeypatch):
    monkeypatch.setattr(story_models, "Default", _caps_cfg(STORY_MAX_FILM_SECONDS=30))
    caps = apply_caps(8, 8)
    assert caps.scene_count * caps.duration <= 30
    assert caps.scene_count >= 3
    assert any("capped" in n for n in caps.notes)


def test_caps_force_configured_resolution(monkeypatch):
    monkeypatch.setattr(story_models, "Default", _caps_cfg())
    caps = apply_caps(4, 6, resolution="4k")
    assert caps.resolution == "720p"
    assert any("Resolution" in n for n in caps.notes)


# ---------------------------------------------------------------------------
# Step transitions
# ---------------------------------------------------------------------------


def _story_with(frames=0, n=3, approved=True, final=""):
    scenes = [
        Scene(visual=f"v{i}", frame_uri=f"local://f{i}.png" if i < frames else "")
        for i in range(n)
    ]
    return Story(scenes=scenes, approved=approved, final_uri=final)


def test_steps_new_story_only_create():
    assert reachable_steps(None) == {"stories", "create"}
    assert not can_enter("scenario", Story())
    assert furthest_step(Story()) == "create"


def test_steps_scenario_needs_scenes_and_storyboard_needs_approval():
    s = _story_with(approved=False)
    assert can_enter("scenario", s)
    assert not can_enter("storyboard", s)
    s.approved = True
    assert can_enter("storyboard", s)
    assert not can_enter("editor", s)
    assert furthest_step(s) == "storyboard"


def test_steps_editor_needs_every_frame():
    assert not can_enter("editor", _story_with(frames=2))
    full = _story_with(frames=3)
    assert can_enter("editor", full) and can_enter("video", full)
    assert furthest_step(full) == "editor"
    assert furthest_step(_story_with(frames=3, final="local://film.mp4")) == "video"


def test_unknown_step_rejected():
    assert not can_enter("publish", _story_with(frames=3))


# ---------------------------------------------------------------------------
# Stitching plan and render
# ---------------------------------------------------------------------------


def _clips(durs):
    return [
        Scene(duration=d, clip_uri=f"local://c{i}.mp4", narration=f"n{i}")
        for i, d in enumerate(durs)
    ]


def test_stitch_plan_order_starts_and_total():
    plan = build_stitch_plan(_clips([4, 6, 8]), crossfade=0.5)
    assert [s.index for s in plan.segments] == [0, 1, 2]
    assert [s.start for s in plan.segments] == [0.0, 3.5, 9.0]
    assert [s.fade_in for s in plan.segments] == [0.0, 0.5, 0.5]
    assert plan.total == pytest.approx(4 + 6 + 8 - 2 * 0.5)


def test_stitch_plan_skips_missing_clips_and_clamps_crossfade():
    scenes = _clips([4, 1, 4])
    scenes.insert(1, Scene(duration=6))  # no clip
    plan = build_stitch_plan(scenes, crossfade=2.0)
    assert [s.index for s in plan.segments] == [0, 2, 3]
    assert plan.crossfade == pytest.approx(1 / 3)


def test_stitch_plan_single_clip_and_empty():
    plan = build_stitch_plan(_clips([6]), crossfade=0.5)
    assert plan.crossfade == 0 and plan.total == 6
    assert build_stitch_plan([Scene()], 0.5).segments == []


def test_stitch_plan_uses_measured_durations():
    plan = build_stitch_plan(_clips([8, 8]), 0.5, clip_durations=[7.9, 8.0])
    assert plan.total == pytest.approx(7.9 + 8.0 - 0.5)


def test_stitch_local_renders_tiny_clips(tmp_path):
    """Real MoviePy render with tiny generated clips, music and voice."""
    moviepy = pytest.importorskip("moviepy")
    import numpy as np

    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = tmp_path / f"c{i}.mp4"
        moviepy.ColorClip((64, 36), color=color, duration=1.0).write_videofile(
            str(p), fps=8, codec="libx264", audio=False, logger=None
        )
        paths.append(str(p))
    music = story_service._write_wav(str(tmp_path / "m.wav"), np.zeros(24000))
    voice = story_service._write_wav(str(tmp_path / "v.wav"), 0.1 * np.ones(6000))
    plan = build_stitch_plan(_clips([1, 1, 1]), crossfade=0.25)
    out = story_service.stitch_local(
        paths, plan, str(tmp_path / "film.mp4"), music, [voice, "", voice], fps=8
    )
    with moviepy.VideoFileClip(out) as film:
        assert film.duration == pytest.approx(plan.total, abs=0.2)
        assert film.audio is not None


def test_stitch_local_keeps_speech_of_spoken_clips(tmp_path):
    """A spoken clip's own audio (Veo speech) ends up in the film."""
    moviepy = pytest.importorskip("moviepy")
    import numpy as np

    def tone(t):
        return 0.3 * np.sin(2 * np.pi * 440 * np.asarray(t))

    paths = []
    for i in range(3):
        p = tmp_path / f"c{i}.mp4"
        clip = moviepy.ColorClip((64, 36), color=(40 * i, 0, 0), duration=1.0)
        if i == 1:
            clip = clip.with_audio(moviepy.AudioClip(tone, duration=1.0, fps=22050))
        clip.write_videofile(
            str(p), fps=8, codec="libx264", audio_codec="aac", logger=None
        )
        paths.append(str(p))
    scenes = _clips([1, 1, 1])
    scenes[1].spoken, scenes[1].narration = True, "Hello"
    plan = build_stitch_plan(scenes, crossfade=0.25)
    # Joins next to the spoken scene are cuts, not crossfades.
    assert [seg.fade_in for seg in plan.segments] == [0.0, 0.0, 0.0]
    assert plan.total == pytest.approx(3.0)
    out = story_service.stitch_local(paths, plan, str(tmp_path / "film.mp4"), fps=8)
    with moviepy.VideoFileClip(out) as film:
        assert film.duration == pytest.approx(3.0, abs=0.2)
        assert film.audio is not None
        loud = np.abs(film.audio.subclipped(1.2, 1.8).to_soundarray(fps=8000)).max()
        quiet = np.abs(film.audio.subclipped(0.1, 0.7).to_soundarray(fps=8000)).max()
        assert loud > 0.1 and quiet < 0.02


def _chain(durs, links):
    """Clips where links[i] says scene i was animated from scene i-1's clip."""
    scenes = _clips(durs)
    for i, linked in enumerate(links):
        if i and linked:
            scenes[i].continues_from = scenes[i - 1].clip_uri
    return scenes


def test_stitch_plan_seamless_cuts_continued_joins():
    plan = build_stitch_plan(
        _chain([6, 6, 6], [0, 1, 1]), crossfade=0.5, seamless=True, fps=24
    )
    head = 1 / 24
    assert [s.fade_in for s in plan.segments] == [0.0, 0.0, 0.0]
    assert [s.trim_head for s in plan.segments] == pytest.approx(
        [0, head, head], abs=1e-3
    )
    assert [s.start for s in plan.segments] == pytest.approx(
        [0.0, 6.0, 12.0 - head], abs=1e-3
    )
    assert plan.total == pytest.approx(18 - 2 * head, abs=1e-3)


def test_stitch_plan_seamless_keeps_crossfade_on_broken_join():
    scenes = _chain([6, 6, 6], [0, 1, 0])
    scenes[2].continues_from = "local://an-older-clip.mp4"  # scene 2 re-rendered
    plan = build_stitch_plan(scenes, crossfade=0.5, seamless=True, fps=24)
    assert [s.fade_in for s in plan.segments] == [0.0, 0.0, 0.5]
    assert plan.segments[2].trim_head == 0.0


def test_stitch_plan_without_seamless_ignores_links():
    plan = build_stitch_plan(_chain([6, 6, 6], [0, 1, 1]), crossfade=0.5)
    assert [s.fade_in for s in plan.segments] == [0.0, 0.5, 0.5]
    assert plan.total == pytest.approx(17.0)


def test_stitch_plan_seamless_needs_adjacent_scene():
    scenes = _chain([6, 6, 6], [0, 1, 1])
    scenes[1].clip_uri = ""  # middle scene missing: 0 -> 2 is not a continuation
    plan = build_stitch_plan(scenes, crossfade=0.5, seamless=True)
    assert [s.index for s in plan.segments] == [0, 2]
    assert plan.segments[1].fade_in == 0.5


def test_old_stories_load_with_new_defaults():
    story = Story.from_dict(
        {"continuity": True, "scenes": [{"visual": "v", "clip_uri": "local://c.mp4"}]}
    )
    assert story.seamless_joins is True
    assert story.scenes[0].continues_from == ""


def test_stitch_local_trims_head_on_seamless_join(tmp_path):
    moviepy = pytest.importorskip("moviepy")

    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 0, 255)]):
        p = tmp_path / f"c{i}.mp4"
        moviepy.ColorClip((64, 36), color=color, duration=1.0).write_videofile(
            str(p), fps=8, codec="libx264", audio=False, logger=None
        )
        paths.append(str(p))
    plan = build_stitch_plan(
        _chain([1, 1], [0, 1]), crossfade=0.25, seamless=True, fps=8
    )
    out = story_service.stitch_local(paths, plan, str(tmp_path / "film.mp4"), fps=8)
    with moviepy.VideoFileClip(out) as film:
        assert film.duration == pytest.approx(2 - 1 / 8, abs=0.2)
        # No blend at the cut: just before it is pure red, just after pure blue.
        before = film.get_frame(0.9).mean(axis=(0, 1))
        after = film.get_frame(1.05).mean(axis=(0, 1))
        assert before[0] > 200 and before[2] < 60
        assert after[2] > 200 and after[0] < 60


def test_stitch_local_refuses_mismatch(tmp_path):
    from common.error_handling import GenerationError

    plan = build_stitch_plan(_clips([1, 1]), 0.25)
    with pytest.raises(GenerationError):
        story_service.stitch_local(["only-one.mp4"], plan, str(tmp_path / "x.mp4"))


# ---------------------------------------------------------------------------
# Owner-only access
# ---------------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    story_store.set_store(store)
    yield store
    story_store.set_store(None)


def test_local_store_owner_only(local_store):
    s = local_store.save(Story(idea="mine"), OWNER)
    assert local_store.get(s.id, OWNER).idea == "mine"
    assert local_store.get(s.id, OTHER) is None
    assert local_store.get(s.id, "") is None
    assert [x.id for x in local_store.list(OWNER)] == [s.id]
    assert local_store.list(OTHER) == []
    with pytest.raises(story_store.StoryAccessError):
        local_store.save(Story(id=s.id, idea="hijack"), OTHER)
    assert local_store.delete(s.id, OTHER) is False
    assert local_store.get(s.id, OWNER).idea == "mine"
    assert local_store.delete(s.id, OWNER) is True


def test_local_store_requires_identity(local_store):
    with pytest.raises(story_store.StoryAccessError):
        local_store.save(Story(), "")


def test_save_forces_owner_to_caller(local_store):
    s = local_store.save(Story(owner=OTHER), OWNER)
    assert s.owner == OWNER


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Doc:
    def __init__(self, db, key):
        self.db, self.key = db, key

    def get(self):
        return _Snap(self.db.data.get(self.key))

    def set(self, data):
        self.db.data[self.key] = data

    def delete(self):
        self.db.data.pop(self.key, None)


class _FakeDb:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        db = self

        class _Col:
            def document(self, key):
                return _Doc(db, key)

        return _Col()


def test_firestore_store_owner_only():
    store = story_store.FirestoreStoryStore(db=_FakeDb(), collection="stories")
    s = store.save(Story(idea="mine"), OWNER)
    assert store.get(s.id, OWNER).idea == "mine"
    assert store.get(s.id, OTHER) is None
    with pytest.raises(story_store.StoryAccessError):
        store.save(Story(id=s.id), OTHER)
    assert store.delete(s.id, OTHER) is False
    assert store.delete(s.id, OWNER) is True
    assert store.get(s.id, OWNER) is None


def test_firestore_store_hides_legacy_ownerless_docs():
    db = _FakeDb()
    db.data["x"] = Story(id="x").to_dict() | {"owner": ""}
    store = story_store.FirestoreStoryStore(db=db, collection="stories")
    assert store.get("x", OWNER) is None


def _story_with_media(bucket):
    return Story(
        scenes=[Scene(frame_uri=f"gs://{bucket}/images/a.png", clip_uri="")],
    )


def test_belongs_here_only_hides_other_deployments_media():
    mine = {"ours-assets"}
    assert story_store.belongs_here(_story_with_media("ours-assets"), mine)
    assert not story_store.belongs_here(_story_with_media("theirs-assets"), mine)
    # No gs:// media yet, or demo-mode local media: nothing to break, keep it.
    assert story_store.belongs_here(Story(idea="script only"), mine)
    local = Story(scenes=[Scene(frame_uri="local://x/frame1.png")])
    assert story_store.belongs_here(local, mine)
    # One foreign file is enough to hide it.
    mixed = _story_with_media("ours-assets")
    mixed.final_uri = "gs://theirs-assets/videos/film.mp4"
    assert not story_store.belongs_here(mixed, mine)


def test_deployment_buckets_reads_config(monkeypatch):
    cfg = SimpleNamespace(
        GENMEDIA_BUCKET="gs://ours-assets",
        VIDEO_BUCKET="ours-assets/videos",
        IMAGE_BUCKET="ours-images/x",
        MEDIA_BUCKET="",
    )
    monkeypatch.setattr(story_store, "Default", lambda: cfg)
    assert story_store.deployment_buckets() == {"ours-assets", "ours-images"}


def test_firestore_store_hides_other_deployments_stories(monkeypatch):
    monkeypatch.setattr(story_store, "deployment_buckets", lambda: {"ours-assets"})
    db = _FakeDb()
    store = story_store.FirestoreStoryStore(db=db, collection="stories")
    theirs = store.save(_story_with_media("theirs-assets"), OWNER)
    ours = store.save(_story_with_media("ours-assets"), OWNER)
    assert store.get(theirs.id, OWNER) is None
    assert store.get(ours.id, OWNER) is not None


# ---------------------------------------------------------------------------
# Jobs with the mock backend (no network)
# ---------------------------------------------------------------------------


class _FastMock(story_service.MockStoryBackend):
    """Mock backend without delays or media encoding."""

    def __init__(self):
        super().__init__(speed=0)

    def generate_frame(self, story, index, reference_uri):
        self.refs = getattr(self, "refs", {})
        self.refs[index] = reference_uri
        return f"local://{story.id}/frame{index}.png"

    def generate_clip(self, story, index, start_frame_uri):
        return f"local://{story.id}/clip{index}.mp4"

    def last_frame(self, story, clip_uri, index):
        return f"local://{story.id}/last{index}.png"

    def generate_music(self, story, prompt, seconds):
        return "local://m.wav"

    def generate_voiceover(self, story, index, text, style="narrator"):
        return f"local://v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        self.plan, self.voices = plan, voice_uris
        return "local://film.mp4"


@pytest.fixture
def fast_backend(local_store):
    backend = _FastMock()
    story_service.set_backend(backend)
    yield backend
    story_service.set_backend(None)


def _run(job):
    done = story_jobs.wait(job.id, OWNER, timeout=20)
    assert done is not None and done.status != "running"
    return done


def test_full_pipeline_with_mock_backend(fast_backend, local_store):
    s = local_store.save(
        Story(idea="A lighthouse keeper befriends a whale", scene_count=3, duration=4),
        OWNER,
    )
    job = _run(story_jobs.start_scenario(s.id, OWNER))
    assert job.status == "done"
    s = local_store.get(s.id, OWNER)
    assert len(s.scenes) == 3 and s.title

    story_jobs.mutate_story(s.id, OWNER, lambda x: setattr(x, "approved", True))
    job = _run(story_jobs.start_storyboard(s.id, OWNER))
    assert job.status == "done"
    # Scene 1 anchors the look: later frames get it as reference.
    assert fast_backend.refs[0] == ""
    assert fast_backend.refs[1] == fast_backend.refs[2] == f"local://{s.id}/frame0.png"

    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    s = local_store.get(s.id, OWNER)
    assert s.final_uri == "local://film.mp4"
    assert [seg.index for seg in fast_backend.plan.segments] == [0, 1, 2]
    assert fast_backend.voices == ["local://v0.wav", "local://v1.wav", "local://v2.wav"]
    snap = story_jobs.job_snapshot(job.id, OWNER)
    assert snap["progress"] == 1.0 and snap["done"] == snap["total"]
    assert story_jobs.job_snapshot(job.id, OTHER) is None


def test_failed_clip_skips_stitch_and_retry_resumes(fast_backend, local_store):
    scenes = [Scene(visual=f"v{i}", frame_uri=f"local://f{i}.png") for i in range(3)]
    s = local_store.save(
        Story(scenes=scenes, approved=True, voice_on=False, music_on=False), OWNER
    )
    calls = []
    original = fast_backend.generate_clip

    def flaky(story, index, start):
        calls.append(index)
        if index == 1 and calls.count(1) == 1:
            raise RuntimeError("503 backend error")
        return original(story, index, start)

    fast_backend.generate_clip = flaky
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "failed"
    statuses = {t.kind: t.status for t in job.tasks if t.kind in ("stitch", "library")}
    assert statuses == {"stitch": "skipped", "library": "skipped"}
    failed = [t for t in job.tasks if t.status == "failed"]
    assert len(failed) == 1 and "Retry" in failed[0].error
    # Finished clips are kept; retry only renders the missing one.
    retry = _run(story_jobs.retry(job.id, OWNER))
    assert retry.status == "done"
    assert [t.scene_index for t in retry.tasks if t.kind == "clip"] == [1]
    assert local_store.get(s.id, OWNER).final_uri == "local://film.mp4"


def test_continuity_uses_last_frame_of_previous_clip(fast_backend, local_store):
    scenes = [Scene(visual=f"v{i}", frame_uri=f"local://f{i}.png") for i in range(3)]
    s = local_store.save(
        Story(
            scenes=scenes,
            approved=True,
            continuity=True,
            voice_on=False,
            music_on=False,
        ),
        OWNER,
    )
    starts = {}
    original = fast_backend.generate_clip

    def record(story, index, start):
        starts[index] = start
        return original(story, index, start)

    fast_backend.generate_clip = record
    _run(story_jobs.start_video(s.id, OWNER))
    assert starts[0] == "local://f0.png"
    assert starts[1] == f"local://{s.id}/last1.png"
    assert starts[2] == f"local://{s.id}/last2.png"


def test_continuity_records_continues_from(fast_backend, local_store):
    scenes = [Scene(visual=f"v{i}", frame_uri=f"local://f{i}.png") for i in range(3)]
    s = local_store.save(
        Story(
            scenes=scenes,
            approved=True,
            continuity=True,
            voice_on=False,
            music_on=False,
        ),
        OWNER,
    )
    _run(story_jobs.start_video(s.id, OWNER))
    done = local_store.get(s.id, OWNER)
    assert done.scenes[0].continues_from == ""
    assert done.scenes[1].continues_from == done.scenes[0].clip_uri
    assert done.scenes[2].continues_from == done.scenes[1].clip_uri


def test_video_requires_frames(fast_backend, local_store):
    from common.error_handling import GenerationError

    s = local_store.save(Story(scenes=[Scene(visual="v")], approved=True), OWNER)
    with pytest.raises(GenerationError):
        story_jobs.start_video(s.id, OWNER)


def test_jobs_owner_only(fast_backend, local_store):
    s = local_store.save(Story(idea="x" * 10), OWNER)
    with pytest.raises(story_store.StoryAccessError):
        story_jobs.start_storyboard(s.id, OTHER)
    with pytest.raises(story_store.StoryAccessError):
        story_jobs.mutate_story(s.id, OTHER, lambda st: None)


def test_scenario_retries_once_on_bad_json(fast_backend, local_store):
    s = local_store.save(Story(idea="An idea long enough", scene_count=3), OWNER)
    replies = iter(["oops", _scenario(3)])
    fast_backend.write_scenario = lambda story: next(replies)
    job = _run(story_jobs.start_scenario(s.id, OWNER))
    assert job.status == "done"
    assert len(local_store.get(s.id, OWNER).scenes) == 3


# ---------------------------------------------------------------------------
# Mode and URLs
# ---------------------------------------------------------------------------


def test_mock_mode_flag(monkeypatch):
    monkeypatch.setattr(
        story_service, "Default", lambda: SimpleNamespace(STORY_STUDIO_MOCK="true")
    )
    assert story_service.is_mock_mode()
    monkeypatch.setattr(
        story_service, "Default", lambda: SimpleNamespace(STORY_STUDIO_MOCK="false")
    )
    assert not story_service.is_mock_mode()


def test_mock_mode_auto_needs_local_env_without_credentials(monkeypatch):
    monkeypatch.setattr(
        story_service, "Default", lambda: SimpleNamespace(STORY_STUDIO_MOCK="")
    )
    monkeypatch.setattr(story_service, "_has_gcp_credentials", lambda: False)
    monkeypatch.setenv("APP_ENV", "local")
    assert story_service.is_mock_mode()
    monkeypatch.setenv("APP_ENV", "production")
    assert not story_service.is_mock_mode()


def test_local_paths_reject_traversal():
    with pytest.raises(ValueError):
        story_service.local_path("local://../secrets.txt")
    assert story_service.display_url("local://abc/x.png") == "/story-media/abc/x.png"
    assert story_service.display_url("") == ""


# ---------------------------------------------------------------------------
# Second-language version
# ---------------------------------------------------------------------------


def test_second_language_is_english_for_arabic_else_arabic():
    assert story_models.other_language("English") == "Arabic"
    assert story_models.other_language("French") == "Arabic"
    assert story_models.other_language("Arabic") == "English"


def test_translation_prompt_asks_for_msa_and_line_count():
    s = Story(title="Fox", scenes=[Scene(narration="Run."), Scene(narration="")])
    prompt = story_models.translation_prompt(s)
    assert "into Arabic" in prompt and "Modern Standard Arabic" in prompt
    assert "exactly 2 lines" in prompt
    english = story_models.translation_prompt(Story(language="Arabic"))
    assert "into English" in english and "Modern Standard" not in english


def test_parse_translation():
    title, lines = story_models.parse_translation(
        '```json' + chr(10) + '{"title": "T", "lines": ["a", ""]}' + chr(10) + '```', 2
    )
    assert title == "T" and lines == ["a", ""]
    for bad in ("nope", "[]", '{"lines": ["a"]}', '{"lines": "a"}'):
        with pytest.raises(story_models.ScenarioError):
            story_models.parse_translation(bad, 2)


def test_alt_story_swaps_language_title_and_narration_only():
    s = Story(
        title="Fox",
        title_alt="TA",
        scenes=[Scene(narration="Run.", narration_alt="RA", clip_uri="local://c")],
    )
    a = story_models.alt_story(s)
    assert (a.language, a.title, a.scenes[0].narration) == ("Arabic", "TA", "RA")
    assert a.scenes[0].clip_uri == "local://c"
    assert s.scenes[0].narration == "Run." and s.title == "Fox"  # original intact


def test_makes_alt_needs_voiceover():
    assert Story(second_on=True, voice_on=True).makes_alt
    assert not Story(second_on=True, voice_on=False).makes_alt
    assert not Story(second_on=False, voice_on=True).makes_alt


class _BilingualMock(_FastMock):
    def generate_voiceover(self, story, index, text, style="narrator"):
        return f"local://{story.language}-v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        self.films = getattr(self, "films", []) + [(story.language, voice_uris)]
        return f"local://film-{story.language}.mp4"

    def save_to_library(self, story, final_uri, owner):
        self.saved = getattr(self, "saved", []) + [(story.title, final_uri)]
        return "id"


@pytest.fixture
def bilingual(local_store):
    backend = _BilingualMock()
    story_service.set_backend(backend)
    yield backend
    story_service.set_backend(None)


def _ready_story(local_store, **kw):
    scenes = [
        Scene(narration="Run.", frame_uri="local://f0"),
        Scene(narration="", frame_uri="local://f1"),
        Scene(narration="Stop.", frame_uri="local://f2"),
    ]
    return local_store.save(
        Story(title="Fox", approved=True, scenes=scenes, **kw), OWNER
    )


def test_render_makes_both_films_from_the_same_clips(bilingual, local_store):
    s = _ready_story(local_store, second_on=True)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    kinds = [t.kind for t in job.tasks]
    assert kinds.count("clip") == 3  # clips are rendered once, not per language
    assert kinds.count("voice_alt") == 2  # the silent scene gets no voice
    assert [lang for lang, _ in bilingual.films] == ["English", "Arabic"]
    assert bilingual.films[1][1] == [
        "local://Arabic-v0.wav",
        "",
        "local://Arabic-v2.wav",
    ]
    s = local_store.get(s.id, OWNER)
    assert s.final_uri == "local://film-English.mp4"
    assert s.final_alt_uri == "local://film-Arabic.mp4"
    assert s.scenes[0].narration_alt == "[Arabic] Run."
    assert s.scenes[1].narration_alt == ""
    assert [t for t, _ in bilingual.saved] == ["Fox", "[Arabic] Fox"]


def test_render_without_toggle_makes_one_film(bilingual, local_store):
    s = _ready_story(local_store)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert not {"translate", "voice_alt", "stitch_alt"} & {t.kind for t in job.tasks}
    assert local_store.get(s.id, OWNER).final_alt_uri == ""


def test_render_without_voiceover_skips_second_film(bilingual, local_store):
    s = _ready_story(local_store, second_on=True, voice_on=False)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert "stitch_alt" not in {t.kind for t in job.tasks}


def test_translation_keeps_edited_lines_unless_forced(bilingual, local_store):
    s = _ready_story(local_store, second_on=True)

    def edited(x):
        x.scenes[0].narration_alt = "my wording"

    story_jobs.mutate_story(s.id, OWNER, edited)
    assert _run(story_jobs.start_translation(s.id, OWNER)).status == "done"
    lines = [sc.narration_alt for sc in local_store.get(s.id, OWNER).scenes]
    assert lines == ["my wording", "", "[Arabic] Stop."]
    assert _run(story_jobs.start_translation(s.id, OWNER, force=True)).status == "done"
    lines = [sc.narration_alt for sc in local_store.get(s.id, OWNER).scenes]
    assert lines == ["[Arabic] Run.", "", "[Arabic] Stop."]


def test_failed_translation_still_makes_main_film(bilingual, local_store):
    bilingual.translate = lambda story: "not json"
    s = _ready_story(local_store, second_on=True)
    job = _run(story_jobs.start_video(s.id, OWNER))
    by_kind = {t.kind: t.status for t in job.tasks}
    assert by_kind["translate"] == "failed"
    assert by_kind["stitch"] == by_kind["library"] == "done"
    assert by_kind["stitch_alt"] == "skipped"
    s = local_store.get(s.id, OWNER)
    assert s.final_uri and not s.final_alt_uri


def test_clear_films_forgets_both():
    s = Story(final_uri="a", final_alt_uri="b")
    s.clear_films()
    assert s.final_uri == s.final_alt_uri == ""


# ---------------------------------------------------------------------------
# On-camera speech
# ---------------------------------------------------------------------------


def test_parse_scenario_reads_spoken_and_voice():
    text = json.dumps(
        {
            "title": "T",
            "voice": "calm male voice",
            "scenes": [
                {"narration": "Hello team.", "spoken": True, "visual": "a"},
                {"narration": "Later.", "spoken": "false", "visual": "b"},
                {"narration": "", "spoken": True, "visual": "c"},
            ],
        }
    )
    _, scenes = parse_scenario(text, 3, 6)
    assert [s.spoken for s in scenes] == [True, False, False]  # no line, no speech
    assert story_models.parse_voice(text) == "calm male voice"
    assert story_models.parse_voice("nope") == ""


@pytest.mark.parametrize("mode, expected", [("narrator", False), ("on_camera", True)])
def test_speech_mode_overrides_model_choice(mode, expected):
    text = json.dumps(
        {
            "title": "T",
            "scenes": [{"narration": "Hi", "spoken": not expected, "visual": "a"}],
        }
    )
    _, scenes = parse_scenario(text, 1, 6, speech_mode=mode)
    assert scenes[0].spoken is expected


def test_scenario_prompt_explains_who_speaks():
    auto = story_models.scenario_prompt(Story(idea="a man presents Gemini"))
    assert "presenter" in auto and '"spoken"' in auto and '"voice"' in auto
    narrator = story_models.scenario_prompt(Story(speech_mode="narrator"))
    assert '"spoken" is false for every' in narrator
    on_camera = story_models.scenario_prompt(Story(speech_mode="on_camera"))
    assert "true for every scene" in on_camera


def test_clip_prompt_carries_the_spoken_line():
    st = Story(speaker_voice="calm male voice")
    spoken = Scene(visual="A man on stage.", narration="Meet Gemini.", spoken=True)
    prompt = story_models.clip_prompt(st, spoken)
    assert '"Meet Gemini."' in prompt and "calm male voice" in prompt
    assert "lip-synced" in prompt and "only voice" in prompt
    # Without a described voice, Veo is told to match the person it shows.
    fallback = story_models.clip_prompt(Story(), spoken)
    assert "matches their age and gender" in fallback
    silent = Scene(visual="A man on stage.", narration="Meet Gemini.")
    assert "Meet Gemini" not in story_models.clip_prompt(st, silent)


def test_line_too_long_uses_scene_length():
    assert not Scene(narration=" ".join(["w"] * 15), duration=6).line_too_long()
    assert Scene(narration=" ".join(["w"] * 16), duration=6).line_too_long()


def test_alt_clip_only_valid_for_its_clip_and_line():
    sc = Scene(clip_uri="c", narration_alt="a", spoken=True)
    sc.clip_alt_uri, sc.clip_alt_key = "ca", sc.alt_clip_key()
    assert sc.has_alt_clip()
    sc.narration_alt = "changed"
    assert not sc.has_alt_clip()
    sc.narration_alt, sc.clip_uri = "a", "new clip"
    assert not sc.has_alt_clip()


class _SpeechMock(_BilingualMock):
    def generate_clip(self, story, index, start_frame_uri):
        self.clips = getattr(self, "clips", []) + [
            (story.language, index, story.scenes[index].narration)
        ]
        return f"local://{story.id}/{story.language}-clip{index}-{len(self.clips)}.mp4"

    def last_frame(self, story, clip_uri, index):
        return f"local://last{index}.png"


@pytest.fixture
def speech(local_store):
    backend = _SpeechMock()
    story_service.set_backend(backend)
    yield backend
    story_service.set_backend(None)


def _spoken_story(local_store, **kw):
    scenes = [
        Scene(narration="Meet Gemini.", spoken=True, frame_uri="local://f0"),
        Scene(narration="It reads your files.", frame_uri="local://f1"),
    ]
    return local_store.save(
        Story(title="Pitch", approved=True, scenes=scenes, **kw), OWNER
    )


def test_veo_voice_mode_gives_spoken_scene_no_voiceover(speech, local_store):
    s = _spoken_story(local_store, same_voice=False)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert [t.scene_index for t in job.tasks if t.kind == "voice"] == [1]
    english_voices = speech.films[0][1]
    assert english_voices[0] == "" and english_voices[1]


def test_second_language_rerenders_only_spoken_clips(speech, local_store):
    s = _spoken_story(local_store, second_on=True, same_voice=False)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    arabic_clips = [c for c in speech.clips if c[0] == "Arabic"]
    assert arabic_clips == [("Arabic", 0, "[Arabic] Meet Gemini.")]
    s = local_store.get(s.id, OWNER)
    assert s.scenes[0].has_alt_clip() and s.final_alt_uri
    # Arabic film: voiceover only for the narrated scene; the spoken scene
    # carries its speech in the Arabic clip.
    assert speech.films[1][0] == "Arabic"
    assert speech.films[1][1][0] == "" and speech.films[1][1][1]

    # Rendering again reuses the Arabic clip while it is current.
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert "clip_alt" not in {t.kind for t in job.tasks}


def test_second_language_without_voiceover_when_scenes_speak(speech, local_store):
    s = _spoken_story(local_store, second_on=True, voice_on=False, same_voice=False)
    job = _run(story_jobs.start_video(s.id, OWNER))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert local_store.get(s.id, OWNER).final_alt_uri


def test_failed_spoken_alt_clip_skips_second_film(speech, local_store):
    original = speech.generate_clip

    def flaky(story, index, start):
        if story.language == "Arabic":
            raise RuntimeError("boom")
        return original(story, index, start)

    speech.generate_clip = flaky
    s = _spoken_story(local_store, second_on=True, same_voice=False)
    job = _run(story_jobs.start_video(s.id, OWNER))
    kinds = {t.kind: t.status for t in job.tasks}
    assert kinds["stitch"] == "done" and kinds["stitch_alt"] == "skipped"
    assert not local_store.get(s.id, OWNER).final_alt_uri


def test_mock_scenario_speaks_for_presenter_ideas(fast_backend, local_store):
    s = local_store.save(
        Story(idea="A man presenting Gemini Enterprise", scene_count=2, duration=4),
        OWNER,
    )
    assert _run(story_jobs.start_scenario(s.id, OWNER)).status == "done"
    s = local_store.get(s.id, OWNER)
    assert all(sc.spoken for sc in s.scenes) and s.speaker_voice


class _ChainMock(_SpeechMock):
    def last_frame(self, story, clip_uri, index):
        self.starts = getattr(self, "starts", []) + [(index, clip_uri)]
        return f"local://last-of-{clip_uri.rsplit('/', 1)[-1]}"


def test_arabic_clips_chain_from_each_other_with_continuity(local_store):
    backend = _ChainMock()
    story_service.set_backend(backend)
    try:
        scenes = [
            Scene(narration="One.", spoken=True, frame_uri="local://f0"),
            Scene(narration="Two.", spoken=True, frame_uri="local://f1"),
        ]
        s = local_store.save(
            Story(
                approved=True,
                continuity=True,
                second_on=True,
                same_voice=False,
                scenes=scenes,
            ),
            OWNER,
        )
        job = _run(story_jobs.start_video(s.id, OWNER))
        assert job.status == "done", [(t.label, t.error) for t in job.tasks]
        s = local_store.get(s.id, OWNER)
        first_ar = s.scenes[0].clip_alt_uri
        # The Arabic scene 2 starts from the end of the Arabic scene 1, not
        # from the English one.
        assert (1, first_ar) in backend.starts
        assert s.scenes[1].clip_alt_from == first_ar
        second = story_models.alt_story(s)
        assert story_models.is_seamless_join(second.scenes[0], second.scenes[1])
    finally:
        story_service.set_backend(None)


def test_scenario_prompt_asks_for_the_speakers_gender():
    prompt = story_models.scenario_prompt(Story(speech_mode="on_camera"))
    assert "starts with their gender" in prompt


# ---------------------------------------------------------------------------
# Same voice in every scene (dubbed on-camera lines)
# ---------------------------------------------------------------------------


def test_speech_span_finds_the_loud_part():
    import numpy as np

    rate = 16000
    a = np.full(rate * 3, 0.002, dtype=np.float32)  # room tone
    t = np.arange(rate) / rate
    a[rate : 2 * rate] = 0.3 * np.sin(2 * np.pi * 180 * t)  # speech 1.0s-2.0s
    start, end = story_service.speech_span(a, rate)
    assert start == pytest.approx(1.0, abs=0.05)
    assert end == pytest.approx(2.0, abs=0.05)
    assert story_service.speech_span(np.zeros(rate, dtype=np.float32), rate) is None


def test_dub_tempo_stays_natural():
    assert story_service.dub_tempo(3.0, 3.0) == 1.0
    assert story_service.dub_tempo(10.0, 3.0) == story_service.DUB_MAX_TEMPO
    assert story_service.dub_tempo(1.0, 3.0) == story_service.DUB_MIN_TEMPO
    assert story_service.dub_tempo(3.0, 0) == 1.0


def test_fit_voice_changes_length_not_pitch(tmp_path):
    import numpy as np

    rate = 24000
    t = np.arange(rate * 2) / rate
    src = story_service._write_wav(
        str(tmp_path / "v.wav"), 0.3 * np.sin(2 * np.pi * 200 * t), rate
    )
    out = story_service.fit_voice(src, str(tmp_path / "fast.wav"), 1.25)
    fast = story_service.read_mono(out, 16000)
    assert len(fast) / 16000 == pytest.approx(1.6, abs=0.08)
    spectrum = np.abs(np.fft.rfft(fast))
    peak_hz = np.argmax(spectrum) * 16000 / len(fast)
    assert peak_hz == pytest.approx(200, abs=10)  # same pitch, only faster
    assert story_service.fit_voice(src, str(tmp_path / "same.wav"), 1.0) == src


def test_stitch_local_dubs_spoken_clip_with_fixed_voice(tmp_path):
    """Veo's own voice (440 Hz) is replaced by the fixed voice (220 Hz),
    placed where the person speaks in the clip."""
    moviepy = pytest.importorskip("moviepy")
    import numpy as np

    def veo_speech(t):
        t = np.asarray(t, dtype=float)
        out = np.where((t > 0.4) & (t < 0.8), 0.3 * np.sin(2 * np.pi * 440 * t), 0.0)
        return float(out) if out.ndim == 0 else out

    paths = []
    for i in range(2):
        p = tmp_path / f"c{i}.mp4"
        clip = moviepy.ColorClip((64, 36), color=(60 * i, 0, 0), duration=1.0)
        if i == 1:
            clip = clip.with_audio(
                moviepy.AudioClip(veo_speech, duration=1.0, fps=22050)
            )
        clip.write_videofile(
            str(p), fps=8, codec="libx264", audio_codec="aac", logger=None
        )
        paths.append(str(p))
    rate = 24000
    t = np.arange(int(rate * 0.4)) / rate
    voice = story_service._write_wav(
        str(tmp_path / "line.wav"), 0.3 * np.sin(2 * np.pi * 220 * t), rate
    )
    scenes = _clips([1, 1])
    scenes[1].spoken, scenes[1].narration = True, "Hello"
    plan = build_stitch_plan(scenes, crossfade=0.25, dub=True)
    assert plan.segments[1].dub
    out = story_service.stitch_local(
        paths, plan, str(tmp_path / "film.mp4"), voice_paths=["", voice], fps=8
    )
    audio = story_service.read_mono(out, 16000)
    window = audio[int(1.45 * 16000) : int(1.75 * 16000)]
    spectrum = np.abs(np.fft.rfft(window))
    peak_hz = np.argmax(spectrum) * 16000 / len(window)
    assert peak_hz == pytest.approx(220, abs=25)  # the fixed voice, not Veo's
    assert np.abs(audio[: int(0.9 * 16000)]).max() < 0.02  # silent first scene


def test_tts_voice_follows_speaker_gender():
    assert story_models.tts_voice_for("A female voice, 40s") == "Kore"
    assert story_models.tts_voice_for("a male voice, mid-30s") == "Charon"
    assert story_models.tts_voice_for("") == "Charon"


def test_dubbed_story_keeps_main_clips_for_second_language():
    sc = Scene(narration="a", narration_alt="b", spoken=True, clip_uri="main")
    sc.clip_alt_uri, sc.clip_alt_key = "refilmed", sc.alt_clip_key()
    assert story_models.alt_story(Story(scenes=[sc])).scenes[0].clip_uri == "main"
    refilm = Story(scenes=[sc], same_voice=False)
    assert story_models.alt_story(refilm).scenes[0].clip_uri == "refilmed"



class _VoiceMock(_SpeechMock):
    def generate_voiceover(self, story, index, text, style="narrator"):
        self.voiced = getattr(self, "voiced", []) + [
            (story.language, index, story.voice_name, style)
        ]
        return f"local://{story.language}-{story.voice_name}-v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        self.plans = getattr(self, "plans", []) + [plan]
        return super().stitch(story, plan, music_uri, voice_uris)


def test_same_voice_voices_spoken_lines_with_the_fixed_voice(local_store):
    backend = _VoiceMock()
    story_service.set_backend(backend)
    try:
        s = _spoken_story(local_store, speaker_tts_voice="Orus", voice_name="Kore")
        job = _run(story_jobs.start_video(s.id, OWNER))
        assert job.status == "done", [(t.label, t.error) for t in job.tasks]
        # Spoken scene: the fixed presenter voice; narrated scene: the narrator.
        assert ("English", 0, "Orus", "presenter") in backend.voiced
        assert ("English", 1, "Kore", "narrator") in backend.voiced
        assert backend.plans[0].segments[0].dub
        assert not backend.plans[0].segments[1].dub
        assert any("Orus voice" in t.label for t in job.tasks)
    finally:
        story_service.set_backend(None)


def test_same_voice_dubs_second_language_over_the_same_clips(local_store):
    backend = _VoiceMock()
    story_service.set_backend(backend)
    try:
        s = _spoken_story(local_store, second_on=True, speaker_tts_voice="Orus")
        job = _run(story_jobs.start_video(s.id, OWNER))
        assert job.status == "done", [(t.label, t.error) for t in job.tasks]
        assert "clip_alt" not in {t.kind for t in job.tasks}  # no re-filming
        assert not [c for c in backend.clips if c[0] == "Arabic"]
        assert ("Arabic", 0, "Orus", "presenter") in backend.voiced
        english, arabic = backend.plans
        assert [g.clip_uri for g in arabic.segments] == [
            g.clip_uri for g in english.segments
        ]
        assert arabic.segments[0].dub
        assert local_store.get(s.id, OWNER).final_alt_uri
    finally:
        story_service.set_backend(None)


def test_same_voice_works_with_narrator_voiceover_off(local_store):
    backend = _VoiceMock()
    story_service.set_backend(backend)
    try:
        s = _spoken_story(local_store, voice_on=False)
        job = _run(story_jobs.start_video(s.id, OWNER))
        assert [t.scene_index for t in job.tasks if t.kind == "voice"] == [0]
    finally:
        story_service.set_backend(None)


def test_scenario_picks_fixed_voice_from_speaker_gender(fast_backend, local_store):
    s = local_store.save(
        Story(idea="A woman presenting a new phone", scene_count=2, duration=4),
        OWNER,
    )

    def female(story):
        return json.dumps(
            {
                "title": "T",
                "voice": "A female voice, 40s, warm",
                "scenes": [
                    {"narration": "Hi.", "spoken": True, "visual": "a"},
                    {"narration": "Look.", "spoken": True, "visual": "b"},
                ],
            }
        )

    fast_backend.write_scenario = female
    assert _run(story_jobs.start_scenario(s.id, OWNER)).status == "done"
    assert local_store.get(s.id, OWNER).speaker_tts_voice == "Kore"



# ---------------------------------------------------------------------------
# Word-level lip timing, stage sound and voice preview
# ---------------------------------------------------------------------------


def test_match_words_pairs_the_same_words_in_order():
    voice = [("Hello", 0.0, 0.4), ("everyone,", 0.5, 1.0), ("welcome", 1.1, 1.6)]
    clip = [("hello", 0.8, 1.1), ("um", 1.2, 1.3), ("everyone", 1.4, 2.0), ("welcome", 2.2, 2.9)]
    pairs = story_service.match_words(voice, clip)
    assert pairs == [(0.0, 0.4, 0.8, 1.1), (0.5, 1.0, 1.4, 2.0), (1.1, 1.6, 2.2, 2.9)]
    assert story_service.match_words(voice, []) == []


def test_warp_points_are_monotonic_and_keep_lead_in_and_tail():
    pairs = [(0.2, 0.5, 1.0, 1.4), (0.6, 1.0, 1.5, 2.0)]
    points = story_service.warp_points(pairs, 1.3)
    assert points[0] == (0.0, pytest.approx(0.8))
    assert points[-1] == (1.3, pytest.approx(2.3))
    assert all(b[0] > a[0] and b[1] > a[1] for a, b in zip(points, points[1:]))


def test_atempo_chain_splits_extreme_tempos():
    assert story_service._atempo_chain(1.2) == "atempo=1.2000"
    assert story_service._atempo_chain(3.0).count("atempo") == 2


def test_warp_voice_moves_each_word_to_its_clip_time(tmp_path):
    import numpy as np

    rate = 24000
    v = np.zeros(int(rate * 1.0), dtype=np.float32)
    t = np.arange(int(rate * 0.2)) / rate
    v[: len(t)] = 0.3 * np.sin(2 * np.pi * 200 * t)  # word 1: 0.0-0.2s
    v[int(rate * 0.5) : int(rate * 0.5) + len(t)] = 0.3 * np.sin(2 * np.pi * 300 * t)  # word 2
    src = story_service._write_wav(str(tmp_path / "v.wav"), v, rate)
    # Word 1 lands at 0.4s, word 2 at 1.4s in the clip.
    points = [(0.0, 0.4), (0.2, 0.6), (0.5, 1.4), (0.7, 1.6), (1.0, 1.9)]
    out = story_service.warp_voice(src, points, str(tmp_path / "w.wav"))
    a = story_service.read_mono(out, 16000)

    def loud(t0, t1):
        return np.abs(a[int(t0 * 16000) : int(t1 * 16000)]).max()

    assert loud(0.0, 0.35) < 0.02
    assert loud(0.42, 0.58) > 0.1
    assert loud(0.7, 1.3) < 0.05
    assert loud(1.42, 1.58) > 0.1


def test_stage_voice_keeps_the_voice_without_echo(tmp_path):
    import numpy as np

    rate = 24000
    v = np.zeros(rate, dtype=np.float32)
    t = np.arange(int(rate * 0.1)) / rate
    v[: len(t)] = 0.3 * np.sin(2 * np.pi * 220 * t)
    src = story_service._write_wav(str(tmp_path / "v.wav"), v, rate)
    out = story_service.read_mono(story_service.stage_voice(src, str(tmp_path / "s.wav")), 16000)
    assert np.abs(out[: int(0.1 * 16000)]).max() > 0.1
    # No repeats of the word after it ends (they sounded boxy).
    assert np.abs(out[int(0.15 * 16000) : int(0.4 * 16000)]).max() < 0.01


def test_room_tone_keeps_only_the_background():
    import numpy as np

    rate = 16000
    rng = np.random.default_rng(1)
    a = (0.01 * rng.standard_normal(rate * 3)).astype(np.float32)
    a[rate : 2 * rate] += 0.5  # loud speech
    a[int(0.85 * rate) : rate] += 0.04  # a soft breath just before it
    bed = story_service.room_tone(a, rate, 3.0)
    assert len(bed) == 3 * rate
    assert np.abs(bed).max() < 0.03  # background only, at half level
    assert story_service.room_tone(np.zeros(0, dtype=np.float32), rate, 1.0) is None


def test_transcribe_words_falls_back_quietly(tmp_path, monkeypatch):
    import numpy as np
    import google.auth

    def broken(*a, **k):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(google.auth, "default", broken)
    src = story_service._write_wav(
        str(tmp_path / "v.wav"), 0.1 * np.ones(1600, dtype=np.float32), 16000
    )
    assert story_service.transcribe_words(src, "en-US") == []


def test_sync_words_only_for_same_language(tmp_path):
    import numpy as np

    src = story_service._write_wav(
        str(tmp_path / "v.wav"), np.zeros(16000, dtype=np.float32), 16000
    )
    words = [("a", 0.1, 0.2), ("b", 0.3, 0.4), ("c", 0.5, 0.6)]
    timer = lambda path, lang: words  # noqa: E731
    out = str(tmp_path / "o.wav")
    assert story_service._sync_words(src, src, out, timer, "ar-SA", "en-US") == ""
    assert story_service._sync_words(src, src, out, None, "en-US", "en-US") == ""
    assert story_service._sync_words(src, src, out, timer, "en-US", "en-US") == out


def test_dubbed_second_language_remembers_clip_language():
    sc = Scene(narration="a", narration_alt="b", spoken=True, clip_uri="main")
    alt = story_models.alt_story(Story(scenes=[sc], second_on=True))
    assert alt.language == "Arabic" and alt.clip_language == "English"


def test_preview_voice_uses_first_spoken_line(local_store):
    calls = []

    class Backend(_SpeechMock):
        def generate_voiceover(self, story, index, text, style="narrator"):
            calls.append((story.voice_name, index, text, style))
            return "local://sample.wav"

    story_service.set_backend(Backend())
    try:
        scenes = [Scene(narration="Intro.", duration=4), Scene(narration="Hi all!", spoken=True, duration=4)]
        assert story_jobs.preview_voice(Story(scenes=scenes), "Orus") == "local://sample.wav"
        assert calls == [("Orus", 1, "Hi all!", "presenter")]
        story_jobs.preview_voice(Story(scenes=[Scene(narration="x", duration=4)]), "Kore")
        assert calls[-1][2] == story_jobs.PREVIEW_LINE["English"]
    finally:
        story_service.set_backend(None)


def test_presenter_lines_use_the_speaker_model():
    from config.default import Default

    cfg = Default()
    assert cfg.STORY_SPEAKER_TTS_MODEL == "gemini-2.5-pro-tts"
    assert "stage" in story_service.PRESENTER_DIRECTION



# ---------------------------------------------------------------------------
# Dubbed lines copy how the person speaks in the clip
# ---------------------------------------------------------------------------


def test_pause_marked_adds_pauses_where_the_person_stops():
    clip = [
        ("good", 0.0, 0.3), ("evening", 0.35, 0.8),  # short gap: no pause
        ("everyone", 1.2, 1.7),  # 0.4 s gap: comma
        ("welcome", 2.5, 3.0),  # 0.8 s gap: dots
        ("home", 3.05, 3.4),
    ]
    out = story_service.pause_marked("Good evening everyone welcome home.", clip)
    assert out == "Good evening, everyone... welcome home."
    # Existing punctuation is kept, and no timings means no change.
    assert story_service.pause_marked("Hi, there", [("hi", 0, 0.2), ("there", 1.0, 1.3)]) == "Hi, there"
    assert story_service.pause_marked("Hi there", []) == "Hi there"


def test_pace_direction_reads_the_speed():
    fast = [(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(10)]
    slow = [(str(i), i * 0.8, i * 0.8 + 0.5) for i in range(5)]
    assert "quickly" in story_service.pace_direction(fast)
    assert "slowly" in story_service.pace_direction(slow)
    assert story_service.pace_direction([]) == ""


def test_spoken_line_is_voiced_after_its_clip_with_its_delivery(local_store):
    order = []

    class Backend(_VoiceMock):
        def generate_clip(self, story, index, start_frame_uri):
            order.append(("clip", index))
            return super().generate_clip(story, index, start_frame_uri)

        def study_delivery(self, story, index, clip_uri, text, same_language):
            order.append(("study", index, bool(clip_uri), same_language))
            return "Warm and excited.", text.replace(" ", ", ", 1)

        def generate_voiceover(self, story, index, text, style="narrator", direction=""):
            order.append(("voice", index, style, direction, text))
            return super().generate_voiceover(story, index, text, style)

    backend = Backend()
    story_service.set_backend(backend)
    try:
        s = _spoken_story(local_store, second_on=True, speaker_tts_voice="Orus")
        job = _run(story_jobs.start_video(s.id, OWNER))
        assert job.status == "done", [(t.label, t.error) for t in job.tasks]
        clip0 = order.index(("clip", 0))
        studies = [e for e in order if e[0] == "study"]
        assert {e[3] for e in studies} == {True, False}  # main line, then Arabic
        assert all(order.index(e) > clip0 and e[2] for e in studies)
        spoken = [e for e in order if e[0] == "voice" and e[2] == "presenter"]
        assert spoken and all(e[3] == "Warm and excited." and ", " in e[4] for e in spoken)
    finally:
        story_service.set_backend(None)


def test_mock_backend_studies_nothing():
    backend = story_service.MockStoryBackend()
    assert backend.study_delivery(Story(), 0, "local://c.mp4", "Hi there", True) == ("", "Hi there")
