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
"""Brands: name, colours, tone of voice and logo. Several per person.

One Firestore document per brand in ``brands`` (random id), with the owner's
email, a reserved ``team`` field (shared brands later) and ``is_default``.
The old one-per-person ``brand_kits`` document is copied into a brand the
first time the person's brands are listed, then marked migrated. Demo mode
keeps brands in a JSON file under the gitignored ``.local/`` folder.

The /brand page lists and edits them; Story Studio, Image Studio and Home
chat apply one:

- :func:`prompt_line` is the sentence added to scenario, frame and image
  prompts (colours and tone).
- Story Studio keeps a copy of the picked brand on the story
  (``Story.brand_json``, plus ``Story.brand_id``), so background jobs need
  no extra read and later edits to the brand do not change a film half way.
- :func:`load` gives the owner's default brand (Image Studio, Home chat).
- :func:`logo_overlay_png` draws the logo in a corner for the film render.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)

COLLECTION = "brand_kits"  # old: one document per person (migrated)
BRANDS = "brands"
MAX_BRANDS = 50
MAX_COLORS = 5
NAME_LIMIT = 60
TONE_LIMIT = 300
CORNERS = ("auto", "br", "bl", "tr", "tl")
# Logo width as a share of the frame's short side (broadcast "bugs" are
# about 5 to 8% of the width; small is about 7% of a 16:9 frame's width).
LOGO_SIZES = {"s": 0.12, "m": 0.16, "l": 0.22}
LOGO_MARGIN = 0.05  # of the short side, inside title-safe
LOGO_OPACITY = 0.85
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def empty() -> dict:
    return {
        "name": "",
        "colors": [],
        "tone": "",
        "logo_uri": "",
        "corner": "auto",
        "logo_size": "s",
    }


def resolve_corner(corner: str, width: int, height: int) -> str:
    """The real corner: "auto" is top right for portrait (9:16) films, where
    social apps draw buttons and captions over the bottom and right edge,
    and bottom right otherwise."""
    if corner in ("br", "bl", "tr", "tl"):
        return corner
    return "tr" if height > width else "br"


def clean_color(value) -> str:
    """'#1a73e8' style, or '' when it is not a colour."""
    m = _HEX.match(str(value or "").strip())
    if not m:
        return ""
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.lower()


def clean(kit: dict | None) -> dict:
    out = empty()
    if not isinstance(kit, dict):
        return out
    out["name"] = " ".join(str(kit.get("name") or "").split())[:NAME_LIMIT]
    colors = []
    for c in kit.get("colors") or []:
        c = clean_color(c)
        if c and c not in colors:
            colors.append(c)
    out["colors"] = colors[:MAX_COLORS]
    out["tone"] = " ".join(str(kit.get("tone") or "").split())[:TONE_LIMIT]
    logo = str(kit.get("logo_uri") or "")
    # local:// is a demo-mode file (services/story_service.py).
    out["logo_uri"] = logo if logo.startswith(("gs://", "/", "http", "local://")) else ""
    out["corner"] = kit.get("corner") if kit.get("corner") in CORNERS else "auto"
    out["logo_size"] = kit.get("logo_size") if kit.get("logo_size") in LOGO_SIZES else "s"
    return out


def is_empty(kit: dict | None) -> bool:
    k = clean(kit)
    return not (k["name"] or k["colors"] or k["tone"] or k["logo_uri"])


def prompt_line(kit: dict | None) -> str:
    """One sentence for a generation prompt, or '' for an empty kit."""
    k = clean(kit)
    parts = []
    if k["name"]:
        parts.append(f"Brand: {k['name']}.")
    if k["colors"]:
        parts.append(
            "Use the brand colours "
            + ", ".join(k["colors"])
            + " in the palette, wardrobe, set and lighting, without adding logos or text."
        )
    if k["tone"]:
        parts.append(f"Tone of voice: {k['tone']}.")
    return " ".join(parts)


def from_json(text: str) -> dict:
    try:
        return clean(json.loads(text)) if text else empty()
    except ValueError:
        return empty()


def _db():
    from common.metadata import db

    return db


def _doc(owner: str):
    key = hashlib.sha1(owner.strip().lower().encode()).hexdigest()
    return _db().collection(COLLECTION).document(key)


def load(owner: str) -> dict:
    """The owner's default brand as a kit (empty when there is none)."""
    if not owner:
        return empty()
    try:
        return clean(default_brand(owner))
    except Exception:
        logger.exception("brand_kit: could not load")
        return empty()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def clean_brand(doc: dict | None) -> dict:
    """A stored brand: the kit fields plus id, owner, team and is_default."""
    doc = doc if isinstance(doc, dict) else {}
    out = clean(doc)
    out["id"] = re.sub(r"[^a-zA-Z0-9_-]", "", str(doc.get("id") or ""))[:40]
    out["owner"] = str(doc.get("owner") or "")
    out["team"] = str(doc.get("team") or "")
    out["is_default"] = bool(doc.get("is_default"))
    out["created"] = str(doc.get("created") or "")
    out["updated"] = str(doc.get("updated") or "")
    return out


def label(brand: dict | None) -> str:
    """The name shown in pickers."""
    return clean(brand)["name"] or "Untitled brand"


def snapshot(brand: dict | None) -> str:
    """The JSON copy a story keeps ("" for no brand or an empty one)."""
    if not brand or is_empty(brand):
        return ""
    return json.dumps(clean(brand))


class BrandStore(Protocol):
    def list(self, owner: str) -> list[dict]: ...
    def get(self, brand_id: str) -> dict | None: ...
    def put(self, brand: dict) -> None: ...
    def delete(self, brand_id: str) -> None: ...
    def legacy(self, owner: str) -> dict | None: ...
    def mark_legacy(self, owner: str, brand_id: str) -> None: ...


class FirestoreBrandStore:
    def _col(self):
        return _db().collection(BRANDS)

    def list(self, owner: str) -> list[dict]:
        rows = self._col().where("owner", "==", owner).limit(MAX_BRANDS).stream()
        return [{**(r.to_dict() or {}), "id": r.id} for r in rows]

    def get(self, brand_id: str) -> dict | None:
        snap = self._col().document(brand_id).get()
        return {**(snap.to_dict() or {}), "id": snap.id} if snap.exists else None

    def put(self, brand: dict) -> None:
        self._col().document(brand["id"]).set(brand)

    def delete(self, brand_id: str) -> None:
        self._col().document(brand_id).delete()

    def legacy(self, owner: str) -> dict | None:
        snap = _doc(owner).get()
        return snap.to_dict() if snap.exists else None

    def mark_legacy(self, owner: str, brand_id: str) -> None:
        _doc(owner).set({"migrated": True, "migrated_to": brand_id}, merge=True)


class MemoryBrandStore:
    """Brands in a dict, optionally saved to a JSON file (demo mode, tests)."""

    def __init__(self, path: str = ""):
        self.path = path
        self._lock = threading.Lock()
        self._data = {"brands": {}, "legacy": {}}
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self._data = {
                        "brands": dict(raw.get("brands") or {}),
                        "legacy": dict(raw.get("legacy") or {}),
                    }
            except OSError, ValueError:
                pass

    def _save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=1)
        os.replace(tmp, self.path)

    def list(self, owner: str) -> list[dict]:
        with self._lock:
            return [
                dict(b)
                for b in self._data["brands"].values()
                if b.get("owner") == owner
            ]

    def get(self, brand_id: str) -> dict | None:
        with self._lock:
            b = self._data["brands"].get(brand_id)
            return dict(b) if b else None

    def put(self, brand: dict) -> None:
        with self._lock:
            self._data["brands"][brand["id"]] = dict(brand)
            self._save()

    def delete(self, brand_id: str) -> None:
        with self._lock:
            self._data["brands"].pop(brand_id, None)
            self._save()

    def legacy(self, owner: str) -> dict | None:
        with self._lock:
            doc = self._data["legacy"].get(owner)
            return dict(doc) if doc else None

    def set_legacy(self, owner: str, kit: dict) -> None:
        with self._lock:
            self._data["legacy"][owner] = dict(kit)
            self._save()

    def mark_legacy(self, owner: str, brand_id: str) -> None:
        with self._lock:
            doc = self._data["legacy"].setdefault(owner, {})
            doc.update({"migrated": True, "migrated_to": brand_id})
            self._save()


_store: BrandStore | None = None
_store_lock = threading.Lock()


def get_store() -> BrandStore:
    """Firestore, or a local JSON file in Story Studio demo mode."""
    global _store
    with _store_lock:
        if _store is None:
            from services.story_service import is_mock_mode

            if is_mock_mode():
                here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _store = MemoryBrandStore(os.path.join(here, ".local", "brands.json"))
            else:
                _store = FirestoreBrandStore()
        return _store


def set_store(store: BrandStore | None) -> None:
    """Swap the brand store (tests)."""
    global _store
    _store = store


def migrate(owner: str, store: BrandStore | None = None) -> dict | None:
    """Copy the old one-per-person kit into a brand once. Returns the new
    brand, or None when there is nothing (left) to migrate."""
    store = store or get_store()
    old = store.legacy(owner)
    if not old or old.get("migrated"):
        return None
    kit = clean(old)
    if is_empty(kit):
        store.mark_legacy(owner, "")
        return None
    has_default = any(b.get("is_default") for b in store.list(owner))
    now = _now()
    brand = clean_brand(
        {
            **kit,
            "name": kit["name"] or "My brand",
            "id": uuid.uuid4().hex[:12],
            "owner": owner,
            "is_default": not has_default,
            "created": now,
            "updated": now,
        }
    )
    store.put(brand)
    store.mark_legacy(owner, brand["id"])
    return brand


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(
        rows, key=lambda b: (not b["is_default"], b["name"].lower(), b["created"])
    )


def list_brands(owner: str, store: BrandStore | None = None) -> list[dict]:
    """The owner's brands, default first. Migrates the old kit on first use.
    If none is marked default, the first one is."""
    if not owner:
        return []
    store = store or get_store()
    try:
        migrate(owner, store)
        rows = [clean_brand(b) for b in store.list(owner) if b.get("owner") == owner]
    except Exception:
        logger.exception("brand_kit: could not list brands")
        return []
    rows = _sorted(rows)
    if rows and not any(b["is_default"] for b in rows):
        rows[0]["is_default"] = True
    return rows


def get_brand(
    owner: str, brand_id: str, store: BrandStore | None = None
) -> dict | None:
    """One of the owner's brands (None for someone else's or a missing one)."""
    if not owner or not brand_id:
        return None
    store = store or get_store()
    try:
        doc = store.get(brand_id)
    except Exception:
        logger.exception("brand_kit: could not load brand")
        return None
    if not doc or doc.get("owner") != owner:
        return None
    return clean_brand({**doc, "id": brand_id})


def default_brand(owner: str, store: BrandStore | None = None) -> dict | None:
    rows = list_brands(owner, store)
    return next((b for b in rows if b["is_default"]), None)


def save_brand(owner: str, brand: dict, store: BrandStore | None = None) -> dict:
    """Create (no id) or update one of the owner's brands. The first brand
    becomes the default."""
    if not owner:
        raise PermissionError("Sign in to save a brand.")
    store = store or get_store()
    existing = get_brand(owner, str(brand.get("id") or ""), store)
    if brand.get("id") and existing is None:
        raise PermissionError("That brand was not found.")
    now = _now()
    if existing is None:
        mine = [b for b in store.list(owner) if b.get("owner") == owner]
        if len(mine) >= MAX_BRANDS:
            raise ValueError(f"You can keep up to {MAX_BRANDS} brands.")
        out = clean_brand(
            {
                **brand,
                "id": uuid.uuid4().hex[:12],
                "owner": owner,
                "is_default": not any(b.get("is_default") for b in mine),
                "created": now,
            }
        )
    else:
        out = clean_brand(
            {
                **existing,
                **clean(brand),
                "id": existing["id"],
                "owner": owner,
                "team": existing["team"],
                "is_default": existing["is_default"],
                "created": existing["created"],
            }
        )
    out["updated"] = now
    store.put(out)
    return out


def set_default(owner: str, brand_id: str, store: BrandStore | None = None) -> bool:
    store = store or get_store()
    if get_brand(owner, brand_id, store) is None:
        return False
    for b in list_brands(owner, store):
        want = b["id"] == brand_id
        if b["is_default"] != want or want:
            store.put({**b, "is_default": want})
    return True


def delete_brand(owner: str, brand_id: str, store: BrandStore | None = None) -> bool:
    """Delete one of the owner's brands; the next one becomes the default."""
    store = store or get_store()
    brand = get_brand(owner, brand_id, store)
    if brand is None:
        return False
    store.delete(brand_id)
    if brand["is_default"]:
        rest = list_brands(owner, store)
        if rest:
            set_default(owner, rest[0]["id"], store)
    return True


def save(owner: str, kit: dict) -> dict:
    """Save into the owner's default brand (creates one if there is none)."""
    kit = clean(kit)
    if owner:
        current = default_brand(owner)
        return clean(save_brand(owner, {**kit, "id": current["id"] if current else ""}))
    return kit


def logo_box(
    logo_w: int, logo_h: int, width: int, height: int, corner: str = "auto", size: str = "s"
) -> tuple[int, int, int, int]:
    """Where the logo goes on a width x height frame: (x, y, w, h).

    The logo is LOGO_SIZES[size] of the short side wide (a tall logo is held
    to the same height instead), LOGO_MARGIN of the short side in from the
    edges, in the resolved corner (see :func:`resolve_corner`)."""
    short = min(width, height)
    box = max(8, round(short * LOGO_SIZES.get(size, LOGO_SIZES["s"])))
    scale = box / max(1, max(logo_w, logo_h))
    w, h = max(1, round(logo_w * scale)), max(1, round(logo_h * scale))
    margin = round(short * LOGO_MARGIN)
    corner = resolve_corner(corner, width, height)
    x = width - w - margin if corner in ("br", "tr") else margin
    y = height - h - margin if corner in ("br", "bl") else margin
    return x, y, w, h


def logo_overlay_png(
    logo_path: str,
    width: int,
    height: int,
    out_path: str,
    corner: str = "auto",
    size: str = "s",
    opacity: float = LOGO_OPACITY,
) -> str:
    """A full-frame transparent PNG with the logo in one corner (see
    :func:`logo_box`), slightly see-through like a broadcast bug."""
    from PIL import Image

    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    with Image.open(logo_path) as raw:
        logo = raw.convert("RGBA")
    x, y, w, h = logo_box(logo.width, logo.height, width, height, corner, size)
    logo = logo.resize((w, h), Image.LANCZOS)
    alpha = logo.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
    logo.putalpha(alpha)
    frame.alpha_composite(logo, (x, y))
    frame.save(out_path)
    return out_path
