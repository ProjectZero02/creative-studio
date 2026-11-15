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
"""Dev-only fake generation, for checking the UI without Google Cloud.

Turn on with GENMEDIA_MOCK_GENERATION=true. It only works when APP_ENV is
"local" or "dev", so it can never switch on in a deployed studio. The fake
results are placeholder pictures and a public sample clip; nothing is saved.
A prompt containing the word "fail" raises an error, to show the error state.
"""

import base64
import html
import os
import time

_SAMPLE_VIDEO = (
    "https://storage.googleapis.com/gdm-deepmind-com-prod-public/media/media/"
    "veo__cover_s0RKXWX.mp4"
)


def mock_enabled() -> bool:
    """True only for local/dev runs with GENMEDIA_MOCK_GENERATION=true."""
    if os.environ.get("GENMEDIA_MOCK_GENERATION", "").lower() not in ("1", "true"):
        return False
    return os.environ.get("APP_ENV", "").lower() in ("local", "dev")


def _ratio(aspect: str) -> tuple[int, int]:
    try:
        w, h = (int(float(x)) for x in aspect.split(":"))
        return max(w, 1), max(h, 1)
    except ValueError:
        return 1, 1


def placeholder_image(prompt: str, aspect: str, index: int = 0) -> str:
    """A small SVG data URL in the given aspect ratio, labelled with the prompt."""
    w, h = _ratio(aspect)
    width = 1024
    height = int(width * h / w)
    hues = [(214, 262), (168, 205), (24, 340), (280, 320)][index % 4]
    label = html.escape((prompt or "Mock image")[:60])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl({hues[0]},70%,62%)"/><stop offset="1" stop-color="hsl({hues[1]},65%,38%)"/>
</linearGradient></defs>
<rect width="100%" height="100%" fill="url(#g)"/>
<circle cx="{width * 0.72}" cy="{height * 0.32}" r="{min(width, height) * 0.16}" fill="rgba(255,255,255,0.28)"/>
<text x="48" y="{height - 56}" font-family="Google Sans, Arial, sans-serif" font-size="34" fill="#fff">{label}</text>
<text x="48" y="64" font-family="Google Sans, Arial, sans-serif" font-size="24" fill="rgba(255,255,255,0.8)">MOCK · {aspect}</text>
</svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def sample_video() -> str:
    """A public sample clip used as the fake video result."""
    return _SAMPLE_VIDEO


def fake_wait(seconds: float, prompt: str = "") -> None:
    """Sleep like a model call; raise for prompts that ask to fail."""
    time.sleep(seconds)
    if "fail" in (prompt or "").lower():
        raise RuntimeError(
            "Mock failure: the prompt asked to fail (GENMEDIA_MOCK_GENERATION)."
        )
