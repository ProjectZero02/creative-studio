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
"""One model list for Video Studio: Gemini Omni first, then the Veo models.

Video Studio (/veo) offers both engines from one composer. This module is a
thin, pure layer over ``config/omni_models.py`` and ``config/veo_models.py``:
it answers "what can the selected model do" (modes, lengths, sizes, aspect
ratios, references) so the page never has to branch on the engine itself.

Studio mode ids are the Veo page's ids plus the Omni-only ones:
``t2v``, ``i2v``, ``interpolation`` (first + last frame), ``r2v``
(references), ``edit``, ``extend`` and ``upscale``. Omni calls the same two
modes ``first_last`` and ``ref2v``; ``omni_mode`` translates.
"""

from dataclasses import dataclass

from config.omni_models import (
    DEFAULT_OMNI_VERSION_ID,
    get_omni_model_config,
    modes_for_model,
)
from config.veo_models import VEO_MODELS, get_veo_model_config

DEFAULT_STUDIO_MODEL_ID = DEFAULT_OMNI_VERSION_ID
VIDEO_STUDIO_PATH = "/veo"


def omni_link_params(image_path: str | None = None) -> dict[str, str]:
    """Query params that open Video Studio with Gemini Omni selected.

    ``image_path`` (a bare ``bucket/object`` path, ``gs://`` URI or signed URL)
    is preloaded as the first frame in image-to-video mode.
    """
    params = {"veo_model": DEFAULT_OMNI_VERSION_ID}
    if image_path:
        params["image_path"] = image_path
    return params


# Plain-language names for the studio modes, in display order.
STUDIO_MODE_LABELS: dict[str, str] = {
    "t2v": "Text",
    "i2v": "Image",
    "interpolation": "First + last frame",
    "r2v": "References",
    "edit": "Edit video",
    "extend": "Extend",
    "upscale": "Upscale",
}

# Modes that take a video as input. The output keeps that video's framing and
# length, so aspect ratio and length settings do not apply.
VIDEO_INPUT_MODES = ("edit", "extend", "upscale")

_OMNI_TO_STUDIO = {"first_last": "interpolation", "ref2v": "r2v"}
_STUDIO_TO_OMNI = {v: k for k, v in _OMNI_TO_STUDIO.items()}


def is_omni(model_id: str) -> bool:
    """True when the id names a Gemini Omni model."""
    return get_omni_model_config(model_id) is not None


def studio_model_ids(current: str = "") -> list[str]:
    """Model ids for the model chip: default Omni first, then every Veo model.

    Older Omni previews stay out of the list, but a preview reached through a
    deep link (``?veo_model=``) is kept so the chip can show it.
    """
    ids = [DEFAULT_STUDIO_MODEL_ID] + [m.version_id for m in VEO_MODELS]
    if (
        current
        and current not in ids
        and (is_omni(current) or get_veo_model_config(current))
    ):
        ids.insert(1 if is_omni(current) else len(ids), current)
    return ids


def is_known_model(model_id: str) -> bool:
    """True for any Omni or Veo model id."""
    return is_omni(model_id) or get_veo_model_config(model_id) is not None


def model_display_name(model_id: str) -> str:
    """The model's display name (the id itself when unknown)."""
    config = get_omni_model_config(model_id) or get_veo_model_config(model_id)
    return config.display_name if config else model_id


def engine_name(model_id: str) -> str:
    """'Gemini Omni' or 'Veo', for progress stage labels."""
    return "Gemini Omni" if is_omni(model_id) else "Veo"


def typical_seconds(model_id: str) -> int:
    """Rough generation time for the progress hint ("usually ~Ns")."""
    config = get_omni_model_config(model_id) or get_veo_model_config(model_id)
    return config.typical_generation_seconds if config else 60


def omni_mode(studio_mode: str) -> str:
    """Translate a studio mode id to the Omni API's mode id."""
    return _STUDIO_TO_OMNI.get(studio_mode, studio_mode)


def studio_modes(model_id: str) -> list[str]:
    """Modes the model supports, as studio ids in display order."""
    if is_omni(model_id):
        offered = {_OMNI_TO_STUDIO.get(m, m) for m in modes_for_model(model_id)}
    else:
        config = get_veo_model_config(model_id)
        offered = set(config.supported_modes) if config else {"t2v"}
    return [m for m in STUDIO_MODE_LABELS if m in offered]


@dataclass(frozen=True)
class StudioLimits:
    """What the composer chips may offer for one model and mode."""

    durations: list[int]
    default_duration: int
    aspect_ratios: list[str]
    resolutions: list[str]
    max_samples: int
    max_references: int
    supports_style_reference: bool
    supports_audio_toggle: bool
    supports_advanced: bool
    follows_input_video: bool


def limits(model_id: str, mode: str) -> StudioLimits | None:
    """Chip limits for a model and studio mode (None for unknown models)."""
    follows_input = mode in VIDEO_INPUT_MODES
    omni = get_omni_model_config(model_id)
    if omni:
        return StudioLimits(
            durations=list(range(omni.min_duration, omni.max_duration + 1)),
            default_duration=omni.default_duration,
            aspect_ratios=list(omni.supported_aspect_ratios),
            resolutions=list(omni.resolutions),
            max_samples=omni.max_samples,
            max_references=omni.max_reference_images,
            supports_style_reference=False,
            # Omni always generates sound and has no seed, negative prompt or
            # people setting, so those controls stay hidden.
            supports_audio_toggle=False,
            supports_advanced=False,
            follows_input_video=follows_input,
        )
    veo = get_veo_model_config(model_id)
    if not veo:
        return None
    durations = veo.supported_durations or list(
        range(veo.min_duration, veo.max_duration + 1)
    )
    aspects = list(veo.supported_aspect_ratios)
    default_duration = veo.default_duration
    style_ref = True
    override = (veo.mode_overrides or {}).get(mode)
    if override:
        durations = override.supported_durations or durations
        aspects = override.supported_aspect_ratios or aspects
        default_duration = override.default_duration or default_duration
        style_ref = override.supports_style_reference
    return StudioLimits(
        durations=list(durations),
        default_duration=default_duration,
        aspect_ratios=aspects,
        resolutions=list(veo.resolutions),
        max_samples=veo.max_samples,
        max_references=3,
        supports_style_reference=style_ref,
        supports_audio_toggle="3." in veo.version_id,
        supports_advanced=True,
        follows_input_video=follows_input,
    )


@dataclass(frozen=True)
class StudioSettings:
    """The settings the composer holds; ``normalise`` keeps them valid."""

    mode: str
    aspect_ratio: str
    resolution: str
    video_length: int
    video_count: int


def normalise(model_id: str, settings: StudioSettings) -> StudioSettings:
    """Return settings that the model supports, changing only what must change.

    An unsupported mode falls back to text; a length, aspect ratio, resolution
    or count out of range falls back to the model's default or first option.
    """
    modes = studio_modes(model_id)
    mode = settings.mode if settings.mode in modes else "t2v"
    lim = limits(model_id, mode)
    if not lim:
        return StudioSettings(
            mode,
            settings.aspect_ratio,
            settings.resolution,
            settings.video_length,
            settings.video_count,
        )
    length = settings.video_length
    if length not in lim.durations:
        length = (
            lim.default_duration
            if lim.default_duration in lim.durations
            else lim.durations[-1]
        )
    aspect = settings.aspect_ratio
    if aspect not in lim.aspect_ratios:
        aspect = lim.aspect_ratios[0]
    resolution = settings.resolution
    if resolution not in lim.resolutions:
        resolution = "720p" if "720p" in lim.resolutions else lim.resolutions[0]
    count = max(1, min(settings.video_count, lim.max_samples))
    return StudioSettings(mode, aspect, resolution, length, count)
