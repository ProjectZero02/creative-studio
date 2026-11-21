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
"""The fields of each studio page that the voice agent may read and fill.

The Live agent's "Fill only" mode works on the page in front of the
presenter: it reads these fields (``read_page``) and sets them
(``fill_fields``) through the page's own Mesop state, exactly as if the
presenter had typed or picked the value. It never presses Generate.

Each page lists its fields once here. A field names the state class and
attribute that hold it, what kind of value it takes (text, a choice from a
list, a number in a range, or on/off), and an optional hook run after it is
set (for example to re-mount a textarea so it shows the new text).

``snapshot`` (what the agent sees) and ``fill`` (what it may change) are
plain functions over a state getter, so they are unit tested without Mesop.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

StateGetter = Callable[[type], Any]
TEXT, CHOICE, NUMBER, SWITCH = "text", "choice", "number", "switch"
TEXT_LIMIT = 4000


@dataclass
class PageField:
    name: str  # what the agent calls it
    label: str  # what the presenter sees on the page
    state: str  # "module:Class" of the Mesop state holding it
    attr: str  # attribute on that state
    kind: str = TEXT
    # Choices: (value, label) pairs, or a function returning them.
    options: list[tuple[str, str]] | Callable[[], list[tuple[str, str]]] = field(
        default_factory=list
    )
    low: float = 0
    high: float = 0
    hint: str = ""
    # Run after the field is set: hook(state_getter, value).
    after: Callable[[StateGetter, Any], None] | None = None
    # Only offered while this returns True for the page's state.
    when: Callable[[StateGetter], bool] | None = None

    def choices(self) -> list[tuple[str, str]]:
        raw = self.options() if callable(self.options) else self.options
        return [(str(v), str(lbl)) for v, lbl in raw]


def _cls(path: str) -> type:
    module, _, name = path.partition(":")
    return getattr(importlib.import_module(module), name)


def _bump(state: str, attr: str) -> Callable[[StateGetter, Any], None]:
    """A hook that bumps a textarea's key so it re-mounts with the new text."""

    def hook(get: StateGetter, _value: Any) -> None:
        st = get(_cls(state))
        setattr(st, attr, int(getattr(st, attr, 0) or 0) + 1)

    return hook


def _pin(name: str) -> Callable[[StateGetter, Any], None]:
    """Story Studio: a setting set by hand (or by the agent) is kept when the
    idea is read again for settings."""

    def hook(get: StateGetter, _value: Any) -> None:
        import json

        st = get(_cls(STORY))
        try:
            pinned = list(json.loads(st.pinned_json or "[]"))
        except ValueError:
            pinned = []
        if name not in pinned:
            pinned.append(name)
        st.pinned_json = json.dumps(pinned)

    return hook


# -- option sources (imported lazily: the config modules are heavy) --------


def _image_models():
    from config.gemini_image_models import GEMINI_IMAGE_MODELS

    return [(m.model_name, m.display_name) for m in GEMINI_IMAGE_MODELS]


def _voice_options(name: str):
    def opts():
        import config.voice as v

        if name == "voice":
            return [(x, x) for x in v.VOICES]
        if name == "style":
            return [(x[0], x[1]) for x in v.STYLES]
        return [(x[0], x[1]) for x in v.PACES]

    return opts


def _story_options(name: str):
    def opts():
        import services.story_models as m

        if name == "style":
            return [(s["id"], s["label"]) for s in m.STYLES]
        if name == "camera":
            return [(k, v.get("label", k)) for k, v in m.CAMERA_PRESETS.items()]
        if name == "language":
            return [(k, k) for k in m.LANGUAGES]
        if name == "speech_mode":
            return [(k, k) for k in m.SPEECH_MODES]
        return [(a, a) for a in m.ASPECT_RATIOS]

    return opts


IMAGE = "pages.gemini_image_generation:PageState"
VIDEO = "state.veo_state:PageState"
MUSIC = "state.lyria_state:PageState"
VOICE = "state.voice_state:VoiceState"
STORY = "state.story_state:StoryState"


def _story_step(*steps: str) -> Callable[[StateGetter], bool]:
    return lambda get: get(_cls(STORY)).step in steps


ASPECTS = [("1:1", "Square"), ("16:9", "Wide"), ("9:16", "Tall"), ("4:3", "4:3"), ("3:4", "3:4")]

PAGES: dict[str, list[PageField]] = {
    "gemini_image_generation": [
        PageField("prompt", "Prompt", IMAGE, "prompt", hint="What the image shows.",
                  after=_bump(IMAGE, "prompt_key")),
        PageField("model", "Model", IMAGE, "selected_model", CHOICE, _image_models),
        PageField("aspect_ratio", "Aspect ratio", IMAGE, "aspect_ratio", CHOICE, ASPECTS),
        PageField("image_size", "Size", IMAGE, "image_size", CHOICE,
                  [("1K", "1K"), ("2K", "2K"), ("4K", "4K")]),
    ],
    "veo": [
        PageField("prompt", "Prompt", VIDEO, "veo_prompt_input",
                  hint="What happens in the video: subject, action, camera, sound.",
                  after=_bump(VIDEO, "veo_prompt_textarea_key")),
        PageField("negative_prompt", "Avoid", VIDEO, "negative_prompt",
                  hint="What the video must not show."),
        PageField("aspect_ratio", "Aspect ratio", VIDEO, "aspect_ratio", CHOICE,
                  [("16:9", "Wide"), ("9:16", "Tall")]),
        PageField("resolution", "Resolution", VIDEO, "resolution", CHOICE,
                  [("720p", "720p"), ("1080p", "1080p")]),
        PageField("length", "Length (seconds)", VIDEO, "video_length", NUMBER, low=4, high=8),
        PageField("sound", "Sound", VIDEO, "generate_audio", SWITCH),
    ],
    "lyria": [
        PageField("prompt", "Music prompt", MUSIC, "music_prompt_input",
                  hint="Genre, instruments, mood and tempo.",
                  after=_bump(MUSIC, "music_prompt_textarea_key")),
        PageField("lyrics", "Lyrics", MUSIC, "lyrics_input",
                  after=_bump(MUSIC, "lyrics_key")),
        PageField("tracks", "Tracks", MUSIC, "sample_count", NUMBER, low=1, high=4),
    ],
    "voice": [
        PageField("script", "Script", VOICE, "text", hint="The words to say.",
                  after=_bump(VOICE, "text_key")),
        PageField("voice", "Voice", VOICE, "voice", CHOICE, _voice_options("voice")),
        PageField("style", "Style", VOICE, "style", CHOICE, _voice_options("style")),
        PageField("pace", "Pace", VOICE, "pace", CHOICE, _voice_options("pace")),
        PageField("style_notes", "Style notes", VOICE, "style_notes"),
    ],
    "story": [
        PageField("idea", "Idea", STORY, "idea", hint="What the film is about.",
                  when=_story_step("create")),
        PageField("character", "Main character", STORY, "character",
                  when=_story_step("create"), after=_pin("character")),
        PageField("scenes", "Scenes", STORY, "scene_count", NUMBER, low=1, high=8,
                  when=_story_step("create"), after=_pin("scene_count")),
        PageField("seconds_per_scene", "Seconds per scene", STORY, "duration", NUMBER,
                  low=4, high=20, when=_story_step("create"), after=_pin("duration")),
        PageField("style", "Style", STORY, "style", CHOICE, _story_options("style"),
                  when=_story_step("create"), after=_pin("style")),
        PageField("camera", "Camera", STORY, "camera", CHOICE, _story_options("camera"),
                  when=_story_step("create"), after=_pin("camera")),
        PageField("aspect_ratio", "Aspect ratio", STORY, "aspect_ratio", CHOICE,
                  _story_options("aspect"), when=_story_step("create"),
                  after=_pin("aspect_ratio")),
        PageField("language", "Language", STORY, "language", CHOICE,
                  _story_options("language"), when=_story_step("create"),
                  after=_pin("language")),
        PageField("speech", "Who speaks", STORY, "speech_mode", CHOICE,
                  _story_options("speech_mode"), when=_story_step("create"),
                  after=_pin("speech_mode")),
        PageField("fix_request", "Fix with AI: what should change?", STORY, "fix_request",
                  hint="What the presenter dislikes about the film.",
                  when=_story_step("video")),
        PageField("fix_time", "Fix with AI: at (seconds)", STORY, "fix_time",
                  hint="A moment of the film, e.g. 12.5.", when=_story_step("video")),
    ],
}


def fields_for(page: str, get: StateGetter) -> list[PageField]:
    return [f for f in PAGES.get(page, []) if f.when is None or f.when(get)]


def _value(f: PageField, get: StateGetter) -> Any:
    try:
        return getattr(get(_cls(f.state)), f.attr)
    except Exception:  # a page whose module is not loaded: nothing to show
        return None


def snapshot(page: str, get: StateGetter) -> list[dict]:
    """What the agent sees of the page: each field with its current value."""
    out = []
    for f in fields_for(page, get):
        row: dict[str, Any] = {"name": f.name, "label": f.label, "kind": f.kind}
        value = _value(f, get)
        row["value"] = value[:600] if isinstance(value, str) else value
        if f.kind == CHOICE:
            row["options"] = [v for v, _ in f.choices()]
        if f.kind == NUMBER:
            row["range"] = [f.low, f.high]
        if f.hint:
            row["hint"] = f.hint
        out.append(row)
    return out


def _coerce(f: PageField, raw: Any) -> tuple[bool, Any]:
    """(ok, value) for what the agent wants to put in a field."""
    if f.kind == TEXT:
        return True, str(raw if raw is not None else "")[:TEXT_LIMIT]
    if f.kind == SWITCH:
        if isinstance(raw, bool):
            return True, raw
        text = str(raw).strip().lower()
        if text in ("true", "on", "yes", "1"):
            return True, True
        if text in ("false", "off", "no", "0"):
            return True, False
        return False, None
    if f.kind == NUMBER:
        try:
            n = float(raw)
        except (TypeError, ValueError):
            return False, None
        n = min(f.high, max(f.low, n)) if f.high > f.low else n
        return True, int(round(n))
    want = str(raw).strip().lower()
    for value, label in f.choices():
        if want in (value.lower(), label.lower()):
            return True, value
    return False, None


def fill(page: str, values: dict, get: StateGetter) -> dict:
    """Set fields on the page's state. Returns what changed and what was
    refused (unknown field, or a value the field does not take)."""
    by_name = {f.name: f for f in fields_for(page, get)}
    changed, refused = {}, {}
    for name, raw in (values or {}).items():
        f = by_name.get(str(name))
        if f is None:
            refused[name] = "not a field on this page"
            continue
        ok, value = _coerce(f, raw)
        if not ok:
            opts = ", ".join(v for v, _ in f.choices()) if f.kind == CHOICE else ""
            refused[name] = f"not allowed{': choose ' + opts if opts else ''}"
            continue
        setattr(get(_cls(f.state)), f.attr, value)
        if f.after is not None:
            f.after(get, value)
        changed[name] = value
    return {"changed": changed, "refused": refused}
