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
"""Story Studio Sets: model, owner-only stores, migration, auto-build, jobs, refs."""

import json
import os

import pytest

from config.default import Default
from services import story_jobs, story_service, story_sets, story_store
from services.story_models import (
    SET_MAX_CHARACTERS,
    SET_MAX_LOCATIONS,
    SET_MAX_PROPS,
    ScenarioError,
    Scene,
    Story,
    parse_scene_links,
    parse_set_build,
    scenario_prompt,
    set_build_prompt,
)
from services.story_sets import (
    Character,
    LocalSetStore,
    Location,
    Prop,
    SetImage,
    StorySet,
    Voice,
)
from services.story_store import StoryAccessError

OWNER = "alice@example.com"
OTHER = "mallory@example.com"


def _maya() -> Character:
    return Character(
        id="maya",
        name="Maya",
        description="woman in her 30s, short black hair",
        outfit="red coat",
        images=[
            SetImage("front", "gs://b/maya_front.png"),
            SetImage("face", "gs://b/maya_face.png"),
        ],
        voice=Voice(tts_voice="Aoede", description="warm alto, London accent"),
    )


def _sample_set() -> StorySet:
    return StorySet(
        name="Cafe crew",
        style="anime",
        characters=[_maya(), Character(id="nar", name="Narrator", narrator=True)],
        locations=[
            Location(
                id="cafe",
                name="The café",
                images=[SetImage("plate", "gs://b/cafe.png")],
            )
        ],
        props=[Prop(id="cup", name="Blue cup", description="chipped enamel")],
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_round_trip_keeps_everything():
    s = _sample_set()
    back = StorySet.from_dict(s.to_dict())
    assert back == s
    assert isinstance(back.characters[0].images[0], SetImage)
    assert back.characters[0].voice.tts_voice == "Aoede"


def test_from_dict_ignores_unknown_and_fixes_bad_values():
    raw = _sample_set().to_dict()
    raw["future_field"] = 1
    raw["style"] = "not-a-style"
    raw["version"] = "x"
    raw["characters"][0]["voice"]["tts_voice"] = "Nobody"
    raw["characters"][0]["images"].append("junk")
    raw["characters"][0]["extra"] = True
    s = StorySet.from_dict(raw)
    assert s.style == "photographic"
    assert s.version == 1
    assert s.characters[0].voice.tts_voice == "Kore"
    assert len(s.characters[0].images) == 2


def test_lookups_and_counts():
    s = _sample_set()
    assert s.character("maya").name == "Maya"
    assert s.location("cafe").name == "The café"
    assert s.prop("cup").name == "Blue cup"
    assert s.asset("prop", "cup") is s.props[0]
    assert s.asset("nope", "cup") is None
    assert s.narrator().name == "Narrator"
    assert [c.id for c in s.on_screen()] == ["maya"]
    # 4 views for Maya, none for the narrator, 2 for the location, 1 for the prop.
    assert s.image_count() == 7
    assert s.missing_images() == 7 - 3
    assert s.summary() == "1 character · 1 location · 1 prop"
    assert "gs://b/cafe.png" in s.media_uris()


def test_ensure_views_adds_slots_in_order():
    maya = _maya()
    story_sets.ensure_views(maya)
    assert [i.view for i in maya.images] == story_sets.CHARACTER_VIEWS
    assert story_sets.image_of(maya, "profile") is None
    assert story_sets.image_of(maya, "front").uri == "gs://b/maya_front.png"


def test_look_phrase():
    assert _maya().look() == "Maya (woman in her 30s, short black hair, red coat)"
    assert Prop(name="Cup").look() == "Cup"


def test_duplicate_gets_new_id_and_version():
    s = _sample_set()
    s.version = 5
    d = story_sets.duplicate(s, OWNER)
    assert d.id != s.id and d.version == 1 and d.name == "Cafe crew copy"
    assert d.characters[0].images[0].uri == s.characters[0].images[0].uri


def test_collection_name_default():
    assert (
        Default.__dataclass_fields__["STORY_SETS_COLLECTION_NAME"].default
        == "story_sets"
    )


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


@pytest.fixture
def set_store(tmp_path):
    store = LocalSetStore(str(tmp_path / "sets.json"))
    story_sets.set_set_store(store)
    yield store
    story_sets.set_set_store(None)


def test_local_set_store_owner_only(set_store):
    s = set_store.save(_sample_set(), OWNER)
    assert set_store.get(s.id, OWNER).name == "Cafe crew"
    assert set_store.get(s.id, OTHER) is None
    assert set_store.get(s.id, "") is None
    assert [x.id for x in set_store.list(OWNER)] == [s.id]
    assert set_store.list(OTHER) == []
    with pytest.raises(StoryAccessError):
        set_store.save(StorySet(id=s.id, name="hijack"), OTHER)
    with pytest.raises(StoryAccessError):
        set_store.save(StorySet(), "")
    assert set_store.delete(s.id, OTHER) is False
    assert set_store.delete(s.id, OWNER) is True
    assert set_store.get(s.id, OWNER) is None


def test_save_bumps_version_only_on_change(set_store):
    s = set_store.save(_sample_set(), OWNER)
    assert s.version == 1
    s = set_store.save(set_store.get(s.id, OWNER), OWNER)
    assert s.version == 1  # nothing changed
    s.characters[0].outfit = "green coat"
    s = set_store.save(s, OWNER)
    assert s.version == 2
    assert set_store.get(s.id, OWNER).version == 2


def test_filling_empty_slots_keeps_the_version(set_store):
    s = _sample_set()
    story_sets.ensure_views(s.characters[0])
    s = set_store.save(s, OWNER)
    for img in s.characters[0].images:
        if img.view == "profile":
            img.uri = "gs://b/new_profile.png"
    s.characters[0].voice.sample_uri = "gs://b/sample.wav"
    s = set_store.save(s, OWNER)
    assert s.version == 1  # new pictures in empty slots: no film used them
    for img in s.characters[0].images:
        if img.view == "profile":
            img.uri = "gs://b/other_profile.png"
    assert set_store.save(s, OWNER).version == 2  # replaced: a real change

def test_locking_an_image_keeps_the_version(set_store):
    s = set_store.save(_sample_set(), OWNER)
    s.characters[0].images[0].locked = True
    s = set_store.save(s, OWNER)
    assert s.version == 1
    assert set_store.get(s.id, OWNER).characters[0].images[0].locked



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
        db.collection_name = name

        class _Col:
            def document(self, key):
                return _Doc(db, key)

        return _Col()


def test_firestore_set_store_owner_only_and_versions():
    db = _FakeDb()
    store = story_sets.FirestoreSetStore(db=db, collection="story_sets")
    s = store.save(_sample_set(), OWNER)
    assert db.collection_name == "story_sets"
    assert store.get(s.id, OWNER).name == "Cafe crew"
    assert store.get(s.id, OTHER) is None
    with pytest.raises(StoryAccessError):
        store.save(StorySet(id=s.id), OTHER)
    s.name = "Renamed"
    assert store.save(s, OWNER).version == 2
    assert store.delete(s.id, OTHER) is False
    assert store.delete(s.id, OWNER) is True
    assert store.get(s.id, OWNER) is None


def test_firestore_set_store_hides_ownerless_docs():
    db = _FakeDb()
    db.data["x"] = StorySet(id="x").to_dict() | {"owner": ""}
    store = story_sets.FirestoreSetStore(db=db, collection="story_sets")
    assert store.get("x", OWNER) is None


# ---------------------------------------------------------------------------
# Story / Scene fields and migration
# ---------------------------------------------------------------------------


@pytest.fixture
def stores(tmp_path, set_store):
    store = story_store.LocalStoryStore(str(tmp_path / "stories.json"))
    story_store.set_store(store)
    yield store, set_store
    story_store.set_store(None)


def test_story_and_scene_set_fields_round_trip():
    st = Story(
        set_id="s1",
        set_version=3,
        scenes=[
            Scene(cast=["a", "b"], location_id="L", prop_ids=["p"], speaker_id="a")
        ],
    )
    back = Story.from_dict(st.to_dict())
    assert (back.set_id, back.set_version) == ("s1", 3)
    sc = back.scenes[0]
    assert (sc.cast, sc.location_id, sc.prop_ids, sc.speaker_id) == (
        ["a", "b"],
        "L",
        ["p"],
        "a",
    )


def test_old_story_dicts_load_with_empty_set_fields():
    raw = Story(scenes=[Scene()]).to_dict()
    raw.pop("set_id"), raw.pop("set_version")
    for key in ("cast", "location_id", "prop_ids", "speaker_id"):
        raw["scenes"][0].pop(key)
    back = Story.from_dict(raw)
    assert back.set_id == "" and back.scenes[0].cast == []


def _legacy_story(**over) -> Story:
    base = dict(
        title="Night shift",
        style="anime",
        reference_uri="gs://b/ref.png",
        character="Maya, a nurse in green scrubs",
        speaker_voice="calm alto, Irish accent",
        voice_on=True,
        voice_name="Leda",
        scenes=[Scene(spoken=True, narration="Hi."), Scene(narration="Later.")],
    )
    base.update(over)
    return Story(**base)


def test_needs_migration():
    assert story_sets.needs_migration(_legacy_story())
    assert not story_sets.needs_migration(_legacy_story(set_id="x"))
    assert not story_sets.needs_migration(
        Story(reference_uri="", character="", speaker_voice="")
    )


def test_legacy_set_keeps_reference_character_and_voices():
    story = _legacy_story()
    made = story_sets.legacy_set(story)
    lead = made.characters[0]
    assert made.created_from == "migrated" and made.style == "anime"
    assert lead.name == "Maya"
    assert lead.description == "Maya, a nurse in green scrubs"
    assert story_sets.image_of(lead, "front").uri == "gs://b/ref.png"
    assert lead.voice.description == "calm alto, Irish accent"
    assert made.narrator().voice.tts_voice == "Leda"
    assert [sc.cast for sc in story.scenes] == [[lead.id], [lead.id]]
    assert [sc.speaker_id for sc in story.scenes] == [lead.id, ""]


def test_legacy_set_long_character_text_gets_generic_name():
    made = story_sets.legacy_set(
        _legacy_story(character="a tall old man with a cane", voice_on=False)
    )
    assert made.characters[0].name == "Lead"
    assert made.narrator() is None


def test_ensure_set_migrates_once_and_owner_only(stores):
    story_db, set_db = stores
    story = story_db.save(_legacy_story(), OWNER)
    assert story_jobs.ensure_set(story.id, OTHER) is None
    migrated = story_jobs.ensure_set(story.id, OWNER)
    assert migrated.set_id
    assert migrated.set_version == 0  # no film yet
    assert set_db.get(migrated.set_id, OWNER).characters[0].name == "Maya"
    assert set_db.get(migrated.set_id, OTHER) is None
    again = story_jobs.ensure_set(story.id, OWNER)
    assert again.set_id == migrated.set_id
    assert len(set_db.list(OWNER)) == 1


def test_ensure_set_records_version_of_existing_film(stores):
    story_db, _ = stores
    story = story_db.save(_legacy_story(final_uri="gs://b/film.mp4"), OWNER)
    assert story_jobs.ensure_set(story.id, OWNER).set_version == 1


def test_ensure_set_leaves_plain_stories_alone(stores):
    story_db, set_db = stores
    story = story_db.save(Story(idea="no cast details"), OWNER)
    assert story_jobs.ensure_set(story.id, OWNER).set_id == ""
    assert set_db.list(OWNER) == []


# ---------------------------------------------------------------------------
# Auto-build prompt and parser
# ---------------------------------------------------------------------------

BUILD_JSON = {
    "name": "Night shift",
    "characters": [
        {
            "key": "c1",
            "name": "Maya",
            "description": "woman, early 30s, short black hair",
            "outfit": "green scrubs",
            "voice": {
                "tts_voice": "Aoede",
                "style": "calm",
                "description": "a female voice, early 30s, soft Irish accent",
            },
        },
        {
            "key": "c2",
            "name": "Dr Okafor",
            "description": "man, 50s",
            "voice": {"tts_voice": "Nobody"},
        },
        {"key": "c3", "name": ""},
    ],
    "narrator": {"tts_voice": "Charon", "style": "low and slow"},
    "locations": [
        {
            "key": "l1",
            "name": "Ward 7",
            "description": "dim hospital ward",
            "time_of_day": "night",
        }
    ],
    "props": [{"key": "p1", "name": "Clipboard", "description": "worn blue clipboard"}],
    "scenes": [
        {"cast": ["c1"], "location": "l1", "props": ["p1"], "speaker": "c1"},
        {
            "cast": ["c1", "c2", "ghost"],
            "location": "Ward 7",
            "props": [],
            "speaker": "",
        },
        {"cast": "c2", "location": "nowhere", "props": "p1", "speaker": "c2"},
    ],
}


def _three_scene_story() -> Story:
    return Story(
        idea="A nurse on a night shift",
        style="anime",
        voice_name="Kore",
        scenes=[
            Scene(spoken=True, narration="I'm Maya.", visual="Maya at the desk"),
            Scene(narration="The night was long.", visual="The ward at night"),
            Scene(spoken=True, narration="Go home.", visual="Okafor talks"),
        ],
    )


def test_parse_set_build_makes_assets_and_links():
    story = _three_scene_story()
    made = parse_set_build("```json\n" + json.dumps(BUILD_JSON) + "\n```", story)
    assert made.created_from == "auto" and made.style == "anime"
    names = [c.name for c in made.characters]
    assert names == ["Maya", "Dr Okafor", "Narrator"]  # nameless one dropped
    maya, okafor, narrator = made.characters
    assert maya.voice.description.startswith("a female voice")
    assert okafor.voice.tts_voice in story_sets.VOICES  # bad voice replaced
    assert narrator.narrator and narrator.voice.tts_voice == "Charon"
    assert [i.view for i in maya.images] == story_sets.CHARACTER_VIEWS
    assert [i.view for i in made.locations[0].images] == story_sets.LOCATION_VIEWS
    ward, clip = made.locations[0], made.props[0]
    s1, s2, s3 = story.scenes
    assert (s1.cast, s1.location_id, s1.prop_ids, s1.speaker_id) == (
        [maya.id],
        ward.id,
        [clip.id],
        maya.id,
    )
    # Unknown cast dropped, location matched by name, narrated scene has no speaker.
    assert (s2.cast, s2.location_id, s2.speaker_id) == (
        [maya.id, okafor.id],
        ward.id,
        "",
    )
    # Single strings accepted, unknown location blank.
    assert (s3.cast, s3.location_id, s3.prop_ids, s3.speaker_id) == (
        [okafor.id],
        "",
        [clip.id],
        okafor.id,
    )


def test_parse_set_build_caps_counts():
    data = dict(BUILD_JSON)
    data["characters"] = [{"name": f"P{i}"} for i in range(9)]
    data["locations"] = [{"name": f"L{i}"} for i in range(9)]
    data["props"] = [{"name": f"X{i}"} for i in range(9)]
    made = parse_set_build(json.dumps(data), _three_scene_story())
    assert len(made.on_screen()) == SET_MAX_CHARACTERS
    assert len(made.locations) == SET_MAX_LOCATIONS
    assert len(made.props) == SET_MAX_PROPS


def test_parse_set_build_no_narrator_without_narrated_lines():
    story = _three_scene_story()
    for sc in story.scenes:
        sc.spoken = True
    made = parse_set_build(json.dumps(BUILD_JSON), story)
    assert made.narrator() is None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1, 2]",
        json.dumps({"characters": [], "locations": []}),
        json.dumps({"props": [{"name": "x"}]}),
    ],
)
def test_parse_set_build_rejects_unusable(text):
    with pytest.raises(ScenarioError):
        parse_set_build(text, _three_scene_story())


def test_spoken_scene_without_speaker_gets_first_cast_member():
    story = _three_scene_story()
    made = parse_set_build(json.dumps(BUILD_JSON), story)
    links = {"scenes": [{"cast": ["Dr Okafor"], "speaker": "nobody"}]}
    parse_scene_links(json.dumps(links), made, story.scenes)
    assert story.scenes[0].speaker_id == made.characters[1].id


def test_scene_links_match_names_and_ignore_bad_json():
    story = _three_scene_story()
    made = _sample_set()
    parse_scene_links(
        json.dumps(
            {
                "scenes": [
                    {
                        "cast": ["MAYA", "Narrator"],
                        "location": "the café",
                        "speaker": "Maya",
                    }
                ]
            }
        ),
        made,
        story.scenes,
    )
    sc = story.scenes[0]
    assert sc.cast == ["maya"]  # the narrator is never on screen
    assert sc.location_id == "cafe" and sc.speaker_id == "maya"
    before = [s.cast for s in story.scenes]
    parse_scene_links("garbage", made, story.scenes)
    assert [s.cast for s in story.scenes] == before


def test_set_build_prompt_lists_scenes_and_voices():
    prompt = set_build_prompt(_three_scene_story())
    assert "1. [spoken on camera] Maya at the desk" in prompt
    assert "2. [narrator]" in prompt
    assert "Aoede (female)" in prompt
    assert '"scenes": [{"cast": [str]' in prompt


def test_scenario_prompt_uses_saved_set():
    story = _three_scene_story()
    plain = scenario_prompt(story)
    assert "Use this cast" not in plain and '"cast"' not in plain
    with_set = scenario_prompt(story, _sample_set())
    assert (
        "Character Maya: Maya (woman in her 30s, short black hair, red coat)."
        in with_set
    )
    assert "Location The café" in with_set
    assert '"speaker": str' in with_set


# ---------------------------------------------------------------------------
# Backend images and the "set" job (mock backend, no network)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_backend(stores, tmp_path, monkeypatch):
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    backend = story_service.MockStoryBackend(speed=0)
    story_service.set_backend(backend)
    yield backend
    story_service.set_backend(None)


def _run(job):
    done = story_jobs.wait(job.id, OWNER, timeout=30)
    assert done is not None and done.status != "running"
    return done


def _story_with_scenes(story_db, **over) -> Story:
    base = dict(
        idea="A lighthouse keeper and a stray cat",
        title="Keeper",
        voice_name="Leda",
        scenes=[
            Scene(spoken=True, narration="Hello.", visual="v1"),
            Scene(narration="Night falls.", visual="v2"),
            Scene(narration="Morning.", visual="v3"),
        ],
    )
    base.update(over)
    return story_db.save(Story(**base), OWNER)


def test_mock_set_image_and_sample_are_local_files(mock_backend):
    s = _sample_set()
    for aspect in ("3:4", "16:9", "1:1"):
        uri = mock_backend.generate_set_image(s, "Full-body character", [], aspect)
        assert uri.startswith(f"local://story_sets/{s.id}/")
        assert os.path.getsize(story_service.local_path(uri)) > 0
    wav = mock_backend.voice_sample(s, s.characters[0])
    assert wav.endswith(".wav") and os.path.isfile(story_service.local_path(wav))


def test_vertex_set_image_uses_nano_banana_with_refs(monkeypatch):
    calls = {}

    def fake(**kw):
        calls.update(kw)
        return ["gs://b/story_sets/x/set_1.png"], 0, [], None, []

    import models.gemini as gemini

    monkeypatch.setattr(gemini, "generate_image_from_prompt_and_images", fake)
    backend = story_service.VertexStoryBackend.__new__(story_service.VertexStoryBackend)
    s = _sample_set()
    uri = backend.generate_set_image(s, "p", ["gs://b/front.png"], "3:4")
    assert uri == "gs://b/story_sets/x/set_1.png"
    assert calls["images"] == ["gs://b/front.png"]
    assert calls["aspect_ratio"] == "3:4"
    assert calls["gcs_folder"] == f"story_sets/{s.id}"


def test_image_prompts_follow_the_recipes():
    s = _sample_set()
    maya, cafe, cup = s.characters[0], s.locations[0], s.props[0]
    front = story_sets.image_prompt(s, maya, "front")
    assert "Full-body character reference of Maya" in front
    assert "plain light-grey studio background" in front.lower()
    assert "preserve identity" in story_sets.image_prompt(s, maya, "profile")
    assert "close-up of the face" in story_sets.image_prompt(s, maya, "face")
    assert "no people" in story_sets.image_prompt(s, cafe, "plate")
    assert "different camera angle" in story_sets.image_prompt(s, cafe, "angle")
    assert "plain light-grey background" in story_sets.image_prompt(s, cup, "item")
    assert story_sets.aspect_for(maya, "front") == "3:4"
    assert story_sets.aspect_for(maya, "face") == "1:1"
    assert story_sets.aspect_for(cafe, "plate") == "16:9"


def test_set_job_casts_paints_and_links_scenes(mock_backend, stores):
    story_db, set_db = stores
    story = _story_with_scenes(story_db)
    job = _run(story_jobs.start_set(story.id, OWNER))
    assert job.status == "done", [t.error for t in job.tasks]
    assert job.kind == "set"
    story = story_db.get(story.id, OWNER)
    made = set_db.get(story.set_id, OWNER)
    assert made.created_from == "auto"
    assert made.missing_images() == 0
    assert all(c.voice.sample_uri for c in made.characters)
    lead = made.on_screen()[0]
    assert story.scenes[0].cast[0] == lead.id
    assert story.scenes[0].speaker_id == lead.id
    assert story.scenes[0].location_id == made.locations[0].id
    # Casting, then one task per image and voice sample.
    assert len(job.tasks) == 1 + made.image_count() + len(made.characters)


def test_set_views_are_made_from_the_front_image(mock_backend, stores):
    story_db, set_db = stores
    seen = []
    real = mock_backend.generate_set_image

    def spy(story_set, prompt, refs, aspect_ratio="1:1"):
        uri = real(story_set, prompt, refs, aspect_ratio)
        seen.append((list(refs), uri))
        return uri

    mock_backend.generate_set_image = spy
    story = _story_with_scenes(story_db)
    _run(story_jobs.start_set(story.id, OWNER))
    made = set_db.get(story_db.get(story.id, OWNER).set_id, OWNER)
    refs_of = {uri: refs for refs, uri in seen}
    lead = made.on_screen()[0]
    front = story_sets.image_of(lead, "front").uri
    assert refs_of[front] == []
    for view in ("three_quarter", "profile", "face"):
        assert refs_of[story_sets.image_of(lead, view).uri] == [front]
    plate = story_sets.image_of(made.locations[0], "plate").uri
    angle = story_sets.image_of(made.locations[0], "angle").uri
    assert refs_of[plate] == [] and refs_of[angle] == [plate]


def test_regenerate_one_image_and_locked_images_stay(mock_backend, stores):
    story_db, set_db = stores
    story = _story_with_scenes(story_db)
    _run(story_jobs.start_set(story.id, OWNER))
    set_id = story_db.get(story.id, OWNER).set_id
    lead = set_db.get(set_id, OWNER).on_screen()[0]
    before = {i.view: i.uri for i in lead.images}

    def lock_face(st):
        for img in st.character(lead.id).images:
            if img.view == "face":
                img.locked = True

    story_jobs.mutate_set(set_id, OWNER, lock_face)
    targets = [["character", lead.id, "profile"], ["character", lead.id, "face"]]
    job = _run(story_jobs.start_set(story.id, OWNER, targets))
    assert [t.label for t in job.tasks] == [f"{lead.name} · Profile"]
    after = {i.view: i.uri for i in set_db.get(set_id, OWNER).character(lead.id).images}
    assert after["profile"] != before["profile"]
    assert after["face"] == before["face"]  # locked
    assert after["front"] == before["front"]


def test_editing_a_description_regenerates_nothing(mock_backend, stores):
    story_db, set_db = stores
    story = _story_with_scenes(story_db)
    _run(story_jobs.start_set(story.id, OWNER))
    set_id = story_db.get(story.id, OWNER).set_id
    v1 = set_db.get(set_id, OWNER)

    def edit(st):
        st.on_screen()[0].description = "now with a beard"

    v2 = story_jobs.mutate_set(set_id, OWNER, edit)
    assert v2.version == v1.version + 1
    assert [i.uri for i in v2.on_screen()[0].images] == [
        i.uri for i in v1.on_screen()[0].images
    ]
    # Nothing is missing, so a plain run has nothing to do.
    job = _run(story_jobs.start_set(story.id, OWNER))
    assert job.tasks == [] and job.status == "done"


class _FlakyFront(story_service.MockStoryBackend):
    def __init__(self):
        super().__init__(speed=0)
        self.fail = True

    def generate_set_image(self, story_set, prompt, refs, aspect_ratio="1:1"):
        if self.fail and prompt.startswith("Full-body character reference"):
            raise story_service.GenerationError("busy")
        return super().generate_set_image(story_set, prompt, refs, aspect_ratio)


def test_failed_front_skips_its_views_and_retry_finishes(stores, tmp_path, monkeypatch):
    story_db, set_db = stores
    monkeypatch.setattr(story_service, "LOCAL_MEDIA_DIR", str(tmp_path / "media"))
    backend = _FlakyFront()
    story_service.set_backend(backend)
    try:
        story = _story_with_scenes(story_db)
        job = _run(story_jobs.start_set(story.id, OWNER))
        assert job.status == "failed"
        lead = set_db.get(story_db.get(story.id, OWNER).set_id, OWNER).on_screen()[0]
        status = {t.label: t.status for t in job.tasks}
        assert status[f"{lead.name} · Front"] == "failed"
        assert status[f"{lead.name} · Profile"] == "skipped"
        assert any(k.endswith("· Wide") and v == "done" for k, v in status.items())
        backend.fail = False
        again = _run(story_jobs.retry(job.id, OWNER))
        assert again.status == "done"
        made = set_db.get(story_db.get(story.id, OWNER).set_id, OWNER)
        assert made.missing_images() == 0
    finally:
        story_service.set_backend(None)


def test_set_job_retries_bad_casting_json_once(mock_backend, stores):
    story_db, _ = stores
    calls = {"n": 0}
    real = mock_backend.write_set

    def flaky(story):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else real(story)

    mock_backend.write_set = flaky
    story = _story_with_scenes(story_db)
    assert _run(story_jobs.start_set(story.id, OWNER)).status == "done"
    assert calls["n"] == 2


def test_set_job_owner_only(mock_backend, stores):
    story_db, _ = stores
    story = _story_with_scenes(story_db)
    with pytest.raises(StoryAccessError):
        story_jobs.start_set(story.id, OTHER)
    with pytest.raises(StoryAccessError):
        story_jobs.attach_set(story.id, OWNER, "someone-elses-set")


def test_scenario_with_a_saved_set_casts_its_people(mock_backend, stores):
    story_db, set_db = stores
    saved = set_db.save(_sample_set(), OWNER)
    story = story_db.save(Story(idea="A morning at the cafe", scene_count=3), OWNER)
    story_jobs.attach_set(story.id, OWNER, saved.id)
    assert _run(story_jobs.start_scenario(story.id, OWNER)).status == "done"
    story = story_db.get(story.id, OWNER)
    assert story.set_id == saved.id
    assert all(sc.cast == ["maya"] for sc in story.scenes)
    assert story.scenes[0].location_id == "cafe"
    assert story.scenes[0].visual.startswith("Maya")
