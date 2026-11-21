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
"""A person's brand kit: name, colours, tone of voice and logo.

One Firestore document per person in ``brand_kits``. The /brand page edits
it; Story Studio and Image Studio can apply it:

- :func:`prompt_line` is the sentence added to scenario, frame and image
  prompts (colours and tone).
- Story Studio keeps a copy of the kit on the story (``Story.brand_json``)
  when "Use my brand kit" is on, so background jobs need no extra read and
  later edits to the kit do not change a film half way.
- :func:`logo_overlay_png` draws the logo in a corner for the film render.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

COLLECTION = "brand_kits"
MAX_COLORS = 5
NAME_LIMIT = 60
TONE_LIMIT = 300
CORNERS = ("br", "bl", "tr", "tl")
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def empty() -> dict:
    return {"name": "", "colors": [], "tone": "", "logo_uri": "", "corner": "br"}


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
    out["logo_uri"] = logo if logo.startswith(("gs://", "/", "http")) else ""
    out["corner"] = kit.get("corner") if kit.get("corner") in CORNERS else "br"
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
    if not owner:
        return empty()
    try:
        snap = _doc(owner).get()
        return clean(snap.to_dict() if snap.exists else None)
    except Exception:
        logger.exception("brand_kit: could not load")
        return empty()


def save(owner: str, kit: dict) -> dict:
    kit = clean(kit)
    if owner:
        _doc(owner).set({**kit, "owner": owner})
    return kit


def logo_overlay_png(
    logo_path: str, width: int, height: int, out_path: str, corner: str = "br"
) -> str:
    """A full-frame transparent PNG with the logo small in one corner."""
    from PIL import Image

    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    with Image.open(logo_path) as raw:
        logo = raw.convert("RGBA")
    box = int(min(width, height) * 0.14)
    logo.thumbnail((max(16, int(box * 1.6)), max(16, box)))
    # Slightly see-through, like a broadcast bug.
    alpha = logo.getchannel("A").point(lambda a: int(a * 0.9))
    logo.putalpha(alpha)
    margin = int(min(width, height) * 0.04)
    x = width - logo.width - margin if corner in ("br", "tr") else margin
    y = height - logo.height - margin if corner in ("br", "bl") else margin
    frame.alpha_composite(logo, (x, y))
    frame.save(out_path)
    return out_path
