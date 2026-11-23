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
"""The Home box's controls: what each type offers and what a job may ask for.

Picking Image, Video, Music, Voice or Film on Home shows that type's settings.
``fields(kind)`` lists them from the same model registries the studio pages
use (config/gemini_image_models, config/video_studio_models,
config/lyria_models, config/voice, services/story_models), so the choices
match the studios. ``clean(kind, raw)`` turns what the browser sent into
settings the model supports, falling back to defaults; the job runners in
services/live_jobs.py read them from ``job.params["settings"]``.

A field is::

    {"name", "label", "default", "options": [{"value", "label"}],
     "tier": "main" | "advanced",
     "type": "select" | "toggle" | "text" | "textarea" | "number",
     "by_model"?: {model: {"default", "options"}},
     "show_if"?: {"<field>": ["value", ...]},
     "placeholder"?, "min"?, "max"?, "max_length"?, "help"?}

Toggles hold "on"/"off". ``inputs(kind)`` lists the file slots (first
frame, references, input video...) and ``all_inputs()`` all of them.
"""

from __future__ import annotations

from typing import Any

from common.i18n import tr

KINDS = ("image", "video", "music", "voice", "film")

ON, OFF = "on", "off"
TEXT_MAX = 200
TEXTAREA_MAX = 4000

_LABELS = {
    "model": "Model",
    "aspect": "Shape",
    "size": "Quality",
    "duration": "Length",
    "resolution": "Quality",
    "audio": "Sound",
    "voice": "Voice",
    "language": "Language",
    "style": "Style",
    "pace": "Pace",
    "length": "Length",
    "count": "Number",
    "brand": "Brand colours",
    "search": "Search grounding",
    "thinking": "Thinking",
    "mode": "Mode",
    "negative_prompt": "Avoid",
    "seed": "Seed",
    "people": "People",
    "enhance": "Improve prompt",
    "lyrics": "Lyrics",
    "lyrics_text": "Lyrics text",
    "instrumental": "Instrumental",
    "dialogue": "Two speakers",
    "speaker_a": "Speaker 1",
    "speaker_b": "Speaker 2",
    "voice_b": "Voice 2",
    "direction": "Direction",
    "pronunciations": "Pronunciations",
    "source": "Start from",
    "engine": "Video engine",
    "pacing": "Pacing",
    "speech": "Who speaks",
    "camera": "Camera",
    "scenes": "Scenes",
    "scene_length": "Scene length",
}

# Fields named in summary() only when changed from their default.
_QUIET = {
    "audio",
    "language",
    "style",
    "pace",
    "length",
    "aspect",
    "mode",
    "search",
    "thinking",
    "people",
    "enhance",
    "brand",
    "instrumental",
    "lyrics",
    "dialogue",
    "count",
    "source",
    "engine",
    "pacing",
    "speech",
    "camera",
    "scenes",
    "scene_length",
    "voice_b",
}
# Per type: the voice model is named only when changed.
_QUIET_BY_KIND = {"voice": {"model"}}


def _label(name: str) -> str:
    return tr(f"studio.field.{name}", _LABELS[name])


def _opts(pairs) -> list[dict]:
    return [{"value": str(v), "label": str(lbl)} for v, lbl in pairs]


def _toggle_opts() -> list[dict]:
    return _opts([(ON, tr("studio.on", "On")), (OFF, tr("studio.off", "Off"))])


def _field(
    name: str,
    default: Any,
    options: list[dict] | None = None,
    by_model: dict | None = None,
    *,
    tier: str = "main",
    type: str = "select",  # pylint: disable=redefined-builtin
    **extra: Any,
) -> dict:
    out = {
        "name": name,
        "label": _label(name),
        "default": str(default),
        "options": options if options is not None else [],
        "tier": tier,
        "type": type,
    }
    if type == "toggle" and not out["options"]:
        out["options"] = _toggle_opts()
    if by_model:
        out["by_model"] = by_model
    for key, value in extra.items():
        if value is not None:
            out[key] = value
    return out


def _counts(maximum: int, unit: str) -> dict:
    return {
        "default": "1",
        "options": _opts((i, f"{i} {unit}") for i in range(1, maximum + 1)),
    }


# ---------------------------------------------------------------- image

# Clearer names for the image models ("Gemini 3 Pro" reads like a chat model).
_IMAGE_NICKNAMES = {
    "3.0-pro": "Nano Banana Pro",
    "3.1-flash": "Nano Banana 2",
    "3.1-flash-lite": "Nano Banana 2 Lite",
    "nano-banana-2.1": "Nano Banana 2.1",
}


def image_model_label(model) -> str:
    """E.g. "Nano Banana Pro · Gemini 3 Pro Image" for a registry entry."""
    full = model.display_name
    nick = _IMAGE_NICKNAMES.get(model.version_id, "")
    if nick and nick.lower() in full.lower():
        return nick
    if "image" not in full.lower():
        full = f"{full} Image"
    return f"{nick} · {full}" if nick else full


def _image_fields() -> list[dict]:
    from config.default import Default
    from config.gemini_image_models import GEMINI_IMAGE_MODELS

    default_model = Default().GEMINI_IMAGE_GEN_MODEL
    names = [m.model_name for m in GEMINI_IMAGE_MODELS]
    if default_model not in names:
        default_model = names[0]
    aspects, sizes, counts = {}, {}, {}
    for m in GEMINI_IMAGE_MODELS:
        ratios = list(m.supported_aspect_ratios)
        aspects[m.model_name] = {
            "default": "1:1" if "1:1" in ratios else ratios[0],
            "options": _opts((r, r) for r in ratios),
        }
        size_list = list(m.supported_image_sizes)
        sizes[m.model_name] = {
            "default": "1K" if "1K" in size_list else size_list[0],
            "options": _opts((s, s) for s in size_list),
        }
        counts[m.model_name] = _counts(max(1, m.max_output_images), "images")
    out = [
        _field(
            "model",
            default_model,
            _opts((m.model_name, image_model_label(m)) for m in GEMINI_IMAGE_MODELS),
        ),
        _field(
            "aspect",
            aspects[default_model]["default"],
            aspects[default_model]["options"],
            aspects,
        ),
        _field(
            "size",
            sizes[default_model]["default"],
            sizes[default_model]["options"],
            sizes,
        ),
    ]
    multi = [m.model_name for m in GEMINI_IMAGE_MODELS if m.max_output_images > 1]
    if multi:
        out.append(
            _field(
                "count",
                "1",
                counts[default_model]["options"],
                counts,
                show_if={"model": multi},
            )
        )
    out.append(_field("brand", OFF, tier="advanced", type="toggle"))
    search = [m.model_name for m in GEMINI_IMAGE_MODELS if m.supports_search]
    if search:
        out.append(
            _field(
                "search",
                ON,
                tier="advanced",
                type="toggle",
                show_if={"model": search},
                help=tr("studio.help.search", "Look things up on Google first"),
            )
        )
    thinking = [m.model_name for m in GEMINI_IMAGE_MODELS if m.supports_thinking]
    if thinking:
        out.append(
            _field(
                "thinking",
                "HIGH",
                _opts(
                    [
                        ("HIGH", tr("studio.thinking.high", "High")),
                        ("MINIMAL", tr("studio.thinking.minimal", "Minimal")),
                    ]
                ),
                tier="advanced",
                show_if={"model": thinking},
            )
        )
    return out


def _image_inputs() -> list[dict]:
    from config.gemini_image_models import GEMINI_IMAGE_MODELS

    by_model = {m.model_name: m.max_input_images for m in GEMINI_IMAGE_MODELS}
    return [
        {
            "name": "references",
            "label": tr("studio.input.references", "References"),
            "accept": "image/*",
            "max": max(by_model.values()),
            "by_model": by_model,
        }
    ]


# ---------------------------------------------------------------- video

PEOPLE = {
    "allow_all": "Allow (All ages)",
    "allow_adult": "Allow (Adults only)",
    "dont_allow": "Don't Allow",
}


def video_modes(model_id: str) -> list[str]:
    """Studio modes for a model; Veo models that extend clips get "extend"."""
    from config.veo_models import get_veo_model_config
    from config.video_studio_models import STUDIO_MODE_LABELS, studio_modes

    modes = list(studio_modes(model_id))
    veo = get_veo_model_config(model_id)
    if veo and veo.supports_video_extension and "extend" not in modes:
        modes.append("extend")
    return [m for m in STUDIO_MODE_LABELS if m in modes]


def _video_fields() -> list[dict]:
    from config.veo_models import get_veo_model_config
    from config.video_studio_models import (
        DEFAULT_STUDIO_MODEL_ID,
        STUDIO_MODE_LABELS,
        limits,
        model_display_name,
        studio_model_ids,
    )

    ids = [m for m in studio_model_ids() if limits(m, "t2v")]
    default_model = (
        DEFAULT_STUDIO_MODEL_ID if DEFAULT_STUDIO_MODEL_ID in ids else ids[0]
    )
    aspects, durations, resolutions, audio, modes, counts = {}, {}, {}, {}, {}, {}
    for m in ids:
        lim = limits(m, "t2v")
        aspects[m] = {
            "default": "16:9" if "16:9" in lim.aspect_ratios else lim.aspect_ratios[0],
            "options": _opts((a, a) for a in lim.aspect_ratios),
        }
        default_len = (
            lim.default_duration
            if lim.default_duration in lim.durations
            else lim.durations[-1]
        )
        durations[m] = {
            "default": str(default_len),
            "options": _opts((d, f"{d}s") for d in lim.durations),
        }
        resolutions[m] = {
            "default": "720p" if "720p" in lim.resolutions else lim.resolutions[0],
            "options": _opts((r, r) for r in lim.resolutions),
        }
        # Omni always makes sound; Veo 3 can turn it off.
        audio[m] = {
            "default": "on",
            "options": _opts(
                [("on", tr("studio.audio.on", "With sound"))]
                + (
                    [("off", tr("studio.audio.off", "No sound"))]
                    if lim.supports_audio_toggle
                    else []
                )
            ),
        }
        modes[m] = {
            "default": "t2v",
            "options": _opts(
                (x, tr(f"studio.mode.{x}", STUDIO_MODE_LABELS[x]))
                for x in video_modes(m)
            ),
        }
        counts[m] = _counts(max(1, lim.max_samples), "videos")
    d = default_model
    out = [
        _field("model", d, _opts((m, model_display_name(m)) for m in ids)),
        _field("aspect", aspects[d]["default"], aspects[d]["options"], aspects),
        _field("duration", durations[d]["default"], durations[d]["options"], durations),
        _field(
            "resolution",
            resolutions[d]["default"],
            resolutions[d]["options"],
            resolutions,
        ),
        _field("audio", "on", audio[d]["options"], audio),
        _field("mode", "t2v", modes[d]["options"], modes),
    ]
    multi = [m for m in ids if limits(m, "t2v").max_samples > 1]
    if multi:
        out.append(
            _field("count", "1", counts[d]["options"], counts, show_if={"model": multi})
        )
    veo = [m for m in ids if get_veo_model_config(m)]
    if veo:
        out += [
            _field(
                "negative_prompt",
                "",
                tier="advanced",
                type="text",
                show_if={"model": veo},
                placeholder=tr("studio.ph.negative", "What to leave out"),
                max_length=TEXT_MAX,
            ),
            _field(
                "seed",
                "0",
                tier="advanced",
                type="number",
                show_if={"model": veo},
                min=0,
                max=4294967295,
                help=tr("studio.help.seed", "0 = random"),
            ),
            _field(
                "people",
                "allow_adult",
                _opts((k, tr(f"studio.people.{k}", lbl)) for k, lbl in PEOPLE.items()),
                tier="advanced",
                show_if={"model": veo},
            ),
        ]
        enhance = [
            m
            for m in veo
            if get_veo_model_config(m).supports_prompt_enhancement
            and not get_veo_model_config(m).requires_prompt_enhancement
        ]
        if enhance:
            out.append(
                _field(
                    "enhance",
                    ON,
                    tier="advanced",
                    type="toggle",
                    show_if={"model": enhance},
                )
            )
    return out


def _video_inputs() -> list[dict]:
    from config.video_studio_models import limits, studio_model_ids

    ids = [m for m in studio_model_ids() if limits(m, "t2v")]
    refs = {m: limits(m, "r2v").max_references for m in ids if "r2v" in video_modes(m)}
    style = [m for m in ids if limits(m, "r2v").supports_style_reference]
    out = [
        {
            "name": "first_frame",
            "label": tr("studio.input.first_frame", "First frame"),
            "accept": "image/*",
            "max": 1,
            "show_if": {"mode": ["i2v", "interpolation"]},
        },
        {
            "name": "last_frame",
            "label": tr("studio.input.last_frame", "Last frame"),
            "accept": "image/*",
            "max": 1,
            "show_if": {"mode": ["interpolation"]},
        },
        {
            "name": "references",
            "label": tr("studio.input.references", "References"),
            "accept": "image/*",
            "max": max(refs.values()) if refs else 3,
            "by_model": refs,
            "show_if": {"mode": ["r2v"]},
        },
    ]
    if style:
        out.append(
            {
                "name": "style",
                "label": tr("studio.input.style", "Style image"),
                "accept": "image/*",
                "max": 1,
                "show_if": {"mode": ["r2v"], "model": style},
            }
        )
    out.append(
        {
            "name": "video",
            "label": tr("studio.input.video", "Input video"),
            "accept": "video/*",
            "max": 1,
            "show_if": {"mode": ["edit", "extend", "upscale"]},
        }
    )
    return out


# ---------------------------------------------------------------- music


def default_music_model() -> str:
    """The studio's default Lyria model name (LYRIA_DEFAULT_MODEL)."""
    from config.default import Default
    from config.lyria_models import LYRIA_MODELS, get_lyria_model_config

    cfg = get_lyria_model_config(Default().LYRIA_DEFAULT_MODEL)
    return cfg.model_name if cfg else LYRIA_MODELS[0].model_name


def _music_fields() -> list[dict]:
    from config.lyria_models import LYRIA_MODELS

    default_model = default_music_model()
    counts = {
        m.model_name: _counts(max(1, m.max_samples), "tracks") for m in LYRIA_MODELS
    }
    multi = [m.model_name for m in LYRIA_MODELS if m.max_samples > 1]
    lyric = [m.model_name for m in LYRIA_MODELS if m.supports_lyrics]
    out = [
        _field(
            "model",
            default_model,
            _opts((m.model_name, m.display_name) for m in LYRIA_MODELS),
        )
    ]
    if multi:
        out.append(
            _field(
                "count",
                "1",
                counts[default_model]["options"],
                counts,
                show_if={"model": multi},
            )
        )
    if lyric:
        out += [
            _field(
                "lyrics", OFF, tier="advanced", type="toggle", show_if={"model": lyric}
            ),
            _field(
                "lyrics_text",
                "",
                tier="advanced",
                type="textarea",
                show_if={"lyrics": [ON]},
                placeholder=tr("studio.ph.lyrics", "Your lyrics"),
                max_length=TEXTAREA_MAX,
            ),
            _field(
                "instrumental",
                OFF,
                tier="advanced",
                type="toggle",
                show_if={"model": lyric},
            ),
        ]
    return out


def _music_inputs() -> list[dict]:
    from config.lyria_models import LYRIA_MODELS

    images = [m.model_name for m in LYRIA_MODELS if m.supports_images]
    if not images:
        return []
    return [
        {
            "name": "image",
            "label": tr("studio.input.image", "Reference image"),
            "accept": "image/*",
            "max": 1,
            "show_if": {"model": images},
        }
    ]


# ---------------------------------------------------------------- voice


def _voice_fields() -> list[dict]:
    from config.voice import (
        CHIRP_ENGINE,
        DEFAULT_LANGUAGE,
        DEFAULT_PACE,
        DEFAULT_SECOND_VOICE,
        DEFAULT_SPEAKERS,
        DEFAULT_STYLE,
        DEFAULT_VOICE,
        DEFAULT_VOICE_ENGINE,
        PACES,
        STYLES,
        VOICES,
        engine_options,
        engine_supports_dialogue,
        is_chirp,
        languages_for,
    )

    engines = [value for value, _label, _hint in engine_options()]
    gemini = [e for e in engines if not is_chirp(e)]
    dialogue = [e for e in engines if engine_supports_dialogue(e)]
    languages = {}
    for e in engines:
        langs = languages_for(e)
        codes = list(langs.values())
        languages[e] = {
            "default": DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in codes else codes[0],
            "options": _opts((code, name) for name, code in sorted(langs.items())),
        }
    d = DEFAULT_VOICE_ENGINE
    voices = _opts((v, v) for v in VOICES)
    out = [
        _field("model", d, _opts((v, lbl) for v, lbl, _h in engine_options())),
        _field("voice", DEFAULT_VOICE, voices),
        _field("language", languages[d]["default"], languages[d]["options"], languages),
        _field(
            "style",
            DEFAULT_STYLE,
            _opts((k, tr(f"studio.style.{k}", lbl)) for k, lbl, _ in STYLES),
            show_if={"model": gemini},
        ),
        _field(
            "pace",
            DEFAULT_PACE,
            _opts((k, tr(f"studio.pace.{k}", lbl)) for k, lbl, _r, _t in PACES),
        ),
    ]
    if dialogue:
        out += [
            _field(
                "dialogue",
                OFF,
                tier="advanced",
                type="toggle",
                show_if={"model": dialogue},
            ),
            _field(
                "speaker_a",
                DEFAULT_SPEAKERS[0],
                tier="advanced",
                type="text",
                show_if={"dialogue": [ON]},
                max_length=40,
            ),
            _field(
                "speaker_b",
                DEFAULT_SPEAKERS[1],
                tier="advanced",
                type="text",
                show_if={"dialogue": [ON]},
                max_length=40,
            ),
            _field(
                "voice_b",
                DEFAULT_SECOND_VOICE,
                voices,
                tier="advanced",
                show_if={"dialogue": [ON]},
            ),
        ]
    out.append(
        _field(
            "direction",
            "",
            tier="advanced",
            type="textarea",
            show_if={"model": gemini},
            placeholder=tr("studio.ph.direction", "How to say it"),
            max_length=1000,
        )
    )
    out.append(
        _field(
            "pronunciations",
            "",
            tier="advanced",
            type="textarea",
            show_if={"model": [CHIRP_ENGINE]},
            placeholder="GenMedia=jen media",
            help=tr("studio.help.pronunciations", "One per line: word=how to say it"),
            max_length=2000,
        )
    )
    return out


# ---------------------------------------------------------------- film

FILM_LENGTHS = (
    ("30", "30s"),
    ("60", "1m"),
    ("120", "2m"),
    ("180", "3m"),
    ("300", "5m"),
    ("600", "10m"),
)


def _film_fields() -> list[dict]:
    """Story Studio's starting choices; "auto" lets it pick from the idea."""
    from config.default import Default
    from services.story_models import (
        ASPECT_RATIOS,
        CAMERA_PRESETS,
        LANGUAGES,
        PACING_MODES,
        SCENE_LENGTHS,
        SPEECH_MODES,
        STORY_VIDEO_ENGINES,
        STYLES,
    )

    auto = tr("studio.auto", "Auto")
    cfg = Default()
    low = int(cfg.STORY_MIN_SCENES)
    high = min(int(cfg.STORY_MAX_SCENES), 12)
    return [
        _field("length", "auto", _opts([("auto", auto)] + list(FILM_LENGTHS))),
        _field(
            "aspect", "auto", _opts([("auto", auto)] + [(a, a) for a in ASPECT_RATIOS])
        ),
        _field(
            "style",
            "auto",
            _opts([("auto", auto)] + [(s["id"], s["label"]) for s in STYLES]),
        ),
        _field(
            "language",
            "auto",
            _opts([("auto", auto)] + [(name, name) for name in LANGUAGES]),
        ),
        _field(
            "source",
            "idea",
            _opts(
                [
                    ("idea", tr("studio.film.idea", "Idea")),
                    ("script", tr("studio.film.script", "Script")),
                ]
            ),
            tier="advanced",
        ),
        _field(
            "engine",
            "auto",
            _opts([("auto", auto)] + list(STORY_VIDEO_ENGINES.items())),
            tier="advanced",
        ),
        _field(
            "pacing",
            "auto",
            _opts(
                [("auto", auto)] + [(k, v["label"]) for k, v in PACING_MODES.items()]
            ),
            tier="advanced",
        ),
        _field(
            "speech",
            "auto",
            _opts(
                [("auto", auto)]
                + [(k, v) for k, v in SPEECH_MODES.items() if k != "auto"]
            ),
            tier="advanced",
        ),
        _field(
            "camera",
            "auto",
            _opts([(k, v["label"]) for k, v in CAMERA_PRESETS.items()]),
            tier="advanced",
        ),
        _field(
            "scenes",
            "auto",
            _opts(
                [("auto", auto)] + [(n, f"{n} scenes") for n in range(low, high + 1)]
            ),
            tier="advanced",
            show_if={"length": ["auto"], "source": ["idea"]},
        ),
        _field(
            "scene_length",
            "auto",
            _opts([("auto", auto)] + [(s, f"{s}s") for s in SCENE_LENGTHS]),
            tier="advanced",
            show_if={"length": ["auto"], "source": ["idea"]},
        ),
    ]


_BUILDERS = {
    "image": _image_fields,
    "video": _video_fields,
    "music": _music_fields,
    "voice": _voice_fields,
    "film": _film_fields,
}

_INPUTS = {
    "image": _image_inputs,
    "video": _video_inputs,
    "music": _music_inputs,
}


def fields(kind: str) -> list[dict]:
    """The settings shown for one type ([] for unknown types)."""
    builder = _BUILDERS.get(kind)
    return builder() if builder else []


def all_fields() -> dict[str, list[dict]]:
    return {k: fields(k) for k in KINDS}


def inputs(kind: str) -> list[dict]:
    """The file slots for one type ([] when it takes no files)."""
    builder = _INPUTS.get(kind)
    return builder() if builder else []


def all_inputs() -> dict[str, list[dict]]:
    return {k: inputs(k) for k in KINDS}


def _clean_value(f: dict, choice: dict, value: Any) -> str:
    kind = f.get("type", "select")
    if kind in ("text", "textarea"):
        text = str(value if value is not None else f["default"])
        text = text.replace("\r\n", "\n").strip()
        if kind == "text":
            text = " ".join(text.split())
        return text[
            : int(f.get("max_length") or (TEXT_MAX if kind == "text" else TEXTAREA_MAX))
        ]
    if kind == "number":
        try:
            number = int(float(str(value).strip()))
        except TypeError, ValueError:
            return str(choice["default"])
        low, high = f.get("min"), f.get("max")
        if low is not None:
            number = max(int(low), number)
        if high is not None:
            number = min(int(high), number)
        return str(number)
    if kind == "toggle" and isinstance(value, bool):
        value = ON if value else OFF
    allowed = {o["value"] for o in choice["options"]}
    value = str(value if value is not None else "")
    return value if value in allowed else str(choice["default"])


def clean(kind: str, raw: Any) -> dict[str, str]:
    """Settings the model supports: each known field, or its default."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for f in fields(kind):
        choice = f
        if f.get("by_model") and out.get("model") in f["by_model"]:
            choice = f["by_model"][out["model"]]
        value = raw.get(f["name"])
        if value is None or value == "":
            value = None if f.get("type") in ("text", "textarea") else choice["default"]
        out[f["name"]] = _clean_value(f, choice, value)
    # A field the person cannot see (show_if) keeps its default.
    for f in fields(kind):
        if not shown(f, out):
            choice = f
            if f.get("by_model") and out.get("model") in f["by_model"]:
                choice = f["by_model"][out["model"]]
            out[f["name"]] = str(choice["default"])
    return out


def shown(f: dict, settings: dict[str, str]) -> bool:
    """True when a field's show_if allows it for these settings."""
    for other, values in (f.get("show_if") or {}).items():
        if settings.get(other) not in values:
            return False
    return True


def option_label(kind: str, name: str, settings: dict[str, str]) -> str:
    """The label of the chosen option for a field (the value when unknown)."""
    value = settings.get(name, "")
    for f in fields(kind):
        if f["name"] != name:
            continue
        choice = f
        if f.get("by_model"):
            choice = f["by_model"].get(settings.get("model"), f)
        return next(
            (o["label"] for o in choice["options"] if o["value"] == value), value
        )
    return value


def summary(kind: str, settings: dict[str, str]) -> str:
    """A short line for the thread, e.g. "Gemini Omni · 16:9 · 8s"."""
    parts = []
    for f in fields(kind):
        value = settings.get(f["name"], "")
        choice = f
        if f.get("by_model"):
            choice = f["by_model"].get(settings.get("model"), f)
        if not value or not shown(f, settings):
            continue
        quiet = _QUIET | _QUIET_BY_KIND.get(kind, set())
        if f["name"] in quiet and value == str(choice["default"]):
            continue
        ftype = f.get("type", "select")
        if ftype in ("text", "textarea", "number"):
            continue  # free text and seeds stay out of the one-line summary
        if ftype == "toggle":
            parts.append(
                f"{f['label']}: {tr('studio.on', 'On') if value == ON else tr('studio.off', 'Off')}"
            )
            continue
        label = next(
            (o["label"] for o in choice["options"] if o["value"] == value), value
        )
        parts.append(label)
    return " · ".join(parts)
