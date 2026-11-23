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
