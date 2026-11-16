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
from dataclasses import asdict, dataclass, field

from config.default import Default
from config.veo_models import get_veo_model_config

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

STEPS: list[tuple[str, str, str]] = [
    # (id, label, Material icon)
    ("stories", "Stories", "collections_bookmark"),
    ("create", "Create", "edit_note"),
    ("scenario", "Scenario", "description"),
    ("storyboard", "Storyboard", "view_carousel"),
    ("editor", "Editor", "tune"),
    ("video", "Video", "movie"),
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


def supported_durations() -> list[int]:
    """Veo-supported clip lengths (seconds) for the configured story model."""
    cfg = Default()
    model = get_veo_model_config(cfg.STORY_VEO_MODEL_VERSION)
    if model and model.supported_durations:
        return list(model.supported_durations)
    if model:
        return list(range(model.min_duration, model.max_duration + 1))
    return [4, 6, 8]


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


@dataclass
class Story:
    """A saved story. Stored in Firestore `stories` (or the local JSON store)."""

    id: str = field(default_factory=new_id)
    owner: str = ""
    title: str = ""
    idea: str = ""
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
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @property
    def cover_uri(self) -> str:
        for s in self.scenes:
            if s.frame_uri:
                return s.frame_uri
        return ""

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
    snaps to a Veo-supported value, and the total length must fit
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
        notes.append(f"Scene length set to {d0}s (supported by Veo).")
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
) -> tuple[str, list[Scene]]:
    """Parse and validate the model's scenario JSON.

    Expected shape: {"title": str, "scenes": [{"narration", "visual", "camera"}]}.
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
        scenes.append(
            Scene(narration=narration, visual=visual, camera=camera, duration=duration)
        )
    if len(scenes) < scene_count:
        raise ScenarioError(f"Expected {scene_count} scenes, got {len(scenes)}.")
    return title[:120], scenes


def parse_single_scene(text: str, duration: int, camera_preset: str = "auto") -> Scene:
    """Parse one regenerated scene: {"narration", "visual", "camera"}."""
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
        json.dumps({"title": "x", "scenes": [data]}), 1, duration, camera_preset
    )
    return scenes[0]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def scenario_prompt(story: Story) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    cams = ", ".join(CAMERA_IDS)
    cam_rule = (
        f'Use the camera move "{story.camera}" for every scene.'
        if story.camera in CAMERA_IDS
        else f"Pick the best camera move for each scene from: {cams}."
    )
    return f"""You are a film director and screenwriter.
Turn the idea below into a short film of exactly {story.scene_count} scenes,
each about {story.duration} seconds long. Visual style: {style["label"]}.

Idea: \"\"\"{story.idea.strip()}\"\"\"

Rules:
- Write the title and every narration line in {story.language}.
- Narration: one short voiceover sentence per scene that can be spoken in
  under {story.duration} seconds.
- Visual: a detailed, self-contained description of what the camera sees
  (subject, action, setting, lighting). Keep the main character's look
  identical in every scene and describe it each time. Write visuals in English.
- {cam_rule}
- Build a clear beginning, middle and end.

Return only JSON: {{"title": str, "scenes": [{{"narration": str, "visual": str, "camera": str}}]}}"""


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
Narration in {story.language}, visual in English, one camera move from:
{", ".join(CAMERA_IDS)}.
Return only JSON: {{"narration": str, "visual": str, "camera": str}}"""


def frame_prompt(story: Story, scene: Scene, has_reference: bool) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    keep = (
        " Keep the same main character, wardrobe, palette and art style as the "
        "reference image."
        if has_reference
        else ""
    )
    character = f" Main character: {story.character}." if story.character else ""
    return (
        f"{scene.visual}{character} Style: {style['prompt']}. "
        f"Aspect ratio {story.aspect_ratio}, one single frame, no text, no captions.{keep}"
    )


def clip_prompt(story: Story, scene: Scene) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    cam = CAMERA_PRESETS.get(scene.camera, CAMERA_PRESETS["static"])["prompt"]
    return f"{scene.visual} Camera: {cam or 'natural camera movement'}. Style: {style['prompt']}."


def default_music_prompt(story: Story) -> str:
    style = STYLE_BY_ID.get(story.style, STYLES[0])
    return (
        f"Cinematic instrumental score for a short {style['label'].lower()} film: "
        f"{story.title or story.idea[:80]}. Warm, building, no vocals."
    )


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
        else float(s.duration)
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
        if k == 0:
            start, fade, trim = 0.0, 0.0, 0.0
        elif cut:
            start, fade, trim = t, 0.0, head
        else:
            start, fade, trim = t - xf, xf, 0.0
        segments.append(
            Segment(
                index=i,
                clip_uri=s.clip_uri,
                start=round(start, 3),
                duration=round(d - trim, 4),
                fade_in=fade,
                narration=s.narration,
                trim_head=round(trim, 4),
            )
        )
        t = start + d - trim
    return StitchPlan(segments=segments, crossfade=xf, total=round(t, 3))
