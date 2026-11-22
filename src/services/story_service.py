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
"""Story Studio service layer: every external call goes through here.

``VertexStoryBackend`` calls Gemini, Gemini Image, Gemini Omni, Lyria and Gemini TTS
through the repo's existing model modules (imported lazily, so demo mode and
tests never touch Google Cloud). ``MockStoryBackend`` produces a fake
scenario, painted placeholder frames, short motion clips, a synth music bed
and a tone "voiceover" on local disk with realistic delays, so the whole
wizard can be clicked through without credentials.

Both backends share :func:`make_film`, which lays the film out as a timeline
and renders it with ffmpeg, so stitching is exercised in demo mode too.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import tempfile
import time
import uuid
import wave
from typing import Protocol

import numpy as np

from common.analytics import get_logger
from common.error_handling import GenerationError
from common.identity import LOCAL_APP_ENVS
from config.default import Default
from services.story_models import (
    CAMERA_IDS,
    CASTING_SYSTEM,
    LANGUAGES,
    SAME_TAKE_REF,
    SCENARIO_SYSTEM,
    STYLE_BY_ID,
    Scene,
    StitchPlan,
    Story,
    apply_caps,
    clip_parts,
    clip_prompt,
    clip_refs,
    frame_refs,
    frame_prompt,
    regen_links,
    scenario_media,
    scenario_prompt,
    scenario_schema,
    scene_regen_prompt,
    scene_schema,
    set_build_prompt,
    set_schema,
    translation_prompt,
)

logger = get_logger(__name__)

LOCAL_MEDIA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), ".local", "story_media"
)
LOCAL_MEDIA_ROUTE = "/story-media"
LOCAL_SCHEME = "local://"


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------


def _has_gcp_credentials() -> bool:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    if os.environ.get("K_SERVICE"):  # Cloud Run always has a service account
        return True
    candidates = [
        os.path.join(
            os.environ.get("APPDATA", ""),
            "gcloud",
            "application_default_credentials.json",
        ),
        os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
    ]
    return any(p and os.path.isfile(p) for p in candidates)


def is_mock_mode() -> bool:
    """Demo mode: STORY_STUDIO_MOCK=true, or local APP_ENV without credentials."""
    flag = (Default().STORY_STUDIO_MOCK or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return (
        os.environ.get("APP_ENV", "") in LOCAL_APP_ENVS
    ) and not _has_gcp_credentials()


# ---------------------------------------------------------------------------
# URIs
# ---------------------------------------------------------------------------


def local_path(uri: str) -> str:
    """Filesystem path for a local:// URI (demo mode)."""
    rel = uri[len(LOCAL_SCHEME) :] if uri.startswith(LOCAL_SCHEME) else uri
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel.split("/"):
        raise ValueError("Bad local media path")
    return os.path.join(LOCAL_MEDIA_DIR, *rel.split("/"))


def display_url(uri: str) -> str:
    """Browser URL for a stored media URI (gs:// or local://)."""
    if not uri:
        return ""
    if uri.startswith(LOCAL_SCHEME):
        return f"{LOCAL_MEDIA_ROUTE}/{uri[len(LOCAL_SCHEME) :]}"
    if uri.startswith("gs://"):
        from common.utils import create_display_url

        return create_display_url(uri)
    return uri


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class StoryBackend(Protocol):
    name: str

    def write_scenario(self, story: Story, story_set=None, note: str = "") -> str: ...
    def live_settings(self, idea: str) -> dict: ...
    def write_set(self, story: Story) -> str: ...
    def generate_set_image(
        self, story_set, prompt: str, refs: list[str], aspect_ratio: str = "1:1"
    ) -> str: ...
    def voice_sample(self, story_set, character) -> str: ...
    def rewrite_scene(self, story: Story, index: int) -> str: ...
    def plan_fix(
        self, story: Story, request: str, scene: int, seconds: float | None
    ) -> str: ...
    def translate(self, story: Story) -> str: ...
    def translate_subtitles(self, story: Story, code: str) -> list[str]: ...
    def generate_frame(self, story: Story, index: int, reference_uri: str) -> str: ...
    def generate_clip(self, story: Story, index: int, start_frame_uri: str) -> str: ...
    def last_frame(self, story: Story, clip_uri: str, index: int) -> str: ...
    def generate_music(self, story: Story, prompt: str, seconds: float) -> str: ...
    def generate_voiceover(
        self, story: Story, index: int, text: str, voice=None
    ) -> str: ...
    def stitch(
        self, story: Story, plan: StitchPlan, music_uri: str, voice_uris: list[str]
    ) -> tuple[str, dict]: ...
    def extend_clip(
        self, story: Story, index: int, prev_clip_uri: str
    ) -> tuple[str, float]: ...
    def interaction_of(self, clip_uri: str) -> str: ...
    def render_timeline(self, story: Story, timeline: dict) -> str: ...
    def save_audio_upload(self, data: bytes, mime_type: str) -> str: ...
    def save_to_library(self, story: Story, final_uri: str, owner: str) -> str: ...
    def save_upload(self, data: bytes, mime_type: str) -> str: ...


_UPLOAD_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AUDIO_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
}
AUDIO_MIME_TYPES = sorted(_AUDIO_EXT)


# ---------------------------------------------------------------------------
# Shared media helpers (MoviePy)
# ---------------------------------------------------------------------------


def frame_size(aspect_ratio: str, long_side: int = 960) -> tuple[int, int]:
    short = int(round(long_side * 9 / 16 / 2) * 2)
    return (short, long_side) if aspect_ratio == "9:16" else (long_side, short)


def read_last_frame_png(video_path: str, out_path: str) -> str:
    """Save the last frame of a video as PNG (for scene-to-scene continuity)."""
    from moviepy import VideoFileClip
    from PIL import Image

    with VideoFileClip(video_path) as clip:
        t = max(0.0, (clip.duration or 0) - 0.05)
        frame = clip.get_frame(t)
    Image.fromarray(np.asarray(frame).astype("uint8")).save(out_path, "PNG")
    return out_path


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def stitch_local(
    clip_paths: list[str],
    plan: StitchPlan,
    out_path: str,
    music_path: str = "",
    voice_paths: list[str] | None = None,
    fps: int = 24,
) -> str:
    """Legacy MoviePy renderer (kept for old callers; films now render
    through :func:`make_film` and the timeline).

    Render the film: clips overlapped with crossfades, music bed, voiceover.

    ``clip_paths`` and ``voice_paths`` follow ``plan.segments`` order. Clip
    audio is dropped except for spoken segments, whose clip carries the
    on-camera speech. The music is
    looped/trimmed to the film and ducked under any speech; the voiceover
    starts just after each crossfade.
    """
    from moviepy import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        VideoFileClip,
        afx,
        vfx,
    )

    if len(clip_paths) != len(plan.segments) or not clip_paths:
        raise GenerationError("Nothing to stitch: some scenes have no clip.")
    opened = []
    try:
        sources = [
            VideoFileClip(p, audio=seg.spoken)
            for p, seg in zip(clip_paths, plan.segments)
        ]
        opened.extend(sources)
        size = sources[0].size
        layers = []
        speech = []
        for seg, src in zip(plan.segments, sources):
            clip = src.subclipped(
                seg.trim_head, min(seg.trim_head + seg.duration, src.duration)
            )
            if seg.spoken and clip.audio is not None:
                speech.append(clip.audio.with_start(seg.start))
            clip = clip.without_audio()
            if tuple(clip.size) != tuple(size):
                clip = clip.resized(new_size=size)
            if seg.fade_in > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(seg.fade_in)])
            layers.append(clip.with_start(seg.start))
        total = plan.total
        video = CompositeVideoClip(layers, size=size).with_duration(total)

        tracks = []
        has_voice = bool(voice_paths and any(voice_paths)) or bool(speech)
        if music_path:
            music = AudioFileClip(music_path)
            opened.append(music)
            if music.duration < total:
                music = music.with_effects([afx.AudioLoop(duration=total)])
            music = music.subclipped(0, total).with_effects(
                [
                    afx.MultiplyVolume(0.35 if has_voice else 0.85),
                    afx.AudioFadeIn(min(1.0, total / 4)),
                    afx.AudioFadeOut(min(1.5, total / 4)),
                ]
            )
            tracks.append(music)
        for seg, vpath in zip(plan.segments, voice_paths or []):
            if not vpath:
                continue
            voice = AudioFileClip(vpath)
            opened.append(voice)
            lead = min(seg.fade_in + 0.25, seg.duration / 3)
            room = max(0.5, seg.duration - lead - 0.1)
            if voice.duration > room:
                voice = voice.subclipped(0, room)
            tracks.append(voice.with_start(seg.start + lead))
        tracks.extend(speech)
        if tracks:
            video = video.with_audio(CompositeAudioClip(tracks).with_duration(total))
        video.write_videofile(
            out_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac" if tracks else None,
            audio=bool(tracks),
            preset="veryfast",
            threads=2,
            logger=None,
        )
        video.close()
    finally:
        for c in opened:
            try:
                c.close()
            except Exception:
                pass
    return out_path


def _write_wav(path: str, samples: np.ndarray, rate: int = 24000) -> str:
    data = np.clip(samples, -1.0, 1.0)
    pcm = (data * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def video_size(path: str) -> tuple[int, int] | None:
    """(width, height) of a video file, or None."""
    err = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, check=False
    ).stderr
    m = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    return (int(m.group(1)), int(m.group(2))) if m else None


def make_film(
    story: Story,
    plan: StitchPlan,
    music_uri: str,
    voice_uris: list[str],
    fetch,
    out_path: str,
) -> dict:
    """Lay the made media out as an editable timeline and render it.

    ``fetch(uri, local_path)`` copies a stored file to disk. Every clip keeps
    its own sound: spoken clips levelled to one dialogue loudness, narrated
    clips as a quiet ambient bed under the voiceover (the music ducks under
    the voice). The user's text overlays
    and music level from the story's previous timeline are kept.
    Returns the timeline (JSON-safe dict).
    """
    import shutil

    from services import story_timeline as tl_mod

    if not plan.segments:
        raise GenerationError("Nothing to stitch: some scenes have no clip.")
    with tempfile.TemporaryDirectory() as tmp:
        cache: dict[str, str] = {}

        def local(uri: str) -> str:
            if uri not in cache:
                ext = os.path.splitext(uri.split("?")[0])[1][:6] or ".bin"
                path = os.path.join(tmp, f"m{len(cache)}{ext}")
                fetch(uri, path)
                cache[uri] = path
            return cache[uri]

        clip_lengths: dict[int, float] = {}
        stills: dict[int, tuple[float, float]] = {}
        gains: dict[int, float] = {}
        voice_lengths: dict[int, float] = {}
        voices = {
            seg.index: v for seg, v in zip(plan.segments, voice_uris or []) if v
        }
        size = None
        for seg in plan.segments:
            path = local(seg.clip_uri)
            length, has_sound = tl_mod.probe(path)
            # The picture's own length (the file can run longer with its
            # sound) and any frozen frames at either end.
            picture, head, tail = tl_mod.clip_edges(path, seg.spoken and has_sound)
            clip_lengths[seg.index] = (
                picture or length or (seg.trim_head + seg.duration)
            )
            stills[seg.index] = (head, tail)
            size = size or video_size(path)
            # Every clip keeps its own sound: speech levelled for dialogue,
            # a narrated clip's ambience kept low under the narrator.
            gains[seg.index] = tl_mod.clip_gain(tl_mod.measure_lufs(path), seg.spoken)
            vuri = voices.get(seg.index)
            if vuri:
                voice_lengths[seg.index] = tl_mod.probe(local(vuri))[0]
        width, height = size or frame_size(story.aspect_ratio, 1280)
        music_len = tl_mod.probe(local(music_uri))[0] if music_uri else 0.0
        timeline = tl_mod.build_timeline(
            story,
            plan,
            width=width,
            height=height,
            clip_lengths=clip_lengths,
            voice_uris=voices,
            voice_lengths=voice_lengths,
            clip_gains=gains,
            clip_stills=stills,
            music_uri=music_uri,
            music_length=music_len,
        )
        timeline = tl_mod.keep_edits(timeline, story.timeline_json)
        tl_mod.render_timeline(
            timeline, lambda uri, dest: shutil.copyfile(local(uri), dest), out_path
        )
    return timeline


def _logo_args(story: Story) -> dict:
    """The brand logo for a render, when the story uses a brand kit."""
    if not story.brand_json:
        return {}
    from common import brand_kit

    kit = brand_kit.from_json(story.brand_json)
    if not kit["logo_uri"]:
        return {}
    return {"logo": kit["logo_uri"], "logo_corner": kit["corner"]}


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------

_STYLE_PALETTES = {
    "photographic": [(18, 32, 58), (196, 120, 72), (246, 205, 150)],
    "2d": [(36, 74, 120), (110, 182, 196), (250, 226, 170)],
    "3d": [(44, 28, 92), (122, 86, 214), (255, 176, 120)],
    "anime": [(24, 44, 96), (232, 122, 150), (255, 222, 196)],
    "claymation": [(70, 46, 32), (198, 120, 70), (240, 206, 150)],
}

_MOCK_BEATS = [
    ("opens on", "We meet our hero at the start of an ordinary day."),
    ("discovers", "Something unexpected changes everything."),
    ("sets out", "There is only one way forward."),
    ("struggles", "The path gets harder with every step."),
    ("finds help", "An unlikely friend appears."),
    ("faces the challenge", "Now comes the moment of truth."),
    ("triumphs", "Against the odds, it works."),
    ("returns home", "And nothing is quite the same again."),
]
_MOCK_PLACES = [
    "a misty harbour at sunrise",
    "a bustling market street",
    "a quiet forest path with long shadows",
    "a windswept hilltop under heavy clouds",
    "a warm workshop full of tools",
    "a rooftop overlooking the city lights",
    "a sunlit meadow by a river",
    "the same harbour at golden hour",
]


def _mock_cast(story: Story, hero: str, spoken: bool) -> dict:
    """The demo scenario's cast: the hero and up to three of the places."""
    look = story.character.strip() or (
        f"the {hero}, early 30s, medium build, warm brown eyes, a small scar on "
        "the chin"
    )
    places = min(3, max(1, story.scene_count))
    return {
        "characters": [
            {
                "key": "c1",
                "name": hero.title(),
                "description": look,
                "outfit": "a weathered olive jacket over a grey shirt",
                "voice": {
                    "tts_voice": "Puck",
                    "style": "warm, unhurried",
                    "description": "a male voice, early 30s, warm and steady",
                },
            }
        ],
        "narrator": None if spoken else {"tts_voice": "Kore", "style": "warm"},
        "locations": [
            {
                "key": f"l{i + 1}",
                "name": _MOCK_PLACES[i % len(_MOCK_PLACES)].capitalize(),
                "description": f"{_MOCK_PLACES[i % len(_MOCK_PLACES)]}, soft light",
                "time_of_day": "golden hour",
            }
            for i in range(places)
        ],
        "props": [],
    }


def _hero_from_idea(idea: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", idea or "")
    stop = {
        "a",
        "an",
        "the",
        "of",
        "and",
        "who",
        "that",
        "with",
        "in",
        "on",
        "to",
        "for",
        "about",
    }
    key = [w for w in words if w.lower() not in stop][:3]
    return " ".join(key).lower() or "a curious traveller"


class MockStoryBackend:
    """Local demo backend with realistic delays. No network calls."""

    name = "demo"

    def __init__(self, speed: float | None = None):
        env = os.environ.get("STORY_STUDIO_MOCK_SPEED")
        self.speed = speed if speed is not None else float(env or 1.0)

    # -- helpers --
    def _sleep(self, lo: float, hi: float) -> None:
        if self.speed > 0:
            time.sleep(random.uniform(lo, hi) * self.speed)

    def _new_uri(self, story: Story, name: str) -> tuple[str, str]:
        rel = f"{story.id}/{name}_{uuid.uuid4().hex[:8]}"
        path = local_path(LOCAL_SCHEME + rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return LOCAL_SCHEME + rel, path

    # -- scenario --
    def write_scenario(self, story: Story, story_set=None, note: str = "") -> str:
        self._sleep(1.6, 2.6)
        hero = _hero_from_idea(story.idea)
        n = story.scene_count
        beats = [
            _MOCK_BEATS[round(i * (len(_MOCK_BEATS) - 1) / max(1, n - 1))]
            for i in range(n)
        ]
        # Demo stand-in for Gemini's choice of who speaks.
        talky = ("present", "speech", "interview", "talk", "vlog", "pitch")
        spoken = story.speech_mode == "on_camera" or (
            story.speech_mode == "auto" and any(w in story.idea.lower() for w in talky)
        )
        scenes = []
        for i, (verb, line) in enumerate(beats):
            cam = (
                story.camera
                if story.camera in CAMERA_IDS
                else CAMERA_IDS[i % len(CAMERA_IDS)]
            )
            scenes.append(
                {
                    "narration": line,
                    "visual": f"The {hero} {verb} in {_MOCK_PLACES[i % len(_MOCK_PLACES)]}, "
                    "same outfit and face as before, soft cinematic light.",
                    "camera": cam,
                    "spoken": spoken,
                }
            )
        first = re.split(r"[.,;:!?]| and | who | that ", story.idea.strip())[0].strip()
        words, title = first.split(), ""
        for w in words:
            if len(title) + len(w) + 1 > 44:
                break
            title = f"{title} {w}".strip()
        title = (title or "Untitled story")[0].upper() + (title or "Untitled story")[1:]
        voice = "a warm, confident voice, mid-30s" if spoken else ""
        style_label = STYLE_BY_ID.get(story.style, {"label": "cinematic"})[
            "label"
        ].lower()
        brief = (
            f"{story.idea.strip().rstrip('.')}. A {n}-scene {style_label} short film "
            f"about the {hero}, warm and hopeful in tone, with a clear beginning, "
            "middle and end, for a general audience."
        )
        reply = {"brief": brief, "title": title, "voice": voice, "scenes": scenes}
        if story_set is not None:  # a saved set: cast it in every scene
            lead = story_set.on_screen()[:1]
            places = story_set.locations
            for i, sc in enumerate(scenes):
                sc["cast"] = [c.name for c in lead]
                sc["location"] = places[i % len(places)].name if places else ""
                sc["speaker"] = lead[0].name if lead and sc["spoken"] else ""
                if lead:
                    sc["visual"] = sc["visual"].replace(f"The {hero}", lead[0].name, 1)
        else:  # demo stand-in for the writer casting the film itself
            reply.update(_mock_cast(story, hero, spoken))
            for i, sc in enumerate(scenes):
                sc["cast"] = ["c1"]
                sc["location"] = f"l{i % 3 + 1}" if n > 1 else "l1"
                sc["props"] = []
                sc["speaker"] = "c1" if sc["spoken"] else ""
        return json.dumps(reply)

    def live_settings(self, idea: str) -> dict:
        """Demo stand-in for the live settings model: the rules pass."""
        from services.story_autoset import infer_settings

        return infer_settings(idea)

    def rewrite_scene(self, story: Story, index: int) -> str:
        self._sleep(1.0, 1.8)
        hero = _hero_from_idea(story.idea)
        place = random.choice(_MOCK_PLACES)
        return json.dumps(
            {
                "narration": random.choice([b[1] for b in _MOCK_BEATS]),
                "visual": f"A new angle: the {hero} pauses in {place}, looking toward the horizon.",
                "camera": random.choice(CAMERA_IDS),
            }
        )

    def plan_fix(
        self, story: Story, request: str, scene: int, seconds: float | None
    ) -> str:
        """Demo stand-in for the fix planner: keyword rules, same JSON."""
        from services.story_fix import scene_at
        from services.story_timeline import normalize

        self._sleep(0.6, 1.2)
        text = request.lower()
        m = re.search(r"scene\s+(\d+)", text)
        if m:
            n = int(m.group(1))
        elif seconds is not None and story.timeline_json:
            n = scene_at(normalize(story.timeline_json), seconds) + 1
        else:
            n = scene + 1 if scene >= 0 else 0
        if not 1 <= n <= len(story.scenes):
            n = 0
        if "music" in text or "song" in text:
            return json.dumps(
                {
                    "action": "music",
                    "summary": "Use calmer music.",
                    "reason": "The request is about the music.",
                    "music_prompt": "Soft, warm piano with light strings, slow tempo.",
                }
            )
        if not n:
            return json.dumps(
                {"action": "none", "question": "Which scene do you mean?"}
            )
        if any(w in text for w in ("blank", "black", "frozen", "freeze", "end")):
            return json.dumps(
                {
                    "action": "timeline",
                    "summary": f"Cut the last second of scene {n}.",
                    "reason": "The clip holds a still or empty picture at its end.",
                    "scene": n,
                    "timeline": [
                        {"op": "trim", "scene": n, "cut_start": 0, "cut_end": 1.0}
                    ],
                }
            )
        if any(w in text for w in ("remove", "drop", "delete")):
            return json.dumps(
                {
                    "action": "timeline",
                    "summary": f"Remove scene {n}.",
                    "reason": "The viewer does not want this scene.",
                    "scene": n,
                    "timeline": [{"op": "remove", "scene": n}],
                }
            )
        cur = story.scenes[n - 1]
        if any(w in text for w in ("look", "face", "colour", "color", "picture")):
            return json.dumps(
                {
                    "action": "repaint_frame",
                    "summary": f"Paint scene {n} again, closer to the rest of the film.",
                    "reason": "The picture does not match.",
                    "scene": n,
                    "visual": cur.visual + " Same character and palette as scene 1.",
                }
            )
        return json.dumps(
            {
                "action": "rewrite_scene",
                "summary": f"Rewrite scene {n}.",
                "reason": "The viewer dislikes what happens in it.",
                "scene": n,
                "narration": random.choice([b[1] for b in _MOCK_BEATS]),
            }
        )

    def translate_subtitles(self, story: Story, code: str) -> list[str]:
        self._sleep(0.3, 0.6)
        return [f"[{code}] {sc.narration}" if sc.narration else "" for sc in story.scenes]

    def translate(self, story: Story) -> str:
        self._sleep(0.8, 1.4)
        tag = f"[{story.alt_language}] "
        return json.dumps(
            {
                "title": tag + (story.title or "Untitled"),
                "lines": [
                    tag + sc.narration if sc.narration else "" for sc in story.scenes
                ],
            },
            ensure_ascii=False,
        )

    # -- frames --
    def generate_frame(self, story: Story, index: int, reference_uri: str) -> str:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        self._sleep(1.8, 3.4)
        w, h = frame_size(story.aspect_ratio, 960)
        top, mid, glow = _STYLE_PALETTES.get(
            story.style, _STYLE_PALETTES["photographic"]
        )
        rng = random.Random(f"{story.id}-{index}-{uuid.uuid4().hex[:4]}")
        # Shift the sky a little per scene so a storyboard reads as different shots.
        shift = (index * 37) % 90 - 45
        mid = tuple(
            max(0, min(255, c + shift * (1 if k == index % 3 else -0.4)))
            for k, c in enumerate(mid)
        )
        y = np.linspace(0, 1, h)[:, None, None]
        grad = (np.array(top) * (1 - y) + np.array(mid) * y).repeat(w, axis=1)
        img = Image.fromarray(grad.astype("uint8"), "RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        # sun / moon
        cx, cy = int(w * rng.uniform(0.25, 0.75)), int(h * rng.uniform(0.22, 0.45))
        r = int(min(w, h) * rng.uniform(0.09, 0.15))
        for k in range(6, 0, -1):
            a = int(28 / k)
            draw.ellipse(
                (
                    cx - r * k * 0.6 - r,
                    cy - r * k * 0.6 - r,
                    cx + r * k * 0.6 + r,
                    cy + r * k * 0.6 + r,
                ),
                fill=(*glow, a),
            )
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*glow, 255))
        # layered hills
        for layer in range(4):
            base = h * (0.55 + layer * 0.11)
            amp = h * (0.08 - layer * 0.012)
            phase = rng.uniform(0, math.tau)
            freq = rng.uniform(1.2, 2.6)
            pts = [(0, h)]
            for x in range(0, w + 16, 16):
                pts.append((x, base + amp * math.sin(phase + freq * x / w * math.tau)))
            pts.append((w, h))
            shade = 0.55 - layer * 0.13
            color = tuple(int(c * shade) for c in top)
            draw.polygon(pts, fill=(*color, 255))
        # silhouette "character" for continuity feel
        hx = int(w * (0.3 + 0.4 * ((index * 0.37) % 1)))
        hy = int(h * 0.72)
        s = int(h * 0.09)
        draw.ellipse(
            (hx - s * 0.32, hy - s * 1.9, hx + s * 0.32, hy - s * 1.26),
            fill=(10, 10, 14, 235),
        )
        draw.rounded_rectangle(
            (hx - s * 0.42, hy - s * 1.25, hx + s * 0.42, hy),
            radius=int(s * 0.3),
            fill=(10, 10, 14, 235),
        )
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        # vignette
        vy, vx = np.ogrid[:h, :w]
        d = np.sqrt(((vx - w / 2) / (w / 2)) ** 2 + ((vy - h / 2) / (h / 2)) ** 2)
        vig = np.clip(1.15 - 0.45 * d, 0.45, 1.0)[..., None]
        arr = (np.asarray(img).astype("float32") * vig).clip(0, 255).astype("uint8")
        img = Image.fromarray(arr, "RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        try:
            font = ImageFont.load_default(size=max(14, h // 30))
        except TypeError:  # older Pillow
            font = ImageFont.load_default()
        label = f"SCENE {index + 1}  ·  DEMO FRAME"
        draw.rounded_rectangle(
            (16, 16, 16 + len(label) * (h // 52) + 28, 16 + h // 18),
            radius=8,
            fill=(0, 0, 0, 120),
        )
        draw.text((30, 20), label, fill=(255, 255, 255, 230), font=font)
        uri, path = self._new_uri(story, f"frame{index + 1}")
        # JPEG keeps demo frames small (~60 KB) so the storyboard loads fast.
        uri, path = uri + ".jpg", path + ".jpg"
        img.save(path, "JPEG", quality=84, optimize=True, progressive=True)
        return uri

    # -- sets --
    def write_set(self, story: Story) -> str:
        """Demo stand-in for the casting call: the hero of the idea, up to
        three of the scenes' places and one prop."""
        self._sleep(1.2, 2.0)
        hero = _hero_from_idea(story.idea)
        words = hero.split()
        name = (
            (words[1] if len(words) > 1 else words[0]).capitalize() if words else "Hero"
        )
        characters = [
            {
                "key": "c1",
                "name": name,
                "description": f"the {hero}, mid-30s, friendly face, short dark hair",
                "outfit": "a weathered blue jacket and boots",
                "voice": {
                    "tts_voice": story.voice_name,
                    "style": "warm, unhurried",
                    "description": "a warm, confident voice, mid-30s, neutral accent",
                },
            }
        ]
        if " and " in f" {story.idea.lower()} ":
            characters.append(
                {
                    "key": "c2",
                    "name": "Sam",
                    "description": "a wiry friend in their 20s, curly red hair",
                    "outfit": "a yellow raincoat",
                    "voice": {
                        "tts_voice": "Puck",
                        "style": "quick, upbeat",
                        "description": "a bright male voice, mid-20s, quick and upbeat",
                    },
                }
            )
        n_places = min(3, max(1, story.scene_count))
        locations = [
            {
                "key": f"l{k + 1}",
                "name": _MOCK_PLACES[k].split(" ", 1)[1].split(" at ")[0].capitalize(),
                "description": _MOCK_PLACES[k],
                "time_of_day": "",
            }
            for k in range(n_places)
        ]
        scenes = []
        for i, sc in enumerate(story.scenes):
            cast = ["c1"] + (["c2"] if len(characters) > 1 and i % 2 else [])
            scenes.append(
                {
                    "cast": cast,
                    "location": f"l{i % n_places + 1}",
                    "props": ["p1"] if i == 1 else [],
                    "speaker": "c1" if sc.spoken else "",
                }
            )
        return json.dumps(
            {
                "name": f"{story.title or name} set",
                "characters": characters,
                "narrator": {"tts_voice": story.voice_name, "style": "warm and clear"},
                "locations": locations,
                "props": [
                    {
                        "key": "p1",
                        "name": "Lantern",
                        "description": "a brass storm lantern",
                    }
                ],
                "scenes": scenes,
            }
        )

    def generate_set_image(
        self, story_set, prompt: str, refs: list[str], aspect_ratio: str = "1:1"
    ) -> str:
        """A placeholder reference image: a figure for characters (3:4 and
        1:1 faces), a landscape for locations (16:9), an object otherwise."""
        from PIL import Image, ImageDraw, ImageFont

        self._sleep(1.0, 2.2)
        w, h = {"3:4": (480, 640), "16:9": (768, 432)}.get(aspect_ratio, (512, 512))
        top, mid, glow = _STYLE_PALETTES.get(
            story_set.style, _STYLE_PALETTES["photographic"]
        )
        rng = random.Random(prompt + uuid.uuid4().hex[:4])
        y = np.linspace(0, 1, h)[:, None, None]
        if aspect_ratio == "16:9":
            grad = (np.array(top) * (1 - y) + np.array(mid) * y).repeat(w, axis=1)
        else:  # studio grey, like the real prompt asks for
            grad = np.array((214, 216, 220)) * (1 - y) + np.array((168, 170, 176)) * y
            grad = grad.repeat(w, axis=1)
        img = Image.fromarray(grad.astype("uint8"), "RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        tint = tuple(int(c) for c in mid)
        if aspect_ratio == "16:9":
            for layer in range(3):
                base = h * (0.55 + layer * 0.14)
                phase = rng.uniform(0, math.tau)
                pts = (
                    [(0, h)]
                    + [
                        (x, base + h * 0.07 * math.sin(phase + 2 * x / w * math.tau))
                        for x in range(0, w + 16, 16)
                    ]
                    + [(w, h)]
                )
                shade = 0.55 - layer * 0.15
                draw.polygon(pts, fill=(*(int(c * shade) for c in top), 255))
            draw.ellipse(
                (w * 0.7, h * 0.15, w * 0.8, h * 0.15 + w * 0.1), fill=(*glow, 255)
            )
        elif (
            aspect_ratio == "3:4"
            or "face" in prompt.lower()
            or "person" in prompt.lower()
        ):
            face = "close-up of the face" in prompt
            cx = w // 2
            head = int(w * (0.22 if face else 0.09))
            hy = int(h * (0.42 if face else 0.2))
            draw.ellipse(
                (cx - head, hy - head, cx + head, hy + head), fill=(*glow, 255)
            )
            body_top = hy + head + 4
            body_w = int(head * (1.6 if face else 1.5))
            body_bottom = h if face else int(h * 0.62)
            draw.rounded_rectangle(
                (cx - body_w, body_top, cx + body_w, body_bottom),
                radius=head // 2,
                fill=(*tint, 255),
            )
            if not face:
                draw.rectangle(
                    (cx - body_w + 6, body_bottom, cx - 6, int(h * 0.92)),
                    fill=(40, 44, 60, 255),
                )
                draw.rectangle(
                    (cx + 6, body_bottom, cx + body_w - 6, int(h * 0.92)),
                    fill=(40, 44, 60, 255),
                )
        else:
            r = int(w * 0.22)
            draw.rounded_rectangle(
                (w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r),
                radius=r // 3,
                fill=(*tint, 255),
            )
        try:
            font = ImageFont.load_default(size=max(12, h // 30))
        except TypeError:  # older Pillow
            font = ImageFont.load_default()
        label = "DEMO SET IMAGE" + ("  ·  FROM REFERENCE" if refs else "")
        draw.rounded_rectangle(
            (12, 12, 24 + len(label) * (h // 52 + 2), 14 + h // 18),
            radius=6,
            fill=(0, 0, 0, 120),
        )
        draw.text((20, 15), label, fill=(255, 255, 255, 230), font=font)
        rel = f"story_sets/{story_set.id}/img_{uuid.uuid4().hex[:10]}.jpg"
        path = local_path(LOCAL_SCHEME + rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path, "JPEG", quality=84, optimize=True)
        return LOCAL_SCHEME + rel

    def voice_sample(self, story_set, character) -> str:
        from services.story_sets import voice_sample_text

        self._sleep(0.5, 1.0)
        rate = 24000
        text = voice_sample_text(character)
        t = np.arange(int(rate * min(5.0, 0.33 * len(text.split()) + 0.4))) / rate
        pitch = 150 + 40 * (sum(map(ord, character.voice.tts_voice)) % 5)
        tone = (
            0.18
            * (0.5 + 0.5 * np.sin(2 * math.pi * 3.2 * t) ** 2)
            * np.sin(2 * math.pi * pitch * t)
        )
        rel = f"story_sets/{story_set.id}/voice_{uuid.uuid4().hex[:10]}.wav"
        path = local_path(LOCAL_SCHEME + rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_wav(path, tone, rate)
        return LOCAL_SCHEME + rel

    # -- clips --
    def generate_clip(self, story: Story, index: int, start_frame_uri: str) -> str:
        from moviepy import VideoClip
        from PIL import Image

        self._sleep(1.5, 3.0)
        scene = story.scenes[index]
        src = Image.open(local_path(start_frame_uri)).convert("RGB")
        w, h = frame_size(story.aspect_ratio, 640)
        big = src.resize((int(w * 1.25), int(h * 1.25)), Image.LANCZOS)
        bw, bh = big.size
        cam = scene.camera
        rng = random.Random(index)

        def make_frame(t: float):
            p = t / max(0.1, scene.duration)
            zoom = 1.0
            ox, oy = 0.5, 0.5
            if cam == "dolly_in":
                zoom = 1.0 + 0.2 * p
            elif cam == "orbit":
                ox = 0.15 + 0.7 * p
            elif cam == "crane_up":
                oy = 0.85 - 0.7 * p
            elif cam == "handheld":
                ox = 0.5 + 0.03 * math.sin(t * 5.1 + rng.random())
                oy = 0.5 + 0.03 * math.cos(t * 4.3)
            else:
                zoom = 1.0 + 0.03 * p
            cw, ch = int(w / zoom), int(h / zoom)
            x0 = int((bw - cw) * ox)
            y0 = int((bh - ch) * oy)
            crop = big.crop((x0, y0, x0 + cw, y0 + ch)).resize((w, h), Image.BILINEAR)
            return np.asarray(crop)

        clip = VideoClip(make_frame, duration=float(scene.duration))
        uri, path = self._new_uri(story, f"clip{index + 1}")
        uri, path = uri + ".mp4", path + ".mp4"
        clip.write_videofile(
            path, fps=12, codec="libx264", audio=False, preset="ultrafast", logger=None
        )
        clip.close()
        return uri

    def last_frame(self, story: Story, clip_uri: str, index: int) -> str:
        uri, path = self._new_uri(story, f"lastframe{index + 1}")
        read_last_frame_png(local_path(clip_uri), path + ".png")
        return uri + ".png"

    # -- audio --
    def generate_music(self, story: Story, prompt: str, seconds: float) -> str:
        self._sleep(1.5, 2.5)
        rate = 24000
        n = int(rate * max(4.0, seconds + 1))
        t = np.arange(n) / rate
        chords = [
            (220.0, 277.18, 329.63),
            (196.0, 246.94, 293.66),
            (174.61, 220.0, 261.63),
            (196.0, 246.94, 329.63),
        ]
        out = np.zeros(n)
        bar = 2.0
        for i, chord in enumerate(chords * int(math.ceil(seconds / (bar * 4) + 1))):
            s, e = int(i * bar * rate), int((i + 1) * bar * rate)
            if s >= n:
                break
            e = min(e, n)
            seg = t[s:e] - t[s]
            env = np.minimum(1, seg / 0.4) * np.exp(-seg * 0.35)
            for f in chord:
                out[s:e] += 0.12 * env * np.sin(2 * math.pi * f * t[s:e])
        uri, path = self._new_uri(story, "music")
        _write_wav(path + ".wav", out, rate)
        return uri + ".wav"

    def generate_voiceover(
        self, story: Story, index: int, text: str, voice=None
    ) -> str:
        self._sleep(0.8, 1.6)
        rate = 24000
        words = max(1, len(text.split()))
        dur = min(story.scenes[index].duration - 1.0, 0.33 * words + 0.4)
        n = int(rate * max(0.8, dur))
        t = np.arange(n) / rate
        syll = 0.5 + 0.5 * np.sin(2 * math.pi * 3.2 * t) ** 2
        tone = (
            0.18
            * syll
            * np.sin(2 * math.pi * (180 + 25 * np.sin(2 * math.pi * 0.7 * t)) * t)
        )
        uri, path = self._new_uri(story, f"voice{index + 1}")
        _write_wav(path + ".wav", tone, rate)
        return uri + ".wav"

    # -- stitch --
    def stitch(
        self, story: Story, plan: StitchPlan, music_uri: str, voice_uris: list[str]
    ) -> tuple[str, dict]:
        import shutil

        uri, path = self._new_uri(story, "film")
        timeline = make_film(
            story,
            plan,
            music_uri,
            voice_uris,
            lambda u, dest: shutil.copyfile(local_path(u), dest),
            path + ".mp4",
        )
        return uri + ".mp4", timeline

    def extend_clip(
        self, story: Story, index: int, prev_clip_uri: str
    ) -> tuple[str, float]:
        """Demo stand-in for an Omni continuation: a new clip from the scene's
        storyboard frame (or the previous clip's last frame without one)."""
        start = story.scenes[index].frame_uri or self.last_frame(
            story, prev_clip_uri, index
        )
        return self.generate_clip(story, index, start), 0.0

    def interaction_of(self, clip_uri: str) -> str:
        """Demo clips have no Omni thread."""
        return ""

    def render_timeline(self, story: Story, timeline: dict) -> str:
        import shutil

        from services.story_timeline import render_timeline

        self._sleep(0.5, 1.0)
        uri, path = self._new_uri(story, "film")
        render_timeline(
            timeline,
            lambda u, dest: shutil.copyfile(local_path(u), dest),
            path + ".mp4",
            **_logo_args(story),
        )
        return uri + ".mp4"

    def save_audio_upload(self, data: bytes, mime_type: str) -> str:
        ext = _AUDIO_EXT.get(mime_type)
        if not ext:
            raise GenerationError("Use an MP3, WAV, M4A or OGG audio file.")
        rel = f"uploads/music_{uuid.uuid4().hex[:10]}.{ext}"
        path = local_path(LOCAL_SCHEME + rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return LOCAL_SCHEME + rel

    def save_to_library(self, story: Story, final_uri: str, owner: str) -> str:
        self._sleep(0.3, 0.6)
        return "demo-library-item"

    def save_upload(self, data: bytes, mime_type: str) -> str:
        ext = _UPLOAD_EXT.get(mime_type)
        if not ext:
            raise GenerationError("Use a PNG, JPEG or WebP image.")
        rel = f"uploads/ref_{uuid.uuid4().hex[:10]}.{ext}"
        path = local_path(LOCAL_SCHEME + rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return LOCAL_SCHEME + rel


# ---------------------------------------------------------------------------
# Vertex AI backend (real mode)
# ---------------------------------------------------------------------------


def _gcs_fetch(uri: str, path: str) -> None:
    """Copy a gs:// object to a local file."""
    from common.storage import download_from_gcs

    with open(path, "wb") as f:
        f.write(download_from_gcs(uri))


def _media_mime(uri: str) -> str:
    """MIME type of a story asset from its extension (images, films, audio)."""
    ext = uri.rsplit(".", 1)[-1].lower() if "." in uri else ""
    return {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
    }.get(ext) or _image_mime(uri)


def _image_mime(uri: str) -> str:
    return "image/jpeg" if uri.lower().split("?")[0].endswith((".jpg", ".jpeg")) else "image/png"


NARRATOR_STYLE = "Narrate warmly and clearly, like a short film voiceover."


def _tts_style(voice) -> str:
    """The TTS style prompt: a set voice's own style, else the default."""
    style = (getattr(voice, "style", "") or "").strip()
    return f"Speak {style}." if style else NARRATOR_STYLE


# Omni's extend task adds at most this many seconds to a video.
OMNI_EXTEND_MAX_SECONDS = 10


def clip_reference_cap() -> int:
    """Most reference images per clip: the video model's limit, capped by
    STORY_MAX_CLIP_REFERENCES (Omni's real cap is unconfirmed)."""
    from config.omni_models import get_omni_model_config

    cfg = Default()
    try:
        model_cap = get_omni_model_config(cfg.STORY_VIDEO_MODEL).max_reference_images
    except Exception:  # unknown model id: be conservative
        model_cap = 3
    return max(1, min(model_cap, cfg.STORY_MAX_CLIP_REFERENCES))


def clip_inputs(
    story: Story,
    scene: Scene,
    start_frame_uri: str,
    story_set=None,
) -> dict:
    """Omni mode and media for a scene's first clip (not a continuation).

    A clip always opens on the picture it is given, so the video follows the
    storyboard: image to video from the frame (the storyboard frame, or the
    previous clip's last frame with continuity). The storyboard frames are painted
    from the set's faces, places and props (and the story's character
    reference), so those stay in the picture. Only a clip with no frame at
    all is made as reference to video from the set (capped, see
    clip_reference_cap) or the character reference. `ref_labels` names each
    reference for the prompt (pop it before building the request).
    """
    from models.requests import APIReferenceImage

    refs = (
        clip_refs(story_set, scene, "", clip_reference_cap())
        if story_set is not None and not start_frame_uri
        else []
    )
    if any(r.group != "frame" for r in refs):
        return {
            "omni_mode": "ref2v",
            "r2v_references": [
                APIReferenceImage(gcs_uri=r.uri, mime_type=_image_mime(r.uri))
                for r in refs
            ],
            "ref_labels": [r.label for r in refs],
        }
    if story.reference_uri and not start_frame_uri:
        return {
            "omni_mode": "ref2v",
            "r2v_references": [
                APIReferenceImage(
                    gcs_uri=story.reference_uri,
                    mime_type=_image_mime(story.reference_uri),
                )
            ],
        }
    if start_frame_uri:
        return {
            "omni_mode": "i2v",
            "reference_image_gcs": start_frame_uri,
            "reference_image_mime_type": _image_mime(start_frame_uri),
        }
    return {"omni_mode": "t2v"}


def _turn(prompt: str, clip_uri: str) -> list[dict]:
    """One Omni thread turn: the prompt (user) and the clip it made (model)."""
    return [
        {"type": "user_input", "content": [{"type": "text", "text": prompt}]},
        {
            "type": "model_output",
            "content": [
                {"type": "video", "gcs_uri": clip_uri, "mime_type": "video/mp4"}
            ],
        },
    ]


def join_plan(lengths: list[float]) -> list[int]:
    """Which parts of a lengthened scene to join, by index. An extension
    turn may return only its new seconds or the whole video so far; a part
    longer than everything before it is the whole video and replaces it."""
    keep: list[int] = []
    total = 0.0
    for i, length in enumerate(lengths):
        if keep and length > total + 1.0:
            keep, total = [i], length
        else:
            keep.append(i)
            total += length
    return keep


# Waits between tries of a call that failed with a passing service error
# (500, 502, 503, timeouts). A third failure is reported to the user.
TRANSIENT_RETRY_WAITS = (3.0, 8.0)


def _retry_transient(fn, what: str):
    """Run ``fn``, retrying passing service errors (see classify_error)."""
    from common.error_handling import classify_error

    for wait in (*TRANSIENT_RETRY_WAITS, None):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            retryable = (
                classify_error(exc).get("retryable") or "timed out" in str(exc).lower()
            )
            if wait is None or not retryable:
                raise
            logger.warning(
                "Story Studio: %s failed (%s), retrying in %.0f s.", what, exc, wait
            )
            time.sleep(wait)
    return None


def concat_args(
    paths: list[str], has_audio: list[bool], lengths: list[float], out: str
) -> list[str]:
    """ffmpeg argv that joins clips end to end (silence for a clip with no
    sound), re-encoded so clips from different turns always fit together."""
    args = [_ffmpeg(), "-v", "error", "-y"]
    for p in paths:
        args += ["-i", p]
    chains, inputs = [], []
    for i, (audio, secs) in enumerate(zip(has_audio, lengths, strict=True)):
        chains.append(f"[{i}:v]setsar=1,fps=24[v{i}]")
        if audio:
            chains.append(f"[{i}:a]aresample=48000[a{i}]")
        else:
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{secs:.3f}[a{i}]")
        inputs.append(f"[v{i}][a{i}]")
    graph = (
        ";".join(chains)
        + ";"
        + "".join(inputs)
        + f"concat=n={len(paths)}:v=1:a=1[v][a]"
    )
    return args + [
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        out,
    ]


LOOKALIKE_MESSAGE = (
    "Gemini Omni turned this scene down because the person in its storyboard "
    "frame looks like a real public figure. Regenerate this scene's frame (or "
    "the character's face in the set), then retry."
)


def is_lookalike_refusal(exc: Exception) -> bool:
    """Omni refused the input because a face looks like a well-known person
    ("This input contains certain prominent individuals ...")."""
    return "prominent individual" in str(exc).lower()


def frame_parts(*uris: str) -> list[dict]:
    """Image parts of an Omni thread turn, in order (empty URIs skipped)."""
    return [{"type": "image", "uri": u, "mime_type": _image_mime(u)} for u in uris if u]


def take_frame(story: Story, index: int) -> str:
    """The storyboard frame that opens the continuous take scene `index`
    continues ("" when the scene starts its own shot)."""
    if not story.continues_take(index):
        return ""
    return story.scenes[story.take_start(index)].frame_uri


def take_turn_frame(story: Story, index: int, first: bool) -> str:
    """Storyboard frame sent with scene `index`'s turn of its take, which the
    turn opens on. The take's first clip only opens on its frame when it was
    made fresh from it (not from the previous clip's last frame)."""
    sc = story.scenes[index]
    return sc.frame_uri if not (first and sc.continues_from) else ""


def take_history(
    story: Story, index: int, prev_clip_uri: str, story_set=None
) -> list[dict]:
    """The Omni thread of scene `index`'s continuous take so far: each earlier
    scene's prompt and storyboard frames (user turn) and clip (model turn),
    oldest first. The clip of the scene just before is `prev_clip_uri`."""
    start = story.take_start(index)
    history: list[dict] = []
    for j in range(start, index):
        sc = story.scenes[j]
        first = j == start
        frame = take_turn_frame(story, j, first)
        text = clip_prompt(
            story,
            sc,
            continuing=not first,
            story_set=story_set,
            start_frame=bool(frame) and not first,
        )
        history += [
            {
                "type": "user_input",
                "content": [{"type": "text", "text": text}, *frame_parts(frame)],
            },
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "video",
                        "gcs_uri": prev_clip_uri if j == index - 1 else sc.clip_uri,
                        "mime_type": "video/mp4",
                    }
                ],
            },
        ]
    return history


class VertexStoryBackend:
    """Real backend on Vertex AI. Untested live in this repo's local setup."""

    name = "vertex"

    def __init__(self):
        self.cfg = Default()
        # clip URI -> Gemini Omni interaction that made it (see interaction_of).
        self._interactions: dict[str, str] = {}

    def _folder(self, story: Story) -> str:
        return f"story_studio/{story.id}"

    def _set(self, story: Story):
        """The story's set (owner-only lookup), or None."""
        if not story.set_id or not story.owner:
            return None
        from services.story_sets import get_set_store

        try:
            return get_set_store().get(story.set_id, story.owner)
        except Exception:
            logger.exception("Story Studio: could not load set %s", story.set_id)
            return None

    def interaction_of(self, clip_uri: str) -> str:
        """The Omni interaction that made `clip_uri` ("" if unknown)."""
        return self._interactions.get(clip_uri, "")

    def _omni_request(self, story: Story, index: int, prompt: str, **extra):
        from config.omni_models import clamp_duration
        from models.requests import OmniVideoGenerationRequest

        scene = story.scenes[index]
        caps = apply_caps(story.scene_count, scene.duration)
        seconds = extra.pop("duration_seconds", caps.duration)
        return OmniVideoGenerationRequest(
            prompt=prompt,
            duration_seconds=clamp_duration(self.cfg.STORY_VIDEO_MODEL, int(seconds)),
            aspect_ratio=story.aspect_ratio,
            resolution=caps.resolution,
            model_version_id=self.cfg.STORY_VIDEO_MODEL,
            **extra,
        )

    def _json_text(
        self,
        prompt: str,
        temperature: float | None = None,
        task: str = "story_scenario",
        model: str = "",
        media: list[str] | None = None,
        schema: dict | None = None,
        system: str = "",
        thinking: bool = False,
    ) -> str:
        """One JSON Gemini call. `media`: GCS URIs (images, films) sent
        before the prompt so the model can look at them. `schema`: a JSON
        schema the reply must follow. `system`: the system instruction.
        `thinking`: let the model think first (dynamic budget). With no
        `temperature` the model's own default is used, as Google advises
        for its reasoning models."""
        from google.genai import types

        from common.analytics import track_model_call
        from models.gemini import client

        model = model or self.cfg.STORY_SCENARIO_MODEL_ID
        parts = [
            types.Part.from_uri(file_uri=u, mime_type=_media_mime(u))
            for u in (media or [])
            if u
        ]
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=temperature,
            response_json_schema=schema,
            system_instruction=system or None,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=-1) if thinking else None
            ),
        )
        with track_model_call(model_name=model, task=task):
            response = client.models.generate_content(
                model=model,
                contents=[*parts, prompt],
                config=config,
            )
        if not response.text:
            raise GenerationError("Gemini returned an empty scenario.")
        return response.text

    def write_scenario(self, story: Story, story_set=None, note: str = "") -> str:
        """`note`: what went wrong in the last try, for the retry."""
        prompt = scenario_prompt(story, story_set)
        return self._json_text(
            f"{prompt}\n\n{note}" if note else prompt,
            media=scenario_media(story, story_set),
            schema=scenario_schema(story, story_set),
            system=SCENARIO_SYSTEM,
            thinking=True,
        )

    def live_settings(self, idea: str) -> dict:
        """Film settings a small Gemini model reads out of the idea (one
        short JSON call per typing pause). {} when turned off or on error."""
        from services.story_autoset import live_settings_prompt, parse_live_settings

        model = getattr(self.cfg, "STORY_LIVE_SETTINGS_MODEL", "")
        if not model:
            return {}
        try:
            text = self._json_text(
                live_settings_prompt(idea),
                temperature=0.0,
                task="story_live_settings",
                model=model,
            )
        except Exception:
            logger.exception("Story Studio: live settings model failed")
            return {}
        return parse_live_settings(text)

    def write_set(self, story: Story) -> str:
        return self._json_text(
            set_build_prompt(story),
            task="story_set",
            schema=set_schema(),
            system=CASTING_SYSTEM,
            thinking=True,
        )

    def generate_set_image(
        self, story_set, prompt: str, refs: list[str], aspect_ratio: str = "1:1"
    ) -> str:
        """One set reference image with Nano Banana, stored under
        story_sets/<set id>/."""
        from models.gemini import generate_image_from_prompt_and_images

        uris, _, _, _, _ = generate_image_from_prompt_and_images(
            prompt=prompt,
            images=list(refs),
            aspect_ratio=aspect_ratio,
            gcs_folder=f"story_sets/{story_set.id}",
            file_prefix="set",
        )
        if not uris:
            raise GenerationError("The image model returned no image. Try again.")
        return uris[0]

    def voice_sample(self, story_set, character) -> str:
        """A ~5 s Gemini TTS sample of a character's voice and style."""
        from common.storage import store_to_gcs
        from models.gemini_tts import synthesize_speech
        from services.story_sets import voice_sample_text

        audio = synthesize_speech(
            text=voice_sample_text(character),
            prompt=_tts_style(character.voice),
            model_name=self.cfg.STORY_TTS_MODEL,
            voice_name=character.voice.tts_voice,
            language_code="en-US",
        )
        if not audio:
            raise GenerationError("Text-to-speech returned no audio.")
        return store_to_gcs(
            f"story_sets/{story_set.id}",
            f"voice_{uuid.uuid4().hex[:10]}.wav",
            "audio/wav",
            audio,
        )

    def rewrite_scene(self, story: Story, index: int) -> str:
        story_set = self._set(story)
        return self._json_text(
            scene_regen_prompt(story, index, story_set),
            schema=scene_schema(with_links=regen_links(story, story_set)),
            system=SCENARIO_SYSTEM,
            thinking=True,
        )

    def plan_fix(
        self, story: Story, request: str, scene: int, seconds: float | None
    ) -> str:
        """One Gemini JSON call that watches the film (and looks at the
        storyboard frames) before picking the smallest fix."""
        from services.story_fix import fix_media, fix_prompt

        return self._json_text(
            fix_prompt(story, request, scene, seconds, self._set(story)),
            temperature=0.2,
            task="story_fix",
            media=fix_media(story),
            thinking=True,
        )

    def translate(self, story: Story) -> str:
        return self._json_text(
            translation_prompt(story), temperature=0.3, task="story_translate"
        )

    def translate_subtitles(self, story: Story, code: str) -> list[str]:
        from services import story_subtitles as subs

        text = self._json_text(
            subs.translation_prompt(story, code), temperature=0.3, task="story_subtitles"
        )
        return subs.parse_translation(text, len(story.scenes))

    def generate_frame(self, story: Story, index: int, reference_uri: str) -> str:
        from models.gemini import generate_image_from_prompt_and_images

        scene = story.scenes[index]
        story_set = self._set(story)
        set_refs = frame_refs(story_set, scene)
        refs = [r.uri for r in set_refs]
        labels = [r.label for r in set_refs]
        same_take = bool(reference_uri) and reference_uri == take_frame(story, index)
        if reference_uri and reference_uri not in refs:
            refs.append(reference_uri)
            if labels:
                labels.append(
                    SAME_TAKE_REF
                    if same_take
                    else "the look, palette and art style of the film"
                )
        uris, _, _, _, _ = generate_image_from_prompt_and_images(
            prompt=frame_prompt(
                story,
                scene,
                bool(reference_uri),
                story_set,
                labels or None,
                same_take=same_take,
            ),
            images=refs,
            aspect_ratio=story.aspect_ratio,
            gcs_folder=self._folder(story),
            file_prefix=f"frame{index + 1}",
        )
        if not uris:
            raise GenerationError("The image model returned no frame. Try again.")
        return uris[0]

    def generate_clip(self, story: Story, index: int, start_frame_uri: str) -> str:
        """One clip with Gemini Omni, with its own sound: the spoken line with
        lip sync for on-camera scenes, ambient sound for narrated ones."""
        from models.omni import generate_omni_video

        scene = story.scenes[index]
        story_set = self._set(story)
        extra = clip_inputs(story, scene, start_frame_uri, story_set)
        labels = extra.pop("ref_labels", None)
        prompt = clip_prompt(
            story,
            scene,
            story_set=story_set,
            ref_labels=labels,
        )
        parts = clip_parts(scene.duration)
        try:
            uri, interaction_id = generate_omni_video(
                self._omni_request(
                    story, index, prompt, duration_seconds=parts[0], **extra
                )
            )
        except GenerationError as exc:
            if not is_lookalike_refusal(exc):
                raise
            uri, interaction_id, prompt = self._clip_from_set(
                story, index, story_set, parts[0], tried_refs=not start_frame_uri
            )
        if not uri:
            raise GenerationError("Gemini Omni returned no video for this scene.")
        if len(parts) > 1:
            uri, interaction_id = self._lengthen(
                story, index, prompt, uri, interaction_id, parts[1:], story_set
            )
        self._interactions[uri] = interaction_id
        return uri

    def _clip_from_set(
        self,
        story: Story,
        index: int,
        story_set,
        seconds: int,
        tried_refs: bool,
    ) -> tuple[str, str, str]:
        """Second try after Omni refused a clip's frame as a lookalike of a
        well-known person: the same scene from the set's own face, body,
        place and prop images instead of the frame. Raises the plain
        LOOKALIKE_MESSAGE when there is nothing else to try or it is refused
        again. Returns (clip, interaction ID, prompt)."""
        from models.omni import generate_omni_video
        from models.requests import APIReferenceImage

        scene = story.scenes[index]
        refs = (
            clip_refs(story_set, scene, "", clip_reference_cap())
            if story_set is not None and not tried_refs
            else []
        )
        if not refs:
            raise GenerationError(LOOKALIKE_MESSAGE)
        logger.info(
            "Omni refused scene %s as a lookalike; retrying from the set", index + 1
        )
        labels = [r.label for r in refs]
        prompt = clip_prompt(story, scene, story_set=story_set, ref_labels=labels)
        try:
            uri, interaction_id = generate_omni_video(
                self._omni_request(
                    story,
                    index,
                    prompt,
                    duration_seconds=seconds,
                    omni_mode="ref2v",
                    r2v_references=[
                        APIReferenceImage(gcs_uri=r.uri, mime_type=_image_mime(r.uri))
                        for r in refs
                    ],
                )
            )
        except GenerationError as exc:
            if is_lookalike_refusal(exc):
                raise GenerationError(LOOKALIKE_MESSAGE) from exc
            raise
        return uri, interaction_id, prompt

    def _lengthen(
        self,
        story: Story,
        index: int,
        prompt: str,
        uri: str,
        interaction_id: str,
        rest: list[int],
        story_set,
    ) -> tuple[str, str]:
        """Make a scene longer than one clip: continue the first clip in its
        Omni thread, one turn per part of `rest`, then join the parts into
        one clip. Returns (joined clip, last interaction ID)."""
        from models.omni import generate_omni_video

        scene = story.scenes[index]
        history = _turn(prompt, uri)
        pieces = [uri]
        for seconds in rest:
            more = clip_prompt(story, scene, continuing=True, story_set=story_set)
            new_uri, interaction_id = generate_omni_video(
                self._omni_request(
                    story,
                    index,
                    more,
                    omni_mode="t2v",
                    duration_seconds=seconds,
                    previous_interaction_id=interaction_id,
                    chat_history_json=json.dumps(history),
                )
            )
            if not new_uri:
                raise GenerationError(
                    f"Gemini Omni could not extend scene {index + 1}."
                )
            history += _turn(more, new_uri)
            pieces.append(new_uri)
        return self._join_parts(story, index, pieces), interaction_id

    def _join_parts(self, story: Story, index: int, pieces: list[str]) -> str:
        """One clip from a scene's parts (see join_plan), stored next to the
        story's other clips."""
        from common.storage import store_to_gcs
        from services.story_timeline import probe

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, piece in enumerate(pieces):
                path = os.path.join(tmp, f"part{i}.mp4")
                _gcs_fetch(piece, path)
                paths.append(path)
            probes = [probe(p) for p in paths]
            keep = join_plan([length for length, _ in probes])
            if len(keep) == 1:
                return pieces[keep[0]]
            out = os.path.join(tmp, "joined.mp4")
            result = subprocess.run(
                concat_args(
                    [paths[i] for i in keep],
                    [probes[i][1] for i in keep],
                    [probes[i][0] for i in keep],
                    out,
                ),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.error(
                    "Story Studio: joining clip parts failed: %s", result.stderr[-2000:]
                )
                raise GenerationError(f"Could not join the parts of scene {index + 1}.")
            with open(out, "rb") as f:
                data = f.read()
        return store_to_gcs(
            self._folder(story),
            f"clip{index + 1}_{uuid.uuid4().hex[:8]}.mp4",
            "video/mp4",
            data,
        )

    def last_frame(self, story: Story, clip_uri: str, index: int) -> str:
        from common.storage import download_from_gcs, store_to_gcs

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "clip.mp4")
            with open(src, "wb") as f:
                f.write(download_from_gcs(clip_uri))
            png = read_last_frame_png(src, os.path.join(tmp, "last.png"))
            with open(png, "rb") as f:
                data = f.read()
        return store_to_gcs(
            self._folder(story),
            f"lastframe{index + 1}_{uuid.uuid4().hex[:8]}.png",
            "image/png",
            data,
        )

    def generate_music(self, story: Story, prompt: str, seconds: float) -> str:
        from models.lyria import generate_music_with_lyria
        from services.story_models import MUSIC_FALLBACK_PROMPTS, music_declined

        # A blocked prompt (often a title that sounds like an existing song)
        # falls back to plainer prompts, so the film still gets music.
        declined: Exception | None = None
        for attempt in (prompt, *MUSIC_FALLBACK_PROMPTS):
            try:
                uris, _, _ = generate_music_with_lyria(
                    attempt, model_name=self.cfg.LYRIA_MODEL_VERSION
                )
            except Exception as exc:  # noqa: BLE001
                if not music_declined(exc):
                    raise
                logger.warning(
                    "Story Studio: Lyria declined a music prompt, trying a plainer one."
                )
                declined = exc
                continue
            if uris:
                return uris[0]
        if declined is not None:
            raise GenerationError(
                "Lyria declined the music prompt. Edit the music prompt and retry."
            ) from declined
        raise GenerationError("Lyria returned no music.")

    def generate_voiceover(
        self, story: Story, index: int, text: str, voice=None
    ) -> str:
        """The narrator's line (Gemini TTS). `voice`: the set narrator's
        pinned TTS voice and style, so every film sounds the same."""
        from common.storage import store_to_gcs
        from models.gemini_tts import synthesize_speech

        if voice is None:  # the set narrator: pinned voice and style
            story_set = self._set(story)
            narrator = story_set.narrator() if story_set else None
            voice = narrator.voice if narrator else None
        audio = _retry_transient(
            lambda: synthesize_speech(
                text=text,
                prompt=_tts_style(voice),
                model_name=self.cfg.STORY_TTS_MODEL,
                voice_name=voice.tts_voice if voice else story.voice_name,
                language_code=LANGUAGES.get(story.language, "en-US"),
            ),
            "voiceover",
        )
        if not audio:
            raise GenerationError("Text-to-speech returned no audio.")
        return store_to_gcs(
            self._folder(story),
            f"voice{index + 1}_{uuid.uuid4().hex[:8]}.wav",
            "audio/wav",
            audio,
        )

    def stitch(
        self, story: Story, plan: StitchPlan, music_uri: str, voice_uris: list[str]
    ) -> tuple[str, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "film.mp4")
            timeline = make_film(story, plan, music_uri, voice_uris, _gcs_fetch, out)
            return self._store_film(story, out), timeline

    def _store_film(self, story: Story, path: str) -> str:
        from common.storage import store_to_gcs

        with open(path, "rb") as f:
            data = f.read()
        return store_to_gcs(
            self._folder(story), f"film_{uuid.uuid4().hex[:8]}.mp4", "video/mp4", data
        )

    def render_timeline(self, story: Story, timeline: dict) -> str:
        from services.story_timeline import render_timeline

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "film.mp4")
            render_timeline(timeline, _gcs_fetch, out, **_logo_args(story))
            return self._store_film(story, out)

    def extend_clip(
        self, story: Story, index: int, prev_clip_uri: str
    ) -> tuple[str, float]:
        """Continue the previous clip in the same Gemini Omni thread, which
        keeps the shot, the person and their voice. The thread is the take so
        far: every earlier turn's prompt and clip are sent again with the
        previous interaction ID. Without a stored interaction (expired, or
        made before a restart) it falls back to Omni's extend task on the
        previous clip. Returns (clip, seconds of it that repeat the previous
        clip), measured, since the model may return the joined video."""
        from models.omni import generate_omni_video
        from services.story_timeline import clip_edges, probe

        scene = story.scenes[index]
        story_set = self._set(story)
        prev = story.scenes[index - 1] if index > 0 else None
        prev_id = (prev.interaction_id if prev else "") or self.interaction_of(
            prev_clip_uri
        )
        if prev_id:
            # A chat follow-up makes the next part of the take at the scene's
            # own length (sent in response_format, like a new clip). The
            # thread keeps the person and voice; the storyboard frame sent
            # with the turn sets the shot, so the take follows the storyboard.
            frame = take_turn_frame(story, index, first=False)
            prompt = clip_prompt(
                story,
                scene,
                continuing=True,
                story_set=story_set,
                start_frame=bool(frame),
            )
            images = {}
            if frame:
                images.update(
                    reference_image_gcs=frame,
                    reference_image_mime_type=_image_mime(frame),
                )
            request = self._omni_request(
                story,
                index,
                prompt,
                omni_mode="t2v",
                previous_interaction_id=prev_id,
                chat_history_json=json.dumps(
                    take_history(story, index, prev_clip_uri, story_set)
                ),
                **images,
            )
        else:
            # Omni's extend task takes only the video: it carries on the shot.
            prompt = clip_prompt(story, scene, continuing=True, story_set=story_set)
            request = self._omni_request(
                story,
                index,
                prompt,
                omni_mode="extend",
                duration_seconds=min(OMNI_EXTEND_MAX_SECONDS, int(scene.duration)),
                reference_video_gcs=prev_clip_uri,
                reference_video_mime_type="video/mp4",
            )
        uri, interaction_id = generate_omni_video(request)
        if not uri:
            raise GenerationError("Gemini Omni returned no video for this scene.")
        self._interactions[uri] = interaction_id
        with tempfile.TemporaryDirectory() as tmp:
            prev_path, new_path = os.path.join(tmp, "a.mp4"), os.path.join(tmp, "b.mp4")
            _gcs_fetch(prev_clip_uri, prev_path)
            _gcs_fetch(uri, new_path)
            # The picture's own lengths: the file runs a little longer with
            # its sound, which put every later cut between two frames.
            prev_len = clip_edges(prev_path)[0] or probe(prev_path)[0]
            new_len = clip_edges(new_path)[0] or probe(new_path)[0]
        joined = new_len > prev_len + 1.0
        return uri, round(prev_len, 3) if joined else 0.0

    def save_audio_upload(self, data: bytes, mime_type: str) -> str:
        from common.storage import store_to_gcs

        ext = _AUDIO_EXT.get(mime_type)
        if not ext:
            raise GenerationError("Use an MP3, WAV, M4A or OGG audio file.")
        return store_to_gcs(
            "story_studio/uploads",
            f"music_{uuid.uuid4().hex[:10]}.{ext}",
            mime_type,
            data,
        )

    def save_to_library(self, story: Story, final_uri: str, owner: str) -> str:
        from common.metadata import (
            MediaItem,
            add_media_item_to_firestore,
        )

        caps = apply_caps(story.scene_count, story.duration)
        item = MediaItem(
            user_email=owner,
            gcsuri=final_uri,
            mime_type="video/mp4",
            media_type="video",
            mode="story_studio",
            model=self.cfg.STORY_VIDEO_MODEL,
            prompt=story.idea,
            original_prompt=story.idea,
            aspect=story.aspect_ratio,
            resolution=caps.resolution,
            duration=float(sum(s.duration for s in story.scenes)),
            thumbnail_uri=story.cover_uri or None,
            reference_image=story.cover_uri or None,
            captions=[s.narration for s in story.scenes],
            source_uris=[s.clip_uri for s in story.scenes if s.clip_uri],
            comment=f"Story Studio: {story.title} ({STYLE_BY_ID.get(story.style, {}).get('label', story.style)})",
            status="complete",
        )
        add_media_item_to_firestore(item)
        return item.id or ""

    def save_upload(self, data: bytes, mime_type: str) -> str:
        from common.storage import store_to_gcs

        ext = _UPLOAD_EXT.get(mime_type)
        if not ext:
            raise GenerationError("Use a PNG, JPEG or WebP image.")
        return store_to_gcs(
            "story_studio/uploads",
            f"ref_{uuid.uuid4().hex[:10]}.{ext}",
            mime_type,
            data,
        )


_backend: StoryBackend | None = None


def get_backend() -> StoryBackend:
    global _backend
    if _backend is None:
        _backend = MockStoryBackend() if is_mock_mode() else VertexStoryBackend()
    return _backend


def set_backend(backend: StoryBackend | None) -> None:
    """Swap the backend (tests)."""
    global _backend
    _backend = backend
