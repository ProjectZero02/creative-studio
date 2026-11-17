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
"""Interim "thinking" images are not saved as results."""

import contextlib
from unittest.mock import MagicMock, patch

from google.genai import types

import models.gemini as gemini


def _response(*parts):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=list(parts)))
        ]
    )


def _image(data, thought=None):
    return types.Part(
        inline_data=types.Blob(data=data, mime_type="image/png"), thought=thought
    )


@contextlib.contextmanager
def _fake_track(**_kwargs):
    yield {"billing_units": {}}


def _run(response):
    client = MagicMock()
    client.models.generate_content.return_value = response
    stored = []

    def fake_store(folder, file_name, mime_type, contents):
        stored.append(contents)
        return f"gs://bucket/{folder}/{len(stored)}.png"

    with (
        patch.object(gemini.GeminiModelSetup, "init", return_value=client),
        patch.object(gemini, "store_to_gcs", side_effect=fake_store),
        patch.object(gemini, "track_model_call", _fake_track),
    ):
        result = gemini.generate_image_from_prompt_and_images(
            prompt="a cat",
            images=[],
            aspect_ratio="1:1",
            gcs_folder="gemini_image_generations",
            model_name="gemini-nano-banana-2.1",
        )
    return result, stored


def test_thought_image_then_final_returns_one_uri():
    response = _response(
        types.Part(text="Sketching the layout", thought=True),
        _image(b"draft", thought=True),
        types.Part(text="Here is your cat"),
        _image(b"final"),
    )
    (uris, _t, captions, _g, thoughts), stored = _run(response)
    assert uris == ["gs://bucket/gemini_image_generations/1.png"]
    assert stored == [b"final"]
    assert captions == ["Here is your cat"]
    # The thought text is kept and attached to the final image.
    assert thoughts == ["Sketching the layout"]


def test_two_final_images_are_both_kept():
    (uris, *_), stored = _run(_response(_image(b"one"), _image(b"two", thought=False)))
    assert len(uris) == 2 and stored == [b"one", b"two"]
