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

from dataclasses import field

import mesop as me
from config.video_studio_models import DEFAULT_STUDIO_MODEL_ID


@me.stateclass
class PageState:
    """Mesop Page State"""
    
    # pylint: disable=E3701:invalid-field-call

    # Video Studio model: Gemini Omni by default, or a Veo version id.
    veo_model: str = DEFAULT_STUDIO_MODEL_ID
    veo_prompt_input: str = ""
    veo_prompt_placeholder: str = ""
    veo_prompt_textarea_key: int = 0

    veo_mode: str = "t2v"

    # The user's main prompt for video generation.
    prompt: str = "A cinematic shot of a baby raccoon wearing an intricate italian mafioso suit, sitting at a table in a bar, with a dark background."
    # The user's negative prompt to steer the model away from certain concepts.
    negative_prompt: str = ""

    veo_seed: int = 0

    original_prompt: str

    video_count: int = 1
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    video_length: int = 8  # Default for 3.1-fast-preview
    generate_audio: bool = True

    # I2V reference Image
    reference_image_file: me.UploadedFile = None
    reference_image_file_key: int = 0
    reference_image_gcs: str
    reference_image_uri: str
    reference_image_mime_type: str

    # Interpolation last reference image
    last_reference_image_file: me.UploadedFile = None
    last_reference_image_file_key: int = 0
    last_reference_image_gcs: str
    last_reference_image_uri: str
    last_reference_image_mime_type: str = ""

    # R2V reference images
    r2v_reference_images: list[str] = field(default_factory=list)
    r2v_reference_mime_types: list[str] = field(default_factory=list)
    r2v_style_image: str | None = None
    r2v_style_image_mime_type: str | None = None

    info_dialog_open: bool = False

    # extend
    video_extend_length: int = 7  # 4-7

    # Rewriter
    auto_enhance_prompt: bool = False

    rewriter_name: str

    is_loading: bool = False
    is_converting_gif: bool = False
    
    gif_url: str = ""

    show_error_dialog: bool = False
    error_message: str = ""
    result_gcs_uris: list[str] = field(default_factory=list)
    result_display_urls: list[str] = field(default_factory=list)
    selected_video_url: str = ""
    timing: str
    
    person_generation: str = "Allow (Adults only)"

    # Async Job Tracking
    current_job_id: str = ""
    job_status: str = ""

    # Video Studio layout (composer, progress card, recent grid)
    show_advanced: bool = False
    is_enhancing: bool = False
    lightbox_url: str = ""
    # Step-by-step progress (components/generation_progress)
    progress_stages: list[str] = field(default_factory=list)
    progress_stage: int = 0
    progress_status: str = ""
    progress_run_id: str = ""
    progress_error: str = ""
    last_action: str = "generate"  # "generate" | "extend", for "Try again"
    # Session history for the "Recent" grid (display URLs, newest first)
    history_urls: list[str] = field(default_factory=list)
    history_prompts: list[str] = field(default_factory=list)
    history_meta: list[str] = field(default_factory=list)
    history_aspects: list[str] = field(default_factory=list)

    # Gemini Omni: the input video for edit, extend and upscale
    reference_video_gcs: str = ""
    reference_video_uri: str = ""
    reference_video_mime_type: str = ""
    reference_video_file_key: int = 0
    video_upload_signed_url: str = ""
    video_upload_gcs_uri: str = ""
    video_upload_progress: int = 0
