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
"""Rough cost estimates per model call, for the usage page.

These are list-price ballparks in US dollars, not a bill: discounts,
committed use and price changes are not known here. The usage page always
says "estimate". Update the numbers when prices change.

A call is priced from the billing units the model wrappers already log
(see ``common.analytics.track_model_call``): seconds of video, images,
music tracks, characters of speech, or Gemini tokens. Failed calls cost 0.
"""

from __future__ import annotations

# (substring of the model name, price) pairs; the first match wins.
VIDEO_PER_SECOND = (
    ("lite", 0.10),
    ("fast", 0.15),
    ("omni", 0.40),
    ("veo", 0.40),
)
IMAGE_PER_IMAGE = (
    ("imagen-4.0-fast", 0.02),
    ("imagen", 0.04),
    ("image", 0.039),  # Gemini image models (Nano Banana)
    ("vto", 0.06),
    ("virtual-try-on", 0.06),
)
MUSIC_PER_TRACK = 0.06
SPEECH_PER_MILLION_CHARS = (
    ("chirp", 30.0),
    ("tts", 10.0),
)
# Gemini text: (input, output) dollars per million tokens.
TOKENS_PER_MILLION = (
    ("pro", (1.25, 10.0)),
    ("neon", (3.0, 15.0)),  # Gemini 4 Neon
    ("flash-lite", (0.10, 0.40)),
    ("flash", (0.30, 2.50)),
    ("live", (0.50, 2.00)),
    ("gemini", (0.30, 2.50)),
)


def _match(model: str, table):
    name = (model or "").lower()
    for key, price in table:
        if key in name:
            return price
    return None


def kind_of(model: str, units: dict) -> str:
    """'video', 'image', 'music', 'speech' or 'text'."""
    name = (model or "").lower()
    if units.get("video_seconds_generated") or "veo" in name:
        return "video"
    if "lyria" in name:
        return "music"
    if units.get("characters_synthesized") is not None or "tts" in name or "chirp" in name:
        return "speech"
    if "image" in name or "imagen" in name or "vto" in name or "try-on" in name:
        return "image"
    return "text"


def estimate(model: str, units: dict | None, status: str = "success") -> float:
    """Estimated dollars for one call."""
    if status != "success":
        return 0.0
    units = units or {}
    kind = kind_of(model, units)
    if kind == "video":
        secs = float(units.get("video_seconds_generated") or 0)
        return secs * (_match(model, VIDEO_PER_SECOND) or 0.40)
    if kind == "image":
        count = int(units.get("sample_count") or units.get("num_images") or 1)
        return count * (_match(model, IMAGE_PER_IMAGE) or 0.04)
    if kind == "music":
        return int(units.get("sample_count") or 1) * MUSIC_PER_TRACK
    if kind == "speech":
        chars = float(units.get("characters_synthesized") or 0)
        return chars / 1e6 * (_match(model, SPEECH_PER_MILLION_CHARS) or 10.0)
    price_in, price_out = _match(model, TOKENS_PER_MILLION) or (0.30, 2.50)
    tokens_in = float(units.get("prompt_tokens") or 0)
    tokens_out = float(units.get("candidates_tokens") or 0)
    return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
