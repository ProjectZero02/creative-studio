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


def _item(item_id: str, owner: str, ts: str) -> lib.MediaItem:
    return lib.MediaItem(
        id=item_id, user_email=owner, timestamp=ts, mime_type="image/png", gcsuri=f"gs://b/{item_id}.png",
    )


def _ids(state: lib.PageState) -> list[str]:
    import json

    return [d["id"] for d in json.loads(state.media_items_json)]


@pytest.fixture
def starred_page(page: lib.PageState, monkeypatch: pytest.MonkeyPatch) -> lib.PageState:
    """Newest-first pages of a, b, c; b (mine) and x (someone else) are starred."""
    items = {
        "a": _item("a", "me@example.com", "2026-11-03T00:00:00"),
        "b": _item("b", "me@example.com", "2026-11-02T00:00:00"),
        "c": _item("c", "me@example.com", "2026-11-01T00:00:00"),
        "x": _item("x", "other@example.com", "2026-10-01T00:00:00"),
    }
    monkeypatch.setattr(
        lib,
        "get_media_for_page",
        lambda **kw: [items[i] for i in "abc"] if kw["page"] == 1 else [],
    )
    monkeypatch.setattr(lib, "get_media_item_by_id", items.get)
    marks = lib.marks_store.empty("me@example.com")
    marks["starred"] = ["b", "x"]
    page.marks_json = lib.json.dumps(marks)
    return page


def test_starred_items_come_first_once(starred_page: lib.PageState) -> None:
    """Mine Only: my starred item leads and is not repeated; others' are left out."""
    list(lib._load_media(starred_page, is_filter_change=True))
    assert _ids(starred_page) == ["b", "a", "c"]


def test_all_users_shows_every_starred_item_first(starred_page: lib.PageState) -> None:
    starred_page.user_filter = "all"
    list(lib._load_media(starred_page, is_filter_change=True))
    assert _ids(starred_page) == ["b", "x", "a", "c"]


def test_later_pages_do_not_repeat_starred(starred_page: lib.PageState) -> None:
    list(lib._load_media(starred_page, is_filter_change=True))
    starred_page.current_page = 2
    list(lib._load_media(starred_page))
    assert _ids(starred_page) == ["b", "a", "c"]


def test_failed_items_without_media_hide_unless_only_errors(
    page: lib.PageState, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed generation with no media leaves the Library looking empty."""
    failed = lib.MediaItem(id="f", user_email="me@example.com", error_message="blocked")
    shown = lib.MediaItem(id="s", user_email="me@example.com", gcsuri="gs://b/s.png")
    monkeypatch.setattr(lib, "get_media_for_page", lambda **kw: [failed, shown] if kw["page"] == 1 else [])
    list(lib._load_media(page, is_filter_change=True))
    assert _ids(page) == ["s"]
    page.error_filter = "only_errors"
    list(lib._load_media(page, is_filter_change=True))
    assert _ids(page) == ["f", "s"]
