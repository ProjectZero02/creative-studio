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

"""Omni-or-Veo video generation for every page that once called Veo directly.

Workflows pick their video model from an environment-driven model name
(``INTERIOR_DESIGN_VIDEO_MODEL``, ``OBJECT_ROTATION_VIDEO_MODEL``,
``CHARACTER_CONSISTENCY_VEO_MODEL``) and pages build Veo-shaped
``VideoGenerationRequest``s. The name or id can be a Gemini Omni model
(``gemini-omni-*``, the default) or a Veo model (``veo-*`` / a Veo version
id); this module routes the call and hides the two request shapes.
"""

from common.error_handling import GenerationError
from config.omni_models import (
    OmniModelConfig,
    clamp_duration,
    get_omni_model_config,
    modes_for_model,
)
from config.omni_models import get_version_id_by_model_name as omni_version_id
from config.veo_models import get_veo_model_config
from config.veo_models import get_version_id_by_model_name as veo_version_id
from models.omni import generate_omni_video
from models.requests import (
    APIReferenceImage,
    OmniVideoGenerationRequest,
    VideoGenerationRequest,
)
from models.veo import generate_video

WORKFLOW_RESOLUTION = "720p"
WORKFLOW_ASPECT_RATIO = "16:9"
ROTATION_OMNI_SECONDS = 8
# Omni 1.2 Flash makes 3-15 s clips, but first + last frame clips stop at 10 s
# (Gemini Omni 1.2 Flash model card, "Durations").
FIRST_LAST_MAX_SECONDS = 10

# Fallbacks used when the configured name is not in either registry.
DEFAULT_VEO_I2V_VERSION = "3.1-lite"
DEFAULT_VEO_R2V_VERSION = "3.1"


def is_omni_model_name(model_name: str) -> bool:
    """Return True if a configured model name is a registered Omni model."""
    return omni_version_id(model_name) is not None


def resolve_omni_model(model_id: str):
    """The Omni model config for a version id or model name (None for Veo)."""
    return get_omni_model_config(omni_version_id(model_id) or model_id)


def omni_mode_for_request(request: VideoGenerationRequest) -> str:
    """Pick the Omni mode a Veo-shaped request asks for, from its inputs."""
    if request.video_input_gcs:
        return "extend"
    if request.r2v_references:
        return "ref2v"
    if request.reference_image_gcs and request.last_reference_image_gcs:
        return "first_last"
    if request.reference_image_gcs:
        return "i2v"
    return "t2v"


def to_omni_request(
    request: VideoGenerationRequest, omni: OmniModelConfig
) -> OmniVideoGenerationRequest:
    """Translate a Veo-shaped request into an Omni request for ``omni``.

    Length, aspect ratio and resolution are kept inside the model's limits.
    Veo-only settings (seed, negative prompt, people, audio toggle, style
    image, sample count) have no Omni equivalent and are dropped.

    Raises:
        GenerationError: If the model does not offer the mode the inputs need.

    """
    mode = omni_mode_for_request(request)
    if mode not in omni.supported_modes:
        raise GenerationError(f"{omni.display_name} does not support '{mode}'.")

    duration = clamp_duration(omni.version_id, request.duration_seconds)
    if mode == "first_last":
        duration = min(duration, FIRST_LAST_MAX_SECONDS)
    aspect = request.aspect_ratio
    if aspect not in omni.supported_aspect_ratios:
        aspect = omni.supported_aspect_ratios[0]
    resolution = request.resolution
    if resolution not in omni.resolutions:
        resolution = "720p" if "720p" in omni.resolutions else omni.resolutions[0]

    return OmniVideoGenerationRequest(
        prompt=request.prompt,
        duration_seconds=duration,
        aspect_ratio=aspect,
        resolution=resolution,
        omni_mode=mode,
        model_version_id=omni.version_id,
        reference_image_gcs=request.reference_image_gcs,
        reference_image_mime_type=request.reference_image_mime_type,
        last_reference_image_gcs=request.last_reference_image_gcs,
        last_reference_image_mime_type=request.last_reference_image_mime_type,
        reference_video_gcs=request.video_input_gcs,
        reference_video_mime_type=request.video_input_mime_type
        if request.video_input_gcs
        else None,
        r2v_references=request.r2v_references,
    )


def generate_video_any_model(
    request: VideoGenerationRequest,
) -> tuple[list[str], str]:
    """Run a Veo-shaped request on Gemini Omni or Veo, whichever it names.

    A drop-in for ``models.veo.generate_video``. When ``model_version_id`` is a
    Gemini Omni model (version id or model name), the request is translated
    with ``to_omni_request`` (mode from the inputs: a video to extend,
    references, first + last frame, one image, or text). Any other id goes to
    Veo unchanged, so the Veo path stays one setting away.

    Returns:
        The GCS URIs of the generated clips (Omni returns at most one) and the
        resolution they were made at.

    """
    omni = resolve_omni_model(request.model_version_id)
    if not omni:
        video_uris, resolution = generate_video(request)
        return list(video_uris or []), resolution

    omni_request = to_omni_request(request, omni)
    gcs_uri, _ = generate_omni_video(omni_request)
    return ([gcs_uri] if gcs_uri else []), omni_request.resolution


def generate_workflow_image_to_video(
    model_name: str,
    image_gcs_uri: str,
    prompt: str,
    duration_seconds: int,
    feature: str | None = None,
) -> str | None:
    """Animate one image into a 16:9 720p clip with Omni or Veo.

    Args:
        model_name: Configured model name (``gemini-omni-*`` or ``veo-*``).
        image_gcs_uri: GCS URI of the source image (PNG).
        prompt: Camera/motion prompt.
        duration_seconds: Requested clip length (clamped for Omni models).

    Returns:
        The GCS URI of the generated clip, or None if no video was returned.

    Raises:
        GenerationError: If the Omni model cannot do image-to-video.

    """
    omni_version = omni_version_id(model_name)
    if omni_version:
        if "i2v" not in modes_for_model(omni_version):
            raise GenerationError(
                f"{model_name} does not support image-to-video.",
            )
        gcs_uri, _ = generate_omni_video(
            OmniVideoGenerationRequest(
                prompt=prompt,
                duration_seconds=clamp_duration(omni_version, duration_seconds),
                aspect_ratio=WORKFLOW_ASPECT_RATIO,
                resolution=WORKFLOW_RESOLUTION,
                omni_mode="i2v",
                model_version_id=omni_version,
                reference_image_gcs=image_gcs_uri,
                reference_image_mime_type="image/png",
            ),
            feature=feature,
        )
        return gcs_uri or None

    video_uris, _ = generate_video(
        request=VideoGenerationRequest(
            model_version_id=veo_version_id(model_name) or DEFAULT_VEO_I2V_VERSION,
            reference_image_gcs=image_gcs_uri,
            reference_image_mime_type="image/png",
            duration_seconds=duration_seconds,
            prompt=prompt,
            aspect_ratio=WORKFLOW_ASPECT_RATIO,
            video_count=1,
            enhance_prompt=False,
            generate_audio=False,
            resolution=WORKFLOW_RESOLUTION,
            person_generation="Allow (Adults only)",
        ),
        feature=feature,
    )
    return video_uris[0] if video_uris else None


def generate_workflow_reference_video(
    model_name: str,
    reference_gcs_uris: list[str],
    prompt: str,
    feature: str | None = None,
) -> str | None:
    """Generate a 16:9 720p clip conditioned on reference images.

    Args:
        model_name: Configured model name (``gemini-omni-*`` or ``veo-*``).
        reference_gcs_uris: GCS URIs of the reference images (PNG), in order.
        prompt: The video prompt.

    Returns:
        The GCS URI of the generated clip, or None if no video was returned.

    Raises:
        GenerationError: If the model cannot do reference-to-video or is unknown.

    """
    references = [
        APIReferenceImage(gcs_uri=uri, mime_type="image/png")
        for uri in reference_gcs_uris
    ]

    omni_version = omni_version_id(model_name)
    if omni_version:
        if "ref2v" not in modes_for_model(omni_version):
            raise GenerationError(
                f"{model_name} does not support reference-to-video.",
            )
        gcs_uri, _ = generate_omni_video(
            OmniVideoGenerationRequest(
                prompt=prompt,
                duration_seconds=clamp_duration(omni_version, ROTATION_OMNI_SECONDS),
                aspect_ratio=WORKFLOW_ASPECT_RATIO,
                resolution=WORKFLOW_RESOLUTION,
                omni_mode="ref2v",
                model_version_id=omni_version,
                r2v_references=references,
            ),
            feature=feature,
        )
        return gcs_uri or None

    version = veo_version_id(model_name) or DEFAULT_VEO_R2V_VERSION
    veo_config = get_veo_model_config(version)
    if not veo_config:
        raise GenerationError(f"Unsupported video model: {model_name}")

    video_uris, _ = generate_video(
        VideoGenerationRequest(
            prompt=prompt,
            duration_seconds=veo_config.default_duration,
            video_count=1,
            aspect_ratio=veo_config.supported_aspect_ratios[0],
            resolution=WORKFLOW_RESOLUTION,
            enhance_prompt=True,
            generate_audio=True,
            model_version_id=version,
            person_generation="dont_allow",
            r2v_references=references,
        ),
        feature=feature,
    )
    return video_uris[0] if video_uris else None
