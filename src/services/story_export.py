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
"""Story Studio Export menu: the options, what each makes, and file names.

Pure helpers (no I/O). ``story_jobs.start_export`` runs the render; the
``/api/story/{id}/download/...`` route serves the files as real downloads.

Options (all optional, cleaned by :func:`clean`)::

    {"short": 1080,        # short side in pixels; 0 = the clips' own size
     "fmt": "mp4",         # story_timeline.EXPORT_FORMATS key (mp3/wav = audio only)
     "subs": "none",       # "none" | "burn" (in the picture) | "srt" (a file)
     "lang": "en",         # story_subtitles variant: "en", "ar", "en+ar"
     "branding": true}     # draw the brand logo
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from services import story_subtitles as subs
from services import story_timeline as tl_mod

SUB_MODES = ("none", "burn", "srt")
SUB_LABELS = {"none": "None", "burn": "In the picture", "srt": "SRT file"}
MAX_EXPORTS = 12
_SAFE = re.compile(r"[^A-Za-z0-9 _().,-]+")


def defaults(timeline: dict | None = None) -> dict:
    return {"short": 0, "fmt": "mp4", "subs": "none", "lang": "en", "branding": True}


def clean(opts: dict | None, timeline: dict | None = None) -> dict:
    """Valid options; unknown values fall back to the defaults. A size equal
    to the clips' own is stored as 0 (no scaling)."""
    out = defaults()
    opts = opts if isinstance(opts, dict) else {}
    try:
        short = int(opts.get("short") or 0)
    except TypeError, ValueError:
        short = 0
    allowed = {r["short"] for r in tl_mod.resolution_options(timeline or {})}
    if short in allowed:
        out["short"] = short
    if timeline and out["short"] == tl_mod.source_short_side(timeline):
        out["short"] = 0
    if opts.get("fmt") in tl_mod.EXPORT_FORMATS:
        out["fmt"] = opts["fmt"]
    if opts.get("subs") in SUB_MODES:
        out["subs"] = opts["subs"]
    if opts.get("lang") in subs.VARIANTS and opts.get("lang") != "none":
        out["lang"] = opts["lang"]
    out["branding"] = bool(opts.get("branding", True))
    if not is_video(out):
        out["short"], out["subs"] = 0, "none"
    return out


def is_video(opts: dict) -> bool:
    return tl_mod.EXPORT_FORMATS[opts["fmt"]]["video"]


def burns_subtitles(opts: dict) -> bool:
    return is_video(opts) and opts["subs"] == "burn"


def wants_srt(opts: dict) -> bool:
    return is_video(opts) and opts["subs"] == "srt"


def sub_langs(opts: dict) -> list[str]:
    """Languages whose subtitle lines the export needs."""
    return subs.variant_langs(opts["lang"]) if opts["subs"] != "none" else []


def key(opts: dict) -> str:
    """A short id for one combination of options (used in download URLs)."""
    parts = [
        opts["fmt"],
        str(opts["short"] or "src"),
        "b" if opts["branding"] else "nb",
    ]
    if burns_subtitles(opts):
        parts.append("sub-" + opts["lang"].replace("+", "-"))
    return "-".join(parts)


def size_label(opts: dict, timeline: dict) -> str:
    short = opts["short"] or tl_mod.source_short_side(timeline)
    return tl_mod.RESOLUTION_LABELS.get(short, f"{short}p")


def label(opts: dict, timeline: dict) -> str:
    """Plain words for an export: "1080p MP4 (H.264), English subtitles"."""
    fmt = tl_mod.EXPORT_FORMATS[opts["fmt"]]
    if not fmt["video"]:
        return f"Audio · {fmt['label']}"
    words = [size_label(opts, timeline), fmt["label"]]
    if burns_subtitles(opts):
        words.append(subs.VARIANT_LABELS[opts["lang"]].lower())
    if not opts["branding"]:
        words.append("no logo")
    return " · ".join(words)


def filename(title: str, opts: dict, timeline: dict) -> str:
    """The download's file name, e.g. "Lighthouse (1080p).mp4"."""
    base = _SAFE.sub("", title or "film").strip()[:60] or "film"
    fmt = tl_mod.EXPORT_FORMATS[opts["fmt"]]
    if not fmt["video"]:
        return f"{base}.{fmt['ext']}"
    extra = [size_label(opts, timeline)]
    if burns_subtitles(opts):
        extra.append(opts["lang"].replace("+", "-"))
    return f"{base} ({', '.join(extra)}).{fmt['ext']}"


def makes_film(opts: dict, has_logo: bool) -> bool:
    """True when the export is the story's main film: an MP4 at the clips'
    own size, without subtitles in the picture, with the logo when the
    story has one. Other exports are extra downloads."""
    return (
        opts["fmt"] == "mp4"
        and not opts["short"]
        and not burns_subtitles(opts)
        and (opts["branding"] or not has_logo)
    )


def made_from(story, opts: dict) -> str:
    """What an export shows: the edit, the brand when the logo is on, and
    the subtitle lines and style when they are in the picture. A stored
    export whose value differs is out of date."""
    parts: list = [tl_mod.normalize(story.timeline_json)]
    if opts["branding"]:
        parts.append(story.brand_json)
    if burns_subtitles(opts):
        parts.append(story.subtitle_style)
        parts.append([subs.lines_for(story, c) for c in sub_langs(opts)])
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def exports(story) -> dict:
    try:
        data = json.loads(story.exports_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def with_export(story, opts: dict, uri: str, name: str, made_from: str) -> str:
    """exports_json with this export added (newest kept, at most MAX_EXPORTS)."""
    rows = exports(story)
    rows.pop(key(opts), None)
    rows[key(opts)] = {"uri": uri, "name": name, "tl": made_from, "at": time.time()}
    keep = sorted(rows.items(), key=lambda kv: kv[1].get("at", 0))[-MAX_EXPORTS:]
    return json.dumps(dict(keep))


def ready(story, opts: dict) -> dict | None:
    """The stored export for these options when it matches the current
    edit, else None."""
    row = exports(story).get(key(opts))
    if row and row.get("tl") == made_from(story, opts):
        return row
    return None
