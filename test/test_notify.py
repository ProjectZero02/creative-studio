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
"""Done notifications."""

from types import SimpleNamespace

from common import notify
from components.generation_progress import generation_progress as gp
from state.notify_state import NotifyState
from state.state import AppState


def _fake_states(monkeypatch, page="veo"):
    notice = NotifyState()
    app = SimpleNamespace(current_page=page)
    states = {NotifyState: notice, AppState: app}
    monkeypatch.setattr(notify.me, "state", lambda cls: states[cls])
    return notice


def test_notice_ids_keep_going_up(monkeypatch):
    notice = _fake_states(monkeypatch)
    notify.notify("A", "first")
    first = notice.seq
    notify.notify("B", "second")
    assert notice.seq > first > 1_000_000_000_000  # a millisecond time stamp
    assert (notice.title, notice.body) == ("B", "second")


def test_progress_helpers_notify_with_the_page_kind(monkeypatch):
    notice = _fake_states(monkeypatch, page="lyria")
    state = SimpleNamespace(progress_stages=["a", "b"], progress_stage=0,
                            progress_status="running", progress_error="")
    gp.progress_done(state)
    assert notice.title == "Ready" and notice.body == "Your music is ready."
    gp.progress_fail(state, "boom")
    assert notice.title == "Something went wrong"


def test_unknown_page_and_no_state_are_fine(monkeypatch):
    notice = _fake_states(monkeypatch, page="somewhere")
    notify.generation_done()
    assert notice.body == "Your generation is ready."

    def boom(cls):
        raise RuntimeError("no request")

    monkeypatch.setattr(notify.me, "state", boom)
    notify.generation_done()  # does not raise
