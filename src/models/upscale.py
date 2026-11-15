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

"""Image resolution helper.

The Imagen upscale model this module wrapped was retired by Google on
2026-06-30, so only the resolution check used by the image pages remains.
"""

import io

from PIL import Image

from common.analytics import get_logger
from common.storage import download_from_gcs

logger = get_logger(__name__)


def get_image_resolution(image_data: bytes | str) -> str:
    """Gets the resolution of an image from GCS URI or bytes."""
    if isinstance(image_data, str) and image_data.startswith("gs://"):
        try:
            image_bytes = download_from_gcs(image_data)
        except Exception as e:
            logger.warning(f"Error downloading image for resolution check: {e}")
            return "Unknown"
    elif isinstance(image_data, bytes):
        image_bytes = image_data
    else:
        return "Unknown"

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return f"{img.width}x{img.height}"
    except Exception as e:
        logger.warning(f"Error getting resolution: {e}")
        return "Unknown"
