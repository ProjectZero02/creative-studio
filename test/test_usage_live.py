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
"""Live calls are recorded every minute or so, not only at the end."""

from types import SimpleNamespace

from common import usage
from routers import live_router


def _bridge(monkeypatch, calls):
    bridge = object.__new__(live_router._Bridge)
    bridge.owner = "a@x"
    bridge.model = "gemini-3.8-live"
    bridge.usage_totals = {}
    bridge.usage_session_id = "s1"
    bridge._usage_recorded_at = 0.0
    monkeypatch.setattr(
        usage, "record", lambda owner, model, status, units, **k: calls.append(units)
    )
    return bridge


def test_turn_complete_records_after_a_minute(monkeypatch):
    calls = []
    bridge = _bridge(monkeypatch, calls)
    now = [1000.0]
    monkeypatch.setattr(live_router.time, "monotonic", lambda: now[0])

    live_router.add_live_usage(
        bridge.usage_totals, SimpleNamespace(prompt_token_count=10)
    )
    bridge._usage_recorded_at = 990.0  # 10 s ago: too soon
    bridge._maybe_record_usage()
    assert calls == []

    now[0] = 1050.0  # 60 s since the last record
    bridge._maybe_record_usage()
    assert calls == [{"prompt_tokens": 10}]
    assert bridge.usage_totals == {}

    # The next record only holds what came after.
    live_router.add_live_usage(
        bridge.usage_totals, SimpleNamespace(prompt_token_count=5)
    )
    now[0] = 1080.0
    bridge._maybe_record_usage()
    assert len(calls) == 1
    bridge._record_usage(bridge.model)  # the close flush
    assert calls[-1] == {"prompt_tokens": 5}


def test_nothing_is_recorded_without_tokens(monkeypatch):
    calls = []
    bridge = _bridge(monkeypatch, calls)
    bridge._maybe_record_usage()
    assert calls == []
