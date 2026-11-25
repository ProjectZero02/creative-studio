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
estimated cost, time). Calls go on one queue that a single writer thread
prices and stores, so a slow or failing Firestore never slows a generation.
A failed write is retried; one that still fails is logged with a count, and
what is queued at exit (atexit, SIGTERM) is flushed for up to 5 seconds.
Each event has an ``event_id`` (also its document id, so a retry never
stores it twice).

Background jobs (Story Studio, Live) run in threads where the page state is
not available. They wrap their work in :func:`acting_for` so their calls are
counted for the right person, page and feature; a page that hands work to a
thread or pool wraps the function in :func:`in_context`.

:func:`summarize` turns events into the page's totals; it is pure.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import datetime
import logging
import os
import queue
import signal
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Iterator

from config import pricing

logger = logging.getLogger(__name__)

COLLECTION = "usage_events"
_owner: contextvars.ContextVar[str] = contextvars.ContextVar("usage_owner", default="")


_page: contextvars.ContextVar[str] = contextvars.ContextVar("usage_page", default="")
_feature: contextvars.ContextVar[str] = contextvars.ContextVar(
    "usage_feature", default=""
)


def current_owner() -> str:
    return _owner.get()


def current_page() -> str:
    return _page.get()


def current_feature() -> str:
    return _feature.get()


@contextlib.contextmanager
def acting_for(owner: str, page: str = "", feature: str = "") -> Iterator[None]:
    """Count model calls made inside this block for `owner` (and, when
    given, `page` and `feature`). For threads where the page state is not
    available."""
    tokens = [(_owner, _owner.set(owner or ""))]
    if page:
        tokens.append((_page, _page.set(page)))
    if feature:
        tokens.append((_feature, _feature.set(feature)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def _from_page_state() -> tuple[str, str]:
    """(owner, page) from the Mesop page state, or ("", "") off the page."""
    try:
        import mesop as me  # pylint: disable=import-outside-toplevel

        from state.state import AppState  # pylint: disable=import-outside-toplevel

        state = me.state(AppState)
        return str(state.user_email or ""), str(state.current_page or "")
    except Exception:
        return "", ""


def in_context(fn):
    """`fn` wrapped to run with this thread's owner, page and feature, for
    handing to a worker thread or pool (``pool.submit(in_context(f), x)``)."""
    owner, page = _from_page_state()
    owner = owner or current_owner()
    page = page or current_page()
    feature = current_feature()

    def run(*args, **kwargs):
        def inner():
            with acting_for(owner, page=page, feature=feature):
                return fn(*args, **kwargs)

        return contextvars.copy_context().run(inner)

    return run


def current_env() -> str:
    """The Cloud Run service name, or "local"."""
    return os.environ.get("K_SERVICE") or "local"


def place_for(model: str) -> tuple[str, str]:
    """(project, location) a model is called in, from the app config. Call
    sites that use another client set ``ctx["project"]``/``ctx["location"]``
    in track_model_call instead."""
    try:
        from config.default import Default  # pylint: disable=import-outside-toplevel

        cfg = Default()
    except Exception:
        return "", ""
    name = (model or "").lower()
    project = cfg.PROJECT_ID or ""
    if "omni" in name:
        return cfg.OMNI_PROJECT_ID or project, cfg.OMNI_LOCATION
    if "veo" in name:
        return cfg.VEO_PROJECT_ID or project, cfg.VEO_LOCATION
    if "lyria" in name:
        location = "global" if "lyria-3" in name else cfg.LYRIA_LOCATION
        return cfg.LYRIA_PROJECT_ID or project, location
    if "live" in name:
        return project, cfg.LIVE_LOCATION
    if "tts" in name or "chirp" in name:
        return project, cfg.GEMINI_TTS_LOCATION
    if "try-on" in name or "vto" in name:
        return project, cfg.VTO_LOCATION
    if "image" in name or "banana" in name:
        return project, cfg.GEMINI_IMAGE_GEN_LOCATION
    if "imagen" in name:
        return project, cfg.LOCATION
    return project, cfg.GEMINI_LOCATION


def event(
    owner: str,
    model: str,
    status: str,
    units: dict | None = None,
    page: str = "",
    task: str = "",
    at: float | None = None,
    feature: str = "",
    event_id: str = "",
    fetch: bool = True,
    env: str = "",
    project: str = "",
    location: str = "",
) -> dict:
    at = at if at is not None else time.time()
    units = units or {}
    if not (project and location):
        default_project, default_location = place_for(model)
        project = project or default_project
        location = location or default_location
    cost, pricing_details = pricing.estimate_details(
        model, units, status, at=at, fetch=fetch, location=location
    )
    return {
        "event_id": event_id or new_event_id(),
        "env": env or current_env(),
        "project": project or "",
        "location": location or "",
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


# ---------------------------------------------------------------------------
# Writing: one queue, one writer thread, retries, flush at exit
# ---------------------------------------------------------------------------

WRITE_ATTEMPTS = 3
WRITE_BACKOFF_SECONDS = (0.5, 1.0, 2.0)
FLUSH_SECONDS = 5.0

_queue: queue.Queue[dict] = queue.Queue()
_writer: threading.Thread | None = None
_writer_lock = threading.Lock()
_stats = {"stored": 0, "failed": 0}
_exiting = threading.Event()  # at exit: price from the book, never the network


def new_event_id() -> str:
    return uuid.uuid4().hex


def _store(item: dict) -> None:
    """Price one queued call and write it, retrying with backoff. A call
    that still cannot be stored is counted and logged, never dropped
    silently."""
    doc = None
    for attempt in range(WRITE_ATTEMPTS):
        try:
            if doc is None:
                doc = event(**item, fetch=not _exiting.is_set())
            _db().collection(COLLECTION).document(doc["event_id"]).set(doc)
            _stats["stored"] += 1
            return
        except Exception:
            if attempt + 1 < WRITE_ATTEMPTS and not _exiting.is_set():
                time.sleep(WRITE_BACKOFF_SECONDS[attempt])
            elif attempt + 1 < WRITE_ATTEMPTS:
                continue  # at exit: retry at once
            else:
                _stats["failed"] += 1
                logger.warning(
                    "usage: could not store a usage event after %d tries "
                    "(%d not stored so far): %s %s",
                    WRITE_ATTEMPTS,
                    _stats["failed"],
                    item.get("model"),
                    item.get("event_id"),
                    exc_info=True,
                )


def _run_writer() -> None:
    while True:
        item = _queue.get()
        try:
            _store(item)
        finally:
            _queue.task_done()


def _ensure_writer() -> None:
    global _writer
    if _writer is not None and _writer.is_alive():
        return
    with _writer_lock:
        if _writer is None or not _writer.is_alive():
            _writer = threading.Thread(
                target=_run_writer, name="usage-writer", daemon=True
            )
            _writer.start()


def flush(timeout: float = FLUSH_SECONDS) -> int:
    """Store what is queued (at exit). Prices from the book, so it never
    waits on the catalog. Returns how many calls were still queued."""
    _exiting.set()
    deadline = time.monotonic() + timeout
    if _writer is None or not _writer.is_alive():
        while time.monotonic() < deadline:  # no writer: drain here
            try:
                item = _queue.get_nowait()
            except queue.Empty:
                break
            try:
                _store(item)
            finally:
                _queue.task_done()
    while _queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.02)
    left = _queue.unfinished_tasks
    if left:
        logger.warning("usage: %d usage event(s) not stored at exit", left)
    return left


def _on_sigterm(signum, frame) -> None:
    flush()
    previous = _previous_sigterm
    if callable(previous):
        previous(signum, frame)
    elif previous != signal.SIG_IGN:
        raise SystemExit(128 + signum)


_previous_sigterm = None


def _install_exit_hooks() -> None:
    global _previous_sigterm
    atexit.register(flush)
    try:  # only the main thread may set signal handlers
        if threading.current_thread() is threading.main_thread():
            _previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError, AttributeError):
        pass


_install_exit_hooks()


def record(
    owner: str,
    model: str,
    status: str,
    units: dict | None = None,
    page: str = "",
    task: str = "",
    feature: str = "",
    event_id: str = "",
    project: str = "",
    location: str = "",
) -> None:
    """Queue one model call; the writer thread prices and stores it."""
    if not owner or owner == "unknown":
        owner = current_owner() or "unknown"
    _queue.put(
        {
            "owner": owner,
            "model": model,
            "status": status,
            "units": dict(units or {}),
            "page": page or current_page(),
            "task": task,
            "feature": feature or current_feature(),
            "at": time.time(),
            "event_id": event_id or new_event_id(),
            "env": current_env(),
            "project": project,
            "location": location,
        }
    )
    _ensure_writer()


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
