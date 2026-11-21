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
        "prompt": "cinematic photorealistic film still, natural light, shallow depth of field, 35mm",
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

CAMERA_PRESETS: dict[str, dict[str, str]] = {
    "auto": {"label": "Director's choice", "prompt": ""},
    "static": {"label": "Static", "prompt": "locked-off static camera"},
    "dolly_in": {
        "label": "Dolly in",
        "prompt": "slow smooth dolly in toward the subject",
    },
    "orbit": {"label": "Orbit", "prompt": "camera orbits slowly around the subject"},
    "crane_up": {"label": "Crane up", "prompt": "camera cranes up to reveal the scene"},
    "handheld": {
        "label": "Handheld",
        "prompt": "handheld camera with gentle natural shake",
    },
}
CAMERA_IDS = [k for k in CAMERA_PRESETS if k != "auto"]

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


def single_clip_max() -> int:
    """Longest clip the story video model makes in one request."""
    model = get_omni_model_config(Default().STORY_VIDEO_MODEL)
    return model.max_duration if model else 8


def supported_durations() -> list[int]:
    """Scene lengths (seconds) the configured story video model can make:
    its own clip range, plus longer scenes up to STORY_MAX_SCENE_SECONDS when
    it can extend a clip."""
    model = get_omni_model_config(Default().STORY_VIDEO_MODEL)
    if not model:
        return [4, 6, 8]
    top = model.max_duration
    if "extend" in model.supported_modes:
        top = max(top, Default().STORY_MAX_SCENE_SECONDS)
    return [d for d in SCENE_LENGTHS if model.min_duration <= d <= top]


def clip_parts(seconds: int, single_max: int | None = None) -> list[int]:
    """How a scene of `seconds` is made: the first clip, then extension
    turns of EXTEND_MIN_SECONDS..EXTEND_MAX_SECONDS each. 20 -> [15, 5],
    30 -> [15, 8, 7], 16 -> [13, 3] (with a 15 s single-clip limit)."""
    seconds = int(seconds)
    top = single_clip_max() if single_max is None else single_max
    if seconds <= top:
        return [seconds]
    first, rest = top, seconds - top
    if rest < EXTEND_MIN_SECONDS:
        first -= EXTEND_MIN_SECONDS - rest
        rest = EXTEND_MIN_SECONDS
    turns = -(-rest // EXTEND_MAX_SECONDS)
    base, extra = divmod(rest, turns)
    return [first] + [base + (1 if i < extra else 0) for i in range(turns)]


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

    def clear_clip(self) -> None:
        """Forget the clip and everything made from it (take, Omni thread)."""
        self.clip_uri = self.extends_from = self.interaction_id = ""
        self.clip_in = 0.0

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
    # Subtitled downloads (services/story_subtitles.py). The main film has no
    # captions; each variant ("en", "ar", "en+ar") is rendered on request.
    subtitle_style: str = "clean"
    # {"en": {"key": source hash, "lines": [one per scene]}, "ar": {...}}
    subtitle_lines_json: str = ""
    # {"en": {"uri": film, "key": what it was made from}, ...}
    film_variants_json: str = ""
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

    def continues_take(self, index: int) -> bool:
        """Scene `index` continues the previous clip (a continuous take):
        both scenes are spoken on camera, continuous takes are on, and the
        take stays within STORY_TAKE_MAX_SECONDS (then it cuts to a new one)."""
        if not self.continuous_takes or not self._spoken_pair(index):
            return False
        cap = Default().STORY_TAKE_MAX_SECONDS
        single = single_clip_max()
        take = 0.0
        for i in range(index + 1):
            d = float(self.scenes[i].duration)
            # A scene longer than one clip is extended in its own thread.
            joins = i > 0 and self._spoken_pair(i) and take + d <= cap and d <= single
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


def nearest_duration(duration: int) -> int:
    allowed = supported_durations()
    return min(allowed, key=lambda d: (abs(d - int(duration)), d))


def apply_caps(scene_count: int, duration: int, resolution: str | None = None) -> Caps:
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
    d0 = nearest_duration(duration)
    if d0 != int(duration):
        notes.append(f"Scene length set to {d0}s (supported by the video model).")
    n, d = n0, d0
    while n * d > limit and n > cfg.STORY_MIN_SCENES:
        n -= 1
    if n * d > limit:
        fitting = [x for x in supported_durations() if n * x <= limit]
        d = max(fitting) if fitting else min(supported_durations())
    if n != n0 or d != d0:
        notes.append(f"Film capped at {limit}s: {n} scenes of {d}s.")
    res = cfg.STORY_VIDEO_RESOLUTION
    if resolution and resolution != res:
        notes.append(f"Resolution set to {res}.")
    return Caps(scene_count=n, duration=d, resolution=res, notes=notes)


# ---------------------------------------------------------------------------
# Scenario parsing
# ---------------------------------------------------------------------------


class ScenarioError(ValueError):
    """The model's scenario could not be used."""


_CAMERA_ALIASES = {
    "dolly": "dolly_in",
    "dolly in": "dolly_in",
    "dolly-in": "dolly_in",
    "push in": "dolly_in",
    "push-in": "dolly_in",
    "zoom in": "dolly_in",
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
) -> tuple[str, list[Scene]]:
    """Parse and validate the model's scenario JSON.

    Expected shape: {"title": str, "voice": str,
    "scenes": [{"narration", "spoken", "visual", "camera"}]}.
    ``speech_mode`` "narrator" or "on_camera" overrides each scene's "spoken".
    Extra scenes are dropped; too few or empty scenes raise ScenarioError.
    A fixed camera preset (not "auto") overrides each scene's camera.
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
        scenes.append(
            Scene(
                narration=narration,
                visual=visual,
                camera=camera,
                duration=_spoken_length(raw.get("seconds"), duration)
                if spoken
                else duration,
                spoken=spoken,
            )
        )
    if len(scenes) < scene_count:
        raise ScenarioError(f"Expected {scene_count} scenes, got {len(scenes)}.")
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
NOT_FAMOUS = (
    "an ordinary, non-famous person who does not resemble any celebrity, "
    "actor or public figure"
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
    lines = ["- Use this cast and these places. Describe them as written here."]
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


def scenario_prompt(story: Story, story_set=None) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    cams = ", ".join(CAMERA_IDS)
    cam_rule = (
        f'Use the camera move "{story.camera}" for every scene.'
        if story.camera in CAMERA_IDS
        else f"Pick the best camera move for each scene from: {cams}."
    )
    links = (
        ', "cast": [str], "location": str, "props": [str], "speaker": str'
        if story_set is not None
        else ""
    )
    brief = (
        f'\nBrief (from an earlier pass; improve it, keep what the user edited): """{story.brief.strip()}"""'
        if story.brief.strip()
        else ""
    )
    return f"""You are a film director and screenwriter.
Turn the idea below into a short film of exactly {story.scene_count} scenes,
each about {story.duration} seconds long. Visual style: {style["label"]}.

Idea: \"\"\"{story.idea.strip()}\"\"\"{brief}

Rules:
- Write the title and every narration line in {story.language}.
- Narration: what is said in each scene (one sentence for a short scene, a few
  for a long one) that can be spoken in under
  {story.duration} seconds (at most {max_words(story.duration)} words), or in
  its "seconds" for a longer spoken scene.
{_speech_rules(story)}
- Visual: a detailed, self-contained description of what the camera sees
  (subject, action, setting, lighting). Keep the main character's look
  identical in every scene and describe it each time. Every person is
  {NOT_FAMOUS}: give them one or two distinctive details (for example
  greying temples, freckles, glasses, a small scar). Write visuals in English.
- {cam_rule}
- Build a clear beginning, middle and end.{_set_cast_rules(story_set)}
- "brief": first, rewrite the idea as a clear, vivid film brief in English
  (3 to 5 sentences: subject, audience, tone, arc, setting and look). Keep
  everything the idea asks for and add nothing that contradicts it. Then
  write the scenes from the brief.

Return only JSON: {{"brief": str, "title": str, "voice": str, "scenes": [{{"narration": str, "spoken": bool, "seconds": int, "visual": str, "camera": str{links}}}]}}"""


def set_build_prompt(story: Story) -> str:
    """Ask Gemini for the story's cast, places and props, with a fixed look
    and voice for each, and which of them appear in every scene."""
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    voices = ", ".join(f"{v} ({VOICE_GENDER.get(v, '')})" for v in VOICES)
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
    return f"""You are a casting director and production designer.
Read this short film and list everything that must look and sound the same
in every shot. Visual style: {style["label"]}.

Idea: \"\"\"{story.idea.strip()}\"\"\"{lead}
Scenes:
{scenes}

Rules:
- Characters: the people (or creatures) who appear on screen, at most
  {SET_MAX_CHARACTERS}. "description": age, build, face, skin, hair; fixed
  wording, no actions. "outfit": what they wear in every scene. Each person
  is {NOT_FAMOUS}: avoid stock "handsome leading man" or "model" wording and
  give one or two distinctive details (greying temples, freckles, glasses,
  a crooked nose, a small scar).
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
- Give every item a short "key" (c1, c2, l1, p1 ...). In "scenes", one entry
  per scene in order: "cast" (keys on screen), "location" (key or ""),
  "props" (keys), "speaker" (key of who says a spoken line, else "").
- Write everything in English.

Return only JSON: {{"name": str, "characters": [{{"key": str, "name": str, "description": str, "outfit": str, "voice": {{"tts_voice": str, "style": str, "description": str}}}}], "narrator": {{"tts_voice": str, "style": str}} | null, "locations": [{{"key": str, "name": str, "description": str, "time_of_day": str}}], "props": [{{"key": str, "name": str, "description": str}}], "scenes": [{{"cast": [str], "location": str, "props": [str], "speaker": str}}]}}"""


def scene_regen_prompt(story: Story, index: int) -> str:
    before = (
        story.scenes[index - 1].visual if index > 0 else "(this is the first scene)"
    )
    after = (
        story.scenes[index + 1].visual
        if index + 1 < len(story.scenes)
        else "(this is the last scene)"
    )
    current = story.scenes[index]
    return f"""You are a film director. Rewrite scene {index + 1} of the film
"{story.title}" with a fresh idea that still fits between its neighbours.
Idea of the film: {story.idea}
Previous scene: {before}
Next scene: {after}
Current scene (replace it): {current.visual}
Narration in {story.language} (at most {max_words(current.duration)} words),
visual in English, one camera move from: {", ".join(CAMERA_IDS)}.
{_scene_speech_rule(story, current)}
Return only JSON: {{"narration": str, "spoken": bool, "visual": str, "camera": str}}"""


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
    """Who is on screen: the scene's cast looks, else the story's character."""
    cast = scene_cast(story_set, scene)
    if cast:
        return "; ".join(c.look() for c in cast)
    return story.character


# How frame_prompt names the take's first frame among the reference images.
SAME_TAKE_REF = "the earlier frame of this take"


def frame_prompt(
    story: Story,
    scene: Scene,
    has_reference: bool,
    story_set=None,
    ref_labels: list[str] | None = None,
    same_take: bool = False,
) -> str:
    """Image prompt for a storyboard frame. With a set, the scene's cast,
    place and props are described and each reference image is named
    (`ref_labels`, in image order). ``same_take``: the reference is the
    first frame of the continuous take this scene belongs to, so the room
    must stay as it is there."""
    style = STYLE_BY_ID.get(story.style, STYLES[0])
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
    cast = scene_cast(story_set, scene)
    who = _cast_text(story, scene, story_set)
    character = f" {'On screen' if cast else 'Main character'}: {who}." if who else ""
    loc = (
        story_set.location(scene.location_id)
        if story_set and scene.location_id
        else None
    )
    place = f" Place: {loc.look()}." if loc else ""
    people = ""
    if who:
        people = f" Every person is {NOT_FAMOUS}."
        if any("face" in label for label in ref_labels or []):
            people += " Keep each face exactly as in its face image."
    facing = (
        f" The speaker: {SPEAKER_FACING}."
        if scene.spoken and scene.narration.strip()
        else ""
    )
    return (
        f"{scene.visual}{character}{place}{facing} Style: {style['prompt']}. "
        f"Aspect ratio {story.aspect_ratio}, one single frame, no text, no captions."
        f"{people}{keep}{refs_sentence(ref_labels or [])}"
    )


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
) -> str:
    """Video prompt for a scene. ``continuing``: the clip continues the
    previous one (a continuous take), so it carries on the same person and
    voice. ``start_frame``: the scene's storyboard frame is attached, so the
    clip opens on it. No clip is told to end on the next scene's frame: it
    would spend its own line morphing into the next shot (the screen, the
    angle), so every scene's picture arrived seconds before its words. Each
    clip holds its own shot and the next one cuts in as its line starts.

    Every clip has its own sound. Narrated scenes ask for natural ambient
    sound only, because the narrator's voiceover and the music go on top.
    With a set, the scene's cast replaces the story's character text, the
    speaker's voice description is used word for word, and the reference
    images (`ref_labels`, in order) are named."""
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    cam = CAMERA_PRESETS.get(scene.camera, CAMERA_PRESETS["static"])["prompt"]
    cast_text = _cast_text(story, scene, story_set)
    base = f"{scene.visual} Camera: {cam or 'natural camera movement'}. Style: {style['prompt']}."
    if scene_cast(story_set, scene):
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
                f"Continue this exact shot without a cut: the same person{who}, "
                "outfit, place, lighting and camera, and the same voice, pace "
                f"and room sound as before. {base}"
            )
    if continuing and start_frame:
        base += (
            " Start exactly on the attached image (this scene's storyboard "
            "frame) and hold that shot: no cut, and the screens and signs keep "
            "what they show."
        )
    if not (scene.spoken and scene.narration.strip()):
        return (
            f"{base} Sound: natural ambient sound and sound effects of the "
            "scene only. No speech, dialogue, narration, singing or music."
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
        f'{story.language}: "{scene.narration.strip()}" '
        f"They speak in {voice}, the same voice in every scene. They are the only "
        "voice: no narrator, no other speakers, no voice-over. Clear, natural, "
        "lip-synced speech with light room sound. No music, no subtitles, no "
        "on-screen text."
    )


def default_music_prompt(story: Story) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
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
    """Lay out clips on a timeline with overlapping crossfades.

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
    for k, ((i, s), d) in enumerate(zip(usable, durs)):
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
        if k == 0:
            start, fade, trim = 0.0, 0.0, base
        elif extended:
            # Continuous take: a straight cut into the clip's new seconds.
            start, fade, trim = t, 0.0, base
        elif cut and not base:
            start, fade, trim = t, 0.0, head
        elif s.spoken or prev.spoken:
            # A crossfade would overlap speech with the next shot: cut instead.
            start, fade, trim = t, 0.0, base
        else:
            start, fade, trim = t - xf, xf, base
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
            )
        )
        t = start + d - trim
    return StitchPlan(segments=segments, crossfade=xf, total=round(t, 3))
