# Copyright 2024 Google LLC
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

"""Virtual model images for the Fashion demo (Gemini image, "Nano Banana").

The Imagen helpers that used to live here were removed: Google retired the
Imagen models on 2026-06-30.
"""

import models.gemini as gemini
from common.analytics import get_logger
from config.default import Default

logger = get_logger(__name__)


def generate_virtual_models(prompt: str, num_images: int) -> list[str]:
    """Generates multiple virtual model images and saves them to GCS.

    Text-to-image virtual model generation via Nano Banana (Gemini image). The
    Imagen model family returns HTTP 404 on Vertex AI, so this helper routes
    through the Gemini image adapter, which is text-only when ``images=[]``.

    Args:
        prompt: The prompt to generate the images.
        num_images: The number of images to generate.

    Returns:
        A list of GCS URIs for the generated images.

    """
    cfg = Default()
    generated_uris: list[str] = []
    for _ in range(num_images):
        gcs_uris, *_ = gemini.generate_image_from_prompt_and_images(
            prompt=prompt,
            images=[],  # text-only
            aspect_ratio="1:1",
            gcs_folder=cfg.IMAGEN_GENERATED_SUBFOLDER,
            file_prefix="virtual_model",
            model_name=cfg.GEMINI_IMAGE_GEN_MODEL,
        )
        generated_uris.extend(gcs_uris)
    return generated_uris
