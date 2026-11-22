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
"""Usage and cost page (/usage).

What the signed-in person generated in the last 7 or 30 days and what it
cost, as an estimate from config/pricing.py: totals, spend per day, and a
table per model. Admins can switch to everyone and see a table per person.
Data comes from common/usage.py.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import field

from contextlib import nullcontext

import mesop as me

from common import usage
from components.header import header
from components.page_scaffold import page_frame, page_scaffold
from state.state import AppState

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "video": "Video",
    "image": "Image",
    "music": "Music",
    "speech": "Speech",
    "text": "Gemini text",
}


def _label(text: str, cls: str) -> None:
    """Text with a CSS class (me.text itself takes no classes)."""
    with me.box(classes=cls):
        me.text(text)


@me.stateclass
class UsageState:
    days: int = 7
    everyone: bool = False
    summary_json: str = ""
    error: str = ""
    loading: bool = False
    loaded_for: list[str] = field(default_factory=list)


def _is_admin() -> bool:
    return me.state(AppState).user_role == "admin"


def money(value: float) -> str:
    if value and value < 0.01:
        return "< $0.01"
    return f"${value:,.2f}"


def _load(s: UsageState) -> None:
    app = me.state(AppState)
    everyone = s.everyone and _is_admin()
    s.everyone = everyone
    try:
        events = usage.load(None if everyone else app.user_email, s.days)
        s.summary_json = json.dumps(usage.summarize(events, s.days))
        s.error = ""
    except Exception as exc:
        logger.exception("Usage: could not load events")
        s.summary_json = ""
        s.error = f"Could not load usage: {str(exc)[:160]}"


def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    s = me.state(UsageState)
    s.loading = True
    yield
    _load(s)
    s.loading = False
    yield


def on_days(e: me.ButtonToggleChangeEvent):
    s = me.state(UsageState)
    s.days = 30 if e.value == "30" else 7
    _load(s)


def on_scope(e: me.ButtonToggleChangeEvent):
    s = me.state(UsageState)
    s.everyone = e.value == "everyone"
    _load(s)


@me.page(path="/usage", title="Usage | GenMedia Studio", on_load=on_load)
def page():
    with page_scaffold(page_name="usage"):  # pylint: disable=not-context-manager
        usage_content()


def _stat(label: str, value: str) -> None:
    with me.box(classes="gm-usage-stat"):
        _label(label, "gm-usage-stat-label")
        _label(value, "gm-usage-stat-value")


def _day_label(day: str) -> str:
    try:
        return datetime.date.fromisoformat(day).strftime("%a %d %b")
    except ValueError:
        return day


def _chart(days: list[dict]) -> None:
    peak = max((d["cost"] for d in days), default=0) or 1
    with me.box(classes="gm-usage-chart", style=me.Style(height=160)):
        for d in days:
            pct = max(0.0, d["cost"] / peak)
            with me.tooltip(message=f"{_day_label(d['day'])}: {money(d['cost'])}"):
                with me.box(classes="gm-usage-col"):
                    me.box(
                        classes="gm-usage-bar" + (" is-zero" if not d["cost"] else ""),
                        style=me.Style(height=f"{max(2, round(pct * 140))}px"),
                    )
    with me.box(classes="gm-usage-axis"):
        me.text(_day_label(days[0]["day"]) if days else "")
        me.text("Today")


def usage_content(embedded: bool = False):
    """The Usage page body; `embedded` drops the frame and title (Settings)."""
    s = me.state(UsageState)
    try:
        summary = json.loads(s.summary_json) if s.summary_json else None
    except ValueError:
        summary = None
    frame = nullcontext() if embedded else page_frame()
    with frame:  # pylint: disable=not-context-manager
        if not embedded:
            header(
                "Usage",
                "monitoring",
                description="What you generated and an estimate of what it cost.",
            )
        with me.box(classes="gm-usage"):
            with me.box(classes="gm-segmented gm-filter-row"):
                me.button_toggle(
                    value=str(s.days),
                    buttons=[
                        me.ButtonToggleButton(label="Last 7 days", value="7"),
                        me.ButtonToggleButton(label="Last 30 days", value="30"),
                    ],
                    hide_selection_indicator=True,
                    on_change=on_days,
                    key="usage-days",
                )
                if _is_admin():
                    me.button_toggle(
                        value="everyone" if s.everyone else "me",
                        buttons=[
                            me.ButtonToggleButton(label="Me", value="me"),
                            me.ButtonToggleButton(label="Everyone", value="everyone"),
                        ],
                        hide_selection_indicator=True,
                        on_change=on_scope,
                        key="usage-scope",
                    )
            if s.error:
                me.text(s.error, style=me.Style(color=me.theme_var("error")))
            if s.loading and not summary:
                me.progress_spinner()
                return
            if not summary or not summary["total"]["calls"]:
                with me.box(classes="gm-usage-card"):
                    me.text("Nothing generated in this period yet.")
                return
            total = summary["total"]
            with me.box(classes="gm-usage-stats"):
                _stat("Estimated cost", money(total["cost"]))
                _stat("Generations", f"{total['calls']:,}")
                _stat("Failed", f"{total['failed']:,}")
            with me.box(classes="gm-usage-card"):
                _label("Estimated cost per day", "gm-usage-title")
                _chart(summary["days"])
            with me.box(classes="gm-usage-card"):
                _label("Per model", "gm-usage-title")
                with me.box(classes="gm-usage-table"):
                    for col in ("Model", "Type", "Calls", "Failed", "Est. cost"):
                        _label(col, "gm-usage-th")
                    for row in summary["models"]:
                        _label(row["model"], "gm-usage-model")
                        me.text(KIND_LABELS.get(row["kind"], row["kind"].title()))
                        me.text(f"{row['calls']:,}")
                        me.text(f"{row['failed']:,}")
                        me.text(money(row["cost"]))
            if s.everyone and summary["owners"]:
                with me.box(classes="gm-usage-card"):
                    _label("Per person", "gm-usage-title")
                    with me.box(classes="gm-usage-table gm-usage-table-3"):
                        for col in ("Person", "Calls", "Est. cost"):
                            _label(col, "gm-usage-th")
                        for row in summary["owners"]:
                            _label(row["owner"], "gm-usage-model")
                            me.text(f"{row['calls']:,}")
                            me.text(money(row["cost"]))
            me.text(
                "Costs are list-price estimates from the billing units of each call "
                "(seconds of video, images, tracks, characters, tokens), not a bill. "
                "Failed calls count as free.",
                style=me.Style(font_size=12, color=me.theme_var("on-surface-variant")),
            )
