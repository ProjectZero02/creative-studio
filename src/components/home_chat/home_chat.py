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

The mode (Image, Video, Music, Voice, Film) comes from the side menu, the
mode pill under the box, or the words being typed (detect_kind.js). A mode
shows its settings as pills under the box, its rarer ones behind "+", and
sends straight to POST /api/chat/job. Without a mode the box is a chat.
"""

from __future__ import annotations

import json
import logging
import re

import mesop as me

from common.i18n import t, tr

# The subtitle's media words and the studio each one belongs to.
WORDS = {
    "images": ("image", "/nano-banana", "Open Image Studio"),
    "video": ("video", "/veo", "Open Video Studio"),
    "voice": ("voice", "/voice", "Open Voice"),
    "music": ("music", "/lyria", "Open Music"),
    "film": ("film", "/story", "Open Film Studio"),
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
    "video": "Clips with sound",
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
    "undo_enhance": ("composer.undo_enhance", "Undo enhance"),
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
    "animate_lead": ("home.chat.animate_lead", "Make a video: "),
    "reference": ("home.chat.reference", "Reference"),
    "reference_tip": ("home.chat.reference_tip", "Use as a reference in your next message"),
    "jobs": ("home.chat.jobs", "Jobs"),
    "jobs_running": ("home.chat.jobs_running", "running"),
    "close": ("home.chat.close", "Close"),
    "open_short": ("home.chat.open_short", "Open"),
    "open": ("home.chat.open", "Open in Library"),
    "open_film": ("home.chat.open_film", "Open in Film Studio"),
    "retry": ("home.chat.retry", "Try again"),
    "story_step": (
        "home.chat.story_step",
        'This step of your film is ready. Say "next step" to keep going, or open it in Film Studio.',
    ),
    "error": ("home.chat.error", "Something went wrong. Please try again."),
    "lost": ("home.chat.lost", "This job was lost. Please try again."),
    "thread": ("home.chat.thread", "Conversation"),
    "auto": ("home.chat.auto", "Auto"),
    "auto_tip": ("home.chat.auto_tip", "The chat picks what to make"),
    "settings": ("home.chat.settings", "Settings"),
    "need_prompt": ("home.chat.need_prompt", "Write what to make first."),
    "film_steps": ("home.chat.film_steps", "Film steps"),
    "step_scenario": ("home.chat.step_scenario", "Scenario"),
    "step_set": ("home.chat.step_set", "Set"),
    "step_storyboard": ("home.chat.step_storyboard", "Storyboard"),
    "step_film": ("home.chat.step_film", "Film"),
    "next_step": ("home.chat.next_step", "Next step"),
    "whole_film": ("home.chat.whole_film", "Whole film"),
    "whole_film_tip": ("home.chat.whole_film_tip", "Run every remaining step"),
    "on": ("home.chat.on", "On"),
    "off": ("home.chat.off", "Off"),
    "more": ("home.chat.more", "Add files and more"),
    "add_files": ("home.chat.add_files", "Add files or photos"),
    "add": ("home.chat.add", "Add"),
    "use": ("home.chat.use", "Use"),
    "use_as": ("home.chat.use_as", "Use as"),
    "advanced": ("home.chat.advanced", "Advanced settings"),
    "changed": ("home.chat.changed", "Changed"),
    "reset": ("home.chat.reset", "Reset"),
    "open_studio": ("home.chat.open_studio", "Open full studio"),
    "detected": ("home.chat.detected", "auto"),
    "clear_mode": ("home.chat.clear_mode", "Back to chat"),
    "ph_image": ("home.chat.ph_image", "Describe the image"),
    "ph_video": ("home.chat.ph_video", "Describe the video"),
    "ph_music": ("home.chat.ph_music", "Describe the music"),
    "ph_voice": ("home.chat.ph_voice", "Type what to say"),
    "ph_film": ("home.chat.ph_film", "Describe your film idea"),
    "thought": ("home.chat.thought", "Thought for {n} s"),
    "t_read": ("home.chat.t_read", "Reading your prompt"),
    "t_mode": ("home.chat.t_mode", "Making"),
    "t_detected": ("home.chat.t_detected", "You wrote “{word}”"),
    "t_picked": ("home.chat.t_picked", "Picked by you"),
    "t_settings": ("home.chat.t_settings", "Settings"),
    "t_files": ("home.chat.t_files", "Files"),
    "about": ("home.chat.about", "about {n} s"),
    "secs": ("home.chat.secs", "{n} s"),
    "mins": ("home.chat.mins", "{m} min {n} s"),
    "steps_done": ("home.chat.steps_done", "Steps"),
    # The headline once a type is picked (until the first message).
    "title_image": ("home.title.image", "Paint a picture with words"),
    "title_video": ("home.title.video", "Direct a scene in seconds"),
    "title_music": ("home.title.music", "Score your moment"),
    "title_voice": ("home.title.voice", "Give your words a voice"),
    "title_film": ("home.title.film", "Write a short film"),
    # The placeholder is an example prompt; Tab puts it in the box.
    "ex_auto": ("home.ex.auto", "Make a 16:9 photo of a lighthouse at dusk, then animate it"),
    "ex_image": ("home.ex.image", "A glass perfume bottle on wet black stone, soft studio light, 85mm close-up"),
    "ex_video": ("home.ex.video", "Slow dolly in on a barista pouring latte art, warm café light, shallow focus"),
    "ex_music": ("home.ex.music", "Warm lo-fi hip hop with soft piano and vinyl crackle, 80 bpm, relaxed"),
    "ex_voice": ("home.ex.voice", "Welcome to our store. Today only, everything is twenty percent off."),
    "ex_film": ("home.ex.film", "A 30-second ad for an electric bike in the city"),
    # How a good prompt is built, shown beside the Tab hint.
    "how_auto": ("home.how.auto", "Say what to make: image, video, music or voice"),
    "how_image": ("home.how.image", "Subject · setting · light · camera"),
    "how_video": ("home.how.video", "Shot · subject · action · mood"),
    "how_music": ("home.how.music", "Genre · instruments · tempo · mood"),
    "how_voice": ("home.how.voice", "The exact words to say"),
    "how_film": ("home.how.film", "Product or story · length · mood"),
    "tab_example": ("home.chat.tab_example", "use example"),
    "tab_accept": ("home.chat.tab_accept", "accept"),
    "suggestion": ("home.chat.suggestion", "Suggestion: {text}. Press Tab to accept."),
    # The path from prompt to result, shown above the box.
    "path": ("home.chat.path", "How this is made"),
    "p_prompt": ("home.chat.p_prompt", "Your prompt"),
    "p_text": ("home.chat.p_text", "Your text"),
    "p_files": ("home.chat.p_files", "+ {n} files"),
    "p_out_image": ("home.chat.p_out_image", "Image"),
    "p_out_video": ("home.chat.p_out_video", "Video clip"),
    "p_out_music": ("home.chat.p_out_music", "Music track"),
    "p_out_voice": ("home.chat.p_out_voice", "Voice-over"),
    "p_saved": ("home.chat.p_saved", "Saved to Library"),
    "live": ("live.talk", "Talk to the studio"),
    # The audio player (gm_audio.js).
    "audio": ("home.chat.audio", "Audio"),
    "audio_play": ("home.chat.audio_play", "Play {name}"),
    "audio_pause": ("home.chat.audio_pause", "Pause {name}"),
    "audio_position": ("home.chat.audio_position", "{name} position"),
    "audio_of": ("home.chat.audio_of", "{a} of {b}"),
    "audio_speed": ("home.chat.audio_speed", "Playback speed {rate}"),
    "audio_download": ("home.chat.audio_download", "Download {name}"),
}


def strings() -> dict:
    return {k: tr(key, english) for k, (key, english) in _STRINGS.items()}


def _inputs() -> dict:
    """File slots per type (first frame, references...); {} if unavailable."""
    try:
        from services.studio_options import all_inputs

        return all_inputs()
    except Exception:  # pylint: disable=broad-except
        logging.getLogger(__name__).exception("Home: file slots unavailable")
        return {}


def _options() -> dict:
    """The type controls (services/studio_options.py); {} if they can't load."""
    try:
        from services.studio_options import all_fields

        return all_fields()
    except Exception:  # pylint: disable=broad-except
        logging.getLogger(__name__).exception("Home: type controls unavailable")
        return {}


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
            "optionsJson": json.dumps(_options(), ensure_ascii=False),
            "inputsJson": json.dumps(_inputs(), ensure_ascii=False),
            "talkJson": json.dumps({**live_strings(), "talk": t("live.talk", "Talk to the studio")}, ensure_ascii=False),
            "live": live,
        },
        events={"navEvent": on_home_nav},
    )
