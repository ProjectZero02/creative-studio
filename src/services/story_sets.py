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
"""Sets: reusable characters (with voice), locations, props and a style.

A set is made once (by hand, or automatically from a story) and reused by
any number of stories, so every clip of every film is anchored to the same
reference images. Storage follows ``story_store``: Firestore collection
``story_sets`` in real mode, a JSON file under ``.local/`` in demo mode, and
both are owner-only (a set someone else owns reads as "not found").
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Protocol

from common.analytics import get_logger
from config.default import Default
from services.story_models import EVERYDAY_PERSON, STYLE_BY_ID, VOICES, _now_iso, new_id
from services.story_store import LOCAL_DIR, StoryAccessError, owns

logger = get_logger(__name__)

# Image views per asset kind, in the order they are made and shown.
CHARACTER_VIEWS = ["front", "three_quarter", "profile", "face"]
LOCATION_VIEWS = ["plate", "angle"]
PROP_VIEWS = ["item"]
VIEW_LABELS = {
    "front": "Front",
    "three_quarter": "3/4",
    "profile": "Profile",
    "face": "Face",
    "plate": "Wide",
    "angle": "Angle",
    "item": "Item",
}
KINDS = ("character", "location", "prop")


def _fields(cls, raw: dict) -> dict:
    known = set(cls.__dataclass_fields__)
    return {k: v for k, v in (raw or {}).items() if k in known}


@dataclass
class SetImage:
    view: str
    uri: str = ""
    prompt: str = ""
    locked: bool = False  # never replaced by a regenerate

    @classmethod
    def from_dict(cls, raw: dict) -> SetImage:
        data = _fields(cls, raw)
        data.setdefault("view", "front")
        return cls(**data)


@dataclass
class Voice:
    tts_voice: str = "Kore"  # Gemini TTS prebuilt voice (narrator, samples)
    style: str = ""  # TTS style prompt, kept identical on every call
    description: str = ""  # on-camera voice, said word for word in Omni prompts
    sample_uri: str = ""
    # Reserved until access is confirmed (see docs/handoff/STORY_SETS_PLAN.md).
    chirp_cloning_key: str = ""
    omni_voice_ref: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> Voice:
        voice = cls(**_fields(cls, raw))
        if voice.tts_voice not in VOICES:
            voice.tts_voice = "Kore"
        return voice


def _images(raw: list | None) -> list[SetImage]:
    return [SetImage.from_dict(i) for i in (raw or []) if isinstance(i, dict)]


@dataclass
class Character:
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    outfit: str = ""
    images: list[SetImage] = field(default_factory=list)
    voice: Voice = field(default_factory=Voice)
    narrator: bool = False  # off-screen narrator: a voice with no images

    @classmethod
    def from_dict(cls, raw: dict) -> Character:
        data = _fields(cls, raw)
        data["images"] = _images(data.get("images"))
        data["voice"] = Voice.from_dict(data.get("voice") or {})
        return cls(**data)

    def look(self) -> str:
        """Name, look and outfit in one phrase for prompts."""
        bits = [b for b in (self.description, self.outfit) if b]
        return f"{self.name} ({', '.join(bits)})" if bits else self.name


@dataclass
class Location:
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    time_of_day: str = ""
    images: list[SetImage] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> Location:
        data = _fields(cls, raw)
        data["images"] = _images(data.get("images"))
        return cls(**data)

    def look(self) -> str:
        bits = [b for b in (self.description, self.time_of_day) if b]
        return f"{self.name} ({', '.join(bits)})" if bits else self.name


@dataclass
class Prop:
    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    images: list[SetImage] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> Prop:
        data = _fields(cls, raw)
        data["images"] = _images(data.get("images"))
        return cls(**data)

    def look(self) -> str:
        return f"{self.name} ({self.description})" if self.description else self.name


Asset = Character | Location | Prop


def views_for(asset: Asset) -> list[str]:
    """The image views an asset should have."""
    if isinstance(asset, Character):
        return [] if asset.narrator else CHARACTER_VIEWS
    if isinstance(asset, Location):
        return LOCATION_VIEWS
    return PROP_VIEWS


# The views frames and clips are made from (story_models.scene_refs): a set
# build makes only these. The others (3/4, profile, angle) are made when the
# user asks for one.
BUILD_VIEWS = ("front", "face", "plate", "item")


def build_views(asset: Asset) -> list[str]:
    """The views a set build makes for an asset."""
    return [v for v in views_for(asset) if v in BUILD_VIEWS]


def image_of(asset: Asset, view: str) -> SetImage | None:
    """The asset's image for `view` (with a URI), or None."""
    for img in asset.images:
        if img.view == view and img.uri:
            return img
    return None


def ensure_views(asset: Asset) -> None:
    """Add an empty slot for every view the asset is missing."""
    have = {i.view for i in asset.images}
    for view in views_for(asset):
        if view not in have:
            asset.images.append(SetImage(view=view))
    order = {v: k for k, v in enumerate(views_for(asset))}
    asset.images.sort(key=lambda i: order.get(i.view, 99))


@dataclass
class StorySet:
    id: str = field(default_factory=new_id)
    owner: str = ""
    name: str = "Untitled set"
    style: str = "photographic"
    style_notes: str = ""
    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    props: list[Prop] = field(default_factory=list)
    created_from: str = "manual"  # "manual" | "auto" | "migrated"
    version: int = 1  # bumped on every saved change
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    # -- serialisation --
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> StorySet:
        data = _fields(cls, raw)
        data["characters"] = [
            Character.from_dict(c)
            for c in data.get("characters") or []
            if isinstance(c, dict)
        ]
        data["locations"] = [
            Location.from_dict(c)
            for c in data.get("locations") or []
            if isinstance(c, dict)
        ]
        data["props"] = [
            Prop.from_dict(c) for c in data.get("props") or [] if isinstance(c, dict)
        ]
        out = cls(**data)
        if out.style not in STYLE_BY_ID:
            out.style = "photographic"
        try:
            out.version = max(1, int(out.version))
        except TypeError, ValueError:
            out.version = 1
        return out

    def content(self, filled: set[str] | None = None) -> dict:
        """What a change means: everything but bookkeeping fields. Media in
        `filled` (URIs new since the stored copy, put in empty slots) is left
        out, because no film can have used a picture that did not exist."""
        data = self.to_dict()
        # The set's name is a label only: renaming changes nothing a film uses.
        for key in (
            "owner",
            "name",
            "created_from",
            "version",
            "created_at",
            "updated_at",
        ):
            data.pop(key, None)
        skip = filled or set()
        for kind in ("characters", "locations", "props"):
            for asset in data[kind]:
                # Locking only protects a picture; it changes nothing a film uses.
                asset["images"] = [
                    {k: v for k, v in i.items() if k != "locked"}
                    for i in asset["images"]
                    if i["uri"] and i["uri"] not in skip
                ]
                voice = asset.get("voice")
                if voice and voice["sample_uri"] in skip:
                    voice["sample_uri"] = ""
        return data

    def slots(self) -> dict[tuple, str]:
        """(kind, asset id, view) -> URI of every image and voice sample."""
        out: dict[tuple, str] = {}
        for kind in KINDS:
            for a in self.assets(kind):
                for i in a.images:
                    out[(kind, a.id, i.view)] = i.uri
                if isinstance(a, Character):
                    out[(kind, a.id, "voice")] = a.voice.sample_uri
        return out

    def touch(self) -> None:
        self.updated_at = _now_iso()

    # -- lookups --
    def character(self, cid: str) -> Character | None:
        return next((c for c in self.characters if c.id == cid), None)

    def location(self, lid: str) -> Location | None:
        return next((c for c in self.locations if c.id == lid), None)

    def prop(self, pid: str) -> Prop | None:
        return next((c for c in self.props if c.id == pid), None)

    def asset(self, kind: str, asset_id: str) -> Asset | None:
        return {
            "character": self.character,
            "location": self.location,
            "prop": self.prop,
        }.get(kind, lambda _x: None)(asset_id)

    def assets(self, kind: str) -> list:
        return {
            "character": self.characters,
            "location": self.locations,
            "prop": self.props,
        }[kind]

    def narrator(self) -> Character | None:
        return next((c for c in self.characters if c.narrator), None)

    def on_screen(self) -> list[Character]:
        return [c for c in self.characters if not c.narrator]

    def media_uris(self) -> list[str]:
        uris: list[str] = []
        for a in [*self.characters, *self.locations, *self.props]:
            uris += [i.uri for i in a.images if i.uri]
        uris += [c.voice.sample_uri for c in self.characters if c.voice.sample_uri]
        return uris

    def image_count(self) -> int:
        """How many images a full build makes (shown before running it)."""
        return sum(
            len(build_views(a)) for a in [*self.characters, *self.locations, *self.props]
        )

    def missing_images(self) -> int:
        """Image slots still without a picture."""
        total = 0
        for a in [*self.characters, *self.locations, *self.props]:
            total += sum(1 for v in build_views(a) if image_of(a, v) is None)
        return total

    def summary(self) -> str:
        """Short count line for pickers, e.g. "2 characters · 1 location"."""

        def n(count: int, word: str) -> str:
            return f"{count} {word}{'' if count == 1 else 's'}"

        parts = [n(len(self.on_screen()), "character")]
        if self.locations:
            parts.append(n(len(self.locations), "location"))
        if self.props:
            parts.append(n(len(self.props), "prop"))
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Stores (owner-only, like services.story_store)
# ---------------------------------------------------------------------------


def _bump(story_set: StorySet, existing: dict | None) -> None:
    """Set the version from the stored copy: +1 when the content changed."""
    if not existing:
        story_set.version = max(1, story_set.version)
        return
    old = StorySet.from_dict(existing)
    before = old.slots()
    filled = {
        uri for key, uri in story_set.slots().items() if uri and not before.get(key)
    }
    changed = old.content() != story_set.content(filled)
    story_set.version = old.version + 1 if changed else old.version
    story_set.created_at = old.created_at or story_set.created_at


class SetStore(Protocol):
    def list(self, owner: str) -> list[StorySet]: ...
    def get(self, set_id: str, owner: str) -> StorySet | None: ...
    def save(self, story_set: StorySet, owner: str) -> StorySet: ...
    def delete(self, set_id: str, owner: str) -> bool: ...


class LocalSetStore:
    """JSON-file store for demo mode (one file, guarded by a lock)."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(LOCAL_DIR, "story_sets.json")
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except OSError, ValueError:
            return {}

    def _write(self, data: dict[str, dict]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def list(self, owner: str) -> list[StorySet]:
        with self._lock:
            rows = [StorySet.from_dict(d) for d in self._read().values()]
        rows = [s for s in rows if owns(s.owner, owner)]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    def get(self, set_id: str, owner: str) -> StorySet | None:
        with self._lock:
            raw = self._read().get(set_id)
        if not raw or not owns(raw.get("owner"), owner):
            return None
        return StorySet.from_dict(raw)

    def save(self, story_set: StorySet, owner: str) -> StorySet:
        if not owner:
            raise StoryAccessError("Sign in to save sets.")
        with self._lock:
            data = self._read()
            existing = data.get(story_set.id)
            if existing and not owns(existing.get("owner"), owner):
                raise StoryAccessError("You can only change your own sets.")
            story_set.owner = owner
            _bump(story_set, existing)
            story_set.touch()
            data[story_set.id] = story_set.to_dict()
            self._write(data)
        return story_set

    def delete(self, set_id: str, owner: str) -> bool:
        with self._lock:
            data = self._read()
            existing = data.get(set_id)
            if not existing or not owns(existing.get("owner"), owner):
                return False
            del data[set_id]
            self._write(data)
        return True


class FirestoreSetStore:
    """Firestore store. Queries are filtered by owner on the server and
    sorted here, so no composite index is needed."""

    def __init__(self, db=None, collection: str | None = None):
        if db is None:
            from config.firebase_config import FirebaseClient

            db = FirebaseClient(database_id=Default().GENMEDIA_FIREBASE_DB).get_client()
        self.db = db
        self.collection = collection or Default().STORY_SETS_COLLECTION_NAME

    def _ref(self, set_id: str):
        return self.db.collection(self.collection).document(set_id)

    def list(self, owner: str) -> list[StorySet]:
        if not owner:
            return []
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = (
            self.db.collection(self.collection)
            .where(filter=FieldFilter("owner", "==", owner))
            .limit(100)
            .stream()
        )
        rows = [StorySet.from_dict(d.to_dict() or {}) for d in docs]
        rows = [s for s in rows if owns(s.owner, owner)]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    def get(self, set_id: str, owner: str) -> StorySet | None:
        if not set_id:
            return None
        snap = self._ref(set_id).get()
        if snap is None or not getattr(snap, "exists", False):
            return None
        data = snap.to_dict() or {}
        if not owns(data.get("owner"), owner):
            return None
        return StorySet.from_dict(data)

    def save(self, story_set: StorySet, owner: str) -> StorySet:
        if not owner:
            raise StoryAccessError("Sign in to save sets.")
        ref = self._ref(story_set.id)
        snap = ref.get()
        existing = (snap.to_dict() or {}) if getattr(snap, "exists", False) else None
        if existing and not owns(existing.get("owner"), owner):
            raise StoryAccessError("You can only change your own sets.")
        story_set.owner = owner
        _bump(story_set, existing)
        story_set.touch()
        ref.set(story_set.to_dict())
        return story_set

    def delete(self, set_id: str, owner: str) -> bool:
        ref = self._ref(set_id)
        snap = ref.get()
        if not getattr(snap, "exists", False):
            return False
        if not owns((snap.to_dict() or {}).get("owner"), owner):
            return False
        ref.delete()
        return True


_set_store: SetStore | None = None
_set_store_lock = threading.Lock()


def get_set_store() -> SetStore:
    """The set store for this process: local JSON in demo mode, else Firestore."""
    global _set_store
    with _set_store_lock:
        if _set_store is None:
            from services.story_service import is_mock_mode

            if is_mock_mode():
                _set_store = LocalSetStore()
            else:
                try:
                    _set_store = FirestoreSetStore()
                    if _set_store.db is None:
                        raise RuntimeError("Firestore client unavailable")
                except Exception as exc:  # pragma: no cover - env specific
                    logger.warning(
                        "Story Studio: Firestore unavailable (%s); using local set store",
                        exc,
                    )
                    _set_store = LocalSetStore()
        return _set_store


def set_set_store(store: SetStore | None) -> None:
    """Swap the set store (tests)."""
    global _set_store
    _set_store = store


def duplicate(story_set: StorySet, owner: str, name: str = "") -> StorySet:
    """A copy with a new id and version 1 (images are shared, not copied)."""
    copy = StorySet.from_dict(story_set.to_dict())
    copy.id = new_id()
    copy.owner = owner
    copy.name = name or f"{story_set.name} copy"
    copy.version = 1
    copy.created_at = copy.updated_at = _now_iso()
    copy.created_from = "manual"
    return copy


# ---------------------------------------------------------------------------
# Migration of stories made before sets
# ---------------------------------------------------------------------------


def needs_migration(story) -> bool:
    """True for a story from before sets that has cast details to keep."""
    if story.set_id:
        return False
    return bool(story.reference_uri or story.character or story.speaker_voice)


def _lead_name(character: str) -> str:
    head = (character or "").split(",")[0].split(".")[0].strip()
    return head if head and len(head.split()) <= 3 else "Lead"


def legacy_set(story) -> StorySet:
    """A one-character set from an old story's reference image, character
    text and voice fields. Also tags every scene with that character (and
    as the speaker of spoken lines). Pure: nothing is saved."""
    lead = Character(
        name=_lead_name(story.character),
        description=story.character or "",
        images=[SetImage("front", story.reference_uri)] if story.reference_uri else [],
        voice=Voice(
            tts_voice=story.voice_name if story.voice_name in VOICES else "Kore",
            description=story.speaker_voice or "",
        ),
    )
    ensure_views(lead)
    characters = [lead]
    if story.voice_on:
        characters.append(
            Character(
                name="Narrator",
                narrator=True,
                voice=Voice(
                    tts_voice=story.voice_name
                    if story.voice_name in VOICES
                    else "Kore",
                    style="Narrate warmly and clearly, like a short film voiceover.",
                ),
            )
        )
    story_set = StorySet(
        name=f"{story.title or 'Story'} set",
        style=story.style,
        characters=characters,
        created_from="migrated",
    )
    for sc in story.scenes:
        if not sc.cast:
            sc.cast = [lead.id]
        if sc.spoken and not sc.speaker_id:
            sc.speaker_id = lead.id
    return story_set


# ---------------------------------------------------------------------------
# Image recipes (Nano Banana): front first, other views from it
# ---------------------------------------------------------------------------

_NO_TEXT = "No text, no captions, no watermark."


def aspect_for(asset: Asset, view: str) -> str:
    if isinstance(asset, Character):
        return "1:1" if view == "face" else "3:4"
    if isinstance(asset, Location):
        return "16:9"
    return "1:1"


def anchor_view(asset: Asset) -> str:
    """The view every other view of the asset is made from."""
    return "front" if isinstance(asset, Character) else "plate"


def image_prompt(story_set: StorySet, asset: Asset, view: str) -> str:
    """The prompt for one image of an asset, in the set's style."""
    style = STYLE_BY_ID.get(story_set.style, STYLE_BY_ID["photographic"])["prompt"]
    notes = (
        f" {story_set.style_notes.strip()}." if story_set.style_notes.strip() else ""
    )
    look = asset.look()
    if isinstance(asset, Character):
        same = (
            "The same person as the reference image, same outfit, preserve identity, "
            "face, hair, body and colours exactly. "
        )
        shots = {
            "front": (
                f"Full-body character reference of {look}. Standing, facing the "
                "camera, neutral pose, arms relaxed, whole body in frame."
            ),
            "three_quarter": f"{same}Full body, three-quarter view, turned 45 degrees.",
            "profile": f"{same}Full body, side profile view.",
            "face": f"{same}Head-and-shoulders close-up of the face, looking at the camera.",
        }
        shot = shots.get(view, shots["front"])
        if view != "front":
            shot += f" The character: {look}."
        return (
            f"{shot} Plain light-grey studio background, even soft light. "
            f"One person only, {EVERYDAY_PERSON}. Style: {style}.{notes} {_NO_TEXT}"
        )
    if isinstance(asset, Location):
        if view == "plate":
            shot = f"Wide establishing shot of {look}."
        else:
            shot = (
                "The same place as the reference image from a different camera "
                "angle: same layout, materials, colours and light. "
                f"The place: {look}."
            )
        return f"{shot} Empty: no people, no animals. Style: {style}.{notes} {_NO_TEXT}"
    return (
        f"Reference image of {look}, centred on a plain light-grey background, "
        f"soft even light, the whole object in frame. Style: {style}.{notes} {_NO_TEXT}"
    )


def voice_sample_text(character: Character) -> str:
    """A ~5 second line for the voice sample."""
    if character.narrator:
        return "Every story starts somewhere. This one starts here, tonight."
    return f"Hi, I'm {character.name}. This is how I sound in every scene."
