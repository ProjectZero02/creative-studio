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
"""Setup references for Story Studio (Kling-style @mentions).

In Setup the user adds references above the idea: a character, an object or
product, a location or a voice. Each has a tag ("Mara") that can be written
as "@Mara" in the idea, and a role ("lead", "product", "setting",
"narrator"). At Create they become assets of the story's set, so the
scenario writer casts them by name and every frame and clip gets their
images. Pure functions; nothing here saves.
"""

from __future__ import annotations

import json
import re

from services.story_models import VOICES, new_id
from services.story_sets import (
    Character,
    Location,
    Prop,
    SetImage,
    StorySet,
    Voice,
    anchor_view,
    duplicate,
    ensure_views,
)

# kind -> (menu label, default role, default tag stem)
KINDS: dict[str, tuple[str, str, str]] = {
    "character": ("Character", "lead", "Character"),
    "object": ("Object or product", "product", "Product"),
    "location": ("Location", "setting", "Location"),
    "voice": ("Voice", "narrator", "Narrator"),
}
MAX_REFS = 8
TAG_LIMIT = 32
ROLE_LIMIT = 60
_TAG_CHARS = re.compile(r"[^\w\- ]+", re.UNICODE)


def clean_tag(text: str) -> str:
    """A short name usable as @Tag (letters, digits, - and _; no spaces)."""
    tag = _TAG_CHARS.sub("", str(text or "")).strip().replace(" ", "")
    return tag[:TAG_LIMIT]


def clean_ref(raw: dict) -> dict | None:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    kind = raw["kind"]
    _label, role, stem = KINDS[kind]
    uri = str(raw.get("uri") or "")
    voice = raw.get("voice") if raw.get("voice") in VOICES else "Kore"
    return {
        "id": re.sub(r"[^a-z0-9]", "", str(raw.get("id") or ""))[:16] or new_id(),
        "kind": kind,
        "tag": clean_tag(raw.get("tag") or "") or stem,
        "role": " ".join(str(raw.get("role") or role).split())[:ROLE_LIMIT],
        "uri": uri if uri.startswith(("gs://", "local://", "/", "http")) else "",
        "voice": voice if kind == "voice" else "",
    }


def parse(text: str) -> list[dict]:
    try:
        raw = json.loads(text or "[]")
    except ValueError:
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        ref = clean_ref(item)
        if ref:
            out.append(ref)
    return out[:MAX_REFS]


def dump(refs: list[dict]) -> str:
    return json.dumps([r for r in (clean_ref(x) for x in refs) if r][:MAX_REFS])


def new_ref(kind: str, existing: list[dict]) -> dict | None:
    """A new reference of `kind` with a tag not used yet."""
    if kind not in KINDS or len(existing) >= MAX_REFS:
        return None
    stem = KINDS[kind][2]
    used = {r["tag"].lower() for r in existing}
    tag, n = stem, 1
    while tag.lower() in used:
        n += 1
        tag = f"{stem}{n}"
    return clean_ref({"id": new_id(), "kind": kind, "tag": tag})


def mention(idea: str, tag: str) -> str:
    """The idea with "@tag" added at the end (once)."""
    idea = (idea or "").rstrip()
    token = f"@{tag}"
    if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", idea):
        return idea
    return f"{idea} {token}".strip()


def mentioned(idea: str, refs: list[dict]) -> set[str]:
    """Ids of references the idea mentions as @tag."""
    found = set()
    for r in refs:
        if re.search(
            rf"(?<!\w)@{re.escape(r['tag'])}(?!\w)", idea or "", re.IGNORECASE
        ):
            found.add(r["id"])
    return found


def narrator_voice(refs: list[dict]) -> str:
    """The narrator voice a Voice reference picks ("" for none)."""
    for r in refs:
        if r["kind"] == "voice" and r["voice"]:
            return r["voice"]
    return ""


def _image(asset, uri: str) -> None:
    ensure_views(asset)
    view = anchor_view(asset) if not isinstance(asset, Prop) else "item"
    for img in asset.images:
        if img.view == view:
            img.uri, img.locked = uri, True
            return
    asset.images.insert(0, SetImage(view=view, uri=uri, locked=True))


def build_set(
    refs: list[dict],
    *,
    base: StorySet | None = None,
    owner: str = "",
    name: str = "",
    style: str = "photographic",
) -> StorySet | None:
    """The story's set with the references added as assets (None when there
    are no references with something to add). A picked set is copied, never
    changed in place."""
    refs = [r for r in (clean_ref(x) for x in refs) if r]
    if not refs:
        return None
    if base is not None:
        out = duplicate(base, owner, name=name or f"{base.name} + references")
    else:
        out = StorySet(owner=owner, name=name or "References", style=style)
    for r in refs:
        role = r["role"]
        if r["kind"] == "character":
            c = Character(name=r["tag"], description=role)
            if r["uri"]:
                _image(c, r["uri"])
            else:
                ensure_views(c)
            out.characters.append(c)
        elif r["kind"] == "location":
            loc = Location(name=r["tag"], description=role)
            if r["uri"]:
                _image(loc, r["uri"])
            else:
                ensure_views(loc)
            out.locations.append(loc)
        elif r["kind"] == "object":
            p = Prop(name=r["tag"], description=role)
            if r["uri"]:
                _image(p, r["uri"])
            else:
                ensure_views(p)
            out.props.append(p)
        elif r["kind"] == "voice":
            narr = out.narrator()
            if narr is not None:
                narr.voice.tts_voice = r["voice"] or narr.voice.tts_voice
            else:
                out.characters.append(
                    Character(
                        name=r["tag"],
                        narrator=True,
                        voice=Voice(
                            tts_voice=r["voice"] or "Kore",
                            style="Narrate warmly and clearly, like a short film voiceover.",
                        ),
                    )
                )
    return out
