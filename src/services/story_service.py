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

``VertexStoryBackend`` calls Gemini, Gemini Image, Veo, Lyria and Gemini TTS
through the repo's existing model modules (imported lazily, so demo mode and
tests never touch Google Cloud). ``MockStoryBackend`` produces a fake
scenario, painted placeholder frames, short motion clips, a synth music bed
and a tone "voiceover" on local disk with realistic delays, so the whole
wizard can be clicked through without credentials.

Both backends share :func:`stitch_local`, the real MoviePy stitcher
(crossfades + music + voiceover), so stitching is exercised in demo mode too.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
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
    LANGUAGES,
    STYLE_BY_ID,
    StitchPlan,
    Story,
    apply_caps,
    clip_prompt,
    frame_prompt,
    scenario_prompt,
    scene_regen_prompt,
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

    def write_scenario(self, story: Story) -> str: ...
    def rewrite_scene(self, story: Story, index: int) -> str: ...
    def translate(self, story: Story) -> str: ...
    def generate_frame(self, story: Story, index: int, reference_uri: str) -> str: ...
    def generate_clip(self, story: Story, index: int, start_frame_uri: str) -> str: ...
    def last_frame(self, story: Story, clip_uri: str, index: int) -> str: ...
    def generate_music(self, story: Story, prompt: str, seconds: float) -> str: ...
    def generate_voiceover(self, story: Story, index: int, text: str) -> str: ...
    def stitch(
        self, story: Story, plan: StitchPlan, music_uri: str, voice_uris: list[str]
    ) -> str: ...
    def save_to_library(self, story: Story, final_uri: str, owner: str) -> str: ...
    def save_upload(self, data: bytes, mime_type: str) -> str: ...


_UPLOAD_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


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


def stitch_local(
    clip_paths: list[str],
    plan: StitchPlan,
    out_path: str,
    music_path: str = "",
    voice_paths: list[str] | None = None,
    fps: int = 24,
) -> str:
    """Render the film: clips overlapped with crossfades, music bed, voiceover.

    ``clip_paths`` and ``voice_paths`` follow ``plan.segments`` order. Clip
    audio is dropped except for spoken segments, whose clip carries the
    on-camera speech. The music is looped/trimmed to the film and ducked under
    any speech; the voiceover starts just after each crossfade.
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
    def write_scenario(self, story: Story) -> str:
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
        return json.dumps({"title": title, "voice": voice, "scenes": scenes})

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

    def generate_voiceover(self, story: Story, index: int, text: str) -> str:
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
    ) -> str:
        clip_paths = [local_path(s.clip_uri) for s in plan.segments]
        uri, path = self._new_uri(story, "film")
        stitch_local(
            clip_paths,
            plan,
            path + ".mp4",
            music_path=local_path(music_uri) if music_uri else "",
            voice_paths=[local_path(v) if v else "" for v in voice_uris],
            fps=12,
        )
        return uri + ".mp4"

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


class VertexStoryBackend:
    """Real backend on Vertex AI. Untested live in this repo's local setup."""

    name = "vertex"

    def __init__(self):
        self.cfg = Default()

    def _folder(self, story: Story) -> str:
        return f"story_studio/{story.id}"

    def _json_text(
        self, prompt: str, temperature: float = 0.8, task: str = "story_scenario"
    ) -> str:
        from google.genai import types

        from common.analytics import track_model_call
        from models.gemini import client

        model = self.cfg.STORY_SCENARIO_MODEL_ID
        with track_model_call(model_name=model, task=task):
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
        if not response.text:
            raise GenerationError("Gemini returned an empty scenario.")
        return response.text

    def write_scenario(self, story: Story) -> str:
        return self._json_text(scenario_prompt(story))

    def rewrite_scene(self, story: Story, index: int) -> str:
        return self._json_text(scene_regen_prompt(story, index))

    def translate(self, story: Story) -> str:
        return self._json_text(
            translation_prompt(story), temperature=0.3, task="story_translate"
        )

    def generate_frame(self, story: Story, index: int, reference_uri: str) -> str:
        from models.gemini import generate_image_from_prompt_and_images

        scene = story.scenes[index]
        refs = [reference_uri] if reference_uri else []
        uris, _, _, _, _ = generate_image_from_prompt_and_images(
            prompt=frame_prompt(story, scene, bool(refs)),
            images=refs,
            aspect_ratio=story.aspect_ratio,
            gcs_folder=self._folder(story),
            file_prefix=f"frame{index + 1}",
        )
        if not uris:
            raise GenerationError("The image model returned no frame. Try again.")
        return uris[0]

    def generate_clip(self, story: Story, index: int, start_frame_uri: str) -> str:
        from models.requests import VideoGenerationRequest
        from models.veo import generate_video

        scene = story.scenes[index]
        caps = apply_caps(story.scene_count, scene.duration)
        uris, _ = generate_video(
            VideoGenerationRequest(
                prompt=clip_prompt(story, scene),
                duration_seconds=caps.duration,
                video_count=1,
                aspect_ratio=story.aspect_ratio,
                resolution=caps.resolution,
                enhance_prompt=True,
                # Spoken scenes: Veo renders the line with lip sync. Other
                # clips stay silent under the music and voiceover.
                generate_audio=bool(scene.spoken and scene.narration.strip()),
                model_version_id=self.cfg.STORY_VEO_MODEL_VERSION,
                person_generation="Allow (Adults only)",
                reference_image_gcs=start_frame_uri or None,
                reference_image_mime_type="image/png" if start_frame_uri else None,
            )
        )
        if not uris:
            raise GenerationError("Veo returned no video for this scene.")
        return uris[0]

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

        uris, _, _ = generate_music_with_lyria(
            prompt, model_name=self.cfg.LYRIA_MODEL_VERSION
        )
        if not uris:
            raise GenerationError("Lyria returned no music.")
        return uris[0]

    def generate_voiceover(self, story: Story, index: int, text: str) -> str:
        from common.storage import store_to_gcs
        from models.gemini_tts import synthesize_speech

        audio = synthesize_speech(
            text=text,
            prompt="Narrate warmly and clearly, like a short film voiceover.",
            model_name=self.cfg.STORY_TTS_MODEL,
            voice_name=story.voice_name,
            language_code=LANGUAGES.get(story.language, "en-US"),
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
    ) -> str:
        from common.storage import download_from_gcs, store_to_gcs

        with tempfile.TemporaryDirectory() as tmp:

            def fetch(uri: str, name: str) -> str:
                if not uri:
                    return ""
                path = os.path.join(tmp, name)
                with open(path, "wb") as f:
                    f.write(download_from_gcs(uri))
                return path

            clips = [
                fetch(s.clip_uri, f"clip{k}.mp4") for k, s in enumerate(plan.segments)
            ]
            music = fetch(music_uri, "music.wav")
            voices = [fetch(v, f"voice{k}.wav") for k, v in enumerate(voice_uris)]
            out = stitch_local(
                clips, plan, os.path.join(tmp, "film.mp4"), music, voices
            )
            with open(out, "rb") as f:
                data = f.read()
        return store_to_gcs(
            self._folder(story), f"film_{uuid.uuid4().hex[:8]}.mp4", "video/mp4", data
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
            model=self.cfg.STORY_VEO_MODEL_VERSION,
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
