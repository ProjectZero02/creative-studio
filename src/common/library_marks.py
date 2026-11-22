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
"""Library stars and collections, per person.

One Firestore document per person in ``library_marks`` holds the ids of the
media items they starred and their named collections::

    {"owner": "a@x", "starred": ["id1", ...], "collections": {"Ads": ["id2"]}}

Marks only point at items; opening one still goes through
``common.metadata.get_media_item_by_id``, so a mark never widens who can
read an item. The edit helpers are pure (they take and return the dict) so
they are easy to test; :func:`save` writes the result.
"""

from __future__ import annotations

import copy
import hashlib
import logging

logger = logging.getLogger(__name__)

COLLECTION = "library_marks"
MAX_ITEMS = 500  # per list: keeps the document small
MAX_COLLECTIONS = 40
NAME_LIMIT = 40


def empty(owner: str = "") -> dict:
    return {"owner": owner, "starred": [], "collections": {}}


def _db():
    from common.metadata import db

    return db


def _doc(owner: str):
    key = hashlib.sha1(owner.strip().lower().encode()).hexdigest()
    return _db().collection(COLLECTION).document(key)


def clean(marks: dict | None, owner: str = "") -> dict:
    """A well-formed marks dict, whatever was stored."""
    out = empty(owner or (marks or {}).get("owner", ""))
    if not isinstance(marks, dict):
        return out
    out["starred"] = [str(i) for i in marks.get("starred") or [] if i][:MAX_ITEMS]
    cols = marks.get("collections") or {}
    if isinstance(cols, dict):
        for name, ids in list(cols.items())[:MAX_COLLECTIONS]:
            name = clean_name(name)
            if name:
                out["collections"][name] = [str(i) for i in ids or [] if i][:MAX_ITEMS]
    return out


def clean_name(name) -> str:
    return " ".join(str(name or "").split())[:NAME_LIMIT]


def load(owner: str) -> dict:
    if not owner:
        return empty()
    try:
        snap = _doc(owner).get()
        return clean(snap.to_dict() if snap.exists else None, owner)
    except Exception:
        logger.exception("library_marks: could not load marks")
        return empty(owner)


def save(owner: str, marks: dict) -> None:
    if owner:
        _doc(owner).set(clean(marks, owner))


# -- pure edits --------------------------------------------------------------


def is_starred(marks: dict, item_id: str) -> bool:
    return item_id in (marks.get("starred") or [])


def toggle_star(marks: dict, item_id: str) -> dict:
    out = copy.deepcopy(marks)
    starred = out.setdefault("starred", [])
    if item_id in starred:
        starred.remove(item_id)
    else:
        starred.insert(0, item_id)
        del starred[MAX_ITEMS:]
    return out


def collections_of(marks: dict, item_id: str) -> list[str]:
    return [n for n, ids in (marks.get("collections") or {}).items() if item_id in ids]


def toggle_in_collection(marks: dict, name: str, item_id: str) -> dict:
    """Add the item to the collection (made if new), or take it out."""
    name = clean_name(name)
    out = copy.deepcopy(marks)
    cols = out.setdefault("collections", {})
    if not name or (name not in cols and len(cols) >= MAX_COLLECTIONS):
        return out
    ids = cols.setdefault(name, [])
    if item_id in ids:
        ids.remove(item_id)
    else:
        ids.insert(0, item_id)
        del ids[MAX_ITEMS:]
    return out


def delete_collection(marks: dict, name: str) -> dict:
    out = copy.deepcopy(marks)
    (out.get("collections") or {}).pop(name, None)
    return out


def ids_for(marks: dict, view: str) -> list[str]:
    """Item ids of a Library view: 'starred' or 'c:<collection name>'."""
    if view == "starred":
        return list(marks.get("starred") or [])
    if view.startswith("c:"):
        return list((marks.get("collections") or {}).get(view[2:], []))
    return []
