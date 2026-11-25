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
"""Usage tracking and cost estimates."""

import threading

import pytest

from common import usage
from config import pricing


def test_estimates_follow_the_billing_units():
    # List prices from the price book (no catalog in tests).
    veo = {"video_seconds_generated": 8, "resolution": "720p", "generate_audio": True}
    assert pricing.estimate("veo-3.1-generate", veo) == pytest.approx(3.2)
    assert pricing.estimate("veo-3.1-fast-generate", veo) == pytest.approx(0.8)
    assert pricing.estimate(
        "gemini-3-pro-image", {"images_generated": 2, "image_size": "1K"}
    ) == pytest.approx(2 * 1120 * 120 / 1e6)
    assert pricing.estimate("lyria-002", {"sample_count": 3}) == pytest.approx(0.18)
    assert pricing.estimate("chirp-3-hd", {"characters_synthesized": 1_000_000}) == pytest.approx(30)
    text = pricing.estimate("gemini-3.5-flash", {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000})
    assert text == pytest.approx(1.5 + 9.0)
    text_with_reasoning = pricing.estimate(
        "gemini-3.5-flash",
        {
            "prompt_tokens": 1_000_000,
            "tool_use_prompt_tokens": 500_000,
            "candidates_tokens": 1_000_000,
            "thoughts_tokens": 500_000,
        },
    )
    assert text_with_reasoning == pytest.approx(1.5 * 1.5 + 1.5 * 9.0)
    neon = pricing.estimate("gemini-4-neon", {"prompt_tokens": 1_000_000, "candidates_tokens": 1_000_000})
    assert neon == pytest.approx(18.0)
    assert pricing.estimate("veo-3.1", {"video_seconds_generated": 8}, "failure") == 0


def test_event_keeps_billing_units_for_auditability(monkeypatch):
    monkeypatch.setattr(
        pricing,
        "get_token_rates",
        lambda model: pricing.TokenRates(0.30, 2.50, "2026-11-23T00:00:00Z"),
    )
    units = {
        "prompt_tokens": 120,
        "candidates_tokens": 45,
        "total_tokens": 165,
    }

    recorded = usage.event("a@x", "gemini-3.5-flash", "success", units, at=1_800_000_000)

    assert recorded["billing_units"] == units
    assert recorded["billing_units"] is not units


def test_event_keeps_feature_attribution(monkeypatch):
    monkeypatch.setattr(
        pricing,
        "get_token_rates",
        lambda model: pricing.TokenRates(0.30, 2.50, "2026-11-23T00:00:00Z"),
    )

    recorded = usage.event(
        "a@x",
        "gemini-3.5-flash",
        "success",
        {"prompt_tokens": 120},
        task="try_on",
        feature="fashion",
        at=1_800_000_000,
    )

    assert recorded["feature"] == "fashion"


def test_kinds():
    assert pricing.kind_of("gemini-omni-video", {"video_seconds_generated": 4}) == "video"
    assert pricing.kind_of("lyria-002", {}) == "music"
    assert pricing.kind_of("gemini-tts", {"characters_synthesized": 3}) == "speech"
    assert pricing.kind_of("imagen-4.0", {}) == "image"
    assert pricing.kind_of("gemini-3.5-flash", {}) == "text"


def test_summary_fills_every_day_and_sorts_by_cost():
    now = 1_800_000_000.0  # fixed clock
    events = [
        usage.event("a@x", "veo-3.1", "success", {"video_seconds_generated": 8}, at=now),
        usage.event("b@x", "lyria-002", "success", {"sample_count": 1}, at=now - 86400),
        usage.event("a@x", "veo-3.1", "failure", {"video_seconds_generated": 8}, at=now),
    ]
    out = usage.summarize(events, 7, now=now)
    assert out["total"]["calls"] == 3 and out["total"]["failed"] == 1
    assert len(out["days"]) == 7 and out["days"][-1]["cost"] == pytest.approx(3.2)
    assert out["days"][-2]["cost"] == pytest.approx(0.06)
    assert out["models"][0]["model"] == "veo-3.1" and out["models"][0]["failed"] == 1
    assert [o["owner"] for o in out["owners"]] == ["a@x", "b@x"]


def test_summary_groups_costs_by_feature():
    now = 1_800_000_000.0
    events = [
        usage.event(
            "a@x",
            "gemini-3.5-flash",
            "success",
            {"prompt_tokens": 1_000_000},
            feature="fashion",
            at=now,
        ),
        usage.event(
            "a@x",
            "gemini-3.5-flash",
            "success",
            {"prompt_tokens": 2_000_000},
            feature="fashion",
            at=now,
        ),
        usage.event(
            "a@x",
            "gemini-3.5-flash",
            "success",
            {"prompt_tokens": 500_000},
            feature="interior_design",
            at=now,
        ),
    ]

    features = usage.summarize(events, 7, now=now)["features"]

    assert features == [
        {
            "feature": "fashion",
            "calls": 2,
            "failed": 0,
            "unpriced": 0,
            "cost": pytest.approx(4.5),  # 3M input tokens at $1.50/M
        },
        {
            "feature": "interior_design",
            "calls": 1,
            "failed": 0,
            "unpriced": 0,
            "cost": pytest.approx(0.75),
        },
    ]


def test_background_calls_are_counted_for_the_job_owner(monkeypatch):
    stored = []
    done = threading.Event()

    def fake_store(item):
        stored.append(usage.event(**item))
        done.set()

    monkeypatch.setattr(usage, "_store", fake_store)
    with usage.acting_for("owner@x"):
        usage.record("", "veo-3.1", "success", {"video_seconds_generated": 4}, task="story")
    assert done.wait(2)
    assert stored[0]["owner"] == "owner@x" and stored[0]["task"] == "story"
    assert stored[0]["cost"] == pytest.approx(1.6)
    assert usage.current_owner() == ""


def test_story_pools_carry_the_owner_into_their_threads():
    from services.story_jobs import _Pool

    with usage.acting_for("pool@x"):
        with _Pool(max_workers=2) as pool:
            seen = pool.submit(usage.current_owner).result()
    assert seen == "pool@x"


def test_log_model_call_records_usage(monkeypatch):
    from common import analytics

    calls = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: calls.append((a, k)))
    with usage.acting_for("thread@x"):
        analytics.log_model_call(
            "lyria-002",
            "success",
            details={"task": "compose", "feature": "fashion"},
            billing_units={"sample_count": 1},
        )
    assert calls and calls[0][0][1] == "lyria-002"
    assert calls[0][1]["feature"] == "fashion"


def test_load_reads_one_person_by_owner_and_filters_by_time(monkeypatch):
    import time

    class Doc:
        def __init__(self, d):
            self._d = d

        def to_dict(self):
            return self._d

    class Query:
        def __init__(self, rows, log):
            self.rows, self.log = rows, log

        def where(self, *args):
            self.log.append(args)
            return self

        def limit(self, n):
            return self

        def stream(self):
            return [Doc(r) for r in self.rows]

    log = []
    now = time.time()
    rows = [{"owner": "a@x", "at": now}, {"owner": "a@x", "at": now - 40 * 86400}]

    class DB:
        def collection(self, name):
            assert name == usage.COLLECTION
            return Query(rows, log)

    monkeypatch.setattr(usage, "_db", lambda: DB())
    assert len(usage.load("a@x", 7)) == 1
    assert log[0] == ("owner", "==", "a@x")
    usage.load(None, 7)
    assert log[1][0] == "at"
