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
"""Subtitled downloads for Story Studio films.

The main film has no captions. At the end of the Edit step the presenter can
download four versions: without subtitles (the main film), with English,
with Arabic, or with English and Arabic together. Each subtitled version is
rendered on request from the current timeline.

Subtitle text per language, one line per scene, comes from the story when
it is already in that language (the narration, or the second-language
narration), else from a translation that is cached on the story
(``subtitle_lines_json``) with a hash of what it was translated from.

Cues are timed from the timeline: a narrated scene's words to its voice
clip, an on-camera line to its video clip. Long lines are cut into short
cues whose length follows the word count. English + Arabic shows the Arabic
line above the English one, cut into the same number of cues.

The cues become ``.srt`` / ``.vtt`` text, and caption clips (``"sub": True``)
on the timeline's text track, which the renderer draws. Everything here is
pure; the job that translates and renders is in services/story_jobs.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from services.story_timeline import clip_length, new_clip_id, normalize, track

STYLES = ("clean", "boxed", "bold")
STYLE_LABELS = {"clean": "Clean", "boxed": "Boxed", "bold": "Bold"}
# Subtitle languages: code -> the story's language label.
LANGS = {"en": "English", "ar": "Arabic"}
VARIANTS = ("none", "en", "ar", "en+ar")
VARIANT_LABELS = {
    "none": "Without subtitles",
    "en": "English subtitles",
    "ar": "Arabic subtitles",
    "en+ar": "English + Arabic subtitles",
}
LINE_CHARS = 42
CUE_CHARS = LINE_CHARS * 2
MIN_CUE = 0.8
GAP = 0.04
# Caption text size on the timeline's 720p scale, per style.
SIZES = {"clean": 34, "boxed": 32, "bold": 40}
DUAL_SIZE = 0.85  # two languages: a little smaller


@dataclass
class Cue:
    start: float
    end: float
    text: str


def variant_langs(variant: str) -> list[str]:
    return [] if variant == "none" else variant.split("+")


# -- text -------------------------------------------------------------------


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def split_text(text: str, limit: int = CUE_CHARS) -> list[str]:
    """Cut a line into cue-sized pieces, preferring sentence and clause ends."""
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?؟])\s+", (text or "").strip()):
        current = ""
        for word in _words(sentence):
            trial = f"{current} {word}".strip()
            if len(trial) > limit and current:
                pieces.append(current)
                current = word
            else:
                current = trial
            # A clause end late in a long piece is a good place to break.
            if len(current) > limit * 0.6 and current[-1] in ",;:،":
                pieces.append(current)
                current = ""
        if current:
            pieces.append(current)
    return pieces


def split_into(text: str, n: int) -> list[str]:
    """Cut `text` into `n` pieces of about the same number of words."""
    words = _words(text)
    if n <= 1 or len(words) <= 1:
        return [" ".join(words)] + [""] * max(0, n - 1)
    out = []
    for k in range(n):
        a, b = round(k * len(words) / n), round((k + 1) * len(words) / n)
        out.append(" ".join(words[a:b]))
    return out


def wrap(text: str, width: int = LINE_CHARS) -> str:
    """At most two lines, broken near the middle on a space."""
    if len(text) <= width:
        return text
    mid = len(text) // 2
    left, right = text.rfind(" ", 0, mid + 1), text.find(" ", mid)
    cut = min((p for p in (left, right) if p > 0), key=lambda p: abs(p - mid), default=-1)
    return text if cut < 0 else f"{text[:cut]}\n{text[cut + 1:]}"


# -- lines per language -----------------------------------------------------


def source_hash(story) -> str:
    """Changes when the narration changes, so a cached translation is redone."""
    raw = json.dumps([story.language] + [sc.narration for sc in story.scenes])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def known_lines(story, code: str) -> list[str] | None:
    """The story's own lines in language `code`, without translating."""
    label = LANGS.get(code)
    if label is None:
        return None
    if story.language == label:
        return [sc.narration or "" for sc in story.scenes]
    if (
        getattr(story, "second_on", False)
        and story.alt_language == label
        and all(sc.narration_alt or not sc.narration for sc in story.scenes)
    ):
        return [sc.narration_alt or "" for sc in story.scenes]
    return None


def cached_lines(story, code: str) -> list[str] | None:
    try:
        cache = json.loads(story.subtitle_lines_json or "{}")
    except ValueError:
        return None
    entry = cache.get(code) or {}
    lines = entry.get("lines")
    if entry.get("key") == source_hash(story) and isinstance(lines, list):
        if len(lines) == len(story.scenes):
            return [str(x or "") for x in lines]
    return None


def lines_for(story, code: str) -> list[str] | None:
    """Subtitle lines in `code`, or None when they need translating first."""
    return known_lines(story, code) or cached_lines(story, code)


def with_cached_lines(story, code: str, lines: list[str]) -> str:
    """subtitle_lines_json with `lines` stored for `code`."""
    try:
        cache = json.loads(story.subtitle_lines_json or "{}")
    except ValueError:
        cache = {}
    cache[code] = {"key": source_hash(story), "lines": [str(x or "") for x in lines]}
    return json.dumps(cache, ensure_ascii=False)


def translation_prompt(story, code: str) -> str:
    dst = LANGS[code]
    lines = [sc.narration for sc in story.scenes]
    arabic = "\n- Write Modern Standard Arabic (fusha)." if dst == "Arabic" else ""
    return f"""You write subtitles for a short film.
Translate each line of this film from {story.language} into {dst} for on-screen subtitles.

Lines (JSON, one per scene, in order): {json.dumps(lines, ensure_ascii=False)}

Rules:
- Keep the meaning and tone; do not add or drop ideas.
- Subtitles are read quickly: prefer short, clear wording over a literal one.
- Keep exactly one line per scene, in the same order. An empty line stays empty.{arabic}

Return only JSON: {{"lines": [str, ...]}} with exactly {len(lines)} lines."""


def parse_translation(text: str, count: int) -> list[str]:
    from common.error_handling import GenerationError

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise GenerationError("The subtitle translation came back unreadable.") from exc
    lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines, list) or len(lines) != count:
        raise GenerationError("The subtitle translation has the wrong number of lines.")
    return [str(x or "").strip() for x in lines]


# -- cues -------------------------------------------------------------------


def _spans(story, timeline: dict) -> list[tuple[int, float, float]]:
    """(scene, start, end) of the speech in each scene, in film order."""
    voices = {c.get("scene"): c for c in track(timeline, "voice")["clips"] if "scene" in c}
    out = []
    for vclip in track(timeline, "video")["clips"]:
        i = vclip.get("scene")
        if not isinstance(i, int) or not 0 <= i < len(story.scenes):
            continue
        voice = voices.get(i)
        if voice is not None:
            start = float(voice["start"])
            end = start + clip_length(voice)
        else:
            # An on-camera line: speech fills the clip, past the crossfade.
            start = float(vclip["start"]) + float(vclip.get("fade_in") or 0) + 0.15
            end = float(vclip["start"]) + clip_length(vclip) - 0.15
        out.append((i, start, end))
    return out


def _timed(pieces: list[str], weights: list[int], start: float, end: float) -> list[Cue]:
    total = sum(weights) or 1
    cues, t = [], start
    for piece, n in zip(pieces, weights, strict=True):
        length = (end - start) * n / total
        cues.append(Cue(round(t, 3), round(t + length - GAP, 3), piece))
        t += length
    return cues


def _merge_short(cues: list[Cue], sep: str = " ") -> list[Cue]:
    merged: list[Cue] = []
    for cue in cues:
        if merged and cue.end - cue.start < MIN_CUE:
            last = merged[-1]
            merged[-1] = Cue(last.start, cue.end, f"{last.text}{sep}{cue.text}")
        else:
            merged.append(cue)
    return merged


def _no_overlap(cues: list[Cue]) -> list[Cue]:
    cues.sort(key=lambda c: c.start)
    for a, b in zip(cues, cues[1:]):
        if a.end > b.start - GAP:
            a.end = round(max(a.start + 0.2, b.start - GAP), 3)
    return cues


def cues(story, timeline: dict | str | None, lines: list[str]) -> list[Cue]:
    """Cues for one language (`lines`: one per scene)."""
    tl = normalize(timeline)
    out: list[Cue] = []
    for i, start, end in _spans(story, tl):
        text = lines[i] if i < len(lines) else ""
        pieces = split_text(text)
        if not pieces or end - start < 0.2:
            continue
        weights = [max(1, len(_words(p))) for p in pieces]
        out.extend(_merge_short(_timed(pieces, weights, start, end)))
    return _no_overlap(out)


def dual_cues(
    story, timeline: dict | str | None, top: list[str], bottom: list[str]
) -> list[Cue]:
    """Two languages at once: `top` above `bottom`, cut into the same cues.
    Each cue's text is "top line\\nbottom line"."""
    tl = normalize(timeline)
    out: list[Cue] = []
    for i, start, end in _spans(story, tl):
        lower = bottom[i] if i < len(bottom) else ""
        upper = top[i] if i < len(top) else ""
        if not (lower.strip() or upper.strip()) or end - start < 0.2:
            continue
        pieces = split_text(lower or upper, LINE_CHARS)
        uppers = split_into(upper, len(pieces)) if lower else pieces
        lowers = pieces if lower else [""] * len(pieces)
        texts = [f"{u}\n{b}".strip("\n") for u, b in zip(uppers, lowers, strict=True)]
        weights = [max(1, len(_words(p))) for p in pieces]
        out.extend(_timed(texts, weights, start, end))
    return _no_overlap(out)


def variant_cues(
    story, timeline: dict | str | None, variant: str, lines: dict[str, list[str]]
) -> list[Cue]:
    langs = variant_langs(variant)
    if not langs:
        return []
    if len(langs) == 1:
        return cues(story, timeline, lines[langs[0]])
    # English + Arabic: Arabic on top, English below.
    return dual_cues(story, timeline, lines["ar"], lines["en"])


# -- files ------------------------------------------------------------------


def _stamp(seconds: float, sep: str) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _cue_text(cue: Cue) -> str:
    return cue.text if "\n" in cue.text else wrap(cue.text)


def to_srt(items: list[Cue]) -> str:
    blocks = [
        f"{n}\n{_stamp(c.start, ',')} --> {_stamp(c.end, ',')}\n{_cue_text(c)}\n"
        for n, c in enumerate(items, 1)
    ]
    return "\n".join(blocks)


def to_vtt(items: list[Cue]) -> str:
    blocks = [
        f"{_stamp(c.start, '.')} --> {_stamp(c.end, '.')}\n{_cue_text(c)}\n" for c in items
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)


# -- timeline ---------------------------------------------------------------


def variant_timeline(
    story, timeline: dict | str | None, variant: str, lines: dict[str, list[str]]
) -> dict:
    """The timeline with caption clips for `variant` (the presenter's own
    titles are kept, earlier caption clips dropped)."""
    tl = normalize(timeline)
    text = track(tl, "text")
    own = [c for c in text["clips"] if not c.get("sub")]
    style = story.subtitle_style if story.subtitle_style in STYLES else "clean"
    size = SIZES[style]
    if len(variant_langs(variant)) > 1:
        size = int(size * DUAL_SIZE)
    subs = [
        {
            "id": new_clip_id(),
            "text": _cue_text(cue),
            "start": cue.start,
            "dur": round(max(0.2, cue.end - cue.start), 3),
            "pos": "bottom",
            "size": size,
            "sub": True,
            "style": style,
        }
        for cue in variant_cues(story, tl, variant, lines)
    ]
    text["clips"] = own + subs
    return normalize(tl)


def variant_key(story, variant: str, lines: dict[str, list[str]]) -> str:
    """What a subtitled film is made from. A stored film whose key differs is
    out of date (the edit, the lines or the style changed)."""
    raw = json.dumps(
        [
            story.final_uri,
            story.timeline_json,
            story.subtitle_style,
            [lines.get(c) for c in variant_langs(variant)],
        ],
        ensure_ascii=False,
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def variants(story) -> dict:
    try:
        data = json.loads(story.film_variants_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def ready_variant(story, variant: str) -> str:
    """The film for `variant` when it is up to date, else ""."""
    if variant == "none":
        return story.final_uri
    lines = {}
    for code in variant_langs(variant):
        got = lines_for(story, code)
        if got is None:
            return ""
        lines[code] = got
    entry = variants(story).get(variant) or {}
    if entry.get("uri") and entry.get("key") == variant_key(story, variant, lines):
        return entry["uri"]
    return ""
