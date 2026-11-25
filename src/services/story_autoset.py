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

"""Story Studio auto settings: read the film settings out of the idea.

While the user types, `infer_settings` (rules, instant, free) picks up what
the idea says ("one minute long", "vertical", "anime", "5 scenes", "a
presenter talks to camera"). A small Gemini model can then refine that from
the same text (`live_settings_prompt` / `parse_live_settings`). Settings the
user picked by hand are "pinned" and never overwritten (`merge_settings`).
"""

from __future__ import annotations

import json
import re

from config.default import Default
from services.story_director import is_one_take
from services.story_models import (
    CAMERA_IDS,
    LANGUAGES,
    PACING_IDS,
    PACING_MODES,
    SPEECH_MODES,
    STORY_VIDEO_ENGINES,
    STYLE_BY_ID,
    _strip_fences,
    supported_durations,
)

# Form fields auto settings may change (StoryState attribute names).
FIELDS = (
    "scene_count",
    "duration",
    "aspect_ratio",
    "language",
    "style",
    "speech_mode",
    "shots",
    "camera",
    "pacing",
    "video_model",
)

# Setup choice: one continuous take, or a film of several shots.
SHOTS = {"auto": "Auto", "one": "One take", "several": "Several shots"}

# Preferred scene length when only the film length is known.
TARGET_SCENE_SECONDS = 10
SHORT_TARGET_SCENE_SECONDS = 6

_NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "twenty-five": 25,
    "twenty five": 25,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "fifty": 50,
    "sixty": 60,
    "ninety": 90,
    "a": 1,
    "an": 1,
    "a couple of": 2,
    "a few": 3,
}
_NUM = (
    r"(\d+(?:\.\d+)?|"
    + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True))
    + r")"
)
# No bare "s" or "m": "the 1990s" is a decade, "5m" may be millions.
_SEC = r"(?:seconds?|secs?)\b"
_MIN = r"(?:minutes?|mins?)\b"
_HOUR = r"(?:hours?|hrs?)\b"
# Film lengths outside this range are ignored (likely not a length).
FILM_SECONDS_RANGE = (5, 3600)


def _num(text: str) -> float:
    text = text.strip().lower()
    return float(_NUM_WORDS[text]) if text in _NUM_WORDS else float(text)


def _film_seconds(t: str) -> int | None:
    """Total film length the idea asks for, in seconds. When it gives more
    than one, the last wins (people add corrections at the end)."""
    lo, hi = FILM_SECONDS_RANGE
    found: list[tuple[int, int]] = []  # (position, seconds)
    fixed = [
        (r"\b(?:a|one) minute and a half\b|\b(?:one|1) and a half minutes?\b", 90),
        (r"\bhalf (?:a|one) minute\b|\bhalf-minute\b", 30),
        (r"\bhalf\s+(?:an?\s+)?hour\b|\bhalf-hour\b", 1800),
    ]
    taken: list[tuple[int, int]] = []
    for pattern, secs in fixed:
        for m in re.finditer(pattern, t):
            found.append((m.start(), secs))
            taken.append(m.span())
    for unit, scale in ((_HOUR, 3600), (_MIN, 60), (_SEC, 1)):
        for m in re.finditer(rf"\b{_NUM}\s*[- ]?\s*{unit}", t):
            if any(a <= m.start() < b for a, b in taken):
                continue
            secs = int(round(_num(m.group(1)) * scale))
            if lo <= secs <= hi:
                found.append((m.start(), secs))
    return max(found)[1] if found else None


def _scene_seconds(t: str) -> tuple[int | None, str]:
    """A per-scene length ("10 second scenes", "each scene 8s"), and the text
    with that phrase removed so it is not read as the film length."""
    pats = [
        rf"\b{_NUM}\s*[- ]?\s*{_SEC}\s*(?:long\s+)?(?:scenes?|shots?|clips?)\b",
        rf"\b(?:scenes?|shots?|clips?)\s+(?:of|lasting|at)\s+{_NUM}\s*[- ]?\s*{_SEC}",
        rf"\beach\s+(?:scene|shot|clip)\s+(?:is\s+|of\s+|lasting\s+)?{_NUM}\s*[- ]?\s*{_SEC}",
        rf"\b{_NUM}\s*[- ]?\s*{_SEC}\s+(?:each|per\s+(?:scene|shot|clip))\b",
    ]
    for p in pats:
        m = re.search(p, t)
        if m:
            return int(round(_num(m.group(1)))), t[: m.start()] + " " + t[m.end() :]
    return None, t


def _scene_count(t: str) -> int | None:
    m = re.search(
        rf"\b{_NUM}\s+(?:short\s+|quick\s+)?(?:scenes?|shots?|parts?|chapters?)\b", t
    )
    if not m or m.group(1) in ("a", "an"):  # "a scene where..." is not a count
        return None
    return int(_num(m.group(1)))


def _aspect(t: str) -> str | None:
    if re.search(
        r"\b(?:vertical|portrait|tiktok|tik tok|reels?|shorts|instagram stor(?:y|ies)|"
        r"stories format|phone screen|9\s*:\s*16)\b",
        t,
    ):
        return "9:16"
    if re.search(
        r"\b(?:landscape|horizontal|widescreen|wide screen|youtube video|16\s*:\s*9)\b",
        t,
    ):
        return "16:9"
    return None


def _language(text: str, t: str) -> str | None:
    names = "|".join(LANGUAGES)
    m = re.search(rf"\bin ({names})\b", text, re.I) or re.search(
        rf"\b({names})\s+(?:narration|voice-?over|voice|language|version|dialogue)\b",
        text,
        re.I,
    )
    if m:
        return next(k for k in LANGUAGES if k.lower() == m.group(1).lower())
    # The idea written in another script is a strong hint.
    scripts = [
        (r"[؀-ۿ]", "Arabic"),
        (r"[぀-ヿ]", "Japanese"),
        (r"[가-힯]", "Korean"),
        (r"[ऀ-ॿ]", "Hindi"),
    ]
    for pattern, lang in scripts:
        if len(re.findall(pattern, text)) >= 4 and lang in LANGUAGES:
            return lang
    return None


def _style(t: str) -> str | None:
    rules = [
        (r"\b(?:anime|manga|studio ghibli|ghibli)\b", "anime"),
        (r"\b(?:clay|claymation|stop[- ]motion|plasticine)\b", "claymation"),
        (r"\b(?:3d|3-d|cgi|pixar|animated film|3d animation)\b", "3d"),
        (
            r"\b(?:2d|illustrat\w*|cartoon|storybook|hand[- ]drawn|watercolou?r|comic)\b",
            "2d",
        ),
        (
            r"\b(?:photo\w*|realistic|live[- ]action|documentary|cinematic|real footage)\b",
            "photographic",
        ),
    ]
    for pattern, sid in rules:
        if re.search(pattern, t) and sid in STYLE_BY_ID:
            return sid
    return None


def _speech(t: str) -> str | None:
    if re.search(
        r"\b(?:no (?:speech|voice\w*|narration|narrator|dialogue|talking|words)|"
        r"music only|only music|without (?:speech|words|voice\w*|narration|a narrator)|"
        r"silent film|wordless)\b",
        t,
    ):
        return "none"
    if re.search(
        r"\b(?:presenter|spokes(?:person|man|woman)|talking to (?:the )?camera|to camera|"
        r"talking head|interview\w*|vlog\w*|testimonial|host(?:ed)? by|keynote|pitch(?:es)? to)\b",
        t,
    ):
        return "on_camera"
    if re.search(r"\b(?:narrat\w*|voice-?over|documentary)\b", t):
        return "narrator"
    return None


def _camera(t: str) -> str | None:
    rules = [
        (r"\b(?:drone|aerial|bird'?s[- ]eye)\b", "crane_up"),
        (r"\b(?:handheld|hand-held|shaky cam)\b", "handheld"),
        (r"\b(?:tripod|static camera|locked[- ]off)\b", "static"),
        (r"\b(?:orbit\w*|360)\b", "orbit"),
        (r"\b(?:dolly|push[- ]in)\b", "dolly_in"),
    ]
    for pattern, cam in rules:
        if re.search(pattern, t) and cam in CAMERA_IDS:
            return cam
    return None


def _pacing(t: str) -> str | None:
    rules = [
        (r"\b(?:dynamic|fast[- ]paced|snappy|quick[- ]cut\w*)\b", "dynamic"),
        (r"\b(?:documentary|docu[- ]style|unhurried|slow[- ]paced)\b", "documentary"),
        (r"\bcinematic\b", "cinematic"),
    ]
    for pattern, pid in rules:
        if re.search(pattern, t) and pid in PACING_IDS:
            return pid
    return None


def _video_model(t: str) -> str | None:
    rules = [
        (r"\b(?:hybrid|omni\s*\+\s*veo|veo\s*\+\s*omni)\b", "hybrid"),
        (r"\bveo\s*(?:3\.1\s*)?fast\b", "3.1-fast"),
        (r"\bveo\s*3\.1\b", "3.1"),
        (r"\bveo\b", "3.1-fast"),
        (r"\b(?:gemini\s+)?omni\b", "gemini-omni-1.2-flash"),
    ]
    for pattern, mid in rules:
        if re.search(pattern, t) and mid in STORY_VIDEO_ENGINES:
            return mid
    return None


def plan_length(
    total: int,
    scene_count: int | None = None,
    duration: int | None = None,
) -> tuple[int, int]:
    """Scenes x scene length for a film of about `total` seconds, keeping a
    count or length the idea fixed. Closest total first, then a scene length
    near TARGET_SCENE_SECONDS (6 s for very short films)."""
    cfg = Default()
    lengths = supported_durations()
    lo, hi = cfg.STORY_MIN_SCENES, cfg.STORY_MAX_SCENES
    target = SHORT_TARGET_SCENE_SECONDS if total < 30 else TARGET_SCENE_SECONDS
    counts = [scene_count] if scene_count else range(lo, hi + 1)
    durations = [duration] if duration else lengths
    best = min(
        ((n, d) for n in counts for d in durations),
        key=lambda nd: (abs(nd[0] * nd[1] - total), abs(nd[1] - target), nd[0]),
    )
    return max(lo, min(hi, best[0])), best[1]


def _nearest_length(seconds: int) -> int:
    return min(supported_durations(), key=lambda d: (abs(d - seconds), d))


def infer_settings(text: str) -> dict:
    """Film settings the idea states or clearly implies, by rules. Only keys
    that were found are returned; "film_seconds" is the length asked for."""
    raw = text or ""
    t = " " + raw.lower() + " "
    out: dict = {}
    per_scene, rest = _scene_seconds(t)
    count = _scene_count(t)
    total = _film_seconds(rest)
    if per_scene:
        out["duration"] = _nearest_length(per_scene)
    cfg = Default()
    if count:
        out["scene_count"] = max(cfg.STORY_MIN_SCENES, min(cfg.STORY_MAX_SCENES, count))
    if total:
        out["film_seconds"] = total
        n, d = plan_length(total, out.get("scene_count"), out.get("duration"))
        out["scene_count"], out["duration"] = n, d
    for key, value in (
        ("aspect_ratio", _aspect(t)),
        ("language", _language(raw, t)),
        ("style", _style(t)),
        ("speech_mode", _speech(t)),
        ("shots", "one" if is_one_take(raw) else None),
        ("camera", _camera(t)),
        ("pacing", _pacing(t)),
        ("video_model", _video_model(t)),
    ):
        if value:
            out[key] = value
    return out


def live_settings_prompt(text: str) -> str:
    """Ask a small model for the settings the idea implies (JSON only)."""
    styles = ", ".join(STYLE_BY_ID)
    langs = ", ".join(LANGUAGES)
    cams = ", ".join(CAMERA_IDS)
    pacings = ", ".join(PACING_IDS)
    engines = ", ".join(STORY_VIDEO_ENGINES)
    return f"""Read this idea for a short film and return the settings it asks for
or clearly implies. Use null for anything it does not say or imply.

Idea: \"\"\"{text.strip()}\"\"\"

- "film_seconds": total length in seconds ("one minute" = 60, "a quick teaser" = 15).
- "scene_count": number of scenes if stated.
- "scene_seconds": length of each scene if stated.
- "aspect_ratio": "9:16" for vertical/phone/social stories, "16:9" for landscape.
- "language": one of {langs}: the language the film is spoken in.
- "style": one of {styles}.
- "speech_mode": "on_camera" when a person talks to camera (presenter,
  interview, pitch, vlog), "narrator" for a voiceover, "none" when nobody
  speaks (music only, no voice), else null.
- "shots": "one" when the idea asks for one continuous shot with no cuts
  (a single take, one shot, the camera never cuts), "several" when it asks
  for different shots or scenes, else null.
- "camera": one of {cams} if the idea asks for a camera move.
- "pacing": one of {pacings} if the idea asks for fast/dynamic, cinematic, or documentary pacing.
- "video_model": one of {engines} if the idea names Veo, Omni, or Hybrid.

Return only JSON: {{"film_seconds": int|null, "scene_count": int|null, "scene_seconds": int|null, "aspect_ratio": str|null, "language": str|null, "style": str|null, "speech_mode": str|null, "shots": str|null, "camera": str|null, "pacing": str|null, "video_model": str|null}}"""


def parse_live_settings(text: str) -> dict:
    """Validated settings from the model's JSON (same keys as
    infer_settings). Anything unknown or malformed is dropped."""
    try:
        data = json.loads(_strip_fences(text or ""))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    cfg = Default()
    out: dict = {}

    def as_int(key):
        try:
            v = int(float(data.get(key)))
        except TypeError, ValueError:
            return None
        return v if v > 0 else None

    per_scene, count, total = (
        as_int("scene_seconds"),
        as_int("scene_count"),
        as_int("film_seconds"),
    )
    if per_scene:
        out["duration"] = _nearest_length(per_scene)
    if count:
        out["scene_count"] = max(cfg.STORY_MIN_SCENES, min(cfg.STORY_MAX_SCENES, count))
    if total:
        out["film_seconds"] = total
        out["scene_count"], out["duration"] = plan_length(
            total, out.get("scene_count"), out.get("duration")
        )
    checks = {
        "aspect_ratio": ("16:9", "9:16"),
        "language": tuple(LANGUAGES),
        "style": tuple(STYLE_BY_ID),
        "speech_mode": tuple(k for k in SPEECH_MODES if k != "auto"),
        "shots": ("one", "several"),
        "camera": tuple(CAMERA_IDS),
        "pacing": tuple(PACING_IDS),
        "video_model": tuple(STORY_VIDEO_ENGINES),
    }
    for key, allowed in checks.items():
        value = data.get(key)
        if isinstance(value, str) and value in allowed:
            out[key] = value
    return out


def merge_settings(current: dict, found: dict, pinned: set[str]) -> dict:
    """The form fields to change: what was found, minus fields the user
    picked by hand, minus values that are already set. When the idea gives
    a film length and the user pinned the scene count or length, the other
    one is planned around the pinned value."""
    found = dict(found)
    total = found.get("film_seconds")
    if total and pinned & {"scene_count", "duration"}:
        n, d = plan_length(
            total,
            current.get("scene_count") if "scene_count" in pinned else None,
            current.get("duration") if "duration" in pinned else None,
        )
        found["scene_count"], found["duration"] = n, d
    return {
        k: v
        for k, v in found.items()
        if k in FIELDS and k not in pinned and current.get(k) != v
    }


def describe(found: dict) -> str:
    """Short summary for the Create step, e.g. "1 min: 6 scenes x 10 s ·
    9:16 · Anime"."""
    parts: list[str] = []
    if "scene_count" in found and "duration" in found:
        secs = found.get("film_seconds")
        length = ""
        if secs:
            length = f"{secs // 60} min" if secs % 60 == 0 else f"{secs} s"
            length += ": "
        parts.append(f"{length}{found['scene_count']} scenes × {found['duration']} s")
    if "aspect_ratio" in found:
        parts.append(
            "Vertical 9:16" if found["aspect_ratio"] == "9:16" else "Landscape 16:9"
        )
    if "language" in found:
        parts.append(found["language"])
    if "style" in found:
        parts.append(STYLE_BY_ID[found["style"]]["label"])
    if "speech_mode" in found:
        parts.append(SPEECH_MODES[found["speech_mode"]].replace("Auto: ", ""))
    if found.get("shots") in ("one", "several"):
        parts.append(SHOTS[found["shots"]])
    if "camera" in found:
        from services.story_models import CAMERA_PRESETS

        parts.append(CAMERA_PRESETS[found["camera"]]["label"])
    if "pacing" in found and found["pacing"] in PACING_MODES:
        parts.append(PACING_MODES[found["pacing"]]["label"])
    if "video_model" in found and found["video_model"] in STORY_VIDEO_ENGINES:
        parts.append(STORY_VIDEO_ENGINES[found["video_model"]])
    return " · ".join(parts)
