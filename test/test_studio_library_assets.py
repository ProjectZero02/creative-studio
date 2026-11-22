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
"""Tests for pulling created assets from the Library into studio tabs and choosers."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from common import metadata, studio_history


class _FakeDoc:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeQuery:
    """In-memory Firestore query fake with optional composite-index failure."""

    def __init__(self, docs: list[_FakeDoc], *, fail_composite: bool = False):
        self._docs = docs
        self._fail_composite = fail_composite
        self._wheres: list[tuple[str, str, object]] = []
        self._ordered_by: list[str] = []
        self._limit: int | None = None

    def where(self, field: str, op: str, value: object):
        self._wheres.append((field, op, value))
        return self

    def order_by(self, field: str, direction=None):
        self._ordered_by.append(field)
        return self

    def start_after(self, snapshot):
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def stream(self):
        if self._fail_composite and self._wheres and self._ordered_by:
            raise RuntimeError("400 The query requires an index.")
        out = []
        for doc in self._docs:
            data = doc.to_dict()
            matched = True
            for field, op, value in self._wheres:
                actual = data.get(field)
                if op == "==" and actual != value:
                    matched = False
                elif op == ">=" and (actual is None or actual < value):
                    matched = False
                elif op == "<" and (actual is None or actual >= value):
                    matched = False
            if matched:
                out.append(doc)
        if self._ordered_by:
            field = self._ordered_by[0]
            out.sort(
                key=lambda d: d.to_dict().get(field) or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                reverse=True,
            )
        if self._limit is not None:
            out = out[: self._limit]
        return iter(out)


class _FakeDB:
    def __init__(self, docs: list[_FakeDoc], *, fail_composite: bool = False):
        self._docs = docs
        self._fail_composite = fail_composite

    def collection(self, _name: str):
        return _FakeQuery(self._docs, fail_composite=self._fail_composite)


def _sample_docs() -> list[_FakeDoc]:
    t1 = datetime.datetime(2026, 11, 20, 10, 0, tzinfo=datetime.UTC)
    t2 = datetime.datetime(2026, 11, 21, 10, 0, tzinfo=datetime.UTC)
    t3 = datetime.datetime(2026, 11, 22, 10, 0, tzinfo=datetime.UTC)
    return [
        _FakeDoc(
            "img-1",
            {
                "user_email": "alice@example.com",
                "mime_type": "image/png",
                "model": "gemini-3.1-flash-image-preview",
                "prompt": "A red fox in snow",
                "gcs_uris": ["gs://bucket/img1.png"],
                "aspect": "16:9",
                "timestamp": t2,
            },
        ),
        _FakeDoc(
            "vid-1",
            {
                "user_email": "alice@example.com",
                "mime_type": "video/mp4",
                "model": "veo-3.1-fast",
                "prompt": "Waves at sunset",
                "gcs_uris": ["gs://bucket/vid1.mp4"],
                "aspect": "16:9",
                "resolution": "720p",
                "duration": 8,
                "timestamp": t3,
            },
        ),
        _FakeDoc(
            "img-bob",
            {
                "user_email": "bob@example.com",
                "mime_type": "image/png",
                "model": "gemini-3.1-flash-image-preview",
                "prompt": "Bob's image",
                "gcs_uris": ["gs://bucket/bob.png"],
                "timestamp": t1,
            },
        ),
    ]


def test_get_media_for_page_optimized_preserves_mime_type_and_metadata(monkeypatch):
    monkeypatch.setattr(metadata, "db", _FakeDB(_sample_docs(), fail_composite=False))

    items, last_doc = metadata.get_media_for_page_optimized(10, ["images"])

    assert [i.id for i in items] == ["img-1", "img-bob"]
    assert items[0].mime_type == "image/png"
    assert items[0].user_email == "alice@example.com"
    assert items[0].model == "gemini-3.1-flash-image-preview"
    assert last_doc is not None


def test_get_media_for_page_optimized_falls_back_when_composite_index_missing(monkeypatch):
    monkeypatch.setattr(metadata, "db", _FakeDB(_sample_docs(), fail_composite=True))

    items, last_doc = metadata.get_media_for_page_optimized(
        10,
        ["images"],
        filter_by_user_email="alice@example.com",
    )

    assert [i.id for i in items] == ["img-1"]
    assert items[0].mime_type == "image/png"
    assert last_doc is not None


# --- studio_history ----------------------------------------------------------


def _mixed_library_rows() -> list[dict]:
    t1 = datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.UTC)
    t2 = datetime.datetime(2026, 11, 20, 10, 0, tzinfo=datetime.UTC)
    t3 = datetime.datetime(2026, 11, 20, 11, 0, tzinfo=datetime.UTC)
    t4 = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.UTC)
    t5 = datetime.datetime(2026, 11, 20, 13, 0, tzinfo=datetime.UTC)
    return [
        # Older image with multiple URIs
        {
            "mime_type": "image/png",
            "model": "gemini-3.1-flash-image-preview",
            "prompt": "Old fox",
            "gcs_uris": ["gs://b/img-a.png", "gs://b/img-b.png"],
            "aspect": "4:3",
            "image_size": "1K",
            "timestamp": t1,
        },
        # Newer image
        {
            "mime_type": "image/png",
            "model": "gemini-3.1-flash-image-preview",
            "prompt": "New fox",
            "gcs_uris": ["gs://b/img-new.png"],
            "aspect": "16:9",
            "image_size": "2K",
            "timestamp": t4,
        },
        # Failed image (must be skipped)
        {
            "mime_type": "image/png",
            "model": "gemini-3.1-flash-image-preview",
            "prompt": "Broken",
            "gcs_uris": ["gs://b/img-err.png"],
            "error_message": "safety block",
            "timestamp": t5,
        },
        # Completed video
        {
            "mime_type": "video/mp4",
            "model": "veo-3.1-fast",
            "prompt": "Ocean waves",
            "gcs_uris": ["gs://b/vid-1.mp4"],
            "aspect": "16:9",
            "resolution": "720p",
            "duration": 8,
            "status": "complete",
            "timestamp": t3,
        },
        # Pending video (must be skipped)
        {
            "mime_type": "video/mp4",
            "model": "veo-3.1-fast",
            "prompt": "Still rendering",
            "gcs_uris": ["gs://b/vid-pending.mp4"],
            "status": "processing",
            "timestamp": t5,
        },
        # Lyria music track
        {
            "mime_type": "audio/wav",
            "model": "lyria-3-pro-preview",
            "original_prompt": "Warm lo-fi piano",
            "prompt": "Rewritten lo-fi piano",
            "gcs_uris": ["gs://b/music-1.wav"],
            "timestamp": t2,
        },
        # Voice clip (non-lyria audio)
        {
            "mime_type": "audio/wav",
            "model": "gemini-3.8-tts",
            "prompt": "Welcome to the studio.",
            "comment": "Gemini 3.8 TTS · Kore · en-US",
            "gcsuri": "gs://b/voice-1.wav",
            "timestamp": t3,
        },
    ]


def test_extract_recent_assets_filters_and_sorts_per_studio():
    rows = _mixed_library_rows()
    warmed: list[list[str]] = []

    def fake_url(uri: str) -> str:
        return uri.replace("gs://", "/media/")

    images = studio_history.extract_recent_assets(
        rows, "gemini_image_generation", url_fn=fake_url, warm_fn=warmed.append
    )
    assert [a.url for a in images] == [
        "/media/b/img-new.png",
        "/media/b/img-a.png",
        "/media/b/img-b.png",
    ]
    assert images[0].prompt == "New fox"
    assert images[0].aspect == "16:9"
    assert "2K" in images[0].meta
    assert warmed == [["gs://b/img-new.png", "gs://b/img-a.png", "gs://b/img-b.png"]]

    videos = studio_history.extract_recent_assets(
        rows, "veo", url_fn=fake_url, warm_fn=lambda _: None
    )
    assert [a.url for a in videos] == ["/media/b/vid-1.mp4"]
    assert videos[0].prompt == "Ocean waves"
    assert "720p" in videos[0].meta and "8s" in videos[0].meta

    music = studio_history.extract_recent_assets(
        rows, "lyria", url_fn=fake_url, warm_fn=lambda _: None
    )
    assert [a.url for a in music] == ["/media/b/music-1.wav"]
    assert music[0].prompt == "Warm lo-fi piano"
    assert music[0].meta == "lyria-3-pro-preview"

    voice = studio_history.extract_recent_assets(
        rows, "voice", url_fn=fake_url, warm_fn=lambda _: None
    )
    assert [a.url for a in voice] == ["/media/b/voice-1.wav"]
    assert voice[0].prompt == "Welcome to the studio."
    assert voice[0].meta == "Gemini 3.8 TTS · Kore · en-US"


def test_extract_recent_assets_deduplicates_and_respects_limit():
    t = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.UTC)
    rows = [
        {"mime_type": "image/png", "gcs_uris": ["gs://b/1.png"], "timestamp": t},
        {"mime_type": "image/png", "gcs_uris": ["gs://b/1.png", "gs://b/2.png"], "timestamp": t},
        {"mime_type": "image/png", "gcs_uris": ["gs://b/3.png"], "timestamp": t},
    ]
    assets = studio_history.extract_recent_assets(
        rows,
        "gemini_image_generation",
        limit=2,
        url_fn=lambda u: u.replace("gs://", "/media/"),
        warm_fn=lambda _: None,
    )
    assert [a.url for a in assets] == ["/media/b/1.png", "/media/b/2.png"]


def test_load_recent_assets_fails_closed_without_owner_and_falls_back_on_missing_index(
    monkeypatch,
):
    fake_db = _FakeDB(_sample_docs(), fail_composite=True)
    monkeypatch.setattr(metadata, "db", fake_db)
    monkeypatch.setattr(
        studio_history, "create_display_url", lambda u: u.replace("gs://", "/media/")
    )
    monkeypatch.setattr(studio_history, "warm_display_urls", lambda _: None)

    assert studio_history.load_recent_assets("", "gemini_image_generation") == []
    assert studio_history.load_recent_assets("alice@example.com", "unknown") == []

    alice_images = studio_history.load_recent_assets(
        "alice@example.com", "gemini_image_generation"
    )
    assert [a.url for a in alice_images] == ["/media/bucket/img1.png"]


def test_apply_recent_assets_preserves_existing_state_when_empty():
    state = SimpleNamespace(
        history_urls=["/media/local.png"],
        history_prompts=["local"],
        history_meta=["meta"],
        history_aspects=["1:1"],
    )
    studio_history.apply_recent_assets(state, [])
    assert state.history_urls == ["/media/local.png"]

    studio_history.apply_recent_assets(
        state,
        [studio_history.RecentAsset("/media/db.png", "from db", "model", "16:9")],
    )
    assert state.history_urls == ["/media/db.png"]
    assert state.history_prompts == ["from db"]
    assert state.history_meta == ["model"]
    assert state.history_aspects == ["16:9"]


# --- Studio page on_load wiring ----------------------------------------------


def _run_page_load(handler, page_state, app_state, params=None):
    from state.state import AppState

    def fake_state(cls):
        return app_state if cls is AppState else page_state

    with (
        patch("mesop.query_params", params or {}),
        patch("mesop.state", side_effect=fake_state),
    ):
        list(handler(MagicMock()))


def test_image_studio_on_load_pulls_recent_library_assets(monkeypatch):
    from pages import gemini_image_generation as img_page

    page_state = SimpleNamespace(
        uploaded_image_gcs_uris=[],
        uploaded_image_display_urls=[],
        prompt="",
        prompt_prefill_seen="",
        prompt_key=0,
        history_urls=[],
        history_prompts=[],
        history_meta=[],
        history_aspects=[],
    )
    app_state = SimpleNamespace(user_email="alice@example.com")
    sample = [
        studio_history.RecentAsset(
            "/media/b/img1.png", "A fox", "Nano Banana 2.1 · 1:1", "1:1"
        )
    ]
    monkeypatch.setattr(studio_history, "load_recent_assets", lambda owner, studio: sample if (owner == "alice@example.com" and studio == "gemini_image_generation") else [])

    _run_page_load(img_page.on_load, page_state, app_state)

    assert page_state.history_urls == ["/media/b/img1.png"]
    assert page_state.history_prompts == ["A fox"]
    assert page_state.history_meta == ["Nano Banana 2.1 · 1:1"]
    assert page_state.history_aspects == ["1:1"]


def test_video_studio_on_load_pulls_recent_library_assets(monkeypatch):
    from pages import veo as veo_page

    page_state = SimpleNamespace(
        veo_prompt_input="",
        prompt_prefill_seen="",
        history_urls=[],
        history_prompts=[],
        history_meta=[],
        history_aspects=[],
    )
    app_state = SimpleNamespace(user_email="alice@example.com")
    sample = [
        studio_history.RecentAsset(
            "/media/b/vid1.mp4", "Waves", "Veo 3.1 · 720p · 8s", "16:9"
        )
    ]
    monkeypatch.setattr(studio_history, "load_recent_assets", lambda owner, studio: sample if (owner == "alice@example.com" and studio == "veo") else [])

    _run_page_load(veo_page.on_veo_load, page_state, app_state)

    assert page_state.history_urls == ["/media/b/vid1.mp4"]
    assert page_state.history_prompts == ["Waves"]
    assert page_state.history_aspects == ["16:9"]


def test_music_studio_on_load_pulls_recent_library_assets(monkeypatch):
    from pages import lyria as lyria_page

    page_state = SimpleNamespace(
        music_prompt_input="",
        music_prompt_placeholder="",
        music_prompt_textarea_key=0,
        prompt_prefill_seen="",
        history_urls=[],
        history_prompts=[],
        history_meta=[],
    )
    app_state = SimpleNamespace(user_email="alice@example.com")
    sample = [
        studio_history.RecentAsset(
            "/media/b/music1.wav", "Warm lo-fi", "lyria-3-pro-preview", ""
        )
    ]
    monkeypatch.setattr(studio_history, "load_recent_assets", lambda owner, studio: sample if (owner == "alice@example.com" and studio == "lyria") else [])

    _run_page_load(lyria_page.on_lyria_load, page_state, app_state)

    assert page_state.history_urls == ["/media/b/music1.wav"]
    assert page_state.history_prompts == ["Warm lo-fi"]
    assert page_state.history_meta == ["lyria-3-pro-preview"]


def test_voice_studio_on_load_pulls_recent_library_assets(monkeypatch):
    from pages import voice as voice_page

    page_state = SimpleNamespace(
        engine="gemini-3.8-tts",
        text="",
        text_key=0,
        prompt_prefill_seen="",
        history_urls=[],
        history_texts=[],
        history_meta=[],
    )
    app_state = SimpleNamespace(user_email="alice@example.com")
    sample = [
        studio_history.RecentAsset(
            "/media/b/voice1.wav", "Hello world", "Gemini 3.8 TTS · Kore", ""
        )
    ]
    monkeypatch.setattr(studio_history, "load_recent_assets", lambda owner, studio: sample if (owner == "alice@example.com" and studio == "voice") else [])

    _run_page_load(voice_page.on_voice_load, page_state, app_state)

    assert page_state.history_urls == ["/media/b/voice1.wav"]
    assert page_state.history_texts == ["Hello world"]
    assert page_state.history_meta == ["Gemini 3.8 TTS · Kore"]


