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
"""Library stars and collections, and prompt history."""

import datetime

from common import library_marks as lm
from common import prompt_history as ph


def test_star_toggles_and_newest_first():
    m = lm.empty("a@x")
    m = lm.toggle_star(m, "1")
    m = lm.toggle_star(m, "2")
    assert m["starred"] == ["2", "1"] and lm.is_starred(m, "1")
    m = lm.toggle_star(m, "1")
    assert m["starred"] == ["2"]


def test_edits_do_not_change_the_input():
    m = lm.empty()
    lm.toggle_star(m, "1")
    lm.toggle_in_collection(m, "Ads", "1")
    assert m == lm.empty()


def test_collections():
    m = lm.toggle_in_collection(lm.empty(), "  Spring   ads ", "1")
    m = lm.toggle_in_collection(m, "Spring ads", "2")
    m = lm.toggle_in_collection(m, "Other", "1")
    assert m["collections"]["Spring ads"] == ["2", "1"]
    assert sorted(lm.collections_of(m, "1")) == ["Other", "Spring ads"]
    m = lm.toggle_in_collection(m, "Spring ads", "1")
    assert lm.collections_of(m, "1") == ["Other"]
    assert lm.ids_for(m, "c:Spring ads") == ["2"]
    assert lm.ids_for(lm.delete_collection(m, "Other"), "c:Other") == []
    assert lm.toggle_in_collection(m, "   ", "3") == m


def test_collection_cap(monkeypatch):
    monkeypatch.setattr(lm, "MAX_COLLECTIONS", 2)
    m = lm.toggle_in_collection(lm.empty(), "a", "1")
    m = lm.toggle_in_collection(m, "b", "1")
    m = lm.toggle_in_collection(m, "c", "1")
    assert sorted(m["collections"]) == ["a", "b"]


def test_clean_survives_bad_documents():
    assert lm.clean(None, "a@x") == lm.empty("a@x")
    out = lm.clean({"starred": ["1", None, ""], "collections": {"": ["x"], "Ok": ["2"]}})
    assert out["starred"] == ["1"] and out["collections"] == {"Ok": ["2"]}
    assert lm.ids_for(out, "starred") == ["1"] and lm.ids_for(out, "") == []


def test_load_and_save_use_one_document_per_person(monkeypatch):
    store = {}

    class Snap:
        def __init__(self, d):
            self._d = d
            self.exists = d is not None

        def to_dict(self):
            return self._d

    class Doc:
        def __init__(self, key):
            self.key = key

        def get(self):
            return Snap(store.get(self.key))

        def set(self, data):
            store[self.key] = data

    class DB:
        def collection(self, name):
            assert name == lm.COLLECTION
            return self

        def document(self, key):
            return Doc(key)

    monkeypatch.setattr(lm, "_db", lambda: DB())
    assert lm.load("A@x") == lm.empty("A@x")
    lm.save("A@x", lm.toggle_star(lm.empty(), "9"))
    assert lm.load("a@x")["starred"] == ["9"]  # same person, any case
    assert len(store) == 1 and "@" not in next(iter(store))


def _row(prompt, mime, model="", minutes=0, **extra):
    ts = datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC) + datetime.timedelta(minutes=minutes)
    return {"prompt": prompt, "mime_type": mime, "model": model, "timestamp": ts, **extra}


def test_prompt_history_per_studio():
    rows = [
        _row("a red fox", "image/png", minutes=1),
        _row("A  red fox", "image/png", minutes=3),
        _row("ocean waves at dusk", "video/mp4", minutes=2),
        _row("rewritten", "audio/wav", "lyria-002", minutes=4, original_prompt="lofi beat"),
        _row("Hello there", "audio/wav", "Chirp3 HD", minutes=5),
        _row("", "image/png", minutes=6),
    ]
    assert ph.pick(rows, "gemini_image_generation") == ["A red fox"]
    assert ph.pick(rows, "veo") == ["ocean waves at dusk"]
    assert ph.pick(rows, "lyria") == ["lofi beat"]
    assert ph.pick(rows, "voice") == ["Hello there"]
    assert ph.pick(rows, "nowhere") == []
    assert ph.field_for("voice") == "script" and ph.field_for("veo") == "prompt"


def test_prompt_history_limit_and_string_times():
    rows = [
        {"prompt": f"prompt {i}", "mime_type": "video/mp4", "timestamp": f"2026-11-0{i}T00:00:00"}
        for i in range(1, 8)
    ]
    assert ph.pick(rows, "veo", limit=2) == ["prompt 7", "prompt 6"]


def test_every_history_studio_has_its_form_field():
    from services import page_forms

    for page, (name, _) in ph.STUDIOS.items():
        assert name in {f.name for f in page_forms.PAGES[page]}, page
