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
"""Python API for <gm-home-chat> (the Home page's one prompt box)."""

from __future__ import annotations

import json
import re

import mesop as me

from common.i18n import t, tr

# The headline's media words: what each one opens and what it says on hover.
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
    "placeholder": ("home.chat.placeholder", "Ask for an image, a video, music, a voice-over or a short film"),
    "send": ("home.chat.send", "Send"),
    "new_chat": ("home.chat.new", "New chat"),
    "new_chat_tip": ("home.chat.new_tip", "Start over with an empty chat"),
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


@me.web_component(path="./home_chat.js")
def home_chat(*, live: bool = False, key: str | None = "home-chat"):
    """The Home chat: hero, prompt box and conversation."""
    from components.live_agent.live_agent import _strings as live_strings

    return me.insert_web_component(
        key=key,
        name="gm-home-chat",
        properties={
            "stringsJson": json.dumps(strings(), ensure_ascii=False),
            "ledeJson": json.dumps(lede_segments(), ensure_ascii=False),
            "examplesJson": json.dumps(examples(), ensure_ascii=False),
            "talkJson": json.dumps({**live_strings(), "talk": t("live.talk", "Talk to the studio")}, ensure_ascii=False),
            "live": live,
        },
    )
