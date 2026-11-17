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
"""Settings typed in a prompt ("16:9", "8 seconds", "2 images", "no audio").

Studios read their settings from chips, so words like "16:9" in the prompt
used to do nothing. On submit a page calls ``apply`` (or the three steps it
wraps):

* ``parse(text, kinds)`` finds explicit setting phrases. It is strict on
  purpose: ratios must stand alone ("A 16:9 TV on the wall" is not a setting),
  durations need a unit, counts need the page's noun.
* ``fit(matches, limits)`` snaps each value to what the model can do and says
  why when it had to change it.
* ``strip(text, matches)`` removes the matched phrases from the prompt sent to
  the model, so the text can't contradict the config.

Pure Python, no Mesop. Limits come from the existing model configs through the
``SettingLimits.from_*`` converters, so no config changes shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.gemini_image_models import GeminiImageModelConfig
    from config.lyria_models import LyriaModelConfig
    from config.video_studio_models import StudioLimits

# Kinds a page can ask for.
ASPECT = "aspect"
IMAGE_SIZE = "image_size"
RESOLUTION = "resolution"
DURATION = "duration"
COUNT = "count"
AUDIO = "audio"
INSTRUMENTAL = "instrumental"

IMAGE_KINDS = frozenset({ASPECT, IMAGE_SIZE, COUNT})
VIDEO_KINDS = frozenset({ASPECT, RESOLUTION, DURATION, COUNT, AUDIO})
MUSIC_KINDS = frozenset({COUNT, INSTRUMENTAL})

# Kinds whose words stay in the prompt: no config field carries
# "instrumental", so the model only hears it through the text.
_KEEP_IN_PROMPT = frozenset({INSTRUMENTAL})

# Every ratio any studio model offers. Others ("4:30", "2x4") are not settings.
KNOWN_RATIOS = frozenset(
    {
        "1:1",
        "3:2",
        "2:3",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
        "9:21",
        "1:4",
        "4:1",
        "1:8",
        "8:1",
    },
)
_WORD_RATIOS = {
    "landscape": "16:9",
    "horizontal": "16:9",
    "portrait": "9:16",
    "vertical": "9:16",
    "square": "1:1",
}
IMAGE_SIZE_ORDER = ("512", "1K", "2K", "4K")
RESOLUTION_ORDER = ("360p", "480p", "720p", "1080p", "4k")

_NUMBER_WORDS = {
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
}
_COUNT_NOUNS = {
    "image": r"images?|pictures?",
    "video": r"videos?|clips?",
    "track": r"tracks?|songs?",
}
_SHARED_COUNT_NOUNS = r"options?|variations?|versions?"

# Characters that end a phrase ("16:9," or "(16:9)"), plus the en and em
# dashes (built with chr so the file holds no ambiguous characters).
_PUNCT = set(",.;:!?()[]{}\"'/-") | {chr(0x2013), chr(0x2014)}
_TIMES = chr(0x00D7)  # the multiplication sign, U+00D7
# Words that may sit next to a value and still make it a setting.
_ASPECT_LEAD = {"at", "in", "aspect", "ratio", "format", "as"}
_ASPECT_TRAIL = {
    "aspect",
    "ratio",
    "format",
    "framing",
    "widescreen",
    "landscape",
    "portrait",
    "vertical",
    "horizontal",
}
_SIZE_LEAD = {"at", "in"}
_SIZE_TRAIL = {"resolution", "quality", "image", "images", "output", "size", "video"}

Translate = Callable[..., str]


def _english(_key: str, english: str, **fmt: object) -> str:
    """Default translator: the English text, formatted."""
    return english.format(**fmt) if fmt else english


@dataclass(frozen=True)
class Match:
    """One setting phrase found in the prompt.

    ``text`` is the phrase itself ("16:9"); ``span`` covers it plus the small
    words around it that go with it ("at 16:9 aspect ratio"), which is what
    ``strip`` removes.
    """

    kind: str
    value: object
    span: tuple[int, int]
    text: str


@dataclass(frozen=True)
class Applied:
    """A value the run will use (maybe snapped, then ``note`` says why)."""

    kind: str
    value: object
    requested: object
    note_key: str = ""
    note_en: str = ""
    note_fmt: dict = field(default_factory=dict)

    def note(self, tr: Translate = _english) -> str:
        """Why the value changed ("" when it didn't)."""
        return tr(self.note_key, self.note_en, **self.note_fmt) if self.note_en else ""


@dataclass(frozen=True)
class Skipped:
    """A value the model can't use; the chip stays as it was."""

    kind: str
    requested: object
    note_key: str = ""
    note_en: str = ""
    note_fmt: dict = field(default_factory=dict)

    def note(self, tr: Translate = _english) -> str:
        """Why the value can't be used ("" when there's nothing to say)."""
        return tr(self.note_key, self.note_en, **self.note_fmt) if self.note_en else ""


@dataclass(frozen=True)
class SettingLimits:
    """What one model can do, in the shape the parser needs.

    An empty tuple means the page has no such chip right now (for example no
    aspect ratio when editing a video), so typed values of that kind are
    ignored.
    """

    model: str = "This model"
    aspect_ratios: tuple[str, ...] = ()
    image_sizes: tuple[str, ...] = ()
    resolutions: tuple[str, ...] = ()
    durations: tuple[int, ...] = ()
    max_count: int = 1
    count_noun: str = "image"
    # "toggle" (a chip), "always" (Omni: always has sound) or "none" (silent).
    audio: str = "none"
    lyrics: bool = False

    @classmethod
    def from_image_config(cls, config: GeminiImageModelConfig) -> SettingLimits:
        """From a ``GeminiImageModelConfig``."""
        return cls(
            model=config.display_name,
            aspect_ratios=tuple(config.supported_aspect_ratios),
            image_sizes=tuple(config.supported_image_sizes),
            max_count=max(1, config.max_output_images),
            count_noun="image",
        )

    @classmethod
    def from_studio_limits(
        cls,
        limits: StudioLimits,
        model: str,
        *,
        always_sound: bool = False,
    ) -> SettingLimits:
        """From Video Studio's ``StudioLimits`` (config/video_studio_models)."""
        follows = limits.follows_input_video
        if limits.supports_audio_toggle:
            audio = "toggle"
        elif always_sound:
            audio = "always"
        else:
            audio = "none"
        return cls(
            model=model,
            aspect_ratios=() if follows else tuple(limits.aspect_ratios),
            resolutions=tuple(limits.resolutions),
            durations=() if follows else tuple(limits.durations),
            max_count=max(1, limits.max_samples),
            count_noun="video",
            audio=audio,
        )

    @classmethod
    def from_lyria_config(cls, config: LyriaModelConfig) -> SettingLimits:
        """From a ``LyriaModelConfig``."""
        return cls(
            model=config.display_name,
            max_count=max(1, config.max_samples),
            count_noun="track",
            lyrics=config.supports_lyrics,
        )


# --- Parsing -----------------------------------------------------------------


def _before(text: str, i: int) -> tuple[str, str]:
    """(last character, last word) before position i, lowercased."""
    before = text[:i].rstrip()
    if not before:
        return "", ""
    word = re.search(r"([A-Za-z]+)$", before)
    return before[-1], word.group(1).lower() if word else ""


def _after(text: str, i: int) -> tuple[str, str]:
    """(first character, first word) after position i, lowercased."""
    after = text[i:].lstrip()
    if not after:
        return "", ""
    word = re.match(r"([A-Za-z]+)", after)
    return after[0], word.group(1).lower() if word else ""


def _edge_ok(ch: str, word: str, words: set[str]) -> bool:
    """Return True at the text's edge, at punctuation or by an allowed word."""
    return ch == "" or ch in _PUNCT or word in words


def _standalone(text: str, start: int, end: int, lead: set, trail: set) -> bool:
    """Return True when either side of a value looks like a setting edge."""
    ch, word = _before(text, start)
    lead_ok = _edge_ok(ch, word, lead)
    ch, word = _after(text, end)
    trail_ok = _edge_ok(ch, word, trail)
    return lead_ok or trail_ok


def _bounded_after(text: str, end: int, extra: set[str] = frozenset()) -> bool:
    ch, word = _after(text, end)
    return ch == "" or ch in _PUNCT or word in ({"and"} | set(extra))


def _bounded_before(text: str, start: int) -> bool:
    ch, _ = _before(text, start)
    return ch == "" or ch in _PUNCT


def _extend(
    text: str, start: int, end: int, lead: str = "", trail: str = ""
) -> tuple[int, int]:
    """Grow a span over the small words that belong to the setting."""
    if lead:
        m = re.search(r"(?:" + lead + r")\s*$", text[:start], re.IGNORECASE)
        if m:
            start = m.start()
    if trail:
        m = re.compile(r"\s*(?:" + trail + r")", re.IGNORECASE).match(text, end)
        if m:
            end = m.end()
    return start, end


_ASPECT_LEAD_RE = (
    r"\b(?:(?:in|at|with)\s+(?:an?\s+)?)?(?:aspect\s+ratio|aspect|ratio)"
    r"(?:\s+of)?\s*:?|\b(?:at|in|as)"
)
_ASPECT_TRAIL_RE = r"(?:aspect\s+ratio|aspect|ratio|format|framing)\b"

_RATIO_RE = re.compile(
    r"(?<![\w:.])(\d{1,2})\s*(?::|x|" + _TIMES + r"|\s+by\s+)\s*(\d{1,2})(?![\w:])",
    re.IGNORECASE,
)
_WORD_RATIO_RE = re.compile(
    r"\b(?:(in|as)\s+(?:a\s+)?)?(landscape|horizontal|portrait|vertical|square)"
    r"(\s+(?:format|orientation|mode|aspect(?:\s+ratio)?|frame))?\b",
    re.IGNORECASE,
)


def _parse_aspect(text: str) -> list[Match]:
    out = []
    for m in _RATIO_RE.finditer(text):
        value = f"{int(m.group(1))}:{int(m.group(2))}"
        if value not in KNOWN_RATIOS:
            continue
        if not _standalone(text, m.start(), m.end(), _ASPECT_LEAD, _ASPECT_TRAIL):
            continue
        span = _extend(text, m.start(), m.end(), _ASPECT_LEAD_RE, _ASPECT_TRAIL_RE)
        out.append(Match(ASPECT, value, span, m.group(0)))
    for m in _WORD_RATIO_RE.finditer(text):
        lead, word, trail = m.group(1), m.group(2).lower(), m.group(3)
        # "in landscape," or "portrait format", never "a portrait of a woman".
        if not trail and not (lead and _bounded_after(text, m.end())):
            continue
        out.append(Match(ASPECT, _WORD_RATIOS[word], m.span(), m.group(0)))
    return out


_K_RE = re.compile(r"(?<![\w.])([124])\s?k(?!\w)", re.IGNORECASE)
_P_RE = re.compile(r"(?<![\w.])(360|480|720|1080|2160)\s?p(?!\w)", re.IGNORECASE)
_SIZE_LEAD_RE = r"\b(?:at|in)"
_SIZE_TRAIL_RE = r"(?:resolution|quality)\b"


def _parse_image_size(text: str) -> list[Match]:
    out = []
    for m in _K_RE.finditer(text):
        if not _standalone(text, m.start(), m.end(), _SIZE_LEAD, _SIZE_TRAIL):
            continue
        span = _extend(text, m.start(), m.end(), _SIZE_LEAD_RE, _SIZE_TRAIL_RE)
        out.append(Match(IMAGE_SIZE, f"{m.group(1)}K", span, m.group(0)))
    return out


def _parse_resolution(text: str) -> list[Match]:
    out = []
    for m in _P_RE.finditer(text):
        value = "4k" if m.group(1) == "2160" else f"{m.group(1)}p"
        span = _extend(text, m.start(), m.end(), _SIZE_LEAD_RE, _SIZE_TRAIL_RE)
        out.append(Match(RESOLUTION, value, span, m.group(0)))
    for m in _K_RE.finditer(text):
        if m.group(1) != "4":
            continue
        if not _standalone(text, m.start(), m.end(), _SIZE_LEAD, _SIZE_TRAIL):
            continue
        span = _extend(text, m.start(), m.end(), _SIZE_LEAD_RE, _SIZE_TRAIL_RE)
        out.append(Match(RESOLUTION, "4k", span, m.group(0)))
    return out


_DURATION_RE = re.compile(
    r"(?<![\w.:])(\d{1,3})(?:\s*|-)(s|secs?|seconds?)(?!\w)",
    re.IGNORECASE,
)


def _parse_duration(text: str) -> list[Match]:
    out = []
    for m in _DURATION_RE.finditer(text):
        value = int(m.group(1))
        if value == 0:
            continue
        # "the 80s" is a decade, not a length.
        if m.group(2).lower() == "s" and _before(text, m.start())[1] in {
            "the",
            "late",
            "early",
            "mid",
        }:
            continue
        span = _extend(text, m.start(), m.end(), r"\b(?:for|lasting)", r"-?\s*long\b")
        out.append(Match(DURATION, value, span, m.group(0)))
    return out


def _count_re(noun: str) -> re.Pattern:
    numbers = r"\d{1,2}|" + "|".join(_NUMBER_WORDS)
    nouns = _COUNT_NOUNS.get(noun, _COUNT_NOUNS["image"]) + "|" + _SHARED_COUNT_NOUNS
    return re.compile(
        r"(?<![\w.])("
        + numbers
        + r")\s+(?:different\s+|separate\s+)?(?:"
        + nouns
        + r")\b",
        re.IGNORECASE,
    )


def _parse_count(text: str, noun: str) -> list[Match]:
    out = []
    for m in _count_re(noun).finditer(text):
        raw = m.group(1).lower()
        value = _NUMBER_WORDS.get(raw) or int(raw)
        span = _extend(
            text,
            m.start(),
            m.end(),
            r"\b(?:give\s+me|show\s+me|make\s+me|make|generate|create)",
            r"of\b",
        )
        out.append(Match(COUNT, value, span, m.group(0)))
    return out


_AUDIO_ON = [
    r"(?:generate\s+)?(?:audio|sound)\s*(?::\s*|\s+)(?:on|yes)",
    r"with\s+(?:audio|sound)",
]
_AUDIO_OFF = [
    r"(?:generate\s+)?(?:audio|sound)\s*(?::\s*|\s+)(?:off|no)",
    r"(?:with\s+)?(?:no|without)\s+(?:audio|sound)",
    r"silent\s+(?:video|clip|film)",
]
# Bare words: need a boundary on both sides (", silent." but not "a silent monk").
_AUDIO_OFF_BARE = [r"silent", r"muted"]


def _parse_audio(text: str) -> list[Match]:
    out = []
    for value, patterns, bare in (
        (True, _AUDIO_ON, False),
        (False, _AUDIO_OFF, False),
        (False, _AUDIO_OFF_BARE, True),
    ):
        for pattern in patterns:
            for m in re.finditer(r"\b" + pattern + r"\b", text, re.IGNORECASE):
                if not _bounded_after(text, m.end()):
                    continue
                if bare and not _bounded_before(text, m.start()):
                    continue
                out.append(Match(AUDIO, value, m.span(), m.group(0)))
    return out


_INSTRUMENTAL_RE = re.compile(
    r"\binstrumental(?:\s+only)?\b|\b(?:no|without)\s+(?:vocals|lyrics|singing)\b",
    re.IGNORECASE,
)


def _parse_instrumental(text: str) -> list[Match]:
    return [
        Match(INSTRUMENTAL, True, m.span(), m.group(0))
        for m in _INSTRUMENTAL_RE.finditer(text)
    ]


def parse(text: str, kinds: Iterable[str], count_noun: str = "image") -> list[Match]:
    """Find setting phrases of the given kinds, in text order, no overlaps."""
    if not text:
        return []
    parsers = {
        ASPECT: _parse_aspect,
        IMAGE_SIZE: _parse_image_size,
        RESOLUTION: _parse_resolution,
        DURATION: _parse_duration,
        COUNT: lambda t: _parse_count(t, count_noun),
        AUDIO: _parse_audio,
        INSTRUMENTAL: _parse_instrumental,
    }
    found: list[Match] = []
    for kind in set(kinds):
        if kind in parsers:
            found += parsers[kind](text)
    # Longest first at each start, then drop anything overlapping a kept span.
    found.sort(key=lambda m: (m.span[0], -(m.span[1] - m.span[0])))
    kept: list[Match] = []
    for m in found:
        if kept and m.span[0] < kept[-1].span[1]:
            continue
        kept.append(m)
    return kept


# --- Fitting to the model ----------------------------------------------------


def _snap_ordered(
    value: str, supported: tuple[str, ...], order: tuple[str, ...]
) -> str:
    """Return the closest supported value at or below the request."""
    ranked = [v for v in order if v in supported] or list(supported)
    if value in ranked:
        return value
    rank = order.index(value) if value in order else len(order)
    below = [v for v in ranked if v in order and order.index(v) <= rank]
    return below[-1] if below else ranked[0]


def _label(kind: str, value: object, noun: str = "image") -> str:
    """Return how a value reads in the notice."""
    if kind == RESOLUTION:
        return "4K" if value == "4k" else str(value)
    if kind == DURATION:
        return f"{value} s"
    if kind == COUNT:
        return f"{value} {noun}" + ("" if value == 1 else "s")
    if kind == AUDIO:
        return "sound on" if value else "sound off"
    if kind == INSTRUMENTAL:
        return "instrumental"
    return str(value)


def _fit_ordered(
    kind: str,
    requested: str,
    supported: tuple[str, ...],
    order: tuple[str, ...],
    model: str,
) -> Applied | Skipped:
    if not supported:
        return Skipped(kind, requested)
    value = _snap_ordered(requested, supported, order)
    if value == requested:
        return Applied(kind, value, requested)
    if len(supported) == 1:
        key, en = "settings.only", "{model} makes {value} only."
    else:
        key, en = "settings.up_to", "{model} goes up to {value}."
    return Applied(
        kind, value, requested, key, en, {"model": model, "value": _label(kind, value)}
    )


def _fit_aspect(m: Match, lim: SettingLimits) -> Applied | Skipped:
    if not lim.aspect_ratios:
        return Skipped(ASPECT, m.value)
    if m.value in lim.aspect_ratios:
        return Applied(ASPECT, m.value, m.value)
    return Skipped(
        ASPECT,
        m.value,
        "settings.cant_aspect",
        "{model} can't make {value}.",
        {"model": lim.model, "value": m.value},
    )


def _fit_image_size(m: Match, lim: SettingLimits) -> Applied | Skipped:
    return _fit_ordered(
        IMAGE_SIZE, m.value, lim.image_sizes, IMAGE_SIZE_ORDER, lim.model
    )


def _fit_resolution(m: Match, lim: SettingLimits) -> Applied | Skipped:
    return _fit_ordered(
        RESOLUTION, m.value, lim.resolutions, RESOLUTION_ORDER, lim.model
    )


def _fit_duration(m: Match, lim: SettingLimits) -> Applied | Skipped:
    requested, durations = m.value, lim.durations
    if not durations:
        return Skipped(DURATION, requested)
    if requested in durations:
        return Applied(DURATION, requested, requested)
    value = min(durations, key=lambda d: (abs(d - requested), d))
    lo, hi = min(durations), max(durations)
    if requested > hi:
        key, en, shown = "settings.up_to", "{model} goes up to {value}.", f"{hi} s"
    elif requested < lo:
        key, en, shown = "settings.starts_at", "{model} starts at {value}.", f"{lo} s"
    elif list(durations) == list(range(lo, hi + 1)):
        return Applied(DURATION, value, requested)
    else:
        options = [str(d) for d in sorted(durations)]
        shown = ", ".join(options[:-1]) + " or " + options[-1] + " s"
        key, en = "settings.makes", "{model} makes {value}."
    return Applied(
        DURATION, value, requested, key, en, {"model": lim.model, "value": shown}
    )


def _fit_count(m: Match, lim: SettingLimits) -> Applied | Skipped:
    value = max(1, min(int(m.value), lim.max_count))
    if value == m.value:
        return Applied(COUNT, value, m.value)
    if lim.max_count == 1:
        return Applied(
            COUNT,
            1,
            m.value,
            "settings.one_at_a_time",
            "{model} makes one {noun} at a time.",
            {"model": lim.model, "noun": lim.count_noun},
        )
    return Applied(
        COUNT,
        value,
        m.value,
        "settings.up_to",
        "{model} goes up to {value}.",
        {"model": lim.model, "value": _label(COUNT, value, lim.count_noun)},
    )


# (audio mode, requested value) -> note for a value the model can't change.
_AUDIO_NOTES = {
    ("always", True): ("settings.always_sound", "{model} always adds sound."),
    ("always", False): ("settings.no_silent", "{model} can't make silent video."),
    ("none", True): ("settings.silent_only", "{model} makes silent video only."),
}


def _fit_audio(m: Match, lim: SettingLimits) -> Applied | Skipped:
    if lim.audio == "toggle":
        return Applied(AUDIO, bool(m.value), m.value)
    key, en = _AUDIO_NOTES.get((lim.audio, bool(m.value)), ("", ""))
    return Skipped(AUDIO, bool(m.value), key, en, {"model": lim.model} if en else {})


def _fit_instrumental(_m: Match, lim: SettingLimits) -> Applied | Skipped:
    # Models without lyrics are always instrumental: nothing to change.
    return (
        Applied(INSTRUMENTAL, True, True) if lim.lyrics else Skipped(INSTRUMENTAL, True)
    )


_FITTERS = {
    ASPECT: _fit_aspect,
    IMAGE_SIZE: _fit_image_size,
    RESOLUTION: _fit_resolution,
    DURATION: _fit_duration,
    COUNT: _fit_count,
    AUDIO: _fit_audio,
    INSTRUMENTAL: _fit_instrumental,
}


def fit(matches: list[Match], limits: SettingLimits) -> list[Applied | Skipped]:
    """Snap each match to the model. When a kind appears twice, the last wins."""
    last: dict[str, Match] = {}
    for m in matches:
        last.pop(m.kind, None)
        last[m.kind] = m
    return [
        _FITTERS[m.kind](m, limits) if m.kind in _FITTERS else Skipped(m.kind, m.value)
        for m in last.values()
    ]


# --- Stripping ---------------------------------------------------------------


def strip(text: str, matches: list[Match]) -> str:
    """Remove matched phrases and tidy the commas they leave behind.

    Returns the text unchanged when nothing would be left of it.
    """
    spans = sorted(m.span for m in matches if m.kind not in _KEEP_IN_PROMPT)
    if not spans:
        return text
    pieces, pos = [], 0
    for start, end in spans:
        if start < pos:
            continue
        pieces.append(text[pos:start])
        pos = end
    pieces.append(text[pos:])
    out = "".join(pieces)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([,.;:!?])", r"\1", out)
    out = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", out)
    out = re.sub(r"[,;:]\s*([.!?])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"^[\s,;:.]+", "", out)
    out = re.sub(r"[\s,;:]+$", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out if out.strip(" .") else text


# --- One call for a page -----------------------------------------------------


@dataclass(frozen=True)
class PromptRun:
    """What a page needs after parsing one submitted prompt."""

    prompt: str  # text to send to the model
    changes: dict  # kind -> new value, only where it differs from the chips
    previous: dict  # kind -> chip value before, for Undo
    notice: str  # one line for the composer ("" when nothing to say)
    undo_json: str  # pass back to ``read_undo`` when the user presses Undo


def notice_text(
    results: list[Applied | Skipped],
    current: dict,
    noun: str = "image",
    tr: Translate = _english,
) -> str:
    """Write the notice, e.g. 'From your prompt: 16:9 (was 1:1).'."""
    changes = [
        tr(
            "settings.was",
            "{new} (was {old})",
            new=_label_tr(r.kind, r.value, noun, tr),
            old=_label_tr(r.kind, current[r.kind], noun, tr),
        )
        for r in results
        if isinstance(r, Applied) and r.kind in current and r.value != current[r.kind]
    ]
    parts = []
    if changes:
        parts.append(
            tr(
                "settings.from_prompt",
                "From your prompt: {items}.",
                items=", ".join(changes),
            ),
        )
    parts += [n for n in (r.note(tr) for r in results) if n]
    return " ".join(parts)


def _label_tr(kind: str, value: object, noun: str, tr: Translate) -> str:
    """Return ``_label`` with its added words passed through the translator."""
    if kind == COUNT:
        n = int(value)
        word = tr(
            f"settings.noun.{noun}" + ("" if n == 1 else "s"),
            noun + ("" if n == 1 else "s"),
        )
        return f"{n} {word}"
    if kind == AUDIO:
        return (
            tr("settings.sound_on", "sound on")
            if value
            else tr("settings.sound_off", "sound off")
        )
    if kind == DURATION:
        return tr("settings.seconds", "{n} s", n=value)
    return _label(kind, value, noun)


def apply(
    text: str,
    kinds: Iterable[str],
    limits: SettingLimits,
    current: dict,
    *,
    ignored: Iterable[list[str]] = (),
    tr: Translate = _english,
) -> PromptRun:
    """Parse, fit and strip in one go.

    ``current`` holds the chip values by kind. ``ignored`` lists
    ``[kind, phrase]`` pairs the user already undid; those are left in the
    prompt as typed and not applied again.
    """
    skip = {(k, p.lower()) for k, p in ignored}
    matches = [
        m
        for m in parse(text, kinds, limits.count_noun)
        if (m.kind, m.text.lower()) not in skip
    ]
    results = fit(matches, limits)
    changes, previous = {}, {}
    for r in results:
        if isinstance(r, Applied) and r.kind in current and r.value != current[r.kind]:
            changes[r.kind] = r.value
            previous[r.kind] = current[r.kind]
    undo = ""
    if changes:
        undo = json.dumps(
            {
                "previous": previous,
                "phrases": [[m.kind, m.text] for m in matches if m.kind in changes],
            },
        )
    return PromptRun(
        prompt=strip(text, matches),
        changes=changes,
        previous=previous,
        notice=notice_text(results, current, limits.count_noun, tr),
        undo_json=undo,
    )


def read_undo(undo_json: str) -> tuple[dict, list[list[str]]]:
    """(previous chip values, phrases to stop applying) from ``undo_json``."""
    try:
        data = json.loads(undo_json or "{}")
    except ValueError:
        return {}, []
    return dict(data.get("previous") or {}), [
        list(p) for p in data.get("phrases") or []
    ]


def add_ignored(ignored_json: str, phrases: list[list[str]]) -> str:
    """Merge undone phrases into a page's JSON list of ignored phrases."""
    try:
        current = json.loads(ignored_json or "[]")
    except ValueError:
        current = []
    for p in phrases:
        if p not in current:
            current.append(p)
    return json.dumps(current)


def ignored_list(ignored_json: str) -> list[list[str]]:
    """Return the ignored phrases a page stored with ``add_ignored``."""
    try:
        return [list(p) for p in json.loads(ignored_json or "[]")]
    except ValueError:
        return []
