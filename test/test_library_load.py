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
"""The Library's first load must not stream an interim "Loading..." render.

Mesop's client applies each render once its JS modules import, without
waiting for the previous render. An interim render that needs a new module
(scroll_sentinel.js) can land after the final one and leave the page stuck.
"""

from collections.abc import Iterator
from types import SimpleNamespace

import pytest

import pages.library_v2 as lib


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> lib.PageState:
    """Return a PageState wired to fake Mesop state, config and Firestore."""
    state = lib.PageState()
    app = SimpleNamespace(user_email="me@example.com")
    monkeypatch.setattr(
        lib.me,
        "state",
        lambda cls: state if cls is lib.PageState else app,
    )
    monkeypatch.setattr(lib.me, "query_params", {})
    monkeypatch.setattr(
        lib,
        "cfg",
        lambda: SimpleNamespace(SHARED_LIBRARY=True, LIBRARY_MEDIA_PER_PAGE=20),
    )
    monkeypatch.setattr(lib, "get_media_for_page", lambda **_kw: [])
    monkeypatch.setattr(lib.marks_store, "load", lambda _owner: lib.marks_store.empty())
    return state


def _loading_at_each_render(gen: Iterator[None], state: lib.PageState) -> list[bool]:
    return [state.is_loading for _ in gen]


def test_first_load_has_no_interim_loading_render(page: lib.PageState) -> None:
    """Every render streamed by on_load already has the result."""
    renders = _loading_at_each_render(lib.on_load(None), page)
    assert renders
    assert not any(renders)
    assert page.all_items_loaded


def test_load_more_still_shows_loading(page: lib.PageState) -> None:
    """Scrolling for more keeps its interim "Loading..." render."""
    renders = _loading_at_each_render(lib._load_media(page), page)
    assert renders == [True, False]
