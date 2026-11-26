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
"""Model calls in worker threads are counted for the right person and page."""

import concurrent.futures
import threading

import pytest

from common import analytics, usage


@pytest.fixture
def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(
        usage,
        "record",
        lambda owner, model, status, units=None, page="", task="", feature="", **k: (
            calls.append({"owner": owner, "page": page, "feature": feature})
        ),
    )
    return calls


def _model_call():
    with analytics.track_model_call("lyria-002", billing_units={"sample_count": 1}):
        pass


def test_worker_thread_started_via_in_context_records_owner_page_feature(recorded):
    with usage.acting_for("owner@x", page="veo", feature="fashion"):
        worker = usage.in_context(_model_call)
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert recorded == [{"owner": "owner@x", "page": "veo", "feature": "fashion"}]


def test_pool_submit_via_in_context(recorded):
    with usage.acting_for("pool@x", page="omni"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(usage.in_context(lambda _: _model_call()), range(3)))
    assert [c["owner"] for c in recorded] == ["pool@x"] * 3
    assert {c["page"] for c in recorded} == {"omni"}


def test_plain_thread_without_in_context_is_unknown(recorded):
    with usage.acting_for("owner@x", page="veo"):
        t = threading.Thread(target=_model_call)
        t.start()
        t.join()
    assert recorded[0]["owner"] == "" and recorded[0]["page"] == ""


def test_in_context_prefers_the_page_state(recorded, monkeypatch):
    monkeypatch.setattr(usage, "_from_page_state", lambda: ("page@x", "banana"))
    worker = usage.in_context(_model_call)
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert recorded[0]["owner"] == "page@x" and recorded[0]["page"] == "banana"


def test_acting_for_restores_the_outer_context():
    with usage.acting_for("a@x", page="p", feature="f"):
        with usage.acting_for("b@x"):
            assert usage.current_owner() == "b@x" and usage.current_page() == "p"
        assert usage.current_feature() == "f"
    assert (usage.current_owner(), usage.current_page(), usage.current_feature()) == (
        "",
        "",
        "",
    )


def test_model_call_log_is_structured_on_cloud_run(monkeypatch):
    """Cloud Run's handler only puts json_fields into jsonPayload."""
    import io
    import json
    import logging

    from google.cloud.logging_v2.handlers import StructuredLogHandler

    stream = io.StringIO()
    handler = StructuredLogHandler(stream=stream, project_id="p")
    analytics.analytics_logger.addHandler(handler)
    monkeypatch.setattr(usage, "record", lambda *a, **k: None)
    try:
        with usage.acting_for("a@x", page="veo"):
            analytics.log_model_call(
                "lyria-002", "success", billing_units={"sample_count": 1}, event_id="e9"
            )
    finally:
        analytics.analytics_logger.removeHandler(handler)
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["event_type"] == "model_call" and line["event_id"] == "e9"
    assert line["user_email"] == "a@x" and line["billing_units"] == {"sample_count": 1}
    assert logging.getLevelName(line["severity"]) == logging.INFO



def test_story_job_model_call_records_owner_page_and_feature(monkeypatch, recorded):
    from services import story_jobs

    monkeypatch.setattr(story_jobs, "_finish", lambda job: None)
    done = threading.Event()

    def target(_job):
        try:
            _model_call()  # a mocked model call inside the job thread
        finally:
            done.set()

    job = story_jobs.Job(id="j1", owner="o@x", story_id="s1", kind="build")
    story_jobs._spawn(job, target)
    assert done.wait(5)
    assert recorded == [{"owner": "o@x", "page": "story", "feature": "story"}]
