# Copyright 2025 Google LLC
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
"""Python API for <gm-home-chat> (the Home page's one prompt box).

Under the box sit type chips (Image, Video, Music, Voice, Film). A chip fills
the box with a sample prompt; sending it then opens that studio with
``?prompt=...&go=1``, which starts making it right away
(common/prompt_prefill.take_autostart). Without a chip the box is a chat.
"""

from __future__ import annotations

import json
import re

import mesop as me

from common.i18n import t, tr

# The subtitle's media words and the studio each one belongs to.
WORDS = {
    "images": ("image", "/nano-banana", "Open Image Studio"),
    "video": ("video", "/veo", "Open Video Studio"),
    "voice": ("voice", "/voice", "Open Voice"),
    "music": ("music", "/lyria", "Open Music"),
    "film": ("film", "/story", "Open Story Studio"),
}

LEDE = "Turn one idea into {images}, {video}, {voice} and {music}, or a finished short {film}."


def lede_segments() -> list[dict]:
    """The lede as text and word segments, in the current language."""
    template = tr("home.lede_words", LEDE)
    out: list[dict] = []
    for part in re.split(r"(\{\w+\})", template):
        name = part[1:-1] if part.startswith("{") and part.endswith("}") else ""
        if name in WORDS:
            kind, href, tip = WORDS[name]
            out.append(
                {
                    "text": tr(f"home.word.{name}", name),
                    "kind": kind,
                    "href": href,
                    "tip": tr(f"home.word.{name}.tip", tip),
                }
            )
        elif part:
            out.append({"text": part})
    return out


def lede() -> str:
    """The subtitle as plain text, in the current language."""
    return "".join(seg["text"] for seg in lede_segments())


# Type tiles under the box: (kind, label key, English label, studio route).
KINDS = (
    ("image", "home.mode.image.label", "Image", "/nano-banana"),
    ("video", "home.mode.video.label", "Video", "/veo"),
    ("music", "home.mode.music.label", "Music", "/lyria"),
    ("voice", "home.mode.voice.label", "Voice", "/voice"),
    ("film", "home.mode.film.label", "Film", "/story"),
)

# One short line under each tile's name.
_DESCS = {
    "image": "Photos and art",
    "video": "Clips up to 8 seconds",
    "music": "Tracks and jingles",
    "voice": "Voice-overs",
    "film": "Short films",
}

# Two sample prompts per chip (clicking a chip again shows the next one).
_SAMPLES = {
    "image": (
        "A perfume bottle on wet black stone, studio light",
        "Our sneaker on a Tokyo street at night",
    ),
    "video": (
        "Slow dolly in on a barista pouring latte art",
        "Drone shot over a desert road at sunrise",
    ),
    "music": (
        "Warm lo-fi beat with soft piano, 80 bpm",
        "Uplifting cinematic strings for a product launch",
    ),
    "voice": (
        "Welcome to our store. Today only, everything is 20% off.",
        "Thanks for calling. Your order is on its way.",
    ),
    "film": (
        "A 30-second ad for an electric bike in the city",
        "A lighthouse keeper finds a message in a bottle",
    ),
}


def kinds() -> list[dict]:
    """The type tiles: {"kind", "label", "desc", "href", "samples"} in the page language."""
    return [
        {
            "kind": kind,
            "label": tr(label_key, label),
            "desc": tr(f"home.kind.{kind}.desc", _DESCS[kind]),
            "href": href,
            "samples": [
                tr(f"home.mode.{kind}.ex{i + 1}", text)
                for i, text in enumerate(_SAMPLES[kind])
            ],
        }
        for kind, label_key, label, href in KINDS
    ]


def examples() -> list[dict]:
    """Three starters of different kinds, so people see it does anything.

    Each is {"text", "kind"}; the kind picks the icon shown beside it.
    """
    return [
        {"kind": "image", "text": tr("home.mode.image.ex1", "A perfume bottle on wet black stone, studio light")},
        {"kind": "video", "text": tr("home.mode.video.ex2", "Drone shot over a desert road at sunrise")},
        {"kind": "film", "text": tr("home.chat.ex_film", "A 30-second film about a lighthouse keeper")},
    ]


_STRINGS = {
    "title": ("home.title", "Google's creative AI, in one studio"),
    "placeholder": ("home.chat.placeholder", "Ask me anything"),
    "enhance": ("composer.enhance", "Enhance prompt"),
    "enhancing": ("home.chat.enhancing", "Enhancing…"),
    "kinds": ("home.chat.kinds", "What to make"),
    "send": ("home.chat.send", "Send"),
    "new_chat": ("home.chat.new", "New chat"),
    "new_chat_tip": ("home.chat.new_tip", "Start over with an empty chat"),
    "attach": ("home.chat.attach", "Add a picture"),
    "attach_tip": ("home.chat.attach_tip", "Add a picture to edit or animate"),
    "attach_default": ("home.chat.attach_default", "What can you make from this?"),
    "attach_failed": ("home.chat.attach_failed", "Could not attach this picture"),
    "remove": ("home.chat.remove", "Remove"),
    "dictate": ("composer.dictate", "Dictate"),
    "dictate_stop": ("composer.dictate_stop", "Stop dictation"),
    "try": ("home.prompt.try", "Try:"),
    "thinking": ("home.chat.thinking", "Thinking"),
    "making": ("home.chat.making", "Making…"),
    "ready": ("home.chat.ready", "Ready"),
    "failed": ("home.chat.failed", "Failed"),
    "download": ("home.chat.download", "Download"),
    "edit": ("home.chat.edit", "Edit"),
    "edit_prefix": ("home.chat.edit_prefix", "Edit"),
    "animate": ("home.chat.animate", "Animate"),
    "animate_prefix": ("home.chat.animate_prefix", "Make a video from"),
    "open": ("home.chat.open", "Open in Library"),
    "open_film": ("home.chat.open_film", "Open in Story Studio"),
    "retry": ("home.chat.retry", "Try again"),
    "story_step": (
        "home.chat.story_step",
        'This step of your film is ready. Say "next step" to keep going, or open it in Story Studio.',
    ),
    "error": ("home.chat.error", "Something went wrong. Please try again."),
    "lost": ("home.chat.lost", "This job was lost. Please try again."),
    "thread": ("home.chat.thread", "Conversation"),
}


def strings() -> dict:
    return {k: tr(key, english) for k, (key, english) in _STRINGS.items()}


ALLOWED_HOME_ROUTES = frozenset(
    {"/nano-banana", "/veo", "/lyria", "/voice", "/story", "/library_v2"}
)


def on_home_nav(e: me.WebEvent):
    """SPA navigation from Home chat chips/cards into studios."""
    value = e.value if isinstance(e.value, dict) else {}
    route = str(value.get("route") or "")
    if route not in ALLOWED_HOME_ROUTES:
        return
    raw_params = value.get("params")
    params = (
        {
            str(k): str(v)[:1000]
            for k, v in raw_params.items()
            if k in {"prompt", "go", "id", "step"} and v is not None and v != ""
        }
        if isinstance(raw_params, dict)
        else None
    )
    me.navigate(route, query_params=params or None)


@me.web_component(path="./home_chat.js")
def home_chat(*, live: bool = False, key: str | None = "home-chat"):
    """The Home chat: hero, prompt box, type chips and conversation."""
    from components.live_agent.live_agent import _strings as live_strings

    return me.insert_web_component(
        key=key,
        name="gm-home-chat",
        properties={
            "stringsJson": json.dumps(strings(), ensure_ascii=False),
            "kindsJson": json.dumps(kinds(), ensure_ascii=False),
            "talkJson": json.dumps({**live_strings(), "talk": t("live.talk", "Talk to the studio")}, ensure_ascii=False),
            "live": live,
        },
        events={"navEvent": on_home_nav},
    )
