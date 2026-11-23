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
"""Settings an admin sets once for everyone (Settings > Admin).

One Firestore document (``app_settings/global``) when deployed, a JSON file
under ``.local/`` in demo mode. Reads are cached for a short time so the side
menu does not hit Firestore on every page.

Today it holds one switch: ``show_demos`` (Fashion, Interiors, Product 360
and Brand kit in the side menu), off by default. The demo pages still open
from their links when it is off.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

DEFAULTS: dict = {"show_demos": False}
# Saved switches older than this version are dropped once, so a demo switch
# left on while testing goes back to off (owner, 2026-11-23). Bump it to reset
# every saved setting again.
VERSION = 2
VERSION_KEY = "settings_version"
CACHE_SECONDS = 30
LOCAL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".local", "app_settings.json")
COLLECTION = "app_settings"
DOC_ID = "global"

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def _local() -> bool:
    try:
        from services.story_service import is_mock_mode

        return is_mock_mode()
    except Exception:  # pylint: disable=broad-except
        return True


def _doc():
    from config.default import Default
    from config.firebase_config import FirebaseClient

    db = FirebaseClient(database_id=Default().GENMEDIA_FIREBASE_DB).get_client()
    return db.collection(COLLECTION).document(DOC_ID)


def _read() -> dict:
    if _local():
        try:
            with open(LOCAL_PATH, encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}
    snap = _doc().get()
    return (snap.to_dict() or {}) if snap.exists else {}


def get_all() -> dict:
    """Every setting, with defaults filled in (cached for a few seconds)."""
    global _cache
    with _lock:
        if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return dict(_cache[1])
    try:
        stored = _read()
        if stored.get(VERSION_KEY, 0) < VERSION:
            stored = {}
        values = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    except Exception:  # pylint: disable=broad-except
        logger.warning("app_settings: read failed, using defaults", exc_info=True)
        values = dict(DEFAULTS)
    with _lock:
        _cache = (time.monotonic(), values)
    return dict(values)


def get(name: str):
    return get_all().get(name, DEFAULTS.get(name))


def set_value(name: str, value) -> None:
    """Save one setting for everyone. Only known settings are accepted."""
    global _cache
    if name not in DEFAULTS:
        raise KeyError(name)
    if _local():
        values = {**get_all(), name: value, VERSION_KEY: VERSION}
        os.makedirs(os.path.dirname(LOCAL_PATH), exist_ok=True)
        with open(LOCAL_PATH, "w", encoding="utf-8") as f:
            json.dump(values, f)
    else:
        _doc().set({name: value, VERSION_KEY: VERSION}, merge=True)
    with _lock:
        _cache = None


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None
