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

import pytest

from config.default import Default
from services import story_sets
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
