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

from common import metadata


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
