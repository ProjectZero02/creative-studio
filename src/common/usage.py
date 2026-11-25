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
"""Usage of the generative models, per person, for the usage page.

Every model call is already logged by ``common.analytics.log_model_call``;
it also calls :func:`record`, which stores one small document per call in
the Firestore collection ``usage_events`` (owner, model, kind, page, status,
estimated cost, time). Writing is best effort and happens on a background
thread, so a slow or failing Firestore never slows a generation.

Background jobs (Story Studio, Live) run in threads where the page state is
not available. They wrap their work in :func:`acting_for` so their calls are
counted for the right person.

:func:`summarize` turns events into the page's totals; it is pure.
"""

from __future__ import annotations

import contextlib
import contextvars
import datetime
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterator

from config import pricing

logger = logging.getLogger(__name__)

COLLECTION = "usage_events"
_owner: contextvars.ContextVar[str] = contextvars.ContextVar("usage_owner", default="")
_pending = threading.Semaphore(32)  # never pile up writer threads


def current_owner() -> str:
    return _owner.get()


@contextlib.contextmanager
def acting_for(owner: str) -> Iterator[None]:
    """Count model calls made inside this block for `owner`."""
    token = _owner.set(owner or "")
    try:
        yield
    finally:
        _owner.reset(token)


def event(
    owner: str,
    model: str,
    status: str,
    units: dict | None = None,
    page: str = "",
    task: str = "",
    at: float | None = None,
    feature: str = "",
) -> dict:
    at = at if at is not None else time.time()
    units = units or {}
    cost, pricing_details = pricing.estimate_details(model, units, status, at=at)
    return {
        "owner": owner or "unknown",
        "model": model or "unknown",
        "kind": pricing.kind_of(model, units),
        "billing_units": dict(units),
        "status": status,
        "page": page or "",
        "task": task or "",
        "feature": feature or "",
        "cost": round(cost, 5) if cost is not None else None,
        **pricing_details,
        "at": at,
        "day": datetime.datetime.fromtimestamp(at, datetime.UTC).strftime("%Y-%m-%d"),
    }


def _db():
    from common.metadata import db

    return db


def _write(
    owner: str,
    model: str,
    status: str,
    units: dict | None,
    page: str,
    task: str,
    feature: str,
) -> None:
    try:
        doc = event(owner, model, status, units, page, task, feature=feature)
        _db().collection(COLLECTION).add(doc)
    except Exception:  # best effort: usage must never break a generation
        logger.debug("usage: could not store an event", exc_info=True)
    finally:
        _pending.release()


def record(
    owner: str,
    model: str,
    status: str,
    units: dict | None = None,
    page: str = "",
    task: str = "",
    feature: str = "",
) -> None:
    """Store one model call (in the background)."""
    if not owner or owner == "unknown":
        owner = current_owner() or "unknown"
    if not _pending.acquire(blocking=False):
        return  # too many writes in flight: drop rather than slow down
    threading.Thread(
        target=_write,
        args=(owner, model, status, units, page, task, feature),
        daemon=True,
    ).start()


def load(owner: str | None, days: int, limit: int = 5000) -> list[dict]:
    """Events of the last `days` days: one person's, or everyone's (None).
    One person's are read by owner only (no composite index needed) and
    filtered by time here."""
    since = time.time() - days * 86400
    coll = _db().collection(COLLECTION)
    if owner:
        query = coll.where("owner", "==", owner).limit(limit)
    else:
        query = coll.where("at", ">=", since).limit(limit)
    rows = [d.to_dict() for d in query.stream()]
    return [r for r in rows if float(r.get("at") or 0) >= since]


def summarize(events: list[dict], days: int, now: float | None = None) -> dict:
    """Totals for the page: overall, per model, per day (every day of the
    period, zero when unused) and per person."""
    now = now if now is not None else time.time()
    today = datetime.datetime.fromtimestamp(now, datetime.UTC).date()
    day_keys = [(today - datetime.timedelta(days=d)).isoformat() for d in range(days - 1, -1, -1)]
    per_day = {d: 0.0 for d in day_keys}
    per_model: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "failed": 0,
            "unpriced": 0,
            "priced": 0,
            "cost": 0.0,
            "kind": "",
        }
    )
    per_feature: dict[str, dict] = defaultdict(
        lambda: {
            "calls": 0,
            "failed": 0,
            "unpriced": 0,
            "priced": 0,
            "cost": 0.0,
        }
    )
    per_owner: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "unpriced": 0, "priced": 0, "cost": 0.0}
    )
    total = {"calls": 0, "failed": 0, "unpriced": 0, "priced": 0, "cost": 0.0}
    for e in events:
        unpriced = e.get("pricing_status") == "unavailable" or e.get("cost") is None
        cost = float(e.get("cost") or 0)
        failed = e.get("status") != "success"
        m = per_model[e.get("model") or "unknown"]
        m["calls"] += 1
        m["failed"] += int(failed)
        m["unpriced"] += int(unpriced)
        m["priced"] += int(not unpriced)
        m["cost"] += cost
        m["kind"] = e.get("kind") or m["kind"]
        feature = e.get("feature") or ""
        if feature:
            f = per_feature[feature]
            f["calls"] += 1
            f["failed"] += int(failed)
            f["unpriced"] += int(unpriced)
            f["priced"] += int(not unpriced)
            f["cost"] += cost
        o = per_owner[e.get("owner") or "unknown"]
        o["calls"] += 1
        o["unpriced"] += int(unpriced)
        o["priced"] += int(not unpriced)
        o["cost"] += cost
        total["calls"] += 1
        total["failed"] += int(failed)
        total["unpriced"] += int(unpriced)
        total["priced"] += int(not unpriced)
        total["cost"] += cost
        if e.get("day") in per_day:
            per_day[e["day"]] += cost
    if not total["priced"]:
        total["cost"] = None
    for row in (*per_model.values(), *per_feature.values(), *per_owner.values()):
        if not row["priced"]:
            row["cost"] = None
        row.pop("priced")
    total.pop("priced")
    models = sorted(
        ({"model": k, **v} for k, v in per_model.items()),
        key=lambda r: -(r["cost"] or 0),
    )
    owners = sorted(
        ({"owner": k, **v} for k, v in per_owner.items()),
        key=lambda r: -(r["cost"] or 0),
    )
    features = sorted(
        ({"feature": k, **v} for k, v in per_feature.items()),
        key=lambda r: -(r["cost"] or 0),
    )
    return {
        "total": total,
        "models": models,
        "features": features,
        "days": [{"day": d, "cost": round(c, 4)} for d, c in per_day.items()],
        "owners": owners,
    }
