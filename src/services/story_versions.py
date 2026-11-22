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
"""Film versions: the last few films of a story, to compare and go back to.

Every time a new film is saved (a render or an export) the previous one is
kept in ``Story.film_versions_json`` with the timeline it was made from.
"Use this version" brings back a film and its timeline; scenes, frames and
the set stay as they are (the fix's Undo restores those). Pure functions over
a Story, unit tested.
"""

from __future__ import annotations

import json
import time

MAX_VERSIONS = 8
LABELS = {
    "render": "New film",
    "export": "Edited and exported",
    "fix": "After an AI fix",
    "before_fix": "Before an AI fix",
}


def versions(story) -> list[dict]:
    """Newest first: {"uri", "timeline_json", "at", "label"}."""
    try:
        data = json.loads(story.film_versions_json or "[]")
    except ValueError:
        return []
    return [v for v in data if isinstance(v, dict) and v.get("uri")]


def remember(story, kind: str, now: float | None = None) -> None:
    """Record the story's current film (call after setting final_uri)."""
    if not story.final_uri:
        return
    rows = versions(story)
    if any(v["uri"] == story.final_uri for v in rows):
        return  # already kept (its place and label stay)
    rows.insert(
        0,
        {
            "uri": story.final_uri,
            "timeline_json": story.timeline_json or "",
            "at": round(now if now is not None else time.time()),
            "label": LABELS.get(kind, LABELS["render"]),
        },
    )
    story.film_versions_json = json.dumps(rows[:MAX_VERSIONS])


def relabel_latest(story, uri: str, label: str) -> None:
    """Give the newest version a clearer label, if it is still `uri`."""
    rows = versions(story)
    if rows and rows[0]["uri"] == uri:
        rows[0]["label"] = label[:80]
        story.film_versions_json = json.dumps(rows)


def restore(story, uri: str) -> bool:
    """Bring back the film `uri` and its timeline. False if unknown."""
    for v in versions(story):
        if v["uri"] == uri:
            story.final_uri = v["uri"]
            if v.get("timeline_json"):
                story.timeline_json = v["timeline_json"]
            story.film_edited = False
            return True
    return False


def ago(at: float, now: float | None = None) -> str:
    """'just now', '5 min ago', '3 h ago', '2 days ago'."""
    secs = max(0, int((now if now is not None else time.time()) - (at or 0)))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} h ago"
    days = secs // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"
