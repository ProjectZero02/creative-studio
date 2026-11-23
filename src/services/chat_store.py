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
"""Owner-only storage for the Home chat's saved chats and projects.

A chat is one conversation thread; a project is a folder of chats. Firestore
collections ``chats`` and ``chat_projects`` in real mode; JSON files under the
gitignored ``.local/`` folder in demo mode. Same rule as Story Studio
(services/story_store.py): a chat or project is visible and writable only by
the email that created it, and someone else's id reads as "not found".

Deleting a project never deletes chats: they move back to "no project".
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from common.analytics import get_logger
from config.default import Default
from services.story_store import owns

logger = get_logger(__name__)

LOCAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".local")

CHATS = "chats"
PROJECTS = "projects"

MAX_MESSAGES = 200  # a chat keeps its last 200 messages
MAX_TEXT = 20_000  # characters per message
MAX_IMAGES = 12  # image URIs per message
MAX_JOBS = 40  # jobs per message
MAX_JOB_IDS = 500  # job ids per chat
MAX_TITLE = 80
MAX_NAME = 60
LIST_LIMIT = 300  # most chats/projects one list call returns
TITLE_WORDS = 6
ROLES = ("user", "assistant")


class ChatAccessError(PermissionError):
    """The caller does not own this chat or project (or is not signed in)."""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit] if not isinstance(value, (dict, list)) else ""


def _json_value(value: Any, depth: int = 0) -> Any:
    """``value`` limited to plain JSON types (drops anything else)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if depth >= 4:
        return None
    if isinstance(value, list):
        return [_json_value(v, depth + 1) for v in value[:MAX_JOBS]]
    if isinstance(value, dict):
        return {
            str(k)[:64]: _json_value(v, depth + 1) for k, v in list(value.items())[:40]
        }
    return None


def clean_message(raw: Any) -> dict | None:
    """One stored message, or None when it is not a message."""
    if not isinstance(raw, dict):
        return None
    role = raw.get("role")
    if role not in ROLES:
        return None
    images = raw.get("images") if isinstance(raw.get("images"), list) else []
    # Only URIs: inline data: URLs would blow Firestore's 1 MiB document limit.
    images = [
        str(u)[:2048]
        for u in images
        if isinstance(u, str) and u and not u.startswith("data:")
    ][:MAX_IMAGES]
    jobs = raw.get("jobs") if isinstance(raw.get("jobs"), list) else []
    return {
        "role": role,
        "text": _text(raw.get("text"), MAX_TEXT),
        "images": images,
        "jobs": [_json_value(j, 1) for j in jobs[:MAX_JOBS]],
        "ask": _json_value(raw.get("ask"), 1),
        # The settings line under a reply from the type controls.
        "meta": _text(raw.get("meta"), 200),
    }


def clean_messages(raw: Any) -> list[dict]:
    rows = [m for m in (clean_message(r) for r in (raw or [])) if m]
    return rows[-MAX_MESSAGES:]


def clean_chat(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    job_ids = raw.get("job_ids") if isinstance(raw.get("job_ids"), list) else []
    source = raw.get("title_source")
    return {
        "id": _text(raw.get("id"), 64) or new_id(),
        "owner": _text(raw.get("owner"), 320),
        "title": " ".join(_text(raw.get("title"), MAX_TITLE).split()),
        "title_source": source if source in ("auto", "user") else "auto",
        "project_id": _text(raw.get("project_id"), 64),
        "pinned": bool(raw.get("pinned")),
        "messages": clean_messages(
            raw.get("messages") if isinstance(raw.get("messages"), list) else []
        ),
        "job_ids": [
            str(j)[:64] for j in job_ids if isinstance(j, (str, int)) and str(j)
        ][-MAX_JOB_IDS:],
        "created_at": _text(raw.get("created_at"), 40),
        "updated_at": _text(raw.get("updated_at"), 40),
    }


def clean_project(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": _text(raw.get("id"), 64) or new_id(),
        "owner": _text(raw.get("owner"), 320),
        "name": " ".join(_text(raw.get("name"), MAX_NAME).split()),
        "created_at": _text(raw.get("created_at"), 40),
        "updated_at": _text(raw.get("updated_at"), 40),
    }


def summary(chat: dict) -> dict:
    """A chat without its messages (for the sidebar list)."""
    row = {k: v for k, v in chat.items() if k != "messages"}
    row["message_count"] = len(chat.get("messages") or [])
    return row


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

TITLE_PROMPT = (
    "Write a short title (at most 6 words) for a chat that starts with the "
    "message below. Plain words, no quotes, no trailing period. Reply with the "
    "title only.\n\nMessage:"
)


def trim_title(text: str) -> str:
    """First line of ``text`` cut to a few words (the no-AI title)."""
    line = next((ln for ln in str(text or "").splitlines() if ln.strip()), "")
    words = line.split()
    title = " ".join(words[:TITLE_WORDS])
    return title[:MAX_TITLE].rstrip(" .,:;-")


def _tidy_ai_title(text: str) -> str:
    quotes = "\"'`*"
    text = str(text or "").strip().strip(quotes).strip()
    text = re.sub(r"^title\s*:\s*", "", text, flags=re.IGNORECASE)
    return trim_title(text.strip(quotes)).strip(quotes).strip()


def first_user_text(messages: list[dict]) -> str:
    return next(
        (
            m.get("text", "")
            for m in messages or []
            if m.get("role") == "user" and (m.get("text") or "").strip()
        ),
        "",
    )


def _mocked() -> bool:
    from common.mock_generation import mock_enabled

    if mock_enabled():
        return True
    from services.story_service import is_mock_mode

    return is_mock_mode()


def auto_title(text: str) -> str:
    """A short title for a chat starting with ``text``.

    Gemini writes it in real mode; demo mode, an empty answer or any error
    falls back to the first few words of the message.
    """
    text = (text or "").strip()[:2000]
    if not text:
        return ""
    fallback = trim_title(text)
    if _mocked():
        return fallback
    try:
        from models.gemini import rewriter

        return _tidy_ai_title(rewriter(text, TITLE_PROMPT)) or fallback
    except Exception:  # pylint: disable=broad-except
        logger.warning("chat title: Gemini failed, trimming the message", exc_info=True)
        return fallback


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


class ChatStore(Protocol):
    def list_chats(self, owner: str, project_id: str | None = None) -> list[dict]: ...
    def get_chat(self, chat_id: str, owner: str) -> dict | None: ...
    def save_chat(self, chat: dict, owner: str, touch: bool = True) -> dict: ...
    def delete_chat(self, chat_id: str, owner: str) -> bool: ...
    def list_projects(self, owner: str) -> list[dict]: ...
    def get_project(self, project_id: str, owner: str) -> dict | None: ...
    def save_project(self, project: dict, owner: str) -> dict: ...
    def delete_project(self, project_id: str, owner: str) -> bool: ...


def _newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: r.get("updated_at") or "", reverse=True)


class _OwnedStore:
    """Owner rules shared by both stores. Subclasses provide raw document I/O:
    ``_load(kind, id)``, ``_put(kind, doc)``, ``_remove(kind, id)`` and
    ``_by_owner(kind, owner, project_id)``.
    """

    def __init__(self):
        self._lock = threading.RLock()

    # -- raw I/O (subclasses) -------------------------------------------
    def _load(self, kind: str, doc_id: str) -> dict | None:
        raise NotImplementedError

    def _put(self, kind: str, doc: dict) -> None:
        raise NotImplementedError

    def _remove(self, kind: str, doc_id: str) -> None:
        raise NotImplementedError

    def _by_owner(
        self, kind: str, owner: str, project_id: str | None = None
    ) -> list[dict]:
        raise NotImplementedError

    # -- helpers --------------------------------------------------------
    def _owned(self, kind: str, doc_id: str, owner: str) -> dict | None:
        if not doc_id or not owner:
            return None
        raw = self._load(kind, doc_id)
        if not raw or not owns(raw.get("owner"), owner):
            return None
        return raw

    def _check_write(self, kind: str, doc_id: str, owner: str) -> dict | None:
        """The existing doc (or None if new); raises if someone else owns it."""
        if not owner:
            raise ChatAccessError("Sign in to save chats.")
        existing = self._load(kind, doc_id)
        if existing and not owns(existing.get("owner"), owner):
            raise ChatAccessError("You can only change your own chats.")
        return existing

    # -- chats ----------------------------------------------------------
    def list_chats(self, owner: str, project_id: str | None = None) -> list[dict]:
        if not owner:
            return []
        rows = [clean_chat(d) for d in self._by_owner(CHATS, owner, project_id)]
        rows = [r for r in rows if owns(r["owner"], owner)]
        if project_id is not None:
            rows = [r for r in rows if r["project_id"] == project_id]
        return _newest_first(rows)[:LIST_LIMIT]

    def get_chat(self, chat_id: str, owner: str) -> dict | None:
        raw = self._owned(CHATS, chat_id, owner)
        return clean_chat(raw) if raw else None

    def save_chat(self, chat: dict, owner: str, touch: bool = True) -> dict:
        """Create or replace a chat. ``touch=False`` keeps its place in Recents."""
        doc = clean_chat(chat)
        with self._lock:
            existing = self._check_write(CHATS, doc["id"], owner)
            if doc["project_id"] and not self._owned(
                PROJECTS, doc["project_id"], owner
            ):
                raise ValueError("Unknown project")
            now = now_iso()
            doc["owner"] = owner
            doc["created_at"] = (
                (existing or {}).get("created_at") or doc["created_at"] or now
            )
            if touch or not doc["updated_at"]:
                doc["updated_at"] = now
            self._put(CHATS, doc)
        return doc

    def delete_chat(self, chat_id: str, owner: str) -> bool:
        with self._lock:
            if not self._owned(CHATS, chat_id, owner):
                return False
            self._remove(CHATS, chat_id)
        return True

    # -- projects -------------------------------------------------------
    def list_projects(self, owner: str) -> list[dict]:
        if not owner:
            return []
        rows = [clean_project(d) for d in self._by_owner(PROJECTS, owner)]
        rows = [r for r in rows if owns(r["owner"], owner)]
        return _newest_first(rows)[:LIST_LIMIT]

    def get_project(self, project_id: str, owner: str) -> dict | None:
        raw = self._owned(PROJECTS, project_id, owner)
        return clean_project(raw) if raw else None

    def save_project(self, project: dict, owner: str) -> dict:
        doc = clean_project(project)
        if not doc["name"]:
            raise ValueError("Name the project.")
        with self._lock:
            existing = self._check_write(PROJECTS, doc["id"], owner)
            now = now_iso()
            doc["owner"] = owner
            doc["created_at"] = (
                (existing or {}).get("created_at") or doc["created_at"] or now
            )
            doc["updated_at"] = now
            self._put(PROJECTS, doc)
        return doc

    def delete_project(self, project_id: str, owner: str) -> bool:
        """Delete a project; its chats move back to "no project"."""
        with self._lock:
            if not self._owned(PROJECTS, project_id, owner):
                return False
            for chat in self._by_owner(CHATS, owner, project_id):
                if (
                    owns(chat.get("owner"), owner)
                    and chat.get("project_id") == project_id
                ):
                    chat = clean_chat(chat)
                    chat["project_id"] = ""
                    self._put(CHATS, chat)
            self._remove(PROJECTS, project_id)
        return True


class LocalChatStore(_OwnedStore):
    """JSON-file store for demo mode (one file per kind, guarded by a lock)."""

    def __init__(self, folder: str | None = None):
        super().__init__()
        folder = folder or LOCAL_DIR
        self.paths = {
            CHATS: os.path.join(folder, "chats.json"),
            PROJECTS: os.path.join(folder, "chat_projects.json"),
        }

    def _read(self, kind: str) -> dict[str, dict]:
        try:
            with open(self.paths[kind], encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except OSError, ValueError:
            return {}

    def _write(self, kind: str, data: dict[str, dict]) -> None:
        path = self.paths[kind]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def _load(self, kind: str, doc_id: str) -> dict | None:
        with self._lock:
            return self._read(kind).get(doc_id)

    def _put(self, kind: str, doc: dict) -> None:
        with self._lock:
            data = self._read(kind)
            data[doc["id"]] = doc
            self._write(kind, data)

    def _remove(self, kind: str, doc_id: str) -> None:
        with self._lock:
            data = self._read(kind)
            if data.pop(doc_id, None) is not None:
                self._write(kind, data)

    def _by_owner(
        self, kind: str, owner: str, project_id: str | None = None
    ) -> list[dict]:
        with self._lock:
            rows = list(self._read(kind).values())
        return [
            r
            for r in rows
            if isinstance(r, dict)
            and owns(r.get("owner"), owner)
            and (project_id is None or r.get("project_id") == project_id)
        ]


class FirestoreChatStore(_OwnedStore):
    """Firestore store. Queries are filtered by owner on the server."""

    def __init__(self, db=None, chats: str | None = None, projects: str | None = None):
        super().__init__()
        if db is None:
            from config.firebase_config import FirebaseClient

            db = FirebaseClient(database_id=Default().GENMEDIA_FIREBASE_DB).get_client()
        self.db = db
        cfg = Default()
        self.collections = {
            CHATS: chats or cfg.CHATS_COLLECTION_NAME,
            PROJECTS: projects or cfg.PROJECTS_COLLECTION_NAME,
        }

    def _ref(self, kind: str, doc_id: str):
        return self.db.collection(self.collections[kind]).document(doc_id)

    def _load(self, kind: str, doc_id: str) -> dict | None:
        if not doc_id:
            return None
        snap = self._ref(kind, doc_id).get()
        if snap is None or not getattr(snap, "exists", False):
            return None
        return snap.to_dict() or {}

    def _put(self, kind: str, doc: dict) -> None:
        self._ref(kind, doc["id"]).set(doc)

    def _remove(self, kind: str, doc_id: str) -> None:
        self._ref(kind, doc_id).delete()

    def _by_owner(
        self, kind: str, owner: str, project_id: str | None = None
    ) -> list[dict]:
        if not owner:
            return []
        from google.cloud.firestore_v1.base_query import FieldFilter

        # Equality filters only, so no composite index is needed; the newest
        # first sort happens in Python.
        query = self.db.collection(self.collections[kind]).where(
            filter=FieldFilter("owner", "==", owner),
        )
        if project_id is not None:
            query = query.where(filter=FieldFilter("project_id", "==", project_id))
        return [d.to_dict() or {} for d in query.limit(LIST_LIMIT).stream()]


_store: ChatStore | None = None
_store_lock = threading.Lock()


def get_store() -> ChatStore:
    """The store for this process: local JSON in demo mode, else Firestore."""
    global _store
    with _store_lock:
        if _store is None:
            from services.story_service import is_mock_mode

            if is_mock_mode():
                _store = LocalChatStore()
            else:
                try:
                    _store = FirestoreChatStore()
                    if _store.db is None:
                        raise RuntimeError("Firestore client unavailable")
                except Exception as exc:  # pragma: no cover - env specific
                    logger.warning(
                        "Chats: Firestore unavailable (%s); using local store", exc
                    )
                    _store = LocalChatStore()
        return _store


def set_store(store: ChatStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store
