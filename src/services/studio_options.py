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

Picking Image, Video, Music or Voice under the Home box shows a row of
settings (model, shape, length, voice...). ``fields(kind)`` lists them from
the same model registries the studio pages use (config/gemini_image_models,
config/video_studio_models, config/lyria_models, config/voice), so the
choices match. ``clean(kind, raw)`` turns what the browser sent into
settings the model supports, falling back to defaults; the job runners in
services/live_jobs.py read them from ``job.params["settings"]``.

A field is ``{"name", "label", "default", "options": [{"value", "label"}]}``.
A field whose choices depend on the model also has ``"by_model": {model:
{"default", "options"}}``.
"""

from __future__ import annotations

from typing import Any

from common.i18n import tr

KINDS = ("image", "video", "music", "voice")

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
}


def _label(name: str) -> str:
    return tr(f"studio.field.{name}", _LABELS[name])


def _opts(pairs) -> list[dict]:
    return [{"value": str(v), "label": str(lbl)} for v, lbl in pairs]


def _field(
    name: str, default: Any, options: list[dict], by_model: dict | None = None
) -> dict:
    out = {
        "name": name,
        "label": _label(name),
        "default": str(default),
        "options": options,
    }
    if by_model:
        out["by_model"] = by_model
    return out


# ---------------------------------------------------------------- per kind


def _image_fields() -> list[dict]:
    from config.default import Default
    from config.gemini_image_models import GEMINI_IMAGE_MODELS

    default_model = Default().GEMINI_IMAGE_GEN_MODEL
    names = [m.model_name for m in GEMINI_IMAGE_MODELS]
    if default_model not in names:
        default_model = names[0]
    aspects, sizes = {}, {}
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
    return [
        _field(
            "model",
            default_model,
            _opts((m.model_name, m.display_name) for m in GEMINI_IMAGE_MODELS),
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


def _video_fields() -> list[dict]:
    from config.video_studio_models import (
        DEFAULT_STUDIO_MODEL_ID,
        limits,
        model_display_name,
        studio_model_ids,
    )

    ids = [m for m in studio_model_ids() if limits(m, "t2v")]
    default_model = (
        DEFAULT_STUDIO_MODEL_ID if DEFAULT_STUDIO_MODEL_ID in ids else ids[0]
    )
    aspects, durations, resolutions, audio = {}, {}, {}, {}
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
    d = default_model
    return [
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
    ]


def _music_fields() -> list[dict]:
    from config.default import Default
    from config.lyria_models import LYRIA_MODELS

    default_model = Default().LYRIA_MODEL_VERSION
    names = [m.model_name for m in LYRIA_MODELS]
    if default_model not in names:
        default_model = names[0]
    return [
        _field(
            "model",
            default_model,
            _opts((m.model_name, m.display_name) for m in LYRIA_MODELS),
        )
    ]


def _voice_fields() -> list[dict]:
    from config.voice import (
        DEFAULT_LANGUAGE,
        DEFAULT_PACE,
        DEFAULT_STYLE,
        DEFAULT_VOICE,
        DEFAULT_VOICE_ENGINE,
        PACES,
        STYLES,
        VOICES,
        languages_for,
    )

    languages = languages_for(DEFAULT_VOICE_ENGINE)
    return [
        _field("voice", DEFAULT_VOICE, _opts((v, v) for v in VOICES)),
        _field(
            "language",
            DEFAULT_LANGUAGE,
            _opts((code, name) for name, code in sorted(languages.items())),
        ),
        _field(
            "style",
            DEFAULT_STYLE,
            _opts((k, tr(f"studio.style.{k}", lbl)) for k, lbl, _ in STYLES),
        ),
        _field(
            "pace",
            DEFAULT_PACE,
            _opts((k, tr(f"studio.pace.{k}", lbl)) for k, lbl, _r, _t in PACES),
        ),
    ]


_BUILDERS = {
    "image": _image_fields,
    "video": _video_fields,
    "music": _music_fields,
    "voice": _voice_fields,
}


def fields(kind: str) -> list[dict]:
    """The settings shown for one type ([] for unknown types)."""
    builder = _BUILDERS.get(kind)
    return builder() if builder else []


def all_fields() -> dict[str, list[dict]]:
    return {k: fields(k) for k in KINDS}


def clean(kind: str, raw: Any) -> dict[str, str]:
    """Settings the model supports: each known field, or its default."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for f in fields(kind):
        choice = f
        if f.get("by_model") and out.get("model") in f["by_model"]:
            choice = f["by_model"][out["model"]]
        allowed = {o["value"] for o in choice["options"]}
        value = str(raw.get(f["name"], "") or "")
        out[f["name"]] = value if value in allowed else str(choice["default"])
    return out


def summary(kind: str, settings: dict[str, str]) -> str:
    """A short line for the thread, e.g. "Gemini Omni · 16:9 · 8s"."""
    quiet = {"audio", "language", "style", "pace"}  # named only when changed
    parts = []
    for f in fields(kind):
        value = settings.get(f["name"], "")
        choice = f
        if f.get("by_model"):
            choice = f["by_model"].get(settings.get("model"), f)
        if not value or (f["name"] in quiet and value == str(choice["default"])):
            continue
        label = next(
            (o["label"] for o in choice["options"] if o["value"] == value), value
        )
        parts.append(label)
    return " · ".join(parts)
