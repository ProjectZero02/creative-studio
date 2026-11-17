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
"""Image Studio P1 fixes: one image per run, cached presets, suggest edits URI."""

from unittest.mock import MagicMock

import pytest

import pages.gemini_image_generation as page


@pytest.fixture
def run_page(monkeypatch):
    """Patch Mesop state and the slow or remote calls the page makes."""
    app_state = MagicMock(user_email="tester@example.com")
    saved = []

    def setup(state):
        monkeypatch.setattr(
            page.me, "state", lambda cls: state if cls is page.PageState else app_state
        )
        monkeypatch.setattr(page, "mock_enabled", lambda: False)
        monkeypatch.setattr(page, "add_media_item_to_firestore", saved.append)
        monkeypatch.setattr(page, "create_display_url", lambda u: "/media/" + u[5:])
        monkeypatch.setattr(page, "get_image_resolution", lambda _u: "1024x1024")
        monkeypatch.setattr(page.c2pa_service, "read_manifest", lambda _u: None)
        monkeypatch.setattr(page.time, "sleep", lambda _s: None)
        return saved

    return setup


def test_one_image_model_keeps_only_the_final_image(run_page, monkeypatch):
    state = page.PageState(selected_model="gemini-nano-banana-2.1")
    saved = run_page(state)
    calls = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        return (["gs://b/draft.png", "gs://b/final.png"], 1.0, ["d", "f"], None, [])

    monkeypatch.setattr(page, "generate_image_from_prompt_and_images", fake_generate)
    list(page._generate_and_save(base_prompt="a cat", input_gcs_uris=[]))

    assert state.num_images_to_generate == 1
    assert calls[0]["prompt"] == "a cat"  # no "Give me N images" suffix
    assert state.generated_image_urls == ["/media/b/final.png"]
    assert state.generated_image_captions == ["f"]
    assert saved[-1].gcs_uris == ["gs://b/final.png"]


def test_keep_requested_leaves_auto_alone():
    uris = ["a", "b", "c"]
    assert page._keep_requested(uris, ["1", "2", "3"], 0) == (uris, ["1", "2", "3"])
    assert page._keep_requested(uris, ["1", "2", "3"], 2) == (["b", "c"], ["2", "3"])


def test_presets_are_cached_between_renders(monkeypatch):
    loads = []

    def fake_load(**_kwargs):
        loads.append(1)
        return []

    monkeypatch.setattr(page.prompt_template_service, "load_templates", fake_load)
    monkeypatch.setitem(page._presets_cache, "at", None)
    clock = [1000.0]
    monkeypatch.setattr(page.time, "monotonic", lambda: clock[0])

    first = page.get_all_image_presets()
    page.get_all_image_presets()
    assert len(loads) == 1
    # A caller changing its copy doesn't change the cache.
    first["edit"].clear()
    assert page.get_all_image_presets()["edit"]
    clock[0] += page._PRESETS_TTL_SECONDS + 1
    page.get_all_image_presets()
    assert len(loads) == 2


@pytest.mark.parametrize(
    "selected,expected",
    [
        # Signed URL (USE_MEDIA_PROXY off): used to become "gs://https://...".
        (
            "https://storage.googleapis.com/bkt/img/2.png?X-Goog-Signature=abc",
            "gs://bkt/img/2.png",
        ),
        ("/media/bkt/img/2.png", "gs://bkt/img/2.png"),
        ("", "gs://bkt/img/1.png"),  # nothing selected: the first image
    ],
)
def test_suggest_edits_uses_the_selected_images_gcs_uri(
    monkeypatch, selected, expected
):
    state = page.PageState(
        generated_image_urls=["/media/bkt/img/1.png", "/media/bkt/img/2.png"],
        selected_image_url=selected,
    )
    monkeypatch.setattr(page.me, "state", lambda _cls: state)
    seen = []

    def fake_suggest(image_uris):
        seen.extend(image_uris)
        return []

    monkeypatch.setattr(page, "generate_transformation_prompts", fake_suggest)
    list(page.on_suggest_transformations_click(MagicMock()))
    assert seen == [expected]
