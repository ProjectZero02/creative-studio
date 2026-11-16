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

# Who speaks each scene's line: a narrator over the picture, or the person on
# screen (Veo renders the speech with lip sync). "auto" lets Gemini choose per
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
    # The same line in the story's second language (see Story.second_on).
    narration_alt: str = ""
    # True: the person on screen says `narration` to camera (Veo renders the
    # speech in the clip). False: a narrator voices it over the picture.
    spoken: bool = False
    # Second-language clip of a spoken scene (the speech is baked into the
    # video, so it is rendered again) and the clip and line it was made from.
    clip_alt_uri: str = ""
    clip_alt_key: str = ""
    # Clip whose last frame the second-language clip started from (the
    # previous scene's clip in that film), like continues_from.
    clip_alt_from: str = ""

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
    # Second-language version: same clips and music, narration translated
    # into alt_language and voiced again. Needs the voiceover on.
    second_on: bool = False
    # Who speaks (SPEECH_MODES) and the on-screen speaker's voice, described
    # the same way in every spoken clip so it stays consistent.
    speech_mode: str = "auto"
    speaker_voice: str = ""
    title_alt: str = ""
    final_alt_uri: str = ""
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

    def media_uris(self) -> list[str]:
        """Every stored media URI this story points at (empty ones skipped)."""
        uris = [self.reference_uri, self.final_uri, self.final_alt_uri]
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
        scenes.append(
            Scene(
                narration=narration,
                visual=visual,
                camera=camera,
                duration=duration,
                spoken=_spoken(raw.get("spoken"), narration, speech_mode),
            )
        )
    if len(scenes) < scene_count:
        raise ScenarioError(f"Expected {scene_count} scenes, got {len(scenes)}.")
    return title[:120], scenes


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
# Prompts
# ---------------------------------------------------------------------------


def _speech_rules(story: Story) -> str:
    voice = (
        '- "voice": one short English description of the on-screen speaker\'s '
        "voice that starts with their gender, e.g. \"a male voice, mid-30s, calm "
        "and confident, neutral American accent\". It is reused for every spoken scene so it "
        'sounds the same. Use "" if nobody speaks on camera.'
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
            "Each visual shows that person facing the camera and speaking.\n"
            + voice
        )
    return (
        "- Decide for each scene who speaks. If the idea features a person "
        "talking (a presenter, a speech, an interview, a conversation, a vlog), "
        'set "spoken" to true and write "narration" as the exact words that '
        "person says on camera, with the visual showing them speaking. Prefer "
        "on-camera speech whenever a speaking person is the point of the film. "
        'Otherwise set "spoken" to false and write a narrator voiceover line.\n'
        + voice
    )


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
- Narration: one short sentence per scene that can be spoken in under
  {story.duration} seconds (at most {max_words(story.duration)} words).
{_speech_rules(story)}
- Visual: a detailed, self-contained description of what the camera sees
  (subject, action, setting, lighting). Keep the main character's look
  identical in every scene and describe it each time. Write visuals in English.
- {cam_rule}
- Build a clear beginning, middle and end.

Return only JSON: {{"title": str, "voice": str, "scenes": [{{"narration": str, "spoken": bool, "visual": str, "camera": str}}]}}"""


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
            "screen says to camera, and the visual shows them speaking."
        )
    return (
        '"spoken" is true if the person on screen should say the line on '
        "camera, false for a narrator voiceover."
    )


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
    base = f"{scene.visual} Camera: {cam or 'natural camera movement'}. Style: {style['prompt']}."
    if not (scene.spoken and scene.narration.strip()):
        return base
    voice = story.speaker_voice or "a voice that matches their age and gender"
    who = f" ({story.character})" if story.character else ""
    return (
        f"{base} The person on screen{who} looks at the camera and says in "
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


def other_language(language: str) -> str:
    """The second language offered for a story: English for Arabic, else Arabic."""
    return "English" if language == "Arabic" else "Arabic"


def alt_story(story: Story) -> Story:
    """A copy of `story` as its second-language version (for voice, stitch and
    library): language, title and narration swapped, media unchanged."""
    return replace(
        story,
        language=story.alt_language,
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
    # The clip carries its own speech (keep its audio, no voiceover).
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
        elif s.spoken or prev.spoken:
            # A crossfade would overlap speech with the next shot: cut instead.
            start, fade, trim = t, 0.0, 0.0
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
                spoken=bool(s.spoken and s.narration.strip()),
                trim_head=round(trim, 4),
            )
        )
        t = start + d - trim
    return StitchPlan(segments=segments, crossfade=xf, total=round(t, 3))
