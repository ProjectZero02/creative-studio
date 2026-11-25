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
"""Usage events are queued, retried and flushed, never dropped silently."""

import logging
import threading

import pytest

from common import usage


class FakeDB:
    """Collects documents; fails the first `fail` writes."""

    def __init__(self, fail: int = 0):
        self.docs: dict[str, dict] = {}
        self.fail = fail
        self.attempts = 0
        self.lock = threading.Lock()

    def collection(self, name):
        assert name == usage.COLLECTION
        return self

    def document(self, doc_id):
        db = self

        class Ref:
            def set(self, doc):
                with db.lock:
                    db.attempts += 1
                    if db.fail:
                        db.fail -= 1
                        raise RuntimeError("firestore unavailable")
                    db.docs[doc_id] = doc

        return Ref()


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(usage, "_db", lambda: db)
    monkeypatch.setattr(usage, "WRITE_BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    usage._exiting.clear()
    yield db
    usage._exiting.clear()


def _wait_idle(timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while usage._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not usage._queue.unfinished_tasks


def test_200_concurrent_records_all_land(fake_db):
    def one(i):
        usage.record(f"u{i}@x", "lyria-002", "success", {"sample_count": 1})

    threads = [threading.Thread(target=one, args=(i,)) for i in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _wait_idle()
    assert len(fake_db.docs) == 200
    assert {d["owner"] for d in fake_db.docs.values()} == {
        f"u{i}@x" for i in range(200)
    }
    # The document id is the event id, so a retry never stores twice.
    assert all(k == d["event_id"] for k, d in fake_db.docs.items())


def test_event_id_is_kept(fake_db):
    usage.record("a@x", "lyria-002", "success", {"sample_count": 1}, event_id="abc123")
    _wait_idle()
    assert fake_db.docs["abc123"]["event_id"] == "abc123"


def test_flush_stores_queued_events_from_the_book(fake_db, monkeypatch):
    fetches = []
    real = usage.pricing.estimate_details

    def spy(*a, **k):
        fetches.append(k.get("fetch"))
        return real(*a, **k)

    monkeypatch.setattr(usage.pricing, "estimate_details", spy)
    # No writer thread: flush drains the queue itself.
    monkeypatch.setattr(usage, "_ensure_writer", lambda: None)
    monkeypatch.setattr(usage, "_writer", None)
    for _ in range(5):
        usage.record("a@x", "lyria-002", "success", {"sample_count": 1})
    assert usage.flush(timeout=5) == 0
    assert len(fake_db.docs) == 5
    assert fetches == [False] * 5


def test_failing_db_is_retried(fake_db):
    fake_db.fail = 2
    usage.record("a@x", "lyria-002", "success", {"sample_count": 1})
    _wait_idle()
    assert len(fake_db.docs) == 1 and fake_db.attempts == 3


def test_db_that_keeps_failing_is_logged_with_a_count(fake_db, caplog):
    fake_db.fail = 10**6
    before = usage._stats["failed"]
    with caplog.at_level(logging.WARNING, logger=usage.logger.name):
        usage.record("a@x", "lyria-002", "success", {"sample_count": 1})
        _wait_idle()
    assert fake_db.attempts == usage.WRITE_ATTEMPTS
    assert usage._stats["failed"] == before + 1
    assert any("could not store a usage event" in r.message for r in caplog.records)
