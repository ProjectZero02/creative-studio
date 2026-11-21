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
"""Recent prompts per studio, for the composer's history button.

Nothing new is stored: the prompts come from the person's own media items
(the Library), newest first, one entry per distinct prompt. Each studio says
which items count and which field of the page the prompt goes back into
(``services.page_forms``).
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

SCAN = 200  # newest items looked at
LIMIT = 12  # prompts shown


def _mime(row: dict) -> str:
    return str(row.get("mime_type") or "")


def _model(row: dict) -> str:
    return str(row.get("model") or "").lower()


# page key (as in services.page_forms.PAGES) -> (form field, which items count)
STUDIOS: dict[str, tuple[str, Callable[[dict], bool]]] = {
    "gemini_image_generation": ("prompt", lambda r: _mime(r).startswith("image/")),
    "veo": ("prompt", lambda r: _mime(r).startswith("video/")),
    "lyria": ("prompt", lambda r: "lyria" in _model(r)),
    "voice": (
        "script",
        lambda r: _mime(r).startswith("audio/") and "lyria" not in _model(r),
    ),
}


def _when(row: dict) -> float:
    ts = row.get("timestamp")
    if isinstance(ts, str):
        try:
            ts = datetime.datetime.fromisoformat(ts)
        except ValueError:
            return 0.0
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.UTC)
        return ts.timestamp()
    return 0.0


def _text(row: dict) -> str:
    # Music keeps what the person typed apart from the rewritten prompt.
    return " ".join(str(row.get("original_prompt") or row.get("prompt") or "").split())


def pick(rows: list[dict], page: str, limit: int = LIMIT) -> list[str]:
    """Distinct prompts of this studio's items, newest first."""
    if page not in STUDIOS:
        return []
    _, counts = STUDIOS[page]
    seen: set[str] = set()
    out: list[str] = []
    for row in sorted(rows, key=_when, reverse=True):
        if not counts(row):
            continue
        text = _text(row)
        key = text.lower()
        if len(text) < 3 or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _rows(owner: str) -> list[dict]:
    from google.cloud import firestore

    from common.metadata import config, db

    coll = db.collection(config.GENMEDIA_COLLECTION_NAME).where("user_email", "==", owner)
    try:
        query = coll.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(SCAN)
        return [d.to_dict() or {} for d in query.stream()]
    except Exception:  # no composite index here: take a bigger unordered batch
        logger.info("prompt_history: ordered query failed, falling back", exc_info=True)
        return [d.to_dict() or {} for d in coll.limit(SCAN * 3).stream()]


def recent(owner: str, page: str, limit: int = LIMIT) -> list[str]:
    if not owner or page not in STUDIOS:
        return []
    try:
        return pick(_rows(owner), page, limit)
    except Exception:
        logger.exception("prompt_history: could not read recent prompts")
        return []


def field_for(page: str) -> str:
    return STUDIOS.get(page, ("prompt", None))[0]
