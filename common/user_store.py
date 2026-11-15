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
"""Users for session sign-in (``AUTH_MODE=session``).

Two backends behind one interface:

* ``FirestoreUserStore``: collection ``studio_users`` (doc id = lowercased
  email) in the app's Firestore database. Used on Cloud Run.
* ``FileUserStore``: a JSON file (default ``.local/users.json``, gitignored)
  for local development without Google Cloud credentials.

``USER_STORE`` picks one (``firestore`` or ``file``). When unset, local envs
use the file and everything else uses Firestore.

Records: ``email, name, role, active, password_hash, created_at, last_login``.
``public_user`` strips the hash before anything leaves this module for the UI.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from pathlib import Path

from common.identity import LOCAL_APP_ENVS
from common.passwords import hash_password, password_problem

logger = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_ADMIN, ROLE_USER)

USERS_COLLECTION = "studio_users"
DEFAULT_FILE_PATH = os.path.join(".local", "users.json")


class UserStoreError(Exception):
    """A user can't be created or changed (shown to the admin as-is)."""


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def public_user(record: dict) -> dict:
    """Return a copy of a user record that is safe to show (no hash)."""
    return {
        "email": record.get("email", ""),
        "name": record.get("name", ""),
        "role": record.get("role", ROLE_USER),
        "active": bool(record.get("active", False)),
        "created_at": record.get("created_at") or "",
        "last_login": record.get("last_login") or "",
    }


class UserStore:
    """Shared logic; subclasses implement ``_get``, ``_put`` and ``_all``."""

    def _get(self, email: str) -> dict | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _put(self, email: str, record: dict) -> None:  # pragma: no cover
        raise NotImplementedError

    def _all(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    # --- reads --------------------------------------------------------- #
    def get(self, email: str) -> dict | None:
        key = normalize_email(email)
        return self._get(key) if key else None

    def list_users(self) -> list[dict]:
        return sorted(self._all(), key=lambda r: r.get("email", ""))

    def has_active_admin(self) -> bool:
        return any(r.get("role") == ROLE_ADMIN and r.get("active") for r in self._all())

    def active_admin_count(self) -> int:
        return sum(
            1 for r in self._all() if r.get("role") == ROLE_ADMIN and r.get("active")
        )

    # --- writes -------------------------------------------------------- #
    def create(self, *, email: str, name: str, role: str, password: str) -> dict:
        key = normalize_email(email)
        if not key or "@" not in key or len(key) > 254:
            raise UserStoreError("Enter a valid email.")
        if role not in ROLES:
            raise UserStoreError("Pick a role.")
        if self._get(key) is not None:
            raise UserStoreError("A user with this email already exists.")
        record = {
            "email": key,
            "name": (name or "").strip()[:120] or key.split("@", 1)[0],
            "role": role,
            "active": True,
            "password_hash": hash_password(password),
            "created_at": _now(),
            "last_login": None,
        }
        self._put(key, record)
        return record

    def update(self, email: str, **fields) -> dict:
        key = normalize_email(email)
        record = self._get(key)
        if record is None:
            raise UserStoreError("No such user.")
        allowed = {"name", "role", "active", "password_hash", "last_login"}
        unknown = set(fields) - allowed
        if unknown:
            raise UserStoreError(f"Can't change {', '.join(sorted(unknown))}.")
        if "role" in fields and fields["role"] not in ROLES:
            raise UserStoreError("Pick a role.")
        record = {**record, **fields}
        self._put(key, record)
        return record

    def set_password(self, email: str, password: str) -> dict:
        return self.update(email, password_hash=hash_password(password))

    def record_login(self, email: str) -> None:
        try:
            self.update(email, last_login=_now())
        except Exception as exc:  # noqa: BLE001 - never block a login on this
            logger.warning("Could not record last login: %s", type(exc).__name__)


class FileUserStore(UserStore):
    """JSON file store for local development (one process)."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict]:
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        return data if isinstance(data, dict) else {}

    def _get(self, email: str) -> dict | None:
        with self._lock:
            record = self._load().get(email)
        return dict(record) if record else None

    def _put(self, email: str, record: dict) -> None:
        with self._lock:
            data = self._load()
            data[email] = record
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)

    def _all(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._load().values()]


class FirestoreUserStore(UserStore):
    """Firestore store (collection ``studio_users``)."""

    def __init__(self, client=None, collection: str = USERS_COLLECTION):
        if client is None:
            from config.firebase_config import FirebaseClient

            client = FirebaseClient(
                database_id=os.environ.get("GENMEDIA_FIREBASE_DB", "(default)"),
            ).get_client()
        if client is None:
            raise UserStoreError("Firestore is not available for the users store.")
        self._col = client.collection(collection)

    def _get(self, email: str) -> dict | None:
        snap = self._col.document(email).get()
        return snap.to_dict() if snap.exists else None

    def _put(self, email: str, record: dict) -> None:
        self._col.document(email).set(record)

    def _all(self) -> list[dict]:
        return [doc.to_dict() for doc in self._col.stream()]


_store: UserStore | None = None
_store_lock = threading.Lock()


def _backend_name() -> str:
    configured = (os.environ.get("USER_STORE") or "").strip().lower()
    if configured in ("file", "firestore"):
        return configured
    is_local = os.environ.get("APP_ENV", "") in LOCAL_APP_ENVS and not os.environ.get(
        "K_SERVICE",
    )
    return "file" if is_local else "firestore"


def get_user_store() -> UserStore:
    """Return the process-wide users store (created on first use)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                if _backend_name() == "file":
                    _store = FileUserStore(
                        os.environ.get("USER_STORE_PATH") or DEFAULT_FILE_PATH,
                    )
                else:
                    _store = FirestoreUserStore()
    return _store


def set_user_store(store: UserStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store


def bootstrap_admin() -> bool:
    """Create the first admin from env vars if the store has no active admin.

    Reads ``BOOTSTRAP_ADMIN_EMAIL`` and ``BOOTSTRAP_ADMIN_PASSWORD``. Returns
    True when a user was created or re-activated. Never logs the password.
    """
    email = normalize_email(os.environ.get("BOOTSTRAP_ADMIN_EMAIL"))
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or ""
    if not email or not password:
        return False
    if password_problem(password):
        logger.error("BOOTSTRAP_ADMIN_PASSWORD is too short; no admin created.")
        return False
    store = get_user_store()
    if store.has_active_admin():
        return False
    if store.get(email) is None:
        store.create(email=email, name="Admin", role=ROLE_ADMIN, password=password)
    else:
        store.update(email, role=ROLE_ADMIN, active=True)
        store.set_password(email, password)
    logger.warning("Created the first admin account for %s.", email)
    return True
