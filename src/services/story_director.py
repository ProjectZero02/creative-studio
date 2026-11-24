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
"""Multi-minute film director: blueprint, script parsing, and two-stage scenarios.

Pure Python (no network, no Mesop) so every rule can be unit tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.default import Default
from services.story_models import (
    CAMERA_IDS,
    NOT_FAMOUS,
    PACING_MODES,
    SCENE_LENGTHS,
    SHOT_SIZE_IDS,
    SHOT_SIZES,
    SPEAKER_FACING,
    VOICES,
    WORDS_PER_SECOND,
    Story,
    _brand_rule,
    _cast_item_rules,
    _links_schema,
    _main_character,
    _set_cast_rules,
    _speech_rules,
    _str,
    _str_list,
    cast_names,
    cast_schema,
    nearest_duration,
    normalize_camera,
    style_of,
    supported_durations,
)

# Director transition choices for Stage 2 shot planning (excludes "auto").
DIRECTOR_TRANSITION_IDS = ("cut", "bridge", "extend", "dissolve", "fade_black")

_SINGLE_SEQ_MAX_SCENES = 8
_SHOTS_PER_SEQUENCE_TARGET = 6
_MIN_BEAT_SECONDS = 4
_MAX_VO_BEAT_SECONDS = 15
_MAX_SPOKEN_BEAT_SECONDS = 25
_SLUGLINE_MIN_PARTS = 2
_SCRIPT_WPS = 2.4
_PAUSE_SECONDS = 0.5

# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

DIRECTOR_SYSTEM = (
    "You are an experienced film director, cinematographer, and screenwriter "
    "planning multi-minute films with hierarchical structure: Act -> Sequence -> Shot. "
    "Establish one global visual grammar lock (lens family, focal length feel, "
    "lighting ratio, and color grade) and hold it across every sequence and shot.\n\n"
    "Continuity & editing craft:\n"
    "- 180-degree rule: preserve consistent screen direction, spatial geography, "
    "and character eyelines across all shots within a sequence.\n"
    "- 30-degree rule: never cut between two consecutive shots in the same "
    "location with the same shot_size or near-identical camera angle; vary "
    "shot_size meaningfully (e.g., wide -> medium -> close_up -> insert) on cuts.\n"
    "- Keep each field strictly separated:\n"
    "  * visual: static keyframe composition ONLY (subject, pose, expression, "
    "shot framing, setting details, lighting). Never put temporal camera-move "
    "verbs or 'then/next' sequences inside visual.\n"
    "  * motion_prompt: temporal blocking, subject movement, and camera move "
    "during the clip.\n"
    "  * audio_cue: specific ambient soundscape, room tone, Foley, and sound "
    "effects (no music; no speech on narrated/B-roll shots).\n"
    "Follow the user's rules, language, style, and script faithfully."
)

# ---------------------------------------------------------------------------
# Blueprint planner
# ---------------------------------------------------------------------------


# Words in an idea that ask for one unbroken camera run.
_ONE_TAKE = re.compile(
    r"\b(one|single|a single|1)[ -](shot|take)\b|\boner\b|\bcontinuous(ly)?\b"
    r"|\bunbroken\b|\bno (jump )?cuts?\b|\bwithout (any )?cuts?\b"
    r"|\bthroughout (that|the) (whole |entire )?(time|film|video|shot|clip)\b"
)


def is_one_take(text: str) -> bool:
    """True when the idea asks for one continuous shot ("one shot", "single
    take", "continuous", "no cuts", "the camera pans ... throughout")."""
    return bool(_ONE_TAKE.search((text or "").lower()))


def plan_one_take(target_seconds: int, video_model: str = "") -> tuple[int, int]:
    """(scenes, seconds each) for a continuous film: as few takes as fit,
    each at most STORY_TAKE_CONTEXT_SECONDS (Omni's documented 30 s chain).
    30 -> (1, 30); 45 -> (2, 25)
    (the stitch trims the film to the asked length); 300 -> (10, 30)."""
    cfg = Default()
    cap = max(1, int(getattr(cfg, "STORY_TAKE_CONTEXT_SECONDS", 30) or 30))
    target = max(1, min(int(target_seconds or 0) or 30, int(cfg.STORY_MAX_FILM_SECONDS)))
    takes = max(1, -(-target // cap))
    each = -(-target // takes)
    lengths = [d for d in supported_durations(video_model) if d >= each]
    duration = min(lengths) if lengths else max(supported_durations(video_model))
    return takes, duration


def plan_film_blueprint(
    target_seconds: int,
    pacing: str = "cinematic",
    video_model: str = "",
    one_take: bool = False,
) -> dict:
    """Plan sequence and shot counts for a target runtime.

    ``one_take``: the idea asks for one continuous shot, so the film is as
    few long takes as fit (plan_one_take), never split to fill a count.

    Respects ``STORY_MIN_SCENES``..``STORY_MAX_SCENES`` and
    ``STORY_MAX_FILM_SECONDS``, snapping durations to
    ``supported_durations(video_model)``.
    """
    cfg = Default()
    min_scenes = max(1, int(cfg.STORY_MIN_SCENES))
    max_scenes = max(min_scenes, int(cfg.STORY_MAX_SCENES))
    max_film = max(1, int(cfg.STORY_MAX_FILM_SECONDS))

    allowed = supported_durations(video_model) or [4, 6, 8]
    pacing_cfg = PACING_MODES.get(pacing, PACING_MODES["cinematic"])
    desired_shot = int(pacing_cfg["target_shot_seconds"])
    preferred_d = nearest_duration(desired_shot, video_model)

    raw_target = int(target_seconds or 0)
    if raw_target <= 0:
        raw_target = min_scenes * preferred_d
    target = max(1, min(raw_target, max_film))

    n_pref = round(target / preferred_d)
    max_fit = max_film // preferred_d
    if one_take:
        scene_count, duration = plan_one_take(target, video_model)
    elif min_scenes <= n_pref <= max_scenes and n_pref * preferred_d <= max_film:
        scene_count, duration = n_pref, preferred_d
    elif (
        n_pref * preferred_d > max_film
        and min_scenes <= max_fit <= max_scenes
        and abs(max_fit * preferred_d - target) <= preferred_d
    ):
        scene_count, duration = max_fit, preferred_d
    else:
        candidates = [
            (n, d)
            for d in allowed
            for n in range(min_scenes, max_scenes + 1)
            if n * d <= max_film
        ]
        if candidates:
            scene_count, duration = min(
                candidates,
                key=lambda nd: (
                    abs(nd[0] * nd[1] - target),
                    abs(nd[1] - preferred_d),
                    nd[0],
                ),
            )
        else:
            scene_count, duration = min_scenes, min(allowed)

    sequence_count = (
        1
        if scene_count <= _SINGLE_SEQ_MAX_SCENES
        else max(2, min(scene_count, round(scene_count / _SHOTS_PER_SEQUENCE_TARGET)))
    )
    base, rem = divmod(scene_count, sequence_count)
    shots_per_sequence = [
        base + (1 if i < rem else 0) for i in range(sequence_count)
    ]
    return {
        "sequence_count": sequence_count,
        "scene_count": scene_count,
        "duration": duration,
        "estimated_seconds": scene_count * duration,
        "shots_per_sequence": shots_per_sequence,
    }


# ---------------------------------------------------------------------------
# Setup: duration text and the live blueprint
# ---------------------------------------------------------------------------

# Used when the duration box is blank and the idea names no length.
DEFAULT_FILM_SECONDS = 30

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
}
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "sixty": 60,
    "ninety": 90, "half": 0.5,
}
_DURATION_PART = re.compile(
    r"(\d+(?:[.,]\d+)?|[a-z-]+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])"
)


def parse_duration_text(text: str) -> int | None:
    """Seconds asked for in the Setup duration box.

    "30s", "30 sec", "2 min", "1m30s", "1:30", "90", "half a minute",
    "2.5 minutes" all work. Blank gives 0 (Gemini decides); text that is not
    a length gives None. The result is capped at STORY_MAX_FILM_SECONDS.
    """
    t = " ".join(str(text or "").lower().replace("and", " ").split())
    if not t:
        return 0
    cap = max(1, int(Default().STORY_MAX_FILM_SECONDS))
    m = re.fullmatch(r"(\d{1,3}):([0-5]\d)", t)
    if m:
        secs = int(m.group(1)) * 60 + int(m.group(2))
        return min(cap, secs) if secs > 0 else None
    m = re.fullmatch(r"\d+(?:[.,]\d+)?", t)
    if m:
        secs = round(float(t.replace(",", ".")))
        return min(cap, secs) if secs > 0 else None
    t = t.replace("half a minute", "30 s").replace("half an hour", "30 min")
    total = 0.0
    found = False
    for num, unit in _DURATION_PART.findall(t):
        if num[0].isdigit():
            value = float(num.replace(",", "."))
        elif num in _WORD_NUMBERS:
            value = float(_WORD_NUMBERS[num])
        else:
            continue
        total += value * _UNIT_SECONDS[unit]
        found = True
    if not found or total <= 0:
        return None
    return min(cap, round(total))


# List prices (USD) for the Setup blueprint when the Cloud Billing Catalog
# price is not cached yet. The blueprint must answer instantly, so it never
# waits on the catalog; the Usage page prices real calls from the catalog.
_FALLBACK_VIDEO_PER_SECOND = (("lite", 0.10), ("fast", 0.15), ("omni", 0.40), ("veo", 0.40))
_FALLBACK_IMAGE = 0.039
_FALLBACK_TTS_PER_MILLION_CHARS = 10.0
_FALLBACK_MUSIC_PER_TRACK = 0.06


def _catalog_rate(model: str, kind: str) -> float | None:
    try:
        from config import pricing

        rate = pricing.cached_unit_rate(model, kind)
    except Exception:  # pricing must never break Setup
        return None
    return rate.price_per_unit if rate else None


def _video_price(video_model: str) -> float:
    from services.story_models import _video_model_spec

    mid = (video_model or "").strip() or Default().STORY_VIDEO_MODEL
    spec, _ = _video_model_spec(mid)
    name = getattr(spec, "model_name", "") or {
        "hybrid": "gemini-omni",
        "3.1": "veo-3.1",
        "3.1-fast": "veo-3.1-fast",
    }.get(mid, mid)
    live = _catalog_rate(name, "video")
    if live:
        return live
    lowered = name.lower()
    return next((p for key, p in _FALLBACK_VIDEO_PER_SECOND if key in lowered), 0.40)


def _pack_takes(shots: int, shot_seconds: int, take_max: int) -> list[int]:
    """Shots per take when every shot carries on the one before until a
    take is full (the director cuts only when it must)."""
    per_take = max(1, int(take_max) // max(1, int(shot_seconds)))
    takes = []
    left = int(shots)
    while left > 0:
        takes.append(min(per_take, left))
        left -= per_take
    return takes


def setup_blueprint(
    seconds: int,
    *,
    pacing: str = "cinematic",
    video_model: str = "",
    resolution: str = "",
    voice_on: bool = True,
    music_on: bool = True,
    one_take: bool = False,
) -> dict:
    """What Setup's live blueprint shows for a film of about `seconds`:
    shots, takes and cuts, resolution, an estimated cost (catalog
    prices when cached, else list prices) and an estimated time. Gemini makes the real cut list;
    these are honest estimates for the request.

    Video is priced per generated second: an extension bills only its new
    seconds, so a take costs its own length once.
    """
    from services.story_models import (
        _video_model_spec,
        apply_caps,
        clip_parts,
        single_clip_max,
    )

    cfg = Default()
    asked = int(seconds or 0) or DEFAULT_FILM_SECONDS
    plan = plan_film_blueprint(
        asked, pacing=pacing, video_model=video_model, one_take=one_take
    )
    shots, shot_secs = int(plan["scene_count"]), int(plan["duration"])
    length = shots * shot_secs
    if one_take:
        # A continuous film is trimmed to the asked length when stitched.
        length = min(length, asked)
    caps = apply_caps(shots, shot_secs, resolution=resolution, model_id=video_model)
    take_max = int(getattr(cfg, "STORY_TAKE_MAX_SECONDS", 40) or 40)
    takes = [1] * shots if one_take else _pack_takes(shots, shot_secs, take_max)
    take_count = len(takes)

    video_rate = _video_price(video_model)
    if caps.resolution == "360p":
        video_rate *= 0.33  # list price: 360p is about a third of 720p
    image_rate = _FALLBACK_IMAGE
    words = length * WORDS_PER_SECOND
    voice_cost = (
        words * 6 / 1e6 * _FALLBACK_TTS_PER_MILLION_CHARS if voice_on else 0.0
    )
    cost = {
        "video": round(length * video_rate, 2),
        "frames": round(take_count * image_rate, 2),
        "voice": round(voice_cost, 4),
        "music": _FALLBACK_MUSIC_PER_TRACK if music_on else 0.0,
    }
    cost["total"] = round(sum(cost.values()), 2)

    model, _ = _video_model_spec(video_model)
    per_call = int(getattr(model, "typical_generation_seconds", 90) or 90)
    single = max(1, single_clip_max(video_model))
    parallel = max(1, int(getattr(cfg, "STORY_MAX_PARALLEL", 3) or 3))
    # A take is one clip plus extension turns, made one after another;
    # separate takes run side by side.
    turns = [max(1, -(-(n * shot_secs - single) // 10) + 1) if n * shot_secs > single else 1
             for n in takes]
    waves = -(-take_count // parallel)
    clip_time = waves * max(turns) * per_call
    if one_take:
        # Continuous takes are made one after another (each starts where
        # the one before ends).
        clip_time = sum(turns) * per_call
    est_time = 30 + 20 * -(-take_count // parallel) + clip_time + 30
    return {
        "asked_seconds": int(seconds or 0),
        "seconds": length,
        "shots": shots,
        "shot_seconds": shot_secs,
        "takes": take_count,
        # A continuous film joins its takes without a cut.
        "cuts": 0 if one_take else max(0, take_count - 1),
        "one_take": bool(one_take),
        "turns": clip_parts(shot_secs, single),
        "shots_per_take": takes,
        "resolution": caps.resolution,
        "cost": cost,
        "time_seconds": int(est_time),
    }


def takes_line(takes: int) -> str:
    """'1 continuous take' or '3 takes, 2 cuts'."""
    if takes <= 1:
        return "1 continuous take"
    cuts = takes - 1
    return f"{takes} takes, {cuts} cut{'s' if cuts != 1 else ''}"


def time_line(seconds: int) -> str:
    """'about 4 min' style."""
    mins = max(1, round(seconds / 60))
    return f"about {mins} min"


# ---------------------------------------------------------------------------
# Deterministic script / voiceover parser
# ---------------------------------------------------------------------------

_SLUGLINE_RE = re.compile(
    r"^(?:INT\.|EXT\.|INT\./EXT\.|EXT\./INT\.|I/E\.?)\s+(.+)$",
    re.IGNORECASE,
)
_SPEAKER_RE = re.compile(r"^([A-Z][A-Z0-9 _.'()-]{1,35}):\s*(.*)$")
_VISUAL_TAG_RE = re.compile(r"\[(?:Visual|VISUAL|visual)\s*:\s*([^\]]+)\]")
_TITLE_LINE_RE = re.compile(r"^(?:Title\s*:\s*|#\s+)(.+)$", re.IGNORECASE)
_NARRATOR_SPEAKER_NAMES = {"NARRATOR", "VOICEOVER", "VOICE OVER", "VO", "NARRATION"}
_SHOT_SIZE_CYCLE = (
    "wide",
    "medium",
    "medium_close",
    "close_up",
    "medium_wide",
    "insert",
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?؟…])\s+")


def _snap_beat_seconds(raw_seconds: float, max_beat: int) -> int:
    choices = [d for d in SCENE_LENGTHS if _MIN_BEAT_SECONDS <= d <= max_beat]
    if not choices:
        return max(_MIN_BEAT_SECONDS, min(max_beat, round(raw_seconds)))
    for d in choices:
        if d >= raw_seconds:
            return d
    return choices[-1]


def _split_text_to_beats(text: str, max_beat: int) -> list[tuple[str, int]]:
    """Split narration or dialogue at sentence boundaries into timed beats."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    max_words_per_beat = max(
        _MIN_BEAT_SECONDS,
        int((max_beat - _PAUSE_SECONDS) * _SCRIPT_WPS),
    )
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s.strip()]
    if not sentences:
        sentences = [cleaned]

    expanded: list[str] = []
    for sent in sentences:
        words = sent.split(" ")
        if len(words) <= max_words_per_beat:
            expanded.append(sent)
            continue
        expanded.extend(
            " ".join(words[start : start + max_words_per_beat])
            for start in range(0, len(words), max_words_per_beat)
        )

    chunks: list[str] = []
    buf: list[str] = []
    for part in expanded:
        candidate = " ".join([*buf, part]).strip()
        cand_secs = len(candidate.split()) / _SCRIPT_WPS + _PAUSE_SECONDS
        if buf and cand_secs > max_beat:
            chunks.append(" ".join(buf))
            buf = [part]
        else:
            buf.append(part)
    if buf:
        chunks.append(" ".join(buf))

    return [
        (chunk, _snap_beat_seconds(len(chunk.split()) / _SCRIPT_WPS + _PAUSE_SECONDS, max_beat))
        for chunk in chunks
    ]


def _parse_slugline(raw_place: str) -> tuple[str, str]:
    """Extract (location_name, time_of_day) from a screenplay slugline body."""
    parts = [p.strip() for p in re.split(r"\s+-\s+", raw_place.strip()) if p.strip()]
    if len(parts) >= _SLUGLINE_MIN_PARTS:
        return " - ".join(parts[:-1]).title(), parts[-1].lower()
    return raw_place.strip().title(), ""


def _resolve_spoken(
    speaker_raw: str,
    speech_mode: str,
    *,
    is_dialogue: bool,
) -> tuple[bool, str]:
    """Determine (spoken, clean_speaker_name) for a script block."""
    upper = speaker_raw.strip().upper()
    vo_tag = bool(re.search(r"\((?:V\.?O\.?|O\.?S\.?)\)", upper))
    clean_name = re.sub(r"\s*\([^)]*\)", "", speaker_raw).strip()
    is_narrator = clean_name.upper() in _NARRATOR_SPEAKER_NAMES or vo_tag

    if speech_mode == "narrator":
        return False, clean_name
    if speech_mode == "on_camera":
        return True, clean_name
    if not is_dialogue or is_narrator:
        return False, ""
    return True, clean_name


def _default_visual_for_beat(
    line: str,
    location_name: str,
    speaker_name: str,
    *,
    spoken: bool,
) -> str:
    excerpt = re.sub(r"\s+", " ", line).strip()[:120]
    where = f" in {location_name}" if location_name else ""
    if spoken and speaker_name:
        return (
            f"{speaker_name.title()} speaking{where} ({SPEAKER_FACING}), "
            "natural expression and grounded lighting."
        )
    if location_name and excerpt:
        return f"Establishing view of {location_name}: {excerpt}"
    if excerpt:
        return f"Illustrative visual scene: {excerpt}"
    return f"Atmospheric shot of {location_name or 'the setting'}."


def _apply_thirty_degree_rule(scenes: list[dict]) -> None:
    """Vary shot_size across consecutive same-location cut shots."""
    prev_loc: str | None = None
    prev_size: str | None = None
    cycle_idx = 0
    for sc in scenes:
        loc = sc.get("location") or ""
        trans = sc.get("transition") or "cut"
        cur_size = sc.get("shot_size") or "medium"
        if (
            prev_loc is not None
            and trans == "cut"
            and loc == prev_loc
            and cur_size == prev_size
        ):
            for step in range(len(_SHOT_SIZE_CYCLE)):
                cand = _SHOT_SIZE_CYCLE[(cycle_idx + 1 + step) % len(_SHOT_SIZE_CYCLE)]
                if cand != prev_size:
                    sc["shot_size"] = cand
                    cycle_idx = (cycle_idx + 1 + step) % len(_SHOT_SIZE_CYCLE)
                    break
        elif cur_size in _SHOT_SIZE_CYCLE:
            cycle_idx = _SHOT_SIZE_CYCLE.index(cur_size)
        prev_loc = loc
        prev_size = sc.get("shot_size") or "medium"


@dataclass
class _ScriptBuilder:
    """Mutable accumulator for deterministic script parsing."""

    pacing: str
    speech_mode: str
    characters: list[dict] = field(default_factory=list)
    char_by_name: dict[str, str] = field(default_factory=dict)
    locations: list[dict] = field(default_factory=list)
    loc_by_name: dict[str, str] = field(default_factory=dict)
    scenes: list[dict] = field(default_factory=list)
    seq_meta: dict[str, dict] = field(default_factory=dict)
    seq_order: list[str] = field(default_factory=list)

    cur_seq: str = ""
    cur_loc_key: str = ""
    cur_loc_name: str = ""
    pending_visual: str = ""

    def ensure_seq(self) -> str:
        if not self.cur_seq:
            self.cur_seq = self.open_sequence(
                self.cur_loc_name or "Opening Sequence",
                self.cur_loc_key,
            )
        return self.cur_seq

    def flush_visual(self) -> None:
        if not self.pending_visual:
            return
        self.append_shot(
            {
                "seq_key": self.ensure_seq(),
                "narration": "",
                "spoken": False,
                "seconds": 6 if self.pacing == "cinematic" else _MIN_BEAT_SECONDS,
                "visual": self.pending_visual,
                "loc_key": self.cur_loc_key,
                "camera": "dolly_in",
            },
        )
        self.pending_visual = ""

    def emit_dialogue(self, speaker_raw: str, dialogue: str) -> None:
        spoken_flag, clean_speaker = _resolve_spoken(
            speaker_raw,
            self.speech_mode,
            is_dialogue=True,
        )
        speaker_key = self.ensure_character(clean_speaker) if clean_speaker else ""
        cast_keys = [speaker_key] if speaker_key else []
        max_beat = _MAX_SPOKEN_BEAT_SECONDS if spoken_flag else _MAX_VO_BEAT_SECONDS
        beats = _split_text_to_beats(dialogue, max_beat)
        if not beats:
            self.flush_visual()
            return
        for b_idx, (beat_text, beat_secs) in enumerate(beats):
            vis = self.pending_visual if (b_idx == 0 and self.pending_visual) else ""
            if b_idx == 0:
                self.pending_visual = ""
            if not vis:
                vis = _default_visual_for_beat(
                    beat_text,
                    self.cur_loc_name,
                    clean_speaker,
                    spoken=spoken_flag,
                )
            self.append_shot(
                {
                    "seq_key": self.ensure_seq(),
                    "narration": beat_text,
                    "spoken": spoken_flag,
                    "seconds": beat_secs,
                    "visual": vis,
                    "loc_key": self.cur_loc_key,
                    "cast_keys": cast_keys,
                    "speaker_key": speaker_key,
                    "camera": "static" if spoken_flag else "dolly_in",
                },
            )

    def ensure_location(self, name: str, time_of_day: str = "") -> str:
        norm = name.strip().lower()
        if not norm:
            return ""
        if norm in self.loc_by_name:
            return self.loc_by_name[norm]
        key = f"l{len(self.locations) + 1}"
        self.loc_by_name[norm] = key
        self.locations.append(
            {
                "key": key,
                "name": name.strip().title(),
                "description": f"{name.strip()}, detailed environment ready for filming",
                "time_of_day": time_of_day,
            },
        )
        return key

    def ensure_character(self, name: str) -> str:
        norm = name.strip().lower()
        if not norm:
            return ""
        if norm in self.char_by_name:
            return self.char_by_name[norm]
        idx = len(self.characters)
        key = f"c{idx + 1}"
        self.char_by_name[norm] = key
        tts_voice = VOICES[idx % len(VOICES)]
        gender = "female" if tts_voice in ("Kore", "Aoede", "Leda", "Zephyr") else "male"
        self.characters.append(
            {
                "key": key,
                "name": name.strip().title(),
                "description": (
                    f"{name.strip().title()}, {NOT_FAMOUS}, natural everyday appearance"
                ),
                "outfit": "practical everyday wardrobe matching the setting",
                "voice": {
                    "tts_voice": tts_voice,
                    "style": "natural, clear",
                    "description": f"a {gender} voice, mid-30s, clear and grounded",
                },
            },
        )
        return key

    def open_sequence(self, seq_title: str, loc_key: str) -> str:
        key = f"seq{len(self.seq_order) + 1}"
        self.seq_order.append(key)
        self.seq_meta[key] = {
            "key": key,
            "title": seq_title or f"Sequence {len(self.seq_order)}",
            "summary": seq_title or "",
            "location": loc_key,
            "cast": [],
        }
        return key

    def append_shot(self, spec: dict) -> None:
        shot_idx = len(self.scenes)
        shot_size = _SHOT_SIZE_CYCLE[shot_idx % len(_SHOT_SIZE_CYCLE)]
        spoken = bool(spec["spoken"])
        if spoken and shot_size in ("extreme_wide", "insert"):
            shot_size = "medium_close"
        camera = str(spec.get("camera") or "static")
        motion = (
            f"Subtle natural movement and {camera.replace('_', ' ')} camera motion."
        )
        audio_cue = (
            "Clean room tone and soft natural ambience."
            if spoken
            else "Natural ambient soundscape and subtle environmental Foley."
        )
        cast_keys = list(spec.get("cast_keys") or [])
        seq_key = str(spec["seq_key"])
        self.scenes.append(
            {
                "narration": spec["narration"],
                "spoken": spoken,
                "seconds": spec["seconds"],
                "visual": spec["visual"],
                "motion_prompt": motion,
                "audio_cue": audio_cue,
                "shot_size": shot_size,
                "camera": camera,
                "transition": "cut",
                "sequence": seq_key,
                "cast": cast_keys,
                "location": spec.get("loc_key") or "",
                "props": [],
                "speaker": spec.get("speaker_key") or "" if spoken else "",
            },
        )
        for ck in cast_keys:
            if ck and ck not in self.seq_meta[seq_key]["cast"]:
                self.seq_meta[seq_key]["cast"].append(ck)


def _match_speaker(line: str) -> re.Match[str] | None:
    if line.lower().startswith(("http:", "https:", "title:", "visual:")):
        return None
    return _SPEAKER_RE.match(line)


def _is_speaker_line(line: str) -> bool:
    return _match_speaker(line) is not None


def _collect_dialogue_lines(lines: list[str], start: int, first: str) -> tuple[str, int]:
    speech_lines = [first] if first else []
    i = start
    while i < len(lines):
        nxt = lines[i].strip()
        if (
            not nxt
            or _SLUGLINE_RE.match(nxt)
            or _SPEAKER_RE.match(nxt)
            or _VISUAL_TAG_RE.match(nxt)
        ):
            break
        speech_lines.append(nxt)
        i += 1
    return " ".join(speech_lines).strip(), i


def _parse_screenplay(lines: list[str], builder: _ScriptBuilder) -> None:
    i = 0
    while i < len(lines):
        raw_ln = lines[i].strip()
        i += 1
        if not raw_ln:
            continue
        slug_m = _SLUGLINE_RE.match(raw_ln)
        if slug_m:
            builder.flush_visual()
            builder.cur_loc_name, tod = _parse_slugline(slug_m.group(1))
            builder.cur_loc_key = builder.ensure_location(builder.cur_loc_name, tod)
            builder.cur_seq = builder.open_sequence(raw_ln, builder.cur_loc_key)
            continue
        vis_matches = _VISUAL_TAG_RE.findall(raw_ln)
        cleaned_ln = _VISUAL_TAG_RE.sub("", raw_ln).strip()
        if vis_matches and not cleaned_ln:
            builder.flush_visual()
            builder.pending_visual = " ".join(v.strip() for v in vis_matches if v.strip())
            continue
        spk_m = _match_speaker(cleaned_ln or raw_ln)
        if spk_m is not None:
            dialogue, i = _collect_dialogue_lines(lines, i, spk_m.group(2).strip())
            builder.emit_dialogue(spk_m.group(1).strip(), dialogue)
            continue
        action_text = " ".join(
            bit for bit in [*vis_matches, cleaned_ln] if bit and bit.strip()
        ).strip()
        if action_text:
            builder.flush_visual()
            builder.pending_visual = action_text

    builder.flush_visual()


def _parse_voiceover_paragraphs(body: str, builder: _ScriptBuilder) -> None:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    spoken_flag = builder.speech_mode == "on_camera"
    max_beat = _MAX_SPOKEN_BEAT_SECONDS if spoken_flag else _MAX_VO_BEAT_SECONDS
    for p_idx, para in enumerate(paragraphs):
        vis_tags = [v.strip() for v in _VISUAL_TAG_RE.findall(para) if v.strip()]
        narration_text = re.sub(r"\s+", " ", _VISUAL_TAG_RE.sub("", para)).strip()
        seq_key = builder.open_sequence(f"Sequence {p_idx + 1}", "")
        if not narration_text and vis_tags:
            for vt in vis_tags:
                builder.append_shot(
                    {
                        "seq_key": seq_key,
                        "narration": "",
                        "spoken": False,
                        "seconds": 6,
                        "visual": vt,
                        "camera": "dolly_in",
                    },
                )
            continue
        beats = _split_text_to_beats(narration_text, max_beat)
        for b_idx, (beat_text, beat_secs) in enumerate(beats):
            vis = (
                vis_tags[b_idx]
                if b_idx < len(vis_tags)
                else (vis_tags[-1] if vis_tags else "")
            )
            if not vis:
                vis = _default_visual_for_beat(beat_text, "", "", spoken=spoken_flag)
            builder.append_shot(
                {
                    "seq_key": seq_key,
                    "narration": beat_text,
                    "spoken": spoken_flag,
                    "seconds": beat_secs,
                    "visual": vis,
                    "camera": CAMERA_IDS[b_idx % len(CAMERA_IDS)],
                },
            )


def _derive_script_title(explicit_title: str, sequences: list[dict], scenes: list[dict]) -> str:
    if explicit_title:
        return explicit_title
    if sequences and sequences[0]["title"] and not sequences[0]["title"].startswith("Sequence "):
        return sequences[0]["title"][:60]
    if scenes:
        seed_text = scenes[0]["narration"] or scenes[0]["visual"]
        return " ".join(seed_text.split()[:6]).rstrip(".,;:!?") or "Untitled story"
    return "Untitled story"


def parse_user_script(
    raw_script: str,
    language: str = "English",
    speech_mode: str = "auto",
    pacing: str = "cinematic",
    target_seconds: int = 0,
) -> dict:
    """Deterministically parse a screenplay or plain voiceover into timed shot beats.

    Supports ``INT./EXT.`` sluglines, ``CHARACTER:`` dialogue blocks,
    ``[Visual: ...]`` brackets, and plain voiceover paragraphs.
    """
    text = (raw_script or "").replace("\r\n", "\n").strip()
    visual_grammar = (
        f"Consistent {pacing} visual grammar, natural lens depth, "
        "balanced contrast, unified color grade."
    )
    if not text:
        return {
            "title": "Untitled story",
            "brief": "",
            "visual_grammar": visual_grammar,
            "sequences": [],
            "scenes": [],
            "characters": [],
            "locations": [],
            "props": [],
        }

    lines = text.split("\n")
    explicit_title = ""
    if lines:
        tm = _TITLE_LINE_RE.match(lines[0].strip())
        if tm:
            explicit_title = tm.group(1).strip()[:120]
            lines = lines[1:]

    non_empty = [ln.strip() for ln in lines if ln.strip()]
    is_screenplay = any(
        _SLUGLINE_RE.match(ln) or _is_speaker_line(ln) for ln in non_empty
    )

    builder = _ScriptBuilder(pacing=pacing, speech_mode=speech_mode)
    if is_screenplay:
        _parse_screenplay(lines, builder)
    else:
        _parse_voiceover_paragraphs("\n".join(lines).strip(), builder)

    _apply_thirty_degree_rule(builder.scenes)

    sequences: list[dict] = []
    for key in builder.seq_order:
        seq_scenes = [s for s in builder.scenes if s["sequence"] == key]
        if not seq_scenes:
            continue
        meta = builder.seq_meta[key]
        sequences.append(
            {
                "key": key,
                "title": meta["title"],
                "summary": meta["summary"]
                or (seq_scenes[0]["narration"][:120] or seq_scenes[0]["visual"][:120]),
                "location": meta["location"],
                "cast": meta["cast"],
                "target_seconds": sum(int(s["seconds"]) for s in seq_scenes),
                "shot_count": len(seq_scenes),
            },
        )

    title = _derive_script_title(explicit_title, sequences, builder.scenes)
    total_secs = sum(int(s["seconds"]) for s in builder.scenes)
    if target_seconds and not builder.scenes:
        total_secs = int(target_seconds)
    brief = (
        f"Parsed script in {language} ({len(sequences)} sequences, "
        f"{len(builder.scenes)} shots, ~{total_secs}s)."
    )
    return {
        "title": title[:120],
        "brief": brief,
        "visual_grammar": visual_grammar,
        "sequences": sequences,
        "scenes": builder.scenes,
        "characters": builder.characters,
        "locations": builder.locations,
        "props": [],
    }


# ---------------------------------------------------------------------------
# Stage 1: Outline prompt & schema
# ---------------------------------------------------------------------------


def _blueprint_for_story(story: Story) -> dict:
    target = int(getattr(story, "target_seconds", 0) or 0)
    if target <= 0:
        target = max(1, int(story.scene_count)) * max(1, int(story.duration))
    pacing = getattr(story, "pacing", "cinematic") or "cinematic"
    video_model = getattr(story, "video_model", "") or ""
    return plan_film_blueprint(target, pacing=pacing, video_model=video_model)


def outline_prompt(story: Story, story_set: object | None = None) -> str:
    """Build Stage 1 prompt: visual grammar lock, cast, and sequence outline."""
    bp = _blueprint_for_story(story)
    style = style_of(story)
    brief = (
        f'\nBrief (from an earlier pass; improve it, keep what the user edited): """{story.brief.strip()}"""'
        if story.brief.strip()
        else ""
    )
    if story_set is not None:
        cast_block = _set_cast_rules(story_set)
        cast_json = ""
    else:
        cast_block = f"""
- Cast the film too: list everyone and everything that must look and sound
  the same in every shot. List the main character first. Write the cast in
  English.
{_cast_item_rules()}"""
        cast_json = (
            ', "characters": [{"key": str, "name": str, "description": str, '
            '"outfit": str, "voice": {"tts_voice": str, "style": str, '
            '"description": str}}], "narrator": {"tts_voice": str, "style": str} | '
            'null, "locations": [{"key": str, "name": str, "description": str, '
            '"time_of_day": str}], "props": [{"key": str, "name": str, '
            '"description": str}]'
        )

    seq_targets = ", ".join(str(c) for c in bp["shots_per_sequence"])
    return f"""Plan a {bp["estimated_seconds"]}-second film broken into exactly {bp["sequence_count"]} sequences
and {bp["scene_count"]} total shots (~{bp["duration"]}s each, pacing: {getattr(story, "pacing", "cinematic")}).
Visual style: {style["label"]}.

Idea: \"\"\"{story.idea.strip()}\"\"\"{brief}{_main_character(story, story_set)}

Rules:
- Write the title in {story.language}; write brief, visual_grammar, and sequence summaries in English.
- "visual_grammar": one concise paragraph locking the global lens family, focal length feel, lighting ratio, contrast, and color grade for the whole film.
{_speech_rules(story)}{cast_block}{_brand_rule(story)}
- "brief": 3 to 5 vivid sentences in English covering subject, audience, tone, dramatic arc, and look.
- "sequences": exactly {bp["sequence_count"]} sequences in narrative order (Act -> Sequence), with shot counts matching [{seq_targets}] and summing to {bp["scene_count"]}.
  For each sequence provide "key" ("seq1", "seq2", ...), "title", "summary", "location" (location key or name), "cast" (character keys or names), "target_seconds", and "shot_count".

Return only JSON: {{"title": str, "brief": str, "visual_grammar": str, "voice": str{cast_json}, "sequences": [{{"key": str, "title": str, "summary": str, "location": str, "cast": [str], "target_seconds": int, "shot_count": int}}]}}"""


def outline_schema(story: Story, story_set: object | None = None) -> dict:
    """Return the JSON schema for Stage 1 outline generation."""
    bp = _blueprint_for_story(story)
    seq_item = {
        "type": "object",
        "properties": {
            "key": _str(),
            "title": _str(),
            "summary": _str(),
            "location": _str(),
            "cast": _str_list(),
            "target_seconds": {"type": "integer"},
            "shot_count": {"type": "integer"},
        },
        "required": [
            "key",
            "title",
            "summary",
            "location",
            "cast",
            "target_seconds",
            "shot_count",
        ],
    }
    props = {
        "title": _str(),
        "brief": _str(),
        "visual_grammar": _str(),
        "voice": _str(),
        "sequences": {
            "type": "array",
            "minItems": bp["sequence_count"],
            "maxItems": bp["sequence_count"],
            "items": seq_item,
        },
    }
    required = ["title", "brief", "visual_grammar", "voice", "sequences"]
    if story_set is None:
        props.update(cast_schema())
        required += ["characters", "locations", "props"]
    return {"type": "object", "properties": props, "required": required}


# ---------------------------------------------------------------------------
# Stage 2: Sequence shot expansion prompt & schema
# ---------------------------------------------------------------------------


def _format_prev_tail(prev_tail: list[dict] | dict | None) -> str:
    if not prev_tail:
        return ""
    items = prev_tail if isinstance(prev_tail, list) else [prev_tail]
    lines = [
        f"  - [{s.get('shot_size', 'medium')}, {s.get('location', '')}, "
        f"transition={s.get('transition', 'cut')}] {s.get('visual', '')}"
        for s in items[-2:]
        if isinstance(s, dict)
    ]
    if not lines:
        return ""
    return (
        "\nPrevious sequence ending shot(s) (maintain continuity & 30-degree rule across the join):\n"
        + "\n".join(lines)
    )


def sequence_shots_prompt(  # noqa: PLR0913, PLR0917
    story: Story,
    seq: dict,
    seq_index: int,
    total_seqs: int,
    prev_tail: list[dict] | dict | None = None,
    story_set: object | None = None,
) -> str:
    """Build Stage 2 prompt: expand one sequence outline into exact shots."""
    style = style_of(story)
    shot_count = max(1, int(seq.get("shot_count") or 1))
    target_secs = int(seq.get("target_seconds") or shot_count * max(1, story.duration))
    avg_dur = max(_MIN_BEAT_SECONDS, round(target_secs / shot_count))
    cams = ", ".join(CAMERA_IDS)
    cam_rule = (
        f'Use the camera move "{story.camera}" for every shot.'
        if story.camera in CAMERA_IDS
        else f"Read the camera from the idea: if it says how the camera moves (for example 'the camera pans left to right slowly'), use that move, direction and speed for every shot it covers and do not change it between shots of one take. Otherwise pick the best camera move for each shot from: {cams}."
    )
    shot_sizes = ", ".join(f"{k} ({v})" for k, v in SHOT_SIZES.items())
    transitions = ", ".join(DIRECTOR_TRANSITION_IDS)

    if story_set is not None:
        cast_block = _set_cast_rules(story_set)
    elif cast_names(story):
        cast_block = (
            "\n- Reuse this fixed cast and these locations (call them by name in visuals, "
            "and use their keys in cast/location/props/speaker):\n" + cast_names(story)
        )
    else:
        cast_block = ""

    grammar = (getattr(story, "visual_grammar", "") or "").strip()
    grammar_line = f"\nVisual grammar lock: {grammar}" if grammar else ""
    brief_line = f"\nFilm brief: {story.brief.strip()}" if story.brief.strip() else ""
    tail_block = _format_prev_tail(prev_tail)

    return f"""Expand sequence {seq_index + 1} of {total_seqs} for the film "{story.title or 'Untitled story'}" into exactly {shot_count} shots
totalling about {target_secs} seconds (~{avg_dur}s per shot). Visual style: {style["label"]}.{brief_line}{grammar_line}

Sequence {seq_index + 1}: "{seq.get("title", "")}" (key: {seq.get("key", f"seq{seq_index + 1}")})
Summary: {seq.get("summary", "")}
Primary location: {seq.get("location", "")}
Cast in sequence: {", ".join(seq.get("cast") or []) or "as needed"}{tail_block}

Rules:
- Write narration in {story.language}; write visual, motion_prompt, and audio_cue in English.
- Narration fits within each shot's "seconds" at about {WORDS_PER_SECOND:g} words/sec.
{_speech_rules(story)}
- "visual": static keyframe composition ONLY (subject, pose, expression, framing, setting, lighting). Every person is {NOT_FAMOUS}. Do NOT describe camera motion or temporal progression in "visual".
- "motion_prompt": describe temporal action, blocking, and camera movement during the shot.
- "audio_cue": specific ambient soundscape, room tone, Foley, and SFX (no music; no speech on narrated shots).
- "shot_size": one of {shot_sizes}.
- 30-degree rule: consecutive "cut" shots in the same location MUST vary "shot_size" (never repeat the same shot_size back-to-back on same-location cuts). Maintain 180-degree eyeline/screen direction.
- {cam_rule}
- "transition": how this shot joins from the previous shot, one of: {transitions}.
- Also provide "cast" (character keys), "location" (location key), "props" (prop keys), and "speaker" (speaking character key or "").{cast_block}{_brand_rule(story)}

Return only JSON: {{"scenes": [{{"visual": str, "motion_prompt": str, "audio_cue": str, "shot_size": str, "camera": str, "spoken": bool, "narration": str, "seconds": int, "transition": str, "cast": [str], "location": str, "props": [str], "speaker": str}}]}}"""


def sequence_shots_schema(shot_count: int, with_links: bool = True) -> dict:
    """Return the JSON schema for Stage 2 sequence shot expansion."""
    props: dict = {
        "visual": _str(),
        "motion_prompt": _str(),
        "audio_cue": _str(),
        "shot_size": {"type": "string", "enum": list(SHOT_SIZE_IDS)},
        "camera": {"type": "string", "enum": list(CAMERA_IDS)},
        "spoken": {"type": "boolean"},
        "narration": _str(),
        "seconds": {"type": "integer"},
        "transition": {"type": "string", "enum": list(DIRECTOR_TRANSITION_IDS)},
    }
    required = [
        "visual",
        "motion_prompt",
        "audio_cue",
        "shot_size",
        "camera",
        "spoken",
        "narration",
        "seconds",
        "transition",
    ]
    if with_links:
        props.update(_links_schema())
        required += ["cast", "location", "props", "speaker"]
    count = max(1, int(shot_count))
    return {
        "type": "object",
        "properties": {
            "scenes": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        },
        "required": ["scenes"],
    }


# ---------------------------------------------------------------------------
# Stage 1 + Stage 2 merge
# ---------------------------------------------------------------------------


def merge_director_scenario(
    outline: dict,
    seq_shots: list[list[dict]],
    story: Story,
) -> dict:
    """Merge Stage 1 outline and Stage 2 per-sequence shots into one scenario JSON dict."""
    outline = dict(outline or {})
    sequences = [s for s in (outline.get("sequences") or []) if isinstance(s, dict)]
    merged_scenes: list[dict] = []

    for idx, shots in enumerate(seq_shots or []):
        seq = sequences[idx] if idx < len(sequences) else {}
        seq_key = str(seq.get("key") or f"seq{idx + 1}").strip()
        for raw in shots or []:
            if not isinstance(raw, dict):
                continue
            narration = str(raw.get("narration") or "").strip()
            if not narration or story.speech_mode == "narrator":
                spoken = False
            elif story.speech_mode == "on_camera":
                spoken = True
            else:
                spoken = bool(raw.get("spoken"))

            raw_shot_size = str(raw.get("shot_size") or "").strip().lower().replace(" ", "_")
            shot_size = raw_shot_size if raw_shot_size in SHOT_SIZE_IDS else "medium"
            raw_trans = str(raw.get("transition") or "").strip().lower()
            transition = raw_trans if raw_trans in DIRECTOR_TRANSITION_IDS else "cut"

            try:
                secs = max(1, int(float(raw.get("seconds") or story.duration)))
            except TypeError, ValueError:
                secs = int(story.duration)

            cam = (
                story.camera
                if story.camera in CAMERA_IDS
                else normalize_camera(str(raw.get("camera") or ""))
            )
            cast_list = raw.get("cast")
            if not isinstance(cast_list, list):
                cast_list = [cast_list] if cast_list else []
            props_list = raw.get("props")
            if not isinstance(props_list, list):
                props_list = [props_list] if props_list else []

            merged_scenes.append(
                {
                    "sequence": str(raw.get("sequence") or seq_key).strip(),
                    "narration": narration,
                    "spoken": spoken,
                    "seconds": secs,
                    "visual": str(raw.get("visual") or "").strip(),
                    "motion_prompt": str(raw.get("motion_prompt") or "").strip(),
                    "audio_cue": str(raw.get("audio_cue") or "").strip(),
                    "shot_size": shot_size,
                    "camera": cam,
                    "transition": transition,
                    "cast": [str(x).strip() for x in cast_list if str(x).strip()],
                    "location": str(raw.get("location") or seq.get("location") or "").strip(),
                    "props": [str(x).strip() for x in props_list if str(x).strip()],
                    "speaker": str(raw.get("speaker") or "").strip() if spoken else "",
                },
            )

    return {
        "brief": str(outline.get("brief") or story.brief or "").strip(),
        "title": str(outline.get("title") or story.title or "Untitled story").strip(),
        "voice": str(outline.get("voice") or "").strip(),
        "visual_grammar": str(
            outline.get("visual_grammar") or getattr(story, "visual_grammar", "") or "",
        ).strip(),
        "sequences": sequences,
        "characters": outline.get("characters") or [],
        "narrator": outline.get("narrator"),
        "locations": outline.get("locations") or [],
        "props": outline.get("props") or [],
        "scenes": merged_scenes,
    }
