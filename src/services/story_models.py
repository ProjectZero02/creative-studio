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
"""Story Studio data model and pure rules (no network, no Mesop).

Everything here is plain Python so it can be unit tested: the story record,
style and camera presets, scenario JSON parsing, cost caps, step rules and the
stitching plan.
"""

from __future__ import annotations

import datetime
import json
import re
import uuid
from dataclasses import asdict, dataclass, field, replace

from config.default import Default
from config.omni_models import get_omni_model_config
from config.veo_models import get_veo_model_config

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

STEPS: list[tuple[str, str, str]] = [
    # (id, label, Material icon)
    ("stories", "Stories", "collections_bookmark"),
    ("create", "Create", "edit_note"),
    ("scenario", "Scenario", "description"),
    ("set", "Set", "groups"),
    ("storyboard", "Storyboard", "view_carousel"),
    ("editor", "Scenes", "tune"),
    ("video", "Edit", "movie"),
]
STEP_IDS = [s[0] for s in STEPS]

STYLES: list[dict[str, str]] = [
    {
        "id": "photographic",
        "label": "Photographic",
        "chip": "Photo",
        # Not "cinematic film still": that pulls faces towards film actors,
        # which the video model refuses as real people.
        "prompt": "photorealistic, natural light, shallow depth of field, 35mm, candid documentary realism",
    },
    {
        "id": "2d",
        "label": "2D illustration",
        "chip": "2D",
        "prompt": "flat 2D illustration, clean line art, soft painterly shading, storybook look",
    },
    {
        "id": "3d",
        "label": "3D",
        "chip": "3D",
        "prompt": "stylized 3D animated film render, soft global illumination, rich materials",
    },
    {
        "id": "anime",
        "label": "Anime",
        "chip": "Anime",
        "prompt": "hand-drawn anime style, expressive characters, detailed painted backgrounds",
    },
    {
        "id": "claymation",
        "label": "Claymation",
        "chip": "Clay",
        "prompt": "stop-motion claymation, handmade clay figures and sets, tactile fingerprints",
    },
]
STYLE_BY_ID = {s["id"]: s for s in STYLES}


def style_of(story) -> dict:
    """The story's style preset, with its prompt replaced by the free style
    text from Setup when there is one."""
    preset = STYLE_BY_ID.get(getattr(story, "style", ""), STYLES[0])
    text = " ".join(str(getattr(story, "style_prompt", "") or "").split())[:400]
    if not text or text == preset["prompt"]:
        return preset
    return {**preset, "prompt": text}

CAMERA_PRESETS: dict[str, dict[str, str]] = {
    "auto": {"label": "Director's choice", "prompt": ""},
    "static": {"label": "Static", "prompt": "locked-off static camera"},
    "dolly_in": {
        "label": "Dolly in",
        "prompt": "slow smooth dolly in toward the subject",
    },
    "dolly_out": {
        "label": "Dolly out",
        "prompt": "slow smooth dolly out revealing the surroundings",
    },
    # Direction spelled out as what the viewer sees: "pan right" alone was
    # read either way by the video model.
    "pan_left": {
        "label": "Pan left",
        "prompt": (
            "slow, steady horizontal pan to the LEFT: the camera turns toward "
            "the left side of the scene, so everything in view slides from "
            "left to right across the frame and new things appear on the left"
        ),
    },
    "pan_right": {
        "label": "Pan right",
        "prompt": (
            "slow, steady horizontal pan to the RIGHT: the camera turns toward "
            "the right side of the scene, so everything in view slides from "
            "right to left across the frame and new things appear on the right"
        ),
    },
    "tilt_up": {
        "label": "Tilt up",
        "prompt": "gentle vertical tilt up to reveal height and scale",
    },
    "tilt_down": {
        "label": "Tilt down",
        "prompt": "gentle vertical tilt down onto the subject",
    },
    "tracking": {
        "label": "Tracking",
        "prompt": "smooth lateral tracking shot keeping pace with the subject",
    },
    "orbit": {"label": "Orbit", "prompt": "camera orbits slowly around the subject"},
    "crane_up": {"label": "Crane up", "prompt": "camera cranes up to reveal the scene"},
    "handheld": {
        "label": "Handheld",
        "prompt": "handheld camera with gentle natural shake",
    },
}
CAMERA_IDS = [k for k in CAMERA_PRESETS if k != "auto"]

SHOT_SIZES: dict[str, str] = {
    "extreme_wide": "Extreme wide shot",
    "wide": "Wide shot",
    "medium_wide": "Medium wide shot",
    "medium": "Medium shot",
    "medium_close": "Medium close-up",
    "close_up": "Close-up",
    "insert": "Insert detail shot",
}
SHOT_SIZE_IDS = list(SHOT_SIZES)

TRANSITION_TYPES: dict[str, str] = {
    "auto": "Smart (Director's choice)",
    "cut": "Clean cut (J/L audio)",
    "bridge": "Seamless bridge (First→Last frame)",
    "extend": "Continuous take (Extend)",
    "dissolve": "Cross-dissolve",
    "fade_black": "Dip to black",
}
TRANSITION_IDS = list(TRANSITION_TYPES)

PACING_MODES: dict[str, dict] = {
    "documentary": {"label": "Calm", "target_shot_seconds": 10},
    "cinematic": {"label": "Normal", "target_shot_seconds": 8},
    "dynamic": {"label": "Fast", "target_shot_seconds": 5},
}
PACING_IDS = list(PACING_MODES)

STORY_VIDEO_ENGINES: dict[str, str] = {
    "gemini-omni-1.2-flash": "Gemini Omni 1.2 Flash",
    "hybrid": "Hybrid (Omni speech + Veo 3.1 visuals)",
    "3.1-fast": "Veo 3.1 Fast",
    "3.1": "Veo 3.1",
}

LANGUAGES: dict[str, str] = {
    # label -> BCP-47 code used for TTS
    "English": "en-US",
    "Arabic": "ar-EG",
    "French": "fr-FR",
    "German": "de-DE",
    "Spanish": "es-ES",
    "Italian": "it-IT",
    "Portuguese": "pt-BR",
    "Hindi": "hi-IN",
    "Japanese": "ja-JP",
    "Korean": "ko-KR",
}

ASPECT_RATIOS = ["16:9", "9:16"]
VOICES = ["Kore", "Puck", "Charon", "Aoede", "Fenrir", "Leda", "Orus", "Zephyr"]
VOICE_GENDER = {
    "Kore": "female",
    "Puck": "male",
    "Charon": "male",
    "Aoede": "female",
    "Fenrir": "male",
    "Leda": "female",
    "Orus": "male",
    "Zephyr": "female",
}


def voice_label(name: str) -> str:
    gender = VOICE_GENDER.get(name)
    return f"{name} ({gender})" if gender else name


# Who speaks each scene's line: a narrator over the picture, or the person on
# screen (the video model renders the speech with lip sync). "auto" lets Gemini choose per
# scene from the idea, e.g. a presenter talks on camera.
SPEECH_MODES: dict[str, str] = {
    "auto": "Auto: Gemini picks per scene",
    "narrator": "Narrator voiceover",
    "on_camera": "People speak on camera",
}
SPEECH_HINTS: dict[str, str] = {
    "auto": "Gemini has the person on screen speak when the idea calls for it "
    "(a presenter, an interview, a conversation) and uses a narrator otherwise. "
    "You can switch any scene later.",
    "narrator": "A narrator speaks over every scene. Nobody on screen talks.",
    "on_camera": "The person on screen says every line, lips in sync. "
    "No narrator.",
}
# Speech pace used to warn about lines that will not fit a scene.
WORDS_PER_SECOND = 2.5


def max_words(duration: int | float) -> int:
    """Roughly how many spoken words fit in a scene of `duration` seconds."""
    return max(1, int(float(duration) * WORDS_PER_SECOND))


# Scene lengths offered (seconds). Up to the model's single-clip limit a
# scene is one clip; longer scenes are extended (see clip_parts).
SCENE_LENGTHS = (4, 6, 8, 10, 12, 15, 20, 25, 30)
# Each Omni extension turn adds this many seconds.
EXTEND_MIN_SECONDS = 3
EXTEND_MAX_SECONDS = 10


def _video_model_spec(model_id: str | None = None):
    """Resolve Omni or Veo model configuration for Story Studio."""
    mid = (model_id or "").strip() or Default().STORY_VIDEO_MODEL
    if mid == "hybrid":
        return get_omni_model_config("gemini-omni-1.2-flash"), True
    omni = get_omni_model_config(mid)
    if omni:
        return omni, "extend" in omni.supported_modes
    veo = get_veo_model_config(mid)
    if not veo and mid.startswith("veo-"):
        from config.veo_models import get_version_id_by_model_name

        vid = get_version_id_by_model_name(mid)
        veo = get_veo_model_config(vid) if vid else None
    if veo:
        return veo, bool(veo.supports_video_extension)
    return None, False


def single_clip_max(model_id: str | None = None) -> int:
    """Longest clip the story video model makes in one request."""
    model, _ = _video_model_spec(model_id)
    return model.max_duration if model else 8


def supported_durations(model_id: str | None = None) -> list[int]:
    """Scene lengths (seconds) the configured story video model can make:
    its own clip range, plus longer scenes up to STORY_MAX_SCENE_SECONDS when
    it can extend a clip."""
    model, can_extend = _video_model_spec(model_id)
    if not model:
        return [4, 6, 8]
    top = model.max_duration
    if can_extend:
        top = max(top, Default().STORY_MAX_SCENE_SECONDS)
    return [d for d in SCENE_LENGTHS if model.min_duration <= d <= top]


def split_narration_parts(text: str, parts: list[int]) -> list[str]:
    """Split `text` across `parts` durations proportionally without repeating words.

    Prefers sentence and clause boundaries so multi-part Omni/Veo extensions
    deliver continuous dialogue instead of repeating the full line on every turn.
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(parts) <= 1:
        return [cleaned]
    words = cleaned.split(" ") if cleaned else []
    if not words:
        return ["" for _ in parts]
    out: list[str] = []
    idx = 0
    for k, sec in enumerate(parts):
        if k == len(parts) - 1:
            out.append(" ".join(words[idx:]).strip())
            break
        remaining_words = len(words) - idx
        if remaining_words <= 0:
            out.append("")
            continue
        rem_sec = sum(max(1, int(p)) for p in parts[k:])
        target = max(1, round(remaining_words * max(1, int(sec)) / max(1, rem_sec)))
        end = min(len(words), idx + target)
        # Prefer landing on a sentence or clause boundary within +/- 3 words.
        best = end
        for offset in range(-3, 4):
            cand = end + offset
            if idx < cand <= len(words):
                w = words[cand - 1]
                if w.endswith((".", "!", "?", "؟", "…")):
                    best = cand
                    break
                if w.endswith((",", ";", ":", "،")) and best == end:
                    best = cand
        out.append(" ".join(words[idx:best]).strip())
        idx = best
    return out


def clip_parts(seconds: int, single_max: int | None = None) -> list[int]:
    """How a scene of `seconds` is made: the first clip, then extension
    turns, all as even as possible. Omni extends at most EXTEND_MAX_SECONDS
    a turn and reads the last 10 s, so even 10 s parts keep every turn's
    script and action the same size: 30 -> [10, 10, 10], 20 -> [10, 10],
    25 -> [9, 8, 8], 16 -> [8, 8] (with a 15 s single-clip limit)."""
    seconds = int(seconds)
    top = single_clip_max() if single_max is None else single_max
    if seconds <= top:
        return [seconds]
    step = max(EXTEND_MIN_SECONDS, min(int(top), EXTEND_MAX_SECONDS))
    turns = max(2, -(-seconds // step))
    base, extra = divmod(seconds, turns)
    return [base + (1 if i < extra else 0) for i in range(turns)]


def record_turns(
    parts: list[int],
    lines: list[str] | None = None,
    prompts: list[str] | None = None,
    ids: list[str] | None = None,
    uris: list[str] | None = None,
) -> str:
    """JSON for `Scene.turns_json`: one record per turn, with its start
    offset in the clip, so a cut found in the take maps to its turn, and
    the turn's own video, so a later turn can be made again from it."""
    records, start = [], 0
    for i, seconds in enumerate(parts):
        records.append(
            {
                "seconds": int(seconds),
                "start": start,
                "lines": (lines[i] if lines and i < len(lines) else ""),
                "interaction_id": (ids[i] if ids and i < len(ids) else ""),
                "prompt": (prompts[i] if prompts and i < len(prompts) else ""),
                "uri": (uris[i] if uris and i < len(uris) else ""),
            }
        )
        start += int(seconds)
    return json.dumps(records)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Scene:
    """One scene of a story. Media are URIs (gs:// or local://), never bytes."""

    id: str = field(default_factory=new_id)
    narration: str = ""
    visual: str = ""
    camera: str = "static"
    duration: int = 6
    frame_uri: str = ""
    clip_uri: str = ""
    # clip_uri of the previous scene this clip was animated from (its last
    # frame was the start frame). Empty when the clip started from its own
    # storyboard frame. Lets the stitcher tell which joins really match.
    continues_from: str = ""
    # The same line in the story's second language (see Story.second_on).
    narration_alt: str = ""
    # True: the person on screen says `narration` to camera (the video model renders the
    # speech in the clip). False: a narrator voices it over the picture.
    spoken: bool = False
    # Second-language clip of a spoken scene (the speech is baked into the
    # video, so it is rendered again) and the clip and line it was made from.
    clip_alt_uri: str = ""
    clip_alt_key: str = ""
    # Clip whose last frame the second-language clip started from (the
    # previous scene's clip in that film), like continues_from.
    clip_alt_from: str = ""
    # Continuous take: this clip continues the previous scene's clip in the
    # same Gemini Omni thread, so it is the same shot, person and voice. If
    # the model returns the joined video, its first `clip_in` seconds repeat
    # the previous clip and are cut by the timeline.
    extends_from: str = ""
    clip_in: float = 0.0
    # Gemini Omni interaction that made clip_uri (the next scene of a take
    # continues from it). Stored interactions expire after about a week.
    interaction_id: str = ""
    # Set assets in this scene (services/story_sets.py): the characters on
    # screen, the location and props, and who says a spoken line.
    cast: list[str] = field(default_factory=list)
    location_id: str = ""
    prop_ids: list[str] = field(default_factory=list)
    speaker_id: str = ""
    # Director v3 cinematography & seamless join metadata.
    sequence: str = ""
    shot_size: str = "medium"
    motion_prompt: str = ""
    audio_cue: str = ""
    transition: str = "auto"  # auto | cut | bridge | extend | dissolve | fade_black
    bridged_to: str = ""  # frame_uri of next scene used as last_frame
    video_model_used: str = ""
    # One record per Omni turn of this clip (see `record_turns`): seconds,
    # start offset, lines, interaction ID and the prompt sent.
    turns_json: str = ""

    def clear_clip(self) -> None:
        """Forget the clip and everything made from it (take, Omni thread)."""
        self.clip_uri = self.extends_from = self.interaction_id = ""
        self.bridged_to = self.video_model_used = self.turns_json = ""
        self.clip_in = 0.0

    def turns(self) -> list[dict]:
        try:
            data = json.loads(self.turns_json or "[]")
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    def turn_at(self, seconds: float) -> int:
        """Index of the turn playing at `seconds` into the clip (0 if unknown)."""
        index = 0
        for i, turn in enumerate(self.turns()):
            if float(turn.get("start", 0)) <= seconds:
                index = i
        return index

    def alt_clip_key(self) -> str:
        """What a second-language clip must match to still be current."""
        return f"{self.clip_uri}|{self.narration_alt}"

    def has_alt_clip(self) -> bool:
        return bool(self.clip_alt_uri) and self.clip_alt_key == self.alt_clip_key()

    def line_too_long(self) -> bool:
        return len(self.narration.split()) > max_words(self.duration)


@dataclass
class Story:
    """A saved story. Stored in Firestore `stories` (or the local JSON store)."""

    id: str = field(default_factory=new_id)
    owner: str = ""
    title: str = ""
    idea: str = ""
    # Gemini's fuller film brief written from the idea (on the first
    # scenario); later scenario rewrites work from it. Editable.
    brief: str = ""
    language: str = "English"
    scene_count: int = 4
    duration: int = 6
    aspect_ratio: str = "16:9"
    style: str = "photographic"
    camera: str = "auto"
    reference_uri: str = ""
    character: str = ""
    scenes: list[Scene] = field(default_factory=list)
    step: str = "create"
    approved: bool = False
    music_on: bool = True
    music_prompt: str = ""
    voice_on: bool = True
    voice_name: str = "Kore"
    # The idea asks for one continuous shot: the film is as few long takes
    # as fit, they run on without a cut, and the film is trimmed to
    # target_seconds when stitched (story_director.is_one_take).
    one_take: bool = False
    continuity: bool = False
    # With continuity on, join scenes that really continue each other with a
    # straight cut instead of a crossfade (a crossfade there double-exposes the
    # same moment twice). Has no effect when continuity is off.
    seamless_joins: bool = True
    final_uri: str = ""
    # The timeline was edited after final_uri was made: Download still gives
    # the old film until the edit is exported.
    film_edited: bool = False
    # The story and its set before the last AI fix (JSON), for undo.
    fix_undo_json: str = ""
    # The last films with their timelines, newest first (services/story_versions.py).
    film_versions_json: str = ""
    # Subtitled downloads (services/story_subtitles.py). The main film has no
    # captions; each variant ("en", "ar", "en+ar") is rendered on request.
    subtitle_style: str = "clean"
    # {"en": {"key": source hash, "lines": [one per scene]}, "ar": {...}}
    subtitle_lines_json: str = ""
    # {"en": {"uri": film, "key": what it was made from}, ...}
    film_variants_json: str = ""
    # The timeline final_uri was made from, and that film's URI (when the
    # film changes elsewhere, the timeline at the first edit is its source).
    # "Edited since the last export" compares the current edit with it.
    film_timeline_json: str = ""
    film_timeline_uri: str = ""
    # Preview: a fast, small render of the current timeline (proxy_key is
    # the hash of what it shows, see story_jobs.proxy_key).
    proxy_uri: str = ""
    proxy_key: str = ""
    # Files made from the Export menu: {option key: {"uri", "name", "tl"}}.
    exports_json: str = ""
    # A copy of the owner's brand kit (common/brand_kit.py) when "Use my brand
    # kit" was on at Create: colours and tone go into the prompts, the logo
    # into the exported film.
    brand_json: str = ""
    # The saved brand the snapshot above came from ("" = no brand). The film
    # keeps the snapshot even if that brand changes later.
    brand_id: str = ""
    # Free style text from Setup ("" = the preset's own text, see style_of).
    style_prompt: str = ""
    # Video resolution for this story ("" = STORY_VIDEO_RESOLUTION).
    resolution: str = ""
    # Setup references (JSON list of {kind, tag, role, uri, voice}): turned
    # into set assets at Create so @tags in the idea link to them.
    references_json: str = ""
    # Second-language version: same clips and music, narration translated
    # into alt_language and voiced again. Needs the voiceover on.
    second_on: bool = False
    # Who speaks (SPEECH_MODES) and the on-screen speaker's voice, described
    # the same way in every spoken clip so it stays consistent.
    speech_mode: str = "auto"
    speaker_voice: str = ""
    # Back-to-back spoken scenes continue the previous clip (one Omni thread),
    # so the person, shot and voice carry on. Those clips render in order.
    continuous_takes: bool = True
    # One seed for every clip of the film (0: pick one on first render).
    seed: int = 0
    # Music made for the film (kept for the editor and re-exports).
    music_uri: str = ""
    # The editable film (services/story_timeline.py), written by the render
    # and changed in the Edit step.
    timeline_json: str = ""
    # Language spoken in the clips when it differs from `language` (set on
    # the dubbed second-language copy, whose clips speak the original).
    clip_language: str = ""
    title_alt: str = ""
    final_alt_uri: str = ""
    # The set this story uses ("" = none) and the set version its film was
    # rendered with (0 = not rendered with a set yet).
    set_id: str = ""
    set_version: int = 0
    # The cast, places and props the scenario call wrote (JSON, with each
    # scene's links by scene id), kept until the Set step turns them into a
    # set. "" when the story has a set or the writer gave no cast.
    cast_json: str = ""
    # Director v3 fields: script input, multi-minute targets, engine & visual lock.
    input_mode: str = "idea"  # "idea" | "script"
    raw_script: str = ""
    target_seconds: int = 0  # 0 = scene_count * duration; >0 = target film runtime
    pacing: str = "cinematic"  # "dynamic" | "cinematic" | "documentary"
    video_model: str = ""  # "" = STORY_VIDEO_MODEL; else "hybrid", "3.1-fast", "3.1", ...
    visual_grammar: str = ""  # global lens, lighting ratio, colour grade lock
    sequences_json: str = ""  # JSON list of sequence outlines for long films
    color_match: bool = True
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @property
    def cover_uri(self) -> str:
        for s in self.scenes:
            if s.frame_uri:
                return s.frame_uri
        return ""

    @property
    def alt_language(self) -> str:
        """Language of the second version: English for Arabic, else Arabic."""
        return other_language(self.language)

    @property
    def has_spoken(self) -> bool:
        return any(sc.spoken and sc.narration.strip() for sc in self.scenes)

    @property
    def makes_alt(self) -> bool:
        """True when a render should also make the second-language film:
        there is a voiceover or an on-camera line to translate."""
        return self.second_on and (self.voice_on or self.has_spoken)

    def needs_translation(self) -> bool:
        """Some narrated scene has no second-language line yet."""
        return any(sc.narration.strip() and not sc.narration_alt.strip() for sc in self.scenes)

    def clear_films(self) -> None:
        """Forget both rendered films (call when anything they used changes)."""
        self.final_uri = ""
        self.final_alt_uri = ""

    def _spoken_pair(self, index: int) -> bool:
        if index <= 0 or index >= len(self.scenes):
            return False
        prev, sc = self.scenes[index - 1], self.scenes[index]
        return bool(prev.spoken and prev.narration.strip()) and bool(
            sc.spoken and sc.narration.strip()
        )

    def _wants_take(self, index: int) -> bool:
        """Scene `index` should carry on the previous scene's shot: its join
        is set to Extend, or left on Auto between two spoken scenes. Cut,
        Bridge, Dissolve and Fade black always start a new shot."""
        if index <= 0 or index >= len(self.scenes):
            return False
        trans = (self.scenes[index].transition or "auto").strip().lower()
        if trans == "extend":
            return True
        return trans == "auto" and self._spoken_pair(index)

    def continues_take(self, index: int) -> bool:
        """Scene `index` continues the previous clip (a continuous take):
        continuous takes are on and the scene wants to (see `_wants_take`).
        While the take is at most STORY_TAKE_CONTEXT_SECONDS long and stays
        within STORY_TAKE_MAX_SECONDS, the model returns the whole take in
        one file. Past that the take rolls on (each extension returns the
        last STORY_TAKE_CONTEXT_SECONDS plus the new seconds, and the film
        joins the files inside that overlap) up to
        STORY_TAKE_ROLLING_MAX_SECONDS, for scenes short enough to fit the
        new seconds of one extension."""
        if not self.continuous_takes or not self._wants_take(index):
            return False
        cfg = Default()
        cap = cfg.STORY_TAKE_MAX_SECONDS
        context = getattr(cfg, "STORY_TAKE_CONTEXT_SECONDS", cap)
        rolling_max = getattr(cfg, "STORY_TAKE_ROLLING_MAX_SECONDS", cap)
        single = single_clip_max()
        take = 0.0
        for i in range(index + 1):
            d = float(self.scenes[i].duration)
            whole = take <= context and take + d <= cap
            rolls = take + d <= rolling_max and d <= cap - context
            # A scene longer than one clip is extended in its own thread.
            joins = i > 0 and self._wants_take(i) and d <= single and (whole or rolls)
            take = take + d if joins else d
            if i == index:
                return joins
        return False

    def take_start(self, index: int) -> int:
        """First scene of the continuous take that scene `index` belongs to."""
        while index > 0 and self.continues_take(index):
            index -= 1
        return index

    def media_uris(self) -> list[str]:
        """Every stored media URI this story points at (empty ones skipped)."""
        uris = [self.reference_uri, self.final_uri, self.final_alt_uri, self.music_uri]
        for sc in self.scenes:
            uris += [sc.frame_uri, sc.clip_uri]
        return [u for u in uris if u]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Story:
        data = dict(data or {})
        scenes = [
            Scene(**{k: v for k, v in sc.items() if k in Scene.__dataclass_fields__})
            for sc in data.pop("scenes", []) or []
            if isinstance(sc, dict)
        ]
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        story = cls(**known)
        story.scenes = scenes
        return story

    def touch(self) -> None:
        self.updated_at = _now_iso()


def scenes_to_json(scenes: list[Scene]) -> str:
    return json.dumps([asdict(s) for s in scenes])


def scenes_from_json(text: str) -> list[Scene]:
    if not text:
        return []
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    return [
        Scene(**{k: v for k, v in sc.items() if k in Scene.__dataclass_fields__})
        for sc in raw
        if isinstance(sc, dict)
    ]


# ---------------------------------------------------------------------------
# Cost caps
# ---------------------------------------------------------------------------


@dataclass
class Caps:
    scene_count: int
    duration: int
    resolution: str
    notes: list[str] = field(default_factory=list)


# Resolutions offered in Setup, lowest first.
# 360p is a cheap draft (about a third of 720p on the price list).
STORY_RESOLUTIONS = ("360p", "720p", "1080p", "4k")
RESOLUTION_LABELS = {"360p": "360p draft", "720p": "720p", "1080p": "1080p", "4k": "4K"}


def resolution_options(model_id: str | None = None) -> list[str]:
    """Resolutions the story video model can make (from config/omni_models.py
    or config/veo_models.py), limited to STORY_RESOLUTIONS."""
    model, _ = _video_model_spec(model_id)
    have = set(getattr(model, "resolutions", None) or ["720p"])
    out = [r for r in STORY_RESOLUTIONS if r in have]
    return out or ["720p"]


def story_resolution(story) -> str:
    """The resolution clips of this story are made at: the story's own
    choice when its engine allows it, else STORY_VIDEO_RESOLUTION."""
    wanted = (getattr(story, "resolution", "") or "").strip().lower()
    if wanted and wanted in resolution_options(getattr(story, "video_model", "")):
        return wanted
    return Default().STORY_VIDEO_RESOLUTION


def take_groups(story) -> list[list[int]]:
    """Scene indices grouped by continuous take, in order. A take has one
    start frame; later scenes of a take continue its clip."""
    groups: list[list[int]] = []
    for i in range(len(story.scenes)):
        if groups and story.continues_take(i):
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def frame_scenes(story) -> list[int]:
    """Scenes that need their own painted frame: the first scene of each
    take. Scenes that continue a take start from the take's clip."""
    return [g[0] for g in take_groups(story)]


def frame_for(story, index: int) -> str:
    """The frame shown for scene ``index``: its own, else its take's."""
    if not 0 <= index < len(story.scenes):
        return ""
    own = story.scenes[index].frame_uri
    if own:
        return own
    return story.scenes[story.take_start(index)].frame_uri


def frames_ready(story) -> bool:
    """Every take has its start frame (what Make film needs)."""
    return bool(story.scenes) and all(
        story.scenes[i].frame_uri for i in frame_scenes(story)
    )


def nearest_duration(duration: int, model_id: str | None = None) -> int:
    allowed = supported_durations(model_id)
    return min(allowed, key=lambda d: (abs(d - int(duration)), d))


def apply_caps(
    scene_count: int,
    duration: int,
    resolution: str | None = None,
    model_id: str | None = None,
) -> Caps:
    """Clamp a film request to the configured guardrails.

    Scene count is clamped to [STORY_MIN_SCENES, STORY_MAX_SCENES], duration
    snaps to a supported clip length, and the total length must fit
    STORY_MAX_FILM_SECONDS (scenes are dropped from the end if it does not).
    """
    cfg = Default()
    notes: list[str] = []
    limit = cfg.STORY_MAX_FILM_SECONDS
    n0 = max(cfg.STORY_MIN_SCENES, min(cfg.STORY_MAX_SCENES, int(scene_count)))
    if n0 != int(scene_count):
        notes.append(f"Scenes limited to {n0}.")
    d0 = nearest_duration(duration, model_id)
    if d0 != int(duration):
        notes.append(f"Scene length set to {d0}s (supported by the video model).")
    n, d = n0, d0
    while n * d > limit and n > cfg.STORY_MIN_SCENES:
        n -= 1
    if n * d > limit:
        fitting = [x for x in supported_durations(model_id) if n * x <= limit]
        d = max(fitting) if fitting else min(supported_durations(model_id))
    if n != n0 or d != d0:
        notes.append(f"Film capped at {limit}s: {n} scenes of {d}s.")
    res = cfg.STORY_VIDEO_RESOLUTION
    if resolution:
        if resolution in resolution_options(model_id):
            res = resolution
        else:
            notes.append(f"Resolution set to {res}.")
    return Caps(scene_count=n, duration=d, resolution=res, notes=notes)


# ---------------------------------------------------------------------------
# Scenario parsing
# ---------------------------------------------------------------------------


# A line may run this far past its scene's word budget before it counts as
# too long (speech pace varies; a word or two over still fits).
NARRATION_SLACK = 1.15


class ScenarioError(ValueError):
    """The model's scenario could not be used."""


_CAMERA_ALIASES = {
    "dolly": "dolly_in",
    "dolly in": "dolly_in",
    "dolly-in": "dolly_in",
    "push in": "dolly_in",
    "push-in": "dolly_in",
    "zoom in": "dolly_in",
    "dolly out": "dolly_out",
    "dolly-out": "dolly_out",
    "pull out": "dolly_out",
    "pull back": "dolly_out",
    "zoom out": "dolly_out",
    "pan left": "pan_left",
    "pan right": "pan_right",
    "tilt up": "tilt_up",
    "tilt down": "tilt_down",
    "tracking": "tracking",
    "track": "tracking",
    "follow": "tracking",
    "orbit": "orbit",
    "arc": "orbit",
    "crane": "crane_up",
    "crane up": "crane_up",
    "crane-up": "crane_up",
    "pedestal up": "crane_up",
    "handheld": "handheld",
    "hand-held": "handheld",
    "static": "static",
    "locked": "static",
    "locked off": "static",
}


def normalize_camera(value: str | None, default: str = "static") -> str:
    v = (value or "").strip().lower().replace("_", " ")
    if v.replace(" ", "_") in CAMERA_IDS:
        return v.replace(" ", "_")
    if v in _CAMERA_ALIASES:
        return _CAMERA_ALIASES[v]
    for alias, cam in _CAMERA_ALIASES.items():
        if alias in v:
            return cam
    return default


class NarrationTooLong(ScenarioError):
    """Narrated lines that cannot be spoken within their scene."""

    def __init__(self, scenes: list[int]):
        self.scenes = scenes
        listed = ", ".join(str(n) for n in scenes)
        super().__init__(f"The narration of scene {listed} is too long for its length.")

    def note(self) -> str:
        """What the writer is told on the retry."""
        listed = " and ".join(str(n) for n in self.scenes)
        return (
            f"In the last try the narration of scene {listed} was too long to "
            "be spoken in its scene. Keep every line within its word limit."
        )


def _words(text: str) -> int:
    return len(text.split())


def fits_narration(words: int, seconds: int | float) -> bool:
    """`words` can be spoken within a scene of `seconds`."""
    return words <= max_words(seconds) * NARRATION_SLACK + 1


def _fit_lengths(scenes: list[Scene]) -> list[int]:
    """Stretch spoken scenes whose line is too long to the shortest length
    that fits (spoken scenes may run longer). Returns the 1-based numbers
    of narrated scenes that still do not fit."""
    long: list[int] = []
    lengths = supported_durations()
    for n, sc in enumerate(scenes, start=1):
        words = _words(sc.narration)
        if not words or fits_narration(words, sc.duration):
            continue
        if sc.spoken:
            fits = [d for d in lengths if d >= sc.duration and fits_narration(words, d)]
            sc.duration = min(fits) if fits else max([sc.duration, *lengths])
            continue
        long.append(n)
    return long


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_scenario(
    text: str,
    scene_count: int,
    duration: int,
    camera_preset: str = "auto",
    speech_mode: str = "auto",
    strict_length: bool = False,
) -> tuple[str, list[Scene]]:
    """Parse and validate the model's scenario JSON.

    Expected shape: {"title": str, "voice": str,
    "scenes": [{"narration", "spoken", "visual", "camera"}]}.
    ``speech_mode`` "narrator" or "on_camera" overrides each scene's "spoken".
    Extra scenes are dropped; too few or empty scenes raise ScenarioError.
    A fixed camera preset (not "auto") overrides each scene's camera.
    A spoken scene whose line is too long is stretched to fit. With
    ``strict_length`` a narrated line that is too long raises
    NarrationTooLong (the caller retries with its note).
    """
    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The scenario was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ScenarioError("The scenario must be a JSON object.")
    title = str(data.get("title") or "").strip() or "Untitled story"
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ScenarioError("The scenario has no scenes.")
    scenes: list[Scene] = []
    for raw in raw_scenes[:scene_count]:
        if not isinstance(raw, dict):
            raise ScenarioError("Each scene must be an object.")
        narration = str(raw.get("narration") or raw.get("voiceover") or "").strip()
        visual = str(
            raw.get("visual")
            or raw.get("visual_description")
            or raw.get("description")
            or ""
        ).strip()
        if not visual:
            raise ScenarioError(f"Scene {len(scenes) + 1} has no visual description.")
        camera = (
            camera_preset
            if camera_preset in CAMERA_IDS
            else normalize_camera(
                str(raw.get("camera") or raw.get("camera_move") or "")
            )
        )
        spoken = _spoken(raw.get("spoken"), narration, speech_mode)
        raw_shot = (
            str(raw.get("shot_size") or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        shot_size = raw_shot if raw_shot in SHOT_SIZE_IDS else "medium"
        raw_trans = (
            str(raw.get("transition") or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        transition = raw_trans if raw_trans in TRANSITION_IDS else "auto"
        scenes.append(
            Scene(
                narration=narration,
                visual=visual,
                camera=camera,
                duration=_spoken_length(raw.get("seconds"), duration)
                if spoken
                else duration,
                spoken=spoken,
                sequence=str(raw.get("sequence") or "").strip(),
                shot_size=shot_size,
                motion_prompt=str(raw.get("motion_prompt") or "").strip(),
                audio_cue=str(raw.get("audio_cue") or "").strip(),
                transition=transition,
            )
        )
    if len(scenes) < scene_count:
        raise ScenarioError(f"Expected {scene_count} scenes, got {len(scenes)}.")
    long = _fit_lengths(scenes)
    if long and strict_length:
        raise NarrationTooLong(long)
    if sum(s.duration for s in scenes) > Default().STORY_MAX_FILM_SECONDS:
        for s in scenes:
            s.duration = duration
    return title[:120], scenes


def _spoken_length(raw, duration: int) -> int:
    """A spoken scene may run longer than the film's scene length (the writer
    gives it "seconds"), so a speech fits in one or two takes. Never shorter."""
    try:
        seconds = int(float(raw))
    except (TypeError, ValueError):
        return duration
    return max(duration, nearest_duration(seconds)) if seconds > duration else duration


def _spoken(raw, narration: str, speech_mode: str) -> bool:
    if not narration:
        return False
    if speech_mode == "narrator":
        return False
    if speech_mode == "on_camera":
        return True
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "yes", "1", "on camera")
    return bool(raw)


def parse_brief(text: str) -> str:
    """The scenario's improved "brief" of the idea, or "" if missing."""
    try:
        data = json.loads(_strip_fences(text))
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("brief") or "").strip()[:1500]


def parse_voice(text: str) -> str:
    """The scenario's "voice" (the on-screen speaker), or "" if missing."""
    try:
        data = json.loads(_strip_fences(text))
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("voice") or "").strip()[:200]


def parse_visual_grammar(text: str) -> str:
    """The scenario's "visual_grammar" (lens, lighting, color grade), or "" if missing."""
    data = _json_dict(text)
    return str(data.get("visual_grammar") or "").strip()[:600]


def parse_sequences(text: str) -> str:
    """The scenario's "sequences" outline list serialized as JSON, or "" if missing."""
    data = _json_dict(text)
    seqs = data.get("sequences")
    if not isinstance(seqs, list):
        return ""
    cleaned = [s for s in seqs if isinstance(s, dict)]
    return json.dumps(cleaned) if cleaned else ""


def parse_single_scene(
    text: str, duration: int, camera_preset: str = "auto", speech_mode: str = "auto"
) -> Scene:
    """Parse one regenerated scene: {"narration", "spoken", "visual", "camera"}."""
    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The scene was not valid JSON.") from exc
    if (
        isinstance(data, dict)
        and isinstance(data.get("scenes"), list)
        and data["scenes"]
    ):
        data = data["scenes"][0]
    if not isinstance(data, dict):
        raise ScenarioError("The scene must be a JSON object.")
    _, scenes = parse_scenario(
        json.dumps({"title": "x", "scenes": [data]}),
        1,
        duration,
        camera_preset,
        speech_mode,
    )
    return scenes[0]


# ---------------------------------------------------------------------------
# Sets: auto-build parser and scene links (models in services/story_sets.py)
# ---------------------------------------------------------------------------

# Cost guardrails for an auto-built set (about 4 images per character, 2 per
# location and 1 per prop).
SET_MAX_CHARACTERS = 4
SET_MAX_LOCATIONS = 3
SET_MAX_PROPS = 3


def _text(raw, limit: int = 400) -> str:
    return str(raw or "").strip()[:limit]


def _as_list(raw) -> list:
    if isinstance(raw, str):
        return [raw]
    return raw if isinstance(raw, list) else []


def _resolver(story_set) -> dict[str, dict[str, str]]:
    """Lower-case id and name of every asset -> its id, per kind."""
    out: dict[str, dict[str, str]] = {"character": {}, "location": {}, "prop": {}}
    for kind, table in out.items():
        for a in story_set.assets(kind):
            for alias in (a.id, a.name):
                if alias:
                    table.setdefault(alias.strip().lower(), a.id)
    return out


def _resolve(table: dict[str, str], value) -> str:
    return table.get(str(value or "").strip().lower(), "")


def parse_scene_links(text: str, story_set, scenes: list[Scene], keys=None) -> None:
    """Tag `scenes` with set ids from the model's per-scene "cast",
    "location", "props" and "speaker" (each a key, an id or a name).

    Unknown names are dropped. A spoken scene whose speaker is unknown gets
    its first cast member. Scenes the JSON leaves out keep what they have.
    `keys` maps the model's own keys (e.g. "c1") to asset ids, per kind.
    """
    try:
        data = json.loads(_strip_fences(text))
    except ValueError:
        return
    rows = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return
    table = _resolver(story_set)
    for kind, mapping in (keys or {}).items():
        for key, asset_id in mapping.items():
            table[kind][key.strip().lower()] = asset_id
    on_screen = {c.id for c in story_set.on_screen()}
    for sc, raw in zip(scenes, rows, strict=False):
        if not isinstance(raw, dict):
            continue
        cast: list[str] = []
        for c in _as_list(raw.get("cast")):
            cid = _resolve(table["character"], c)
            if cid in on_screen and cid not in cast:
                cast.append(cid)
        props: list[str] = []
        for pr in _as_list(raw.get("props") or raw.get("prop_ids")):
            pid = _resolve(table["prop"], pr)
            if pid and pid not in props:
                props.append(pid)
        sc.cast = cast
        sc.location_id = _resolve(
            table["location"], raw.get("location") or raw.get("location_id")
        )
        sc.prop_ids = props
        sc.speaker_id = ""
        if sc.spoken:
            speaker = _resolve(table["character"], raw.get("speaker"))
            if speaker not in on_screen:
                speaker = cast[0] if cast else ""
            if speaker and speaker not in sc.cast:
                sc.cast.insert(0, speaker)
            sc.speaker_id = speaker


def parse_set_build(text: str, story: Story):
    """Parse the auto-build JSON into a new StorySet (no images yet) and tag
    the story's scenes with its ids. Raises ScenarioError when unusable.

    Expected shape: {"name", "characters": [{"key", "name", "description",
    "outfit", "voice": {"tts_voice", "style", "description"}}], "narrator":
    {"tts_voice", "style"} | null, "locations": [{"key", "name",
    "description", "time_of_day"}], "props": [{"key", "name", "description"}],
    "scenes": [{"cast": [key], "location": key, "props": [key], "speaker": key}]}.
    """
    from services.story_sets import (
        Character,
        Location,
        Prop,
        StorySet,
        Voice,
        ensure_views,
    )

    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The set was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ScenarioError("The set must be a JSON object.")
    keys: dict[str, dict[str, str]] = {"character": {}, "location": {}, "prop": {}}

    def rows(name: str, limit: int) -> list[dict]:
        return [r for r in _as_list(data.get(name)) if isinstance(r, dict)][:limit]

    def remember(kind: str, raw: dict, asset_id: str) -> None:
        for alias in (raw.get("key"), raw.get("id")):
            if alias:
                keys[kind][_text(alias, 60).lower()] = asset_id

    characters = []
    for i, raw in enumerate(rows("characters", SET_MAX_CHARACTERS)):
        name = _text(raw.get("name"), 60)
        if not name:
            continue
        v = raw.get("voice") if isinstance(raw.get("voice"), dict) else {}
        voice = Voice(
            tts_voice=_text(v.get("tts_voice"), 20),
            style=_text(v.get("style"), 200),
            description=_text(
                v.get("description") or raw.get("voice_description"), 200
            ),
        )
        if voice.tts_voice not in VOICES:
            voice.tts_voice = VOICES[i % len(VOICES)]
        c = Character(
            name=name,
            description=_text(raw.get("description") or raw.get("look")),
            outfit=_text(raw.get("outfit"), 200),
            voice=voice,
        )
        ensure_views(c)
        remember("character", raw, c.id)
        characters.append(c)
    narrator = data.get("narrator")
    if isinstance(narrator, dict) and any(
        sc.narration.strip() and not sc.spoken for sc in story.scenes
    ):
        tts = _text(narrator.get("tts_voice"), 20)
        characters.append(
            Character(
                name="Narrator",
                narrator=True,
                voice=Voice(
                    tts_voice=tts if tts in VOICES else story.voice_name,
                    style=_text(narrator.get("style"), 200)
                    or "Narrate warmly and clearly, like a short film voiceover.",
                ),
            )
        )
    locations = []
    for raw in rows("locations", SET_MAX_LOCATIONS):
        name = _text(raw.get("name"), 60)
        if not name:
            continue
        loc = Location(
            name=name,
            description=_text(raw.get("description")),
            time_of_day=_text(raw.get("time_of_day"), 40),
        )
        ensure_views(loc)
        remember("location", raw, loc.id)
        locations.append(loc)
    props = []
    for raw in rows("props", SET_MAX_PROPS):
        name = _text(raw.get("name"), 60)
        if not name:
            continue
        prop = Prop(name=name, description=_text(raw.get("description")))
        ensure_views(prop)
        remember("prop", raw, prop.id)
        props.append(prop)
    if not any(not c.narrator for c in characters) and not locations:
        raise ScenarioError("The set has no characters or locations.")
    story_set = StorySet(
        name=_text(data.get("name"), 60) or f"{story.title or 'Story'} set",
        style=story.style,
        characters=characters,
        locations=locations,
        props=props,
        created_from="auto",
    )
    parse_scene_links(text, story_set, story.scenes, keys)
    return story_set


_CAST_PARTS = ("characters", "narrator", "locations", "props")
_LINK_FIELDS = ("cast", "location", "props", "speaker")


def _json_dict(text: str) -> dict:
    try:
        data = json.loads(_strip_fences(text))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def cast_from_scenario(text: str, story: Story) -> str:
    """The cast the scenario call wrote, as the story's `cast_json`: its
    characters, narrator, locations and props, and each scene's links by
    scene id. "" when the reply has no usable cast (the Set step then casts
    the film with its own call)."""
    data = _json_dict(text)
    rows = [r if isinstance(r, dict) else {} for r in _as_list(data.get("scenes"))]
    if not data or len(rows) < len(story.scenes):
        return ""
    cast = {k: data[k] for k in _CAST_PARTS if data.get(k) is not None}
    cast["scenes"] = {
        sc.id: {k: rows[i][k] for k in _LINK_FIELDS if k in rows[i]}
        for i, sc in enumerate(story.scenes)
    }
    out = json.dumps(cast)
    try:
        parse_set_build(set_text_from_cast(out, story.scenes), _copy_story(story))
    except ScenarioError:
        return ""
    return out


def _copy_story(story: Story) -> Story:
    """A throwaway copy, so trial parses never tag the real scenes."""
    return Story.from_dict(story.to_dict())


def set_text_from_cast(cast_json: str, scenes: list[Scene]) -> str:
    """The Set step's casting JSON rebuilt from a story's `cast_json`, with
    the scene rows in the scenes' current order. "" when some scene has no
    row (it was added later), so the film is cast afresh."""
    data = _json_dict(cast_json)
    links = data.get("scenes")
    if not isinstance(links, dict) or any(sc.id not in links for sc in scenes):
        return ""
    body = {k: v for k, v in data.items() if k != "scenes"}
    return json.dumps({**body, "scenes": [links[sc.id] for sc in scenes]})


def _keyed(data: dict, part: str) -> dict[str, dict]:
    """A cast part's items by lower-case key and name."""
    out: dict[str, dict] = {}
    for item in _as_list(data.get(part)):
        if isinstance(item, dict):
            for alias in (item.get("key"), item.get("name")):
                if alias:
                    out.setdefault(str(alias).strip().lower(), item)
    return out


def _item_look(item: dict) -> str:
    """One cast item in the words a set asset's look() would use."""
    name = _text(item.get("name"), 60)
    bits = [_text(item.get("description")), _text(item.get("outfit"), 200)]
    bits = [b for b in bits if b]
    return f"{name} ({', '.join(bits)})" if bits else name


def cast_looks(story: Story, scene: Scene) -> tuple[str, str]:
    """(who is on screen, the place) for a scene from the story's
    `cast_json`, before the Set step has made a set. ("", "") if unknown."""
    data = _json_dict(story.cast_json)
    row = (data.get("scenes") or {}).get(scene.id) if data else None
    if not isinstance(row, dict):
        return "", ""
    people = _keyed(data, "characters")
    who = [
        _item_look(people[str(c).strip().lower()])
        for c in _as_list(row.get("cast"))
        if str(c).strip().lower() in people
    ]
    places = _keyed(data, "locations")
    place = places.get(str(row.get("location") or "").strip().lower())
    where = ""
    if place:
        where = _item_look(place)
        if _text(place.get("time_of_day"), 40):
            where += f", {_text(place.get('time_of_day'), 40)}"
    return "; ".join(who), where


def cast_names(story: Story) -> str:
    """The cast's keys and names from `cast_json`, for a scene rewrite."""
    data = _json_dict(story.cast_json)
    lines = []
    parts = (("characters", "Character"), ("locations", "Location"), ("props", "Prop"))
    for part, label in parts:
        for item in _as_list(data.get(part)):
            if isinstance(item, dict) and item.get("name"):
                lines.append(f"  {label} {item.get('key', '')}: {_item_look(item)}.")
    return "\n".join(lines)


def relink_scene(story: Story, scene: Scene, text: str, story_set=None) -> None:
    """After a scene rewrite: point the scene at the cast its new JSON
    names, in the set (scene links) or in the story's `cast_json` (its row).
    Leaves the links alone when the reply names nobody."""
    data = _json_dict(text)
    row = {k: data[k] for k in _LINK_FIELDS if k in data}
    if not row:
        return
    if story_set is not None:
        parse_scene_links(json.dumps({"scenes": [row]}), story_set, [scene])
        return
    cast = _json_dict(story.cast_json)
    if isinstance(cast.get("scenes"), dict):
        cast["scenes"][scene.id] = row
        story.cast_json = json.dumps(cast)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


# Where an on-camera speaker looks. "Facing the camera" put the camera in
# front of a stage speaker and the audience behind them.
SPEAKER_FACING = (
    "they face the people they are talking to. With an audience in the scene, "
    "the camera is among the audience (heads in the foreground, or a side "
    "angle) and the speaker faces the crowd, never with their back to it; "
    "they look into the lens only when they talk straight to the viewer with "
    "nobody else there"
)

# Generated faces that drift towards a famous face are refused by the video
# model ("prominent individuals"), so people are invented as ordinary ones.
# NOT_FAMOUS is for Gemini's writing, which follows "not" well.
NOT_FAMOUS = (
    "an ordinary, non-famous person with an invented name, who does not "
    "resemble or share the name of any celebrity, actor or public figure"
)
# EVERYDAY_PERSON is for image prompts. Image models follow "not" poorly, so
# naming celebrities there pulls faces towards them: describe the opposite.
EVERYDAY_PERSON = (
    "a believable everyday person with their own natural, slightly uneven "
    "features and real skin texture, like a candid photo of someone met on "
    "the street, not glamorous or model-like"
)


def _speech_rules(story: Story) -> str:
    voice = (
        '- "voice": one short English description of the on-screen speaker\'s '
        "voice that starts with their gender, e.g. \"a male voice, mid-30s, calm "
        "and confident, neutral American accent\". It is reused for every spoken scene so it "
        'sounds the same. Use "" if nobody speaks on camera.'
    )
    longest = max(supported_durations())
    takes = (
        "- Keep each person's speech in as few spoken scenes as possible: one "
        "or two back-to-back spoken scenes, never many short ones. A spoken "
        f'scene may run longer: set "seconds" (up to {longest}) so its line '
        f"fits at about {WORDS_PER_SECOND:g} words a second, and write the line to "
        "fill it. Back-to-back spoken scenes are filmed as one continuous take."
    )
    if story.speech_mode == "narrator":
        return (
            '- Every line is a narrator voiceover: "spoken" is false for every '
            'scene and nobody on screen talks. "voice" is "".'
        )
    if story.speech_mode == "on_camera":
        return (
            '- Every line is said on camera by the person on screen: "spoken" is '
            'true for every scene and "narration" is the exact words they say. '
            f"Each visual shows that person speaking: {SPEAKER_FACING}.\n"
            + voice
            + "\n"
            + takes
        )
    return (
        "- Decide for each scene who speaks. If the idea features a person "
        "talking (a presenter, a speech, an interview, a conversation, a vlog), "
        'set "spoken" to true and write "narration" as the exact words that '
        "person says on camera, with the visual showing them speaking "
        f"({SPEAKER_FACING}). Prefer "
        "on-camera speech whenever a speaking person is the point of the film. "
        'Otherwise set "spoken" to false and write a narrator voiceover line.\n'
        + voice
        + "\n"
        + takes
    )


def _set_cast_rules(story_set) -> str:
    """Scenario rules that make the story use a saved set's cast and places."""
    if story_set is None:
        return ""
    lines = [
        "- Use this cast and these places. Their looks are fixed here: call "
        "them by name in the visuals."
    ]
    for c in story_set.on_screen():
        lines.append(f"  Character {c.name}: {c.look()}.")
    for loc in story_set.locations:
        lines.append(f"  Location {loc.name}: {loc.look()}.")
    for p in story_set.props:
        lines.append(f"  Prop {p.name}: {p.look()}.")
    lines.append(
        '- For each scene also give "cast" (names of the characters on screen), '
        '"location" (a location name or ""), "props" (prop names) and '
        '"speaker" (who says a spoken line, or "").'
    )
    return "\n" + "\n".join(lines)


def _brand_line(story: Story) -> str:
    if not story.brand_json:
        return ""
    from common import brand_kit

    return brand_kit.prompt_line(brand_kit.from_json(story.brand_json))


def _brand_rule(story: Story) -> str:
    line = _brand_line(story)
    return (
        f"\n- Brand: {line} Match this in the visuals and the narration; never "
        "show the brand name or a logo in a scene."
        if line
        else ""
    )


REFERENCE_PHOTO_NOTE = (
    "The attached image is a photo of the main character: match their face, "
    "hair, build and look."
)


def scenario_media(story: Story, story_set=None) -> list[str]:
    """Images sent with the scenario call: the Create step's reference photo
    of the main character (a saved set already fixes the cast's looks)."""
    return [story.reference_uri] if story.reference_uri and story_set is None else []


def _main_character(story: Story, story_set) -> str:
    """The Create step's main character text and reference photo, so the
    writer builds the film around that person instead of inventing one."""
    if story_set is not None:
        return ""
    lines = []
    if story.character.strip():
        lines.append(f"Main character (keep this look): {story.character.strip()}")
    if scenario_media(story):
        lines.append(REFERENCE_PHOTO_NOTE)
    return "\n" + "\n".join(lines) if lines else ""


def scenario_prompt(story: Story, story_set=None) -> str:
    style = style_of(story)
    cams = ", ".join(CAMERA_IDS)
    cam_rule = (
        f'Use the camera move "{story.camera}" for every scene.'
        if story.camera in CAMERA_IDS
        else f"Read the camera from the idea: if it says how the camera moves (for example 'the camera pans left to right slowly'), use that move, direction and speed for every shot it covers and do not change it between shots of one take. Otherwise pick the best camera move for each scene from: {cams}."
    )
    casting = scenario_casts(story_set)
    links = (
        ', "cast": [str], "location": str, "props": [str], "speaker": str'
        if story_set is not None or casting
        else ""
    )
    cast_shape = f", {CAST_JSON_SHAPE}" if casting else ""
    brief = (
        f'\nBrief (from an earlier pass; improve it, keep what the user edited): """{story.brief.strip()}"""'
        if story.brief.strip()
        else ""
    )
    if getattr(story, "one_take", False):
        total = int(getattr(story, "target_seconds", 0) or 0) or story.scene_count * story.duration
        parts = (
            "one scene"
            if story.scene_count == 1
            else f"exactly {story.scene_count} scenes that run on from each other with no cut"
        )
        opening = (
            f"Turn the idea below into ONE CONTINUOUS TAKE of {total} seconds: {parts},\n"
            f"each {story.duration} seconds long. Visual style: {style['label']}."
        )
        take_rules = ONE_TAKE_RULES
    else:
        opening = (
            f"Turn the idea below into a short film of exactly {story.scene_count} scenes,\n"
            f"each about {story.duration} seconds long. Visual style: {style['label']}."
        )
        take_rules = ""
    return f"""{opening}

Idea: \"\"\"{story.idea.strip()}\"\"\"{brief}{_main_character(story, story_set)}

Rules:
- Write the title and every narration line in {story.language}.
- Narration: what is said in each scene (one sentence for a short scene, a few
  for a long one) that can be spoken in under
  {story.duration} seconds (at most {max_words(story.duration)} words), or in
  its "seconds" for a longer spoken scene.
{_speech_rules(story)}
- Visual: a detailed, self-contained description of what the camera sees
  (subject, action, expression, framing, setting details, lighting). Call
  each person and place by their name from the cast and do not describe
  their face, hair, build or clothes there: the cast holds their looks, the
  same in every shot. Every person is {NOT_FAMOUS}. Write visuals in English.
- {cam_rule}
- Build a clear beginning, middle and end.{take_rules}{_set_cast_rules(story_set)}{_scenario_cast_rules(casting)}{_brand_rule(story)}
- "brief": first, rewrite the idea as a clear, vivid film brief in English
  (3 to 5 sentences: subject, audience, tone, arc, setting and look). Keep
  everything the idea asks for and add nothing that contradicts it. Then
  write the scenes from the brief.

Return only JSON: {{"brief": str, "title": str, "voice": str, "scenes": [{{"narration": str, "spoken": bool, "seconds": int, "visual": str, "camera": str{links}}}]{cast_shape}}}"""


# Breakdown rules for a one-take film (Story.one_take).
ONE_TAKE_RULES = """
- ONE CONTINUOUS TAKE: the camera never cuts, jumps or reframes. Scene 1's
  visual sets the framing, place and lighting once; any later scene only says
  what changes (the action and the words), never a new framing, backdrop,
  angle or lighting.
- One camera move for the whole take, slow and steady. When the camera moves
  for a long time, the person moves with it (walks across the space while the
  camera tracks them) so they stay in frame the whole time; the camera never
  leaves the person.
- The speaker talks the whole time in one voice; the narration is one
  continuous speech split across the scenes at sentence ends."""


# System instructions: the role and the craft rules that never change. The
# story's own settings and the idea go in the user message.
SCENARIO_SYSTEM = (
    "You are a film director and screenwriter. You turn a short idea into a "
    "short film that image and video models shoot one scene at a time, so "
    "every scene's visual must stand on its own as a shot description, and "
    "the scenes together must tell one story with a clear beginning, middle "
    "and end. Follow the user's rules and settings exactly, keep everything "
    "the idea asks for, and never add anything that contradicts it."
)
CASTING_SYSTEM = (
    "You are a casting director and production designer. You fix how every "
    "person, place and object in a short film looks and sounds, in plain, "
    "fixed wording that an image model can paint the same way every time."
)


def _str() -> dict:
    return {"type": "string"}


def _str_list() -> dict:
    return {"type": "array", "items": {"type": "string"}}


def _links_schema() -> dict:
    """Per-scene links to the set: keys (or names) of who, where and what."""
    return {
        "cast": _str_list(),
        "location": _str(),
        "props": _str_list(),
        "speaker": _str(),
    }


def cast_schema() -> dict:
    """JSON-schema properties for a film's cast, places and props."""
    voice = {
        "type": "object",
        "properties": {
            "tts_voice": {"type": "string", "enum": list(VOICES)},
            "style": _str(),
            "description": _str(),
        },
        "required": ["tts_voice", "style", "description"],
    }
    item = {"key": _str(), "name": _str(), "description": _str()}
    return {
        "characters": {
            "type": "array",
            "maxItems": SET_MAX_CHARACTERS,
            "items": {
                "type": "object",
                "properties": {**item, "outfit": _str(), "voice": voice},
                "required": ["key", "name", "description", "outfit", "voice"],
            },
        },
        "narrator": {
            "type": "object",
            "properties": {
                "tts_voice": {"type": "string", "enum": list(VOICES)},
                "style": _str(),
            },
        },
        "locations": {
            "type": "array",
            "maxItems": SET_MAX_LOCATIONS,
            "items": {
                "type": "object",
                "properties": {**item, "time_of_day": _str()},
                "required": ["key", "name", "description"],
            },
        },
        "props": {
            "type": "array",
            "maxItems": SET_MAX_PROPS,
            "items": {
                "type": "object",
                "properties": item,
                "required": ["key", "name", "description"],
            },
        },
    }


def scene_schema(with_links: bool = False) -> dict:
    """JSON schema for one scene of the scenario."""
    props = {
        "narration": _str(),
        "spoken": {"type": "boolean"},
        "seconds": {"type": "integer"},
        "visual": _str(),
        "camera": {"type": "string", "enum": list(CAMERA_IDS)},
    }
    required = ["narration", "spoken", "visual", "camera"]
    if with_links:
        props.update(_links_schema())
        required += ["cast", "location", "props", "speaker"]
    return {"type": "object", "properties": props, "required": required}


def scenario_schema(story: Story, story_set=None) -> dict:
    """Response schema for the scenario call: exactly `scene_count` scenes,
    a camera move from the presets, and the cast when there is no saved set
    (scenario_casts)."""
    casting = scenario_casts(story_set)
    props = {
        "brief": _str(),
        "title": _str(),
        "voice": _str(),
        "scenes": {
            "type": "array",
            "minItems": story.scene_count,
            "maxItems": story.scene_count,
            "items": scene_schema(with_links=story_set is not None or casting),
        },
    }
    required = ["brief", "title", "voice", "scenes"]
    if casting:
        props.update(cast_schema())
        required += ["characters", "locations", "props"]
    return {"type": "object", "properties": props, "required": required}


def set_schema() -> dict:
    """Response schema for the Set step's casting call."""
    return {
        "type": "object",
        "properties": {
            "name": _str(),
            **cast_schema(),
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": _links_schema(),
                    "required": ["cast", "location", "props", "speaker"],
                },
            },
        },
        "required": ["name", "characters", "locations", "props", "scenes"],
    }


def scenario_casts(story_set) -> bool:
    """The scenario call also casts the film (no saved set yet)."""
    return story_set is None


# The cast part of the scenario and set JSON (as written in the prompts).
CAST_JSON_SHAPE = (
    '"characters": [{"key": str, "name": str, "description": str, '
    '"outfit": str, "voice": {"tts_voice": str, "style": str, '
    '"description": str}}], "narrator": {"tts_voice": str, "style": str} | '
    'null, "locations": [{"key": str, "name": str, "description": str, '
    '"time_of_day": str}], "props": [{"key": str, "name": str, '
    '"description": str}]'
)


def _cast_item_rules() -> str:
    """How to write the cast: the same rules for the scenario and the Set
    step's casting call."""
    voices = ", ".join(f"{v} ({VOICE_GENDER.get(v, '')})" for v in VOICES)
    return f"""- Characters: the people (or creatures) who appear on screen, at most
  {SET_MAX_CHARACTERS}. "description": age, build, face, skin, hair; fixed
  wording, no actions. "outfit": what they wear in every scene. Each person
  is {NOT_FAMOUS}: avoid stock "handsome leading man" or "model" wording and
  give one or two distinctive details (greying temples, freckles, glasses,
  a crooked nose, a small scar). Never base a character on a real, named
  person: if the idea names a famous person, write an original character in
  a similar role, because the video model refuses real people's faces.
- Each character's "voice": "tts_voice" is one of {voices} and matches
  their gender; "style" is a short delivery note (e.g. "warm, unhurried");
  "description" is one fixed English line that starts with gender, then age,
  accent, pace and timbre (e.g. "a female voice, early 30s, soft Irish
  accent, unhurried, warm alto").
- "narrator": {{"tts_voice", "style"}} for the off-screen narrator if any
  line is narrated, else null.
- Locations: the places scenes happen in, at most {SET_MAX_LOCATIONS}.
  "description": the empty place (no people), materials, light, colours.
- Props: objects that matter to the story and recur, at most
  {SET_MAX_PROPS}. Often none.
- Give every item a short "key" (c1, c2, l1, p1 ...)."""


def _scenario_cast_rules(casting: bool) -> str:
    """Scenario rules that make the writer cast the film in the same call,
    so each look is written once and every scene points at it."""
    if not casting:
        return ""
    return f"""
- Cast the film too: list everyone and everything that must look and sound
  the same in every shot. List the main character first. Write the cast in
  English.
{_cast_item_rules()}
- For each scene also give "cast" (keys of the characters on screen),
  "location" (a location key or ""), "props" (prop keys) and "speaker" (key
  of who says a spoken line, or "")."""


def set_build_prompt(story: Story) -> str:
    """Ask Gemini for the story's cast, places and props, with a fixed look
    and voice for each, and which of them appear in every scene."""
    style = style_of(story)
    scenes = "\n".join(
        f"{i + 1}. [{'spoken on camera' if sc.spoken else 'narrator'}] "
        f"{sc.visual} | Line: {sc.narration}"
        for i, sc in enumerate(story.scenes)
    )
    lead = (
        f"\nMain character (keep this look, list them first): {story.character.strip()}"
        if story.character.strip()
        else ""
    )
    return f"""Read this short film and list everything that must look and sound the same
in every shot. Visual style: {style["label"]}.

Idea: \"\"\"{story.idea.strip()}\"\"\"{lead}
Scenes:
{scenes}

Rules:
{_cast_item_rules()}
- In "scenes", one entry per scene in order: "cast" (keys on screen), "location" (key or ""),
  "props" (keys), "speaker" (key of who says a spoken line, else "").
- Write everything in English.

Return only JSON: {{"name": str, "characters": [{{"key": str, "name": str, "description": str, "outfit": str, "voice": {{"tts_voice": str, "style": str, "description": str}}}}], "narrator": {{"tts_voice": str, "style": str}} | null, "locations": [{{"key": str, "name": str, "description": str, "time_of_day": str}}], "props": [{{"key": str, "name": str, "description": str}}], "scenes": [{{"cast": [str], "location": str, "props": [str], "speaker": str}}]}}"""


def _regen_cast_rules(story: Story, story_set) -> str:
    """The cast a rewritten scene must reuse: the set's, or the cast the
    scenario wrote before there is a set."""
    if story_set is not None:
        return _set_cast_rules(story_set)
    names = cast_names(story)
    if not names:
        return ""
    return (
        "\n- Use this cast and these places. Their looks are fixed here: call "
        "them by name in the visual.\n" + names + '\n- Also give "cast" (keys of '
        'the characters on screen), "location" (a location key or ""), "props" '
        '(prop keys) and "speaker" (key of who says a spoken line, or "").'
    )


def regen_links(story: Story, story_set) -> bool:
    """A scene rewrite also says who and where the scene is."""
    return story_set is not None or bool(cast_names(story))


def scene_regen_prompt(story: Story, index: int, story_set=None) -> str:
    before = (
        story.scenes[index - 1].visual if index > 0 else "(this is the first scene)"
    )
    after = (
        story.scenes[index + 1].visual
        if index + 1 < len(story.scenes)
        else "(this is the last scene)"
    )
    current = story.scenes[index]
    links = (
        ', "cast": [str], "location": str, "props": [str], "speaker": str'
        if regen_links(story, story_set)
        else ""
    )
    return f"""Rewrite scene {index + 1} of the film
"{story.title}" with a fresh idea that still fits between its neighbours.
Idea of the film: {story.idea}
Previous scene: {before}
Next scene: {after}
Current scene (replace it): {current.visual}
Narration in {story.language} (at most {max_words(current.duration)} words),
visual in English, one camera move from: {", ".join(CAMERA_IDS)}.
{_scene_speech_rule(story, current)}{_regen_cast_rules(story, story_set)}
Return only JSON: {{"narration": str, "spoken": bool, "visual": str, "camera": str{links}}}"""


def _scene_speech_rule(story: Story, current: Scene) -> str:
    if story.speech_mode == "narrator":
        return '"spoken" is false: the line is a narrator voiceover.'
    if story.speech_mode == "on_camera" or current.spoken:
        return (
            '"spoken" is true: "narration" is the exact words the person on '
            f"screen says, and the visual shows them speaking: {SPEAKER_FACING}."
        )
    return (
        '"spoken" is true if the person on screen should say the line on '
        "camera, false for a narrator voiceover."
    )


# ---------------------------------------------------------------------------
# Set references for frames and clips
# ---------------------------------------------------------------------------

# Most set images sent with one storyboard frame (Nano Banana takes more, but
# a few clear references beat many).
FRAME_MAX_REFERENCES = 8


@dataclass
class Ref:
    """One reference image: what it is (named in the prompt) and its URI.
    `group`: "face" / "front" (a character view), "plate" or "prop"."""

    group: str
    label: str
    uri: str
    owner_id: str = ""


def scene_cast(story_set, scene: Scene) -> list:
    """The scene's on-screen characters, in cast order."""
    if story_set is None:
        return []
    out = []
    for cid in scene.cast:
        c = story_set.character(cid)
        if c is not None and not c.narrator and c not in out:
            out.append(c)
    return out


def scene_refs(story_set, scene: Scene) -> list[Ref]:
    """The scene's set images in prompt order: each cast member's face then
    full-body front, the location's wide plate, then the props."""
    if story_set is None:
        return []
    from services.story_sets import image_of

    refs: list[Ref] = []
    for c in scene_cast(story_set, scene):
        face, front = image_of(c, "face"), image_of(c, "front")
        if face:
            refs.append(Ref("face", f"{c.name}'s face", face.uri, c.id))
        if front:
            refs.append(
                Ref("front", f"{c.name}, full body and outfit", front.uri, c.id)
            )
    loc = story_set.location(scene.location_id) if scene.location_id else None
    plate = image_of(loc, "plate") if loc else None
    if plate:
        refs.append(Ref("plate", f"the place, {loc.name}", plate.uri, loc.id))
    for pid in scene.prop_ids:
        prop = story_set.prop(pid)
        item = image_of(prop, "item") if prop else None
        if item:
            refs.append(Ref("prop", f"the {prop.name}", item.uri, prop.id))
    seen: set[str] = set()
    unique = []
    for r in refs:
        if r.uri not in seen:
            seen.add(r.uri)
            unique.append(r)
    return unique


def cap_refs(refs: list[Ref], cap: int) -> list[Ref]:
    """Keep at most `cap` references, order unchanged. Props go first, then
    extra character views (full-body fronts, last character first), then the
    location, then whole characters from the end."""
    out = list(refs)
    cap = max(0, cap)

    def drop_last(pred) -> bool:
        for k in range(len(out) - 1, -1, -1):
            if pred(out[k]):
                del out[k]
                return True
        return False

    while len(out) > cap:
        faced = {r.owner_id for r in out if r.group == "face"}
        if drop_last(lambda r: r.group == "prop"):
            continue
        # A character keeps one view: its face if it has one.
        if drop_last(lambda r, faced=faced: r.group == "front" and r.owner_id in faced):
            continue
        if drop_last(lambda r: r.group == "plate"):
            continue
        out.pop()
    return out


def frame_refs(story_set, scene: Scene, cap: int = FRAME_MAX_REFERENCES) -> list[Ref]:
    """Set images for a storyboard frame: cast face + front, plate, props."""
    return cap_refs(scene_refs(story_set, scene), cap)


def clip_refs(story_set, scene: Scene, frame_uri: str, cap: int) -> list[Ref]:
    """Reference-to-video images for a clip: the storyboard frame first, then
    the scene's set images, capped at `cap` in all (see cap_refs)."""
    head = (
        [Ref("frame", "the storyboard frame (how the shot looks)", frame_uri)]
        if frame_uri
        else []
    )
    rest = [r for r in scene_refs(story_set, scene) if r.uri != frame_uri]
    return head + cap_refs(rest, cap - len(head))


def refs_sentence(labels: list[str]) -> str:
    """Name each reference image, in order, for the prompt."""
    if not labels:
        return ""
    named = "; ".join(f"image {k + 1} is {label}" for k, label in enumerate(labels))
    return f" Use the images as references: {named}. Keep every person, place and object exactly as shown."


def _cast_text(story: Story, scene: Scene, story_set) -> str:
    """Who is on screen: the scene's cast looks, else the cast the scenario
    wrote (no set yet), else the story's character."""
    cast = scene_cast(story_set, scene)
    if not cast and story_set is not None and getattr(scene, "spoken", False):
        # A spoken scene the breakdown did not link: its speaker is the
        # set's lead, so later turns can still name who is on screen.
        cast = list(story_set.on_screen())[:1]
    if cast:
        return "; ".join(c.look() for c in cast)
    if story_set is None:
        who, _ = cast_looks(story, scene)
        if who:
            return who
    return story.character


def _who_short(story: Story, scene: Scene, story_set) -> str:
    """A short name for who is on screen ("Arthur", "the presenter"), so a
    camera line can say to keep them in frame. Empty when nobody is."""
    cast = scene_cast(story_set, scene)
    if not cast and story_set is not None:
        cast = list(story_set.on_screen())[:1]
    if cast:
        name = (getattr(cast[0], "name", "") or "").strip()
        return name.split()[0] if name else "the person on screen"
    if (story.character or "").strip() or getattr(scene, "spoken", False):
        return "the person on screen"
    return ""


def _names_cast(story: Story, scene: Scene, story_set) -> bool:
    """The scene's people come from a cast (a set, or the scenario's own),
    not from the story's one-line character."""
    if scene_cast(story_set, scene):
        return True
    return story_set is None and bool(cast_looks(story, scene)[0])


# How frame_prompt names the take's first frame among the reference images.
SAME_TAKE_REF = "the earlier frame of this take"


def frame_prompt(
    story: Story,
    scene: Scene,
    has_reference: bool,
    story_set=None,
    ref_labels: list[str] | None = None,
    same_take: bool = False,
    note: str = "",
) -> str:
    """Image prompt for a storyboard frame. With a set, the scene's cast,
    place and props are described and each reference image is named
    (`ref_labels`, in image order). ``same_take``: the reference is the
    first frame of the continuous take this scene belongs to, so the room
    must stay as it is there. ``note``: the director's "Redo with note"
    for this frame."""
    style = style_of(story)
    keep = (
        " Keep the same main character, wardrobe, palette and art style as the "
        "reference image."
        if has_reference and not ref_labels
        else ""
    )
    if has_reference and same_take:
        # One continuous take is filmed in one place without a cut, so the
        # set cannot change between its frames (seen: a slide went blank and
        # an audience appeared, and the take followed the frames).
        keep += (
            f" This frame is later in the same continuous shot as {SAME_TAKE_REF}: "
            "keep the same room, set and props, exactly what is shown on any "
            "screen or board, and the same people in the same places. Only "
            "the camera framing and the action change, as described."
        )
    cast = _names_cast(story, scene, story_set)
    who = _cast_text(story, scene, story_set)
    character = f" {'On screen' if cast else 'Main character'}: {who}." if who else ""
    loc = (
        story_set.location(scene.location_id)
        if story_set and scene.location_id
        else None
    )
    where = loc.look() if loc else ""
    if story_set is None and not where:
        where = cast_looks(story, scene)[1]
    place = f" Place: {where}." if where else ""
    people = ""
    if who:
        people = f" Every person is {EVERYDAY_PERSON}."
        if any("face" in label for label in ref_labels or []):
            people += " Keep each face exactly as in its face image."
    facing = (
        f" The speaker: {SPEAKER_FACING}."
        if scene.spoken and scene.narration.strip()
        else ""
    )
    brand = _brand_line(story)
    brand = f" {brand}" if brand else ""
    shot = SHOT_SIZES.get(getattr(scene, "shot_size", ""), "")
    shot_text = f" Framing: {shot}." if shot else ""
    grammar = (getattr(story, "visual_grammar", "") or "").strip()
    grammar_text = f" Visual grammar: {grammar}." if grammar else ""
    return (
        f"{scene.visual}{shot_text}{character}{place}{facing} Style: {style['prompt']}.{grammar_text}{brand} "
        f"Aspect ratio {story.aspect_ratio}, one single frame, no text, no captions."
        f"{people}{keep}{refs_sentence(ref_labels or [])}{_note_text(note)}"
    )


def _note_text(note: str) -> str:
    note = " ".join((note or "").split())[:400]
    return f" Director's note for this version, follow it: {note}." if note else ""


def speaker_voice(story: Story, scene: Scene, story_set=None) -> str:
    """The on-camera voice line for a spoken scene: the speaking character's
    fixed voice description (word for word), else the story's."""
    if story_set is not None and scene.speaker_id:
        c = story_set.character(scene.speaker_id)
        if c is not None and c.voice.description.strip():
            return c.voice.description.strip()
    return story.speaker_voice


def clip_prompt(
    story: Story,
    scene: Scene,
    continuing: bool = False,
    story_set=None,
    ref_labels: list[str] | None = None,
    start_frame: bool = False,
    part_narration: str | None = None,
    bridge_to_next: bool = False,
) -> str:
    """Video prompt for a scene. ``continuing``: the clip continues the
    previous one (a continuous take), so it carries on the same person and
    voice. ``start_frame``: the scene's storyboard frame is attached, so the
    clip opens on it. ``part_narration`` overrides the spoken text for a
    multi-part extension (empty string produces an ambient-only prompt).
    ``bridge_to_next`` appends first-to-last frame transition guidance.

    Every clip has its own sound. Narrated scenes ask for natural ambient
    sound only, because the narrator's voiceover and the music go on top.
    With a set, the scene's cast replaces the story's character text, the
    speaker's voice description is used word for word, and the reference
    images (`ref_labels`, in order) are named."""
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    cam = CAMERA_PRESETS.get(scene.camera, CAMERA_PRESETS["static"])["prompt"]
    cast_text = _cast_text(story, scene, story_set)
    motion = (getattr(scene, "motion_prompt", "") or "").strip()
    grammar = (getattr(story, "visual_grammar", "") or "").strip()
    # One layout for every clip: shot, camera, picture, action, style, then
    # sound. The camera move leads and is said to win, so the action text
    # cannot turn the camera the other way.
    moving = bool(cam) and scene.camera not in ("static", "auto")
    who_short = _who_short(story, scene, story_set)
    # A later turn of the same scene (part_narration set) only continues:
    # resending the scene's framing makes Omni reframe with a cut.
    same_scene_turn = continuing and part_narration is not None
    base = "One continuous shot, no cuts."
    if cam:
        follow = f", keeping {who_short} in frame" if moving and who_short else ""
        base += f" Camera: {cam}{follow}."
    else:
        base += " Camera: natural camera movement."
    if same_scene_turn:
        base += (
            f" Keep the same framing, place and lighting; {who_short or 'the subject'}"
            " carries on from the last frame."
        )
    elif continuing:
        base += f" What happens now: {scene.visual}"
    else:
        base += f" {scene.visual}"
    if motion:
        base += f" Action: {motion}."
        if moving:
            base += " Keep the camera move above; the action does not change it."
    base += f" Style: {style['prompt']}."
    if grammar:
        base += f" Visual grammar: {grammar}."
    if _names_cast(story, scene, story_set):
        base += f" On screen: {cast_text}."
    base += refs_sentence(ref_labels or [])
    if continuing:
        # Name the character again: each turn of the thread is its own prompt.
        who = f" ({cast_text})" if cast_text else ""
        if start_frame:
            # The storyboard frame sets the shot; the thread keeps the voice.
            base = (
                f"Carry on the same take: the same person{who}, outfit and "
                "place, and the same voice, pace and room sound as before. "
                f"{base}"
            )
        else:
            base = (
                f"Continue this exact shot without a cut, from its last frame: "
                f"the same person{who}, outfit, place, lighting and camera "
                "height, the camera moving the same way and at the same speed, "
                f"and the same voice, pace and room sound. {base}"
            )
    base += " Avoid: cuts, jump cuts, a new location, new people."
    if continuing and start_frame:
        base += (
            " Start exactly on the attached image (this scene's storyboard "
            "frame) and hold that shot: no cut, and the screens and signs keep "
            "what they show."
        )
    bridge_note = (
        " Use the first image as the opening frame and smoothly transition to the second image as the ending frame."
        if bridge_to_next
        else ""
    )
    spoken_line = (
        scene.narration.strip() if part_narration is None else part_narration.strip()
    )
    audio_cue = (getattr(scene, "audio_cue", "") or "").strip()
    if not (scene.spoken and spoken_line):
        sound = (
            f"Sound: {audio_cue}. Natural ambient sound and sound effects of the scene only."
            if audio_cue
            else "Sound: natural ambient sound and sound effects of the scene only."
        )
        return (
            f"{base} {sound} No speech, dialogue, narration, singing or music."
            f"{bridge_note}"
        )
    voice = (
        speaker_voice(story, scene, story_set)
        or "a voice that matches their age and gender"
    )
    speaker = (
        story_set.character(scene.speaker_id)
        if story_set and scene.speaker_id
        else None
    )
    who = (
        f" ({speaker.look() if speaker else cast_text})"
        if (speaker or cast_text)
        else ""
    )
    return (
        f"{base} The person on screen{who} speaks to whoever they are "
        "addressing (the audience in the scene; the camera only when nobody "
        "else is there) and says in "
        f'{story.language}: "{spoken_line}" '
        f"They speak in {voice}, the same voice in every scene. They are the only "
        "voice: no narrator, no other speakers, no voice-over. Clear, natural, "
        "lip-synced speech over quiet room tone. No music, applause, crowd "
        "noise or hiss; no subtitles, no "
        f"on-screen text.{bridge_note}"
    )


def default_music_prompt(story: Story) -> str:
    style = style_of(story)
    return (
        f"Cinematic instrumental score for a short {style['label'].lower()} film: "
        f"{story.title or story.idea[:80]}. Warm, building, no vocals."
    )


# Plainer music prompts for when Lyria blocks the first one (its recitation
# check refuses prompts that sound like an existing piece, often because of a
# title). No title or story words, so they are very unlikely to be blocked.
MUSIC_FALLBACK_PROMPTS = (
    "Gentle cinematic instrumental underscore, soft piano and warm strings, "
    "slowly building, hopeful, no vocals.",
    "Calm ambient instrumental background music, warm synth pads, no vocals.",
)


def music_declined(exc: Exception) -> bool:
    """True when Lyria refused the prompt (recitation or safety block), as
    opposed to a service error."""
    text = str(exc).lower()
    return any(k in text for k in ("recitation", "blocked", "safety", "declined"))


def other_language(language: str) -> str:
    """The second language offered for a story: English for Arabic, else Arabic."""
    return "English" if language == "Arabic" else "Arabic"


def alt_story(story: Story) -> Story:
    """A copy of `story` as its second-language version (for voice, stitch and
    library): language, title and narration swapped, media unchanged."""
    return replace(
        story,
        language=story.alt_language,
        clip_language=story.language,
        title=story.title_alt or story.title,
        scenes=[
            replace(
                sc,
                narration=sc.narration_alt,
                clip_uri=sc.clip_alt_uri,
                continues_from=sc.clip_alt_from,
            )
            if sc.spoken and sc.has_alt_clip()
            else replace(sc, narration=sc.narration_alt)
            for sc in story.scenes
        ],
    )


def translation_prompt(story: Story) -> str:
    src, dst = story.language, story.alt_language
    lines = [sc.narration for sc in story.scenes]
    secs = [sc.duration for sc in story.scenes]
    arabic = (
        "\n- Write Modern Standard Arabic (fusha), natural and clear when read aloud."
        if dst == "Arabic"
        else ""
    )
    return f"""You translate voiceover scripts for short films.
Translate the title and each narration line of this film from {src} into {dst}.

Title: {json.dumps(story.title, ensure_ascii=False)}
Lines (JSON, one per scene, in order): {json.dumps(lines, ensure_ascii=False)}
Scene lengths in seconds (same order): {json.dumps(secs)}

Rules:
- Keep the meaning, tone and emotion; do not add or drop ideas.
- Each line must be speakable within its scene length, about as long as the
  original when read aloud. Prefer a shorter wording over a literal one.
- Keep exactly one line per scene, in the same order. An empty line stays empty.{arabic}

Return only JSON: {{"title": str, "lines": [str, ...]}} with exactly {len(lines)} lines."""


def parse_translation(text: str, count: int) -> tuple[str, list[str]]:
    """Parse {"title", "lines"}; raise ScenarioError unless there are `count` lines."""
    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The translation was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ScenarioError("The translation had the wrong shape.")
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) != count:
        raise ScenarioError("The translation had the wrong number of lines.")
    title = str(data.get("title") or "").strip()[:120]
    return title, [str(x or "").strip() for x in lines]


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def reachable_steps(story: Story | None) -> set[str]:
    """Steps the user may open for this story."""
    reach = {"stories", "create"}
    if story is None:
        return reach
    if story.scenes:
        reach.add("scenario")
    if story.approved and story.scenes:
        reach.add("set")
        reach.add("storyboard")
        if all(s.frame_uri for s in story.scenes):
            reach.add("editor")
            reach.add("video")
    if story.final_uri:
        reach.add("video")
    return reach


def can_enter(step: str, story: Story | None) -> bool:
    return step in STEP_IDS and step in reachable_steps(story)


def furthest_step(story: Story | None) -> str:
    reach = reachable_steps(story)
    for sid in reversed(STEP_IDS):
        if sid in reach and sid != "stories":
            if sid == "video" and story is not None and not story.final_uri:
                continue
            return sid
    return "create"


# ---------------------------------------------------------------------------
# Stitching plan
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    index: int
    clip_uri: str
    start: float
    duration: float
    fade_in: float
    narration: str = ""
    # The clip carries its own speech (levelled as dialogue, no voiceover).
    # Otherwise its sound is an ambient bed under the narrator.
    spoken: bool = False
    # Seconds skipped at the start of the clip. A seamless join drops the
    # clip's first frame, which repeats the previous clip's last frame.
    trim_head: float = 0.0
    join: str = "cut"
    # The clip extends the previous segment's clip (one continuous take).
    same_take: bool = False


@dataclass
class StitchPlan:
    segments: list[Segment]
    crossfade: float
    total: float


def is_seamless_join(prev: Scene, scene: Scene) -> bool:
    """True when scene's clip was animated from prev's current clip."""
    return bool(scene.continues_from) and scene.continues_from == prev.clip_uri


def build_stitch_plan(
    scenes: list[Scene],
    crossfade: float,
    clip_durations: list[float] | None = None,
    seamless: bool = False,
    fps: int = 24,
) -> StitchPlan:
    """Lay out clips on a timeline with overlapping crossfades or explicit
    scene transitions (``cut``, ``bridge``, ``extend``, ``dissolve``,
    ``fade_black``, ``auto``).

    Each clip starts `crossfade` seconds before the previous one ends, so the
    film is sum(durations) - crossfade * (n - 1) long. The crossfade is
    shortened when a clip is too short to hold it (at most a third of the
    shortest clip). Scenes without a clip are skipped.

    With ``seamless``, a join where the clip was animated from the previous
    scene's current clip (see ``is_seamless_join``) is a straight cut: no
    overlap, and the clip's first frame (a copy of the previous last frame)
    is dropped. Every other join keeps the crossfade.
    """
    usable = [(i, s) for i, s in enumerate(scenes) if s.clip_uri]
    if not usable:
        return StitchPlan(segments=[], crossfade=0.0, total=0.0)
    durs = [
        float(clip_durations[k])
        if clip_durations and k < len(clip_durations)
        else float(s.duration) + float(s.clip_in or 0)
        for k, (_, s) in enumerate(usable)
    ]
    xf = max(0.0, min(float(crossfade), min(durs) / 3.0)) if len(usable) > 1 else 0.0
    segments: list[Segment] = []
    t = 0.0
    head = 1.0 / fps if fps > 0 else 0.0
    for k, ((i, s), d) in enumerate(zip(usable, durs, strict=True)):
        prev_i, prev = usable[k - 1] if k else (-1, None)
        cut = (
            seamless
            and prev is not None
            and prev_i == i - 1
            and d > head
            and is_seamless_join(prev, s)
        )
        # An extended clip starts with a copy of the clip it continued:
        # always skip those seconds.
        base = float(s.clip_in or 0) if 0 < float(s.clip_in or 0) < d - 0.5 else 0.0
        extended = (
            base > 0
            and prev is not None
            and prev_i == i - 1
            and s.extends_from == prev.clip_uri
        )
        bridged = (
            prev is not None
            and prev_i == i - 1
            and bool(getattr(prev, "bridged_to", ""))
            and bool(s.frame_uri)
            and prev.bridged_to == s.frame_uri
        )
        trans = (getattr(s, "transition", "auto") or "auto").strip().lower()
        if k == 0:
            start, fade, trim, join = 0.0, 0.0, base, "cut"
        elif extended:
            # Continuous take: a straight cut into the clip's new seconds.
            start, fade, trim, join = t, 0.0, base, "extend"
        elif cut and not base:
            start, fade, trim, join = t, 0.0, head, "cut"
        elif bridged:
            trim = head if (d > head and not base) else base
            start, fade, join = t, 0.0, "bridge"
        elif trans == "cut":
            start, fade, trim, join = t, 0.0, base, "cut"
        elif trans == "bridge":
            trim = head if (seamless and d > head and not base) else base
            start, fade, join = t, 0.0, "bridge"
        elif trans == "extend":
            start, fade, trim, join = t, 0.0, base, "extend"
        elif trans == "fade_black":
            start, fade, trim, join = t, xf, base, "fade_black"
        elif trans == "dissolve":
            start, fade, trim, join = t - xf, xf, base, "dissolve"
        elif s.spoken or prev.spoken:
            # A crossfade would overlap speech with the next shot: cut instead.
            start, fade, trim, join = t, 0.0, base, "cut"
        else:
            start, fade, trim = t - xf, xf, base
            join = "dissolve" if xf > 0 else "cut"
        segments.append(
            Segment(
                index=i,
                clip_uri=s.clip_uri,
                start=round(start, 3),
                duration=round(d - trim, 4),
                fade_in=fade,
                narration=s.narration,
                spoken=bool(s.spoken and s.narration.strip()),
                trim_head=round(trim, 4),
                join=join,
                same_take=bool(extended),
            )
        )
        t = start + d - trim
    _one_file_per_take(segments)
    return StitchPlan(segments=segments, crossfade=xf, total=round(t, 3))


def _one_file_per_take(segments: list[Segment]) -> None:
    """A continuous take is one file. Each extension returns the whole take
    so far, so every scene of the take is cut from the take's last file at
    its own offset (the same seconds it had in its own file). Cutting the
    take from several files showed a jump at every join: each file encodes
    the shared seconds a little differently, and the sound changed source."""
    k = len(segments) - 1
    while k > 0:
        if not segments[k].same_take:
            k -= 1
            continue
        j = k
        while j > 0 and segments[j].same_take:
            j -= 1
        _cut_take(segments[j : k + 1])
        k = j - 1


def _cut_take(take: list[Segment], tol: float = 0.05) -> None:
    """Cut one take's scenes from its files. File m starts (its own 0 s) at
    film time ``start - trim_head`` of its scene. Each scene uses the newest
    file that still holds its start: for a take of at most the model's
    context that is the last file for every scene. In a longer (rolling)
    take older seconds drop out of newer files, so the scene at a change of
    file starts STORY_ROLL_CROSSFADE early and fades over the previous one,
    inside the overlap where both files show the same moment."""
    origins = [s.start - s.trim_head for s in take]
    # Each file ends where its own scene ends.
    ends = [s.start + s.duration for s in take]
    uris = [s.clip_uri for s in take]
    xf = float(getattr(Default(), "STORY_ROLL_CROSSFADE", 0.0) or 0.0)
    prev_file = -1
    for m, seg in enumerate(take):
        end = seg.start + seg.duration
        if prev_file >= 0 and origins[prev_file] <= seg.start + tol and ends[prev_file] >= end - tol:
            # The file in use still holds this scene: no change of file.
            f = prev_file
        else:
            f = max(j for j in range(m, len(take)) if j == m or origins[j] <= seg.start + tol)
        seg.clip_uri = uris[f]
        seg.trim_head = round(seg.start - origins[f], 4)
        if m > 0 and f != prev_file and xf > 0 and seg.trim_head >= xf:
            # A change of file inside the take: a short crossfade.
            seg.start = round(seg.start - xf, 3)
            seg.trim_head = round(seg.trim_head - xf, 4)
            seg.duration = round(seg.duration + xf, 4)
            seg.fade_in = xf
        prev_file = f
