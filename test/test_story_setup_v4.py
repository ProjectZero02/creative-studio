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
"""Story Studio v4 Phases B and C: one Setup screen, live blueprint,
several brands, references, take-start frames and the guided flow."""

import json
from types import SimpleNamespace

import pytest

import pages.story_studio as page
from common import brand_kit as bk
from components.story_studio import setup_view
from services import story_director as sd
from services import story_jobs, story_refs, story_service, story_store
from services import story_models as sm
from services.story_models import Scene, Story
from services.story_sets import LocalSetStore, StorySet, set_set_store
from state.story_state import StoryState

OWNER = "alice@example.com"
OTHER = "bob@example.com"


# ---------------------------------------------------------------------------
# Duration text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, secs",
    [
        ("30s", 30),
        ("30 sec", 30),
        ("2 min", 120),
        ("2 minutes", 120),
        ("1m30s", 90),
        ("1 min 30 sec", 90),
        ("1:30", 90),
        ("90", 90),
        ("2.5 minutes", 150),
        ("half a minute", 30),
        ("two minutes", 120),
        ("", 0),
        ("   ", 0),
    ],
)
def test_parse_duration_text(text, secs):
    assert sd.parse_duration_text(text) == secs


@pytest.mark.parametrize("text", ["abc", "soon", "0", "0:00", "-"])
def test_parse_duration_text_rejects_non_lengths(text):
    assert sd.parse_duration_text(text) is None


def test_parse_duration_text_is_capped():
    cap = sm.Default().STORY_MAX_FILM_SECONDS
    assert sd.parse_duration_text("10 hours") == cap


# ---------------------------------------------------------------------------
# Live blueprint
# ---------------------------------------------------------------------------


def test_blueprint_30s_is_one_continuous_take():
    bp = sd.setup_blueprint(30, video_model="gemini-omni-1.2-flash")
    assert bp["takes"] == 1 and bp["cuts"] == 0
    assert sd.takes_line(bp["takes"]) == "1 continuous take"
    assert bp["shots"] * bp["shot_seconds"] == bp["seconds"]
    assert abs(bp["seconds"] - 30) <= bp["shot_seconds"]


def test_blueprint_cost_uses_pricing_per_second():
    bp = sd.setup_blueprint(30, video_model="gemini-omni-1.2-flash")
    cost = bp["cost"]
    assert cost["video"] == round(bp["seconds"] * 0.40, 2)  # Omni list price
    assert cost["frames"] > 0 and cost["music"] == 0.06
    assert cost["total"] == round(
        cost["video"] + cost["frames"] + cost["voice"] + cost["music"], 2
    )
    fast = sd.setup_blueprint(30, video_model="3.1-fast")
    assert fast["cost"]["video"] < cost["video"]


def test_blueprint_long_film_has_cuts_and_takes_fit_the_take_limit():
    bp = sd.setup_blueprint(120, video_model="gemini-omni-1.2-flash")
    cap = sm.Default().STORY_TAKE_MAX_SECONDS
    assert bp["takes"] >= 2 and bp["cuts"] == bp["takes"] - 1
    assert sum(bp["shots_per_take"]) == bp["shots"]
    assert all(n * bp["shot_seconds"] <= cap for n in bp["shots_per_take"])
    assert sd.takes_line(3) == "3 takes, 2 cuts"
    assert bp["time_seconds"] > sd.setup_blueprint(30)["time_seconds"] - 1


def test_blueprint_blank_uses_the_default_length():
    assert (
        sd.setup_blueprint(0)["seconds"]
        == sd.setup_blueprint(sd.DEFAULT_FILM_SECONDS)["seconds"]
    )


def test_blueprint_resolution_follows_the_engine():
    assert (
        sd.setup_blueprint(30, video_model="gemini-omni-1.2-flash", resolution="4k")[
            "resolution"
        ]
        == "4k"
    )
    assert sm.resolution_options("gemini-omni-1.2-flash") == ["720p", "1080p", "4k"]
    # An engine without 4K falls back to the configured default.
    assert "4k" not in sm.resolution_options("gemini-omni-flash-preview")


def test_story_resolution_is_per_story():
    story = Story(video_model="gemini-omni-1.2-flash", resolution="1080p")
    assert sm.story_resolution(story) == "1080p"
    story.resolution = "8k"
    assert sm.story_resolution(story) == sm.Default().STORY_VIDEO_RESOLUTION
    assert sm.story_resolution(Story()) == sm.Default().STORY_VIDEO_RESOLUTION


def _setup_state(**kw) -> StoryState:
    s = StoryState()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_setup_blueprint_updates_from_the_duration_box_and_the_idea():
    s = _setup_state(duration_text="2 min")
    assert setup_view.blueprint(s)["seconds"] == 120
    assert setup_view.blueprint(s)["source"] == "box"
    s = _setup_state(auto_json=json.dumps({"film_seconds": 60}))
    assert setup_view.blueprint(s)["source"] == "idea"
    assert setup_view.blueprint(s)["seconds"] == 64
    assert setup_view.blueprint(_setup_state())["source"] == "auto"


def test_pacing_chips_are_calm_normal_fast():
    assert [sm.PACING_MODES[p]["label"] for p in setup_view.PACING_CHIPS] == [
        "Calm",
        "Normal",
        "Fast",
    ]


def test_style_text_replaces_the_preset_prompt():
    story = Story(style="anime")
    assert sm.style_of(story)["prompt"] == sm.STYLE_BY_ID["anime"]["prompt"]
    story.style_prompt = "grainy 16mm film, warm tungsten light"
    assert sm.style_of(story)["prompt"] == "grainy 16mm film, warm tungsten light"
    assert "grainy 16mm" in sm.frame_prompt(story, Scene(visual="A pier."), False)
    assert "grainy 16mm" in sm.scenario_prompt(story) or "Anime" in sm.scenario_prompt(
        story
    )


def test_director_reads_the_camera_from_the_idea():
    prompt = sm.scenario_prompt(Story(idea="the camera pans left to right slowly"))
    assert "Read the camera from the idea" in prompt


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------


def test_migration_copies_the_old_kit_once():
    store = bk.MemoryBrandStore()
    store.set_legacy(OWNER, {"name": "Acme", "colors": ["#ff0000"], "tone": "calm"})
    rows = bk.list_brands(OWNER, store)
    assert len(rows) == 1 and rows[0]["name"] == "Acme" and rows[0]["is_default"]
    assert store.legacy(OWNER)["migrated"] is True
    assert len(bk.list_brands(OWNER, store)) == 1  # not copied again


def test_migration_of_an_unnamed_or_empty_kit():
    store = bk.MemoryBrandStore()
    store.set_legacy(OWNER, {"colors": ["#00ff00"]})
    assert bk.list_brands(OWNER, store)[0]["name"] == "My brand"
    other = bk.MemoryBrandStore()
    other.set_legacy(OWNER, {"name": ""})
    assert bk.list_brands(OWNER, other) == []
    assert bk.migrate(OWNER, other) is None


def test_several_brands_with_one_default():
    store = bk.MemoryBrandStore()
    a = bk.save_brand(OWNER, {"name": "Acme"}, store)
    b = bk.save_brand(OWNER, {"name": "Beta", "colors": ["#123456"]}, store)
    assert a["is_default"] and not b["is_default"]
    assert bk.set_default(OWNER, b["id"], store)
    rows = bk.list_brands(OWNER, store)
    assert [r["name"] for r in rows] == ["Beta", "Acme"]
    assert [r["is_default"] for r in rows] == [True, False]
    assert bk.default_brand(OWNER, store)["id"] == b["id"]
    # Deleting the default makes the next one the default.
    assert bk.delete_brand(OWNER, b["id"], store)
    assert bk.default_brand(OWNER, store)["id"] == a["id"]


def test_brands_are_owner_only():
    store = bk.MemoryBrandStore()
    a = bk.save_brand(OWNER, {"name": "Acme"}, store)
    assert bk.get_brand(OTHER, a["id"], store) is None
    assert bk.list_brands(OTHER, store) == []
    assert bk.delete_brand(OTHER, a["id"], store) is False
    assert bk.set_default(OTHER, a["id"], store) is False
    with pytest.raises(PermissionError):
        bk.save_brand(OTHER, {"id": a["id"], "name": "Stolen"}, store)
    assert bk.get_brand(OWNER, a["id"], store)["name"] == "Acme"


def test_update_keeps_id_default_and_created():
    store = bk.MemoryBrandStore()
    a = bk.save_brand(OWNER, {"name": "Acme"}, store)
    b = bk.save_brand(
        OWNER, {"id": a["id"], "name": "Acme 2", "is_default": False}, store
    )
    assert b["id"] == a["id"] and b["is_default"] and b["created"] == a["created"]


def test_load_and_save_use_the_default_brand(monkeypatch):
    store = bk.MemoryBrandStore()
    bk.set_store(store)
    try:
        assert bk.load(OWNER) == bk.empty()
        bk.save(OWNER, {"name": "Acme", "tone": "warm"})
        assert bk.load(OWNER)["name"] == "Acme"
        bk.save(OWNER, {"name": "Acme", "tone": "bold"})
        assert len(bk.list_brands(OWNER)) == 1 and bk.load(OWNER)["tone"] == "bold"
    finally:
        bk.set_store(None)


def test_story_keeps_a_brand_snapshot(monkeypatch):
    store = bk.MemoryBrandStore()
    bk.set_store(store)
    try:
        a = bk.save_brand(OWNER, {"name": "Acme", "colors": ["#ff0000"]}, store)
        bid, snap = page._brand_snapshot(OWNER, "")  # "" = the default brand
        assert bid == a["id"] and json.loads(snap)["name"] == "Acme"
        assert page._brand_snapshot(OWNER, "none") == ("", "")
        assert page._brand_snapshot(OTHER, a["id"]) == ("", "")
    finally:
        bk.set_store(None)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------


def test_new_refs_get_unique_tags_and_mentions():
    refs = []
    for kind in ("character", "character", "object"):
        refs.append(story_refs.new_ref(kind, refs))
    assert [r["tag"] for r in refs] == ["Character", "Character2", "Product"]
    assert story_refs.new_ref("brand", refs) is None
    idea = story_refs.mention("A launch film for", "Product")
    assert idea == "A launch film for @Product"
    assert story_refs.mention(idea, "Product") == idea
    assert story_refs.mentioned(idea, refs) == {refs[2]["id"]}
    assert story_refs.clean_tag(" Mara Lee! ") == "MaraLee"


def test_refs_become_set_assets_with_locked_images():
    refs = [
        {
            "kind": "character",
            "tag": "Mara",
            "role": "presenter",
            "uri": "gs://b/m.png",
        },
        {"kind": "object", "tag": "Phone", "uri": "gs://b/p.png"},
        {"kind": "location", "tag": "Stage"},
        {"kind": "voice", "tag": "Narrator", "voice": "Puck"},
    ]
    made = story_refs.build_set(refs, owner=OWNER, name="Refs")
    assert [c.name for c in made.on_screen()] == ["Mara"]
    assert made.characters[0].description == "presenter"
    front = next(i for i in made.characters[0].images if i.view == "front")
    assert front.uri == "gs://b/m.png" and front.locked
    assert made.props[0].images[0].uri == "gs://b/p.png"
    assert made.locations[0].name == "Stage"
    assert made.narrator().voice.tts_voice == "Puck"
    assert story_refs.narrator_voice(story_refs.parse(json.dumps(refs))) == "Puck"
    assert story_refs.build_set([], owner=OWNER) is None


def test_refs_copy_a_picked_set_and_never_change_it():
    base = StorySet(owner=OWNER, name="Office")
    made = story_refs.build_set(
        [{"kind": "object", "tag": "Mug"}], base=base, owner=OWNER
    )
    assert made.id != base.id and made.name == "Office + references"
    assert base.props == [] and [p.name for p in made.props] == ["Mug"]


# ---------------------------------------------------------------------------
# Take-start frames (Phase C)
# ---------------------------------------------------------------------------


def _take_story(n=4, joins=("extend", "extend", "cut")) -> Story:
    scenes = [Scene(visual=f"v{i}", duration=8) for i in range(n)]
    for sc, join in zip(scenes[1:], joins, strict=False):
        sc.transition = join
    return Story(owner=OWNER, scenes=scenes, continuous_takes=True)


def test_frames_only_where_a_take_starts():
    story = _take_story()
    assert sm.take_groups(story) == [[0, 1, 2], [3]]
    assert sm.frame_scenes(story) == [0, 3]
    assert not sm.frames_ready(story)
    story.scenes[0].frame_uri = "gs://b/a.png"
    story.scenes[3].frame_uri = "gs://b/d.png"
    assert sm.frames_ready(story)  # scenes 1 and 2 continue take 1
    assert sm.frame_for(story, 2) == "gs://b/a.png"
    assert sm.frame_for(story, 3) == "gs://b/d.png"


class _FastMock(story_service.MockStoryBackend):
    def __init__(self):
        super().__init__(speed=0)
        self.painted = []
        self.notes = {}

    def generate_frame(self, story, index, reference_uri, note=""):
        self.painted.append(index)
        self.notes[index] = note
        return f"local://{story.id}/frame{index}-{len(self.painted)}.png"

    def generate_clip(self, story, index, start_frame_uri, end_frame_uri=""):
        return f"local://{story.id}/clip{index}.mp4"

    def extend_clip(self, story, index, prev_clip):
        return f"local://{story.id}/take{index}.mp4", 0.0

    def last_frame(self, story, clip_uri, index):
        return f"local://{story.id}/last{index}.png"

    def generate_music(self, story, prompt, seconds):
        return "local://m.wav"

    def generate_voiceover(self, story, index, text, style="narrator"):
        return f"local://v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        return "local://film.mp4"


@pytest.fixture
def jobs_env(tmp_path):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    story_store.set_store(store)
    set_set_store(LocalSetStore(str(tmp_path / "sets.json")))
    backend = _FastMock()
    story_service.set_backend(backend)
    yield store, backend
    story_service.set_backend(None)
    story_store.set_store(None)
    set_set_store(None)


def _run(job):
    done = story_jobs.wait(job.id, OWNER, timeout=20)
    assert done is not None and done.status != "running"
    return done


def test_storyboard_paints_take_starts_only(jobs_env):
    store, backend = jobs_env
    story = store.save(_take_story(), OWNER)
    job = _run(story_jobs.start_storyboard(story.id, OWNER))
    assert job.status == "done"
    assert sorted(backend.painted) == [0, 3]
    story = store.get(story.id, OWNER)
    assert [bool(sc.frame_uri) for sc in story.scenes] == [True, False, False, True]
    assert sm.frames_ready(story)


def test_redo_frame_inside_a_take_repaints_the_take_start_with_the_note(jobs_env):
    store, backend = jobs_env
    story = _take_story()
    for i in (0, 3):
        story.scenes[i].frame_uri = f"gs://b/{i}.png"
    story.scenes[1].clip_uri = "gs://b/c1.mp4"
    story = store.save(story, OWNER)
    job = _run(story_jobs.start_storyboard(story.id, OWNER, [2], note="warmer light"))
    assert job.status == "done"
    assert backend.painted == [0] and backend.notes[0] == "warmer light"
    story = store.get(story.id, OWNER)
    assert story.scenes[0].frame_uri.startswith("local://")
    assert story.scenes[1].clip_uri == ""  # the take's clips change with its frame
    assert story.scenes[3].frame_uri == "gs://b/3.png"


def test_make_film_needs_take_start_frames_only(jobs_env):
    store, _backend = jobs_env
    story = _take_story()
    story.scenes[0].frame_uri = "gs://b/0.png"
    story = store.save(story, OWNER)
    with pytest.raises(story_jobs.GenerationError):
        story_jobs.start_video(story.id, OWNER)
    story_jobs.mutate_story(
        story.id, OWNER, lambda s: setattr(s.scenes[3], "frame_uri", "gs://b/3.png")
    )
    job = _run(story_jobs.start_video(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks if t.error]
    assert store.get(story.id, OWNER).final_uri == "local://film.mp4"


def test_frame_prompt_carries_the_redo_note():
    story = Story()
    prompt = sm.frame_prompt(story, Scene(visual="A pier."), False, note="more fog")
    assert "Director's note for this version, follow it: more fog." in prompt
    assert "Director's note" not in sm.frame_prompt(
        story, Scene(visual="A pier."), False
    )


def test_scenario_then_frames_runs_on_its_own(jobs_env):
    store, backend = jobs_env
    story = store.save(
        Story(idea="A lighthouse keeper befriends a whale", scene_count=3, duration=4),
        OWNER,
    )
    job = _run(story_jobs.start_scenario(story.id, OWNER, then_frames=True))
    assert job.status == "done"
    snap = story_jobs.job_snapshot(job.id, OWNER)
    assert snap["next_job"]
    frames = _run(story_jobs.get_job(snap["next_job"], OWNER))
    assert frames.kind == "storyboard" and frames.status == "done"
    assert sm.frames_ready(store.get(story.id, OWNER))


def test_redo_clip_plan():
    story = _take_story()
    assert page.redo_clip_plan(story, 3) == ([3], False)
    assert page.redo_clip_plan(story, 1) == ([1, 2], True)


# ---------------------------------------------------------------------------
# Page: Setup handlers
# ---------------------------------------------------------------------------


@pytest.fixture
def state(monkeypatch):
    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    monkeypatch.setattr(page, "_owner", lambda: OWNER)
    return st


def test_duration_box_sets_the_target(state):
    page.on_duration_live(SimpleNamespace(value={"value": "2 min"}))
    assert state.duration_text == "2 min" and state.target_seconds == 120
    page.on_duration_blur(SimpleNamespace(value=""))
    assert state.target_seconds == 0


def test_style_chip_fills_real_style_text(state):
    page.on_style_chip(SimpleNamespace(key="sty-anime"))
    assert state.style == "anime"
    assert state.style_text == sm.STYLE_BY_ID["anime"]["prompt"]
    page.on_style_blur(SimpleNamespace(value="pastel watercolour"))
    assert state.style_text == "pastel watercolour" and state.style == "anime"


def test_pacing_chip_and_resolution(state):
    page.on_pacing(SimpleNamespace(key="pace-dynamic"))
    assert state.pacing == "dynamic"
    page.on_resolution(SimpleNamespace(value="1080p"))
    assert state.resolution == "1080p"
    page.on_resolution(SimpleNamespace(value="8k"))
    assert state.resolution == "1080p"


def test_reference_menu_add_tag_mention_remove(state):
    page.on_add_ref(SimpleNamespace(key="addref-character"))
    ref = story_refs.parse(state.refs_json)[0]
    page.on_ref_tag(SimpleNamespace(key=f"reftag-{ref['id']}", value="Mara"))
    page.on_ref_mention(SimpleNamespace(key=f"refat-{ref['id']}"))
    assert state.idea == "@Mara"
    page.on_ref_remove(SimpleNamespace(key=f"refrm-{ref['id']}"))
    assert story_refs.parse(state.refs_json) == []


def test_setup_plan_uses_the_blueprint(state):
    state.duration_text = "1 min"
    target, count, dur = page.setup_plan(state)
    assert target == 60 and count * dur == sd.setup_blueprint(60)["seconds"]
