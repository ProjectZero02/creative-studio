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
"""Owner-only storage for Story Studio stories.

Firestore collection ``stories`` in real mode; a JSON file under the
gitignored ``.local/`` folder in demo mode. Both stores apply the same rule:
a story is visible and writable only by the email that created it. Reads of
someone else's story return ``None`` (indistinguishable from "not found").
"""

from __future__ import annotations

import json
import os
import threading
from typing import Protocol

from common.analytics import get_logger
from config.default import Default
from services.story_models import Story

logger = get_logger(__name__)

LOCAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".local")


class StoryAccessError(PermissionError):
    """The caller does not own this story."""


def owns(story_owner: str | None, caller: str | None) -> bool:
    """Strict owner check: both must be set and equal (fails closed)."""
    return bool(caller) and bool(story_owner) and story_owner == caller


def _bucket_of(uri: str) -> str:
    """Bucket name of a gs:// URI or a configured bucket path, else ""."""
    rest = (uri or "").strip().removeprefix("gs://")
    return rest.split("/", 1)[0]


def deployment_buckets() -> set[str]:
    """Buckets this deployment writes media to (see config.default)."""
    cfg = Default()
    names = {
        _bucket_of(cfg.GENMEDIA_BUCKET or ""),
        _bucket_of(cfg.VIDEO_BUCKET or ""),
        _bucket_of(cfg.IMAGE_BUCKET or ""),
        _bucket_of(cfg.MEDIA_BUCKET or ""),
    }
    return {n for n in names if n}


def belongs_here(story: Story, buckets: set[str] | None = None) -> bool:
    """False when the story's media lives in another deployment's bucket.

    Two services can share one Firestore database (for example a quickstart
    deploy next to a Terraform one). Each writes media to its own bucket,
    which the other cannot read, so a story from the other service would
    show here with every image and clip broken. Such stories are hidden.
    Stories with no gs:// media yet, and demo-mode local:// media, stay.
    """
    used = {_bucket_of(u) for u in story.media_uris() if u.startswith("gs://")}
    if not used:
        return True
    mine = deployment_buckets() if buckets is None else buckets
    return not mine or used <= mine


class StoryStore(Protocol):
    def list(self, owner: str) -> list[Story]: ...
    def get(self, story_id: str, owner: str) -> Story | None: ...
    def save(self, story: Story, owner: str) -> Story: ...
    def delete(self, story_id: str, owner: str) -> bool: ...


class LocalStoryStore:
    """JSON-file store for demo mode (one file, guarded by a lock)."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(LOCAL_DIR, "stories.json")
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

    def list(self, owner: str) -> list[Story]:
        with self._lock:
            rows = [Story.from_dict(d) for d in self._read().values()]
        rows = [s for s in rows if owns(s.owner, owner)]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    def get(self, story_id: str, owner: str) -> Story | None:
        with self._lock:
            raw = self._read().get(story_id)
        if not raw or not owns(raw.get("owner"), owner):
            return None
        return Story.from_dict(raw)

    def save(self, story: Story, owner: str) -> Story:
        if not owner:
            raise StoryAccessError("Sign in to save stories.")
        with self._lock:
            data = self._read()
            existing = data.get(story.id)
            if existing and not owns(existing.get("owner"), owner):
                raise StoryAccessError("You can only change your own stories.")
            story.owner = owner
            story.touch()
            data[story.id] = story.to_dict()
            self._write(data)
        return story

    def delete(self, story_id: str, owner: str) -> bool:
        with self._lock:
            data = self._read()
            existing = data.get(story_id)
            if not existing or not owns(existing.get("owner"), owner):
                return False
            del data[story_id]
            self._write(data)
        return True


class FirestoreStoryStore:
    """Firestore store. Queries are filtered by owner on the server."""

    def __init__(self, db=None, collection: str | None = None):
        if db is None:
            from config.firebase_config import FirebaseClient

            db = FirebaseClient(database_id=Default().GENMEDIA_FIREBASE_DB).get_client()
        self.db = db
        self.collection = collection or Default().STORIES_COLLECTION_NAME

    def _ref(self, story_id: str):
        return self.db.collection(self.collection).document(story_id)

    def list(self, owner: str) -> list[Story]:
        if not owner:
            return []
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = (
            self.db.collection(self.collection)
            .where(filter=FieldFilter("owner", "==", owner))
            .limit(60)
            .stream()
        )
        rows = [Story.from_dict(d.to_dict() or {}) for d in docs]
        mine = deployment_buckets()
        rows = [s for s in rows if owns(s.owner, owner) and belongs_here(s, mine)]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    def get(self, story_id: str, owner: str) -> Story | None:
        if not story_id:
            return None
        snap = self._ref(story_id).get()
        if snap is None or not getattr(snap, "exists", False):
            return None
        data = snap.to_dict() or {}
        if not owns(data.get("owner"), owner):
            return None
        story = Story.from_dict(data)
        return story if belongs_here(story) else None

    def save(self, story: Story, owner: str) -> Story:
        if not owner:
            raise StoryAccessError("Sign in to save stories.")
        ref = self._ref(story.id)
        snap = ref.get()
        if getattr(snap, "exists", False):
            existing = snap.to_dict() or {}
            if not owns(existing.get("owner"), owner):
                raise StoryAccessError("You can only change your own stories.")
        story.owner = owner
        story.touch()
        ref.set(story.to_dict())
        return story

    def delete(self, story_id: str, owner: str) -> bool:
        ref = self._ref(story_id)
        snap = ref.get()
        if not getattr(snap, "exists", False):
            return False
        if not owns((snap.to_dict() or {}).get("owner"), owner):
            return False
        ref.delete()
        return True


_store: StoryStore | None = None
_store_lock = threading.Lock()


def get_store() -> StoryStore:
    """The store for this process: local JSON in demo mode, else Firestore."""
    global _store
    with _store_lock:
        if _store is None:
            from services.story_service import is_mock_mode

            if is_mock_mode():
                _store = LocalStoryStore()
            else:
                try:
                    _store = FirestoreStoryStore()
                    if _store.db is None:
                        raise RuntimeError("Firestore client unavailable")
                except Exception as exc:  # pragma: no cover - env specific
                    logger.warning(
                        "Story Studio: Firestore unavailable (%s); using local store",
                        exc,
                    )
                    _store = LocalStoryStore()
        return _store


def set_store(store: StoryStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store
