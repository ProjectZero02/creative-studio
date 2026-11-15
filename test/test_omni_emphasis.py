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

"""Tests for Omni-first emphasis on Veo/Omni surfaces."""

import importlib
import inspect
import os
import re
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.mark.parametrize(
    "module_name",
    [
        "pages.banana_studio",
        "pages.gemini_image_generation",
        "pages.vto",
        "components.interior_design.design_studio",
        "components.library.image_details",
    ],
)
def test_omni_button_is_rendered_before_veo_button(module_name: str) -> None:
    """Omni is listed first wherever both buttons are offered."""
    source = inspect.getsource(importlib.import_module(module_name))
    # Indented calls only: import lines start at column 0.
    omni_call = re.search(r"^\s+omni_button\(", source, re.MULTILINE)
    veo_call = re.search(r"^\s+veo_button\(", source, re.MULTILINE)
    assert omni_call
    assert veo_call
    assert omni_call.start() < veo_call.start()


def test_video_studio_has_no_omni_promo_banner() -> None:
    """Omni is built into Video Studio, so the "Try Gemini Omni" banner is gone."""
    from pages import veo

    source = inspect.getsource(veo.veo_content)
    assert "omni_hint" not in source


def test_video_studio_lists_omni_first_and_defaults_to_it() -> None:
    """The model chip leads with Gemini Omni 1.2 Flash, then the Veo models."""
    import dataclasses

    from config.veo_models import VEO_MODELS
    from config.video_studio_models import studio_model_ids
    from state.veo_state import PageState

    ids = studio_model_ids()
    assert ids[0] == "gemini-omni-1.2-flash"
    assert ids[1:] == [m.version_id for m in VEO_MODELS]
    defaults = {f.name: f.default for f in dataclasses.fields(PageState)}
    assert defaults["veo_model"] == "gemini-omni-1.2-flash"
