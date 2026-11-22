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
"""Recent generated assets per studio, pulled from the user's Library.

Each Create studio (Image Studio, Video Studio, Music, Voice) renders a
"Recent" grid backed by ``state.history_*``. This module hydrates those lists
from the user's own completed items in Firestore (the Library), newest first,
so assets created in earlier sessions, other tabs, or via the Live Agent show
up immediately when opening a studio.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass

from common.utils import create_display_url, warm_display_urls

logger = logging.getLogger(__name__)

SCAN = 120  # newest owner items scanned from Firestore
LIMIT = 16  # recent cards shown in a studio tab
_INCOMPLETE_STATUSES = frozenset({"pending", "processing", "failed"})


@dataclass(frozen=True)
class RecentAsset:
    """One card in a studio's Recent grid."""

    url: str
    prompt: str
    meta: str
    aspect: str = ""


def _mime(row: dict) -> str:
    return str(row.get("mime_type") or "").lower()


def _model(row: dict) -> str:
    return str(row.get("model") or "").strip()


def _is_lyria(row: dict) -> bool:
    return "lyria" in _model(row).lower()


_STUDIO_FILTERS: dict[str, Callable[[dict], bool]] = {
    "gemini_image_generation": lambda r: _mime(r).startswith("image/"),
    "veo": lambda r: _mime(r).startswith("video/"),
    "lyria": lambda r: _mime(r).startswith("audio/") and _is_lyria(r),
    "voice": lambda r: _mime(r).startswith("audio/") and not _is_lyria(r),
}

_DEFAULT_ASPECTS: dict[str, str] = {
    "gemini_image_generation": "1:1",
    "veo": "16:9",
    "lyria": "",
    "voice": "",
}


def _when(row: dict) -> float:
    ts = row.get("timestamp")
    if isinstance(ts, str):
        try:
            ts = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=datetime.UTC)
        return ts.timestamp()
    return 0.0


def _prompt_text(row: dict) -> str:
    return " ".join(str(row.get("original_prompt") or row.get("prompt") or "").split())


def _extract_gcs_uris(row: dict) -> list[str]:
    """Return all valid ``gs://`` URIs stored on a Library document."""
    uris: list[str] = []
    raw_list = row.get("gcs_uris")
    if isinstance(raw_list, list):
        for uri in raw_list:
            if isinstance(uri, str) and uri.startswith("gs://"):
                uris.append(uri)
    raw_single = row.get("gcsuri")
    if isinstance(raw_single, list):
        for uri in raw_single:
            if isinstance(uri, str) and uri.startswith("gs://") and uri not in uris:
                uris.append(uri)
    elif (
        isinstance(raw_single, str)
        and raw_single.startswith("gs://")
        and raw_single not in uris
    ):
        uris.append(raw_single)
    return uris


def _format_meta(row: dict, studio: str) -> str:
    model = _model(row)
    if studio == "voice":
        comment = str(row.get("comment") or "").strip()
        return comment or model
    if studio == "lyria":
        return model
    if studio == "gemini_image_generation":
        parts = [
            model,
            str(row.get("aspect") or "").strip(),
            str(row.get("image_size") or row.get("resolution") or "").strip(),
        ]
        return " · ".join(p for p in parts if p)
    if studio == "veo":
        dur = row.get("duration")
        dur_str = ""
        if dur is not None:
            try:
                dur_str = f"{int(round(float(dur)))}s"
            except (TypeError, ValueError):
                dur_str = ""
        parts = [
            model,
            str(row.get("resolution") or "").strip(),
            dur_str,
        ]
        return " · ".join(p for p in parts if p)
    return model


def extract_recent_assets(
    rows: list[dict],
    studio: str,
    limit: int = LIMIT,
    *,
    url_fn: Callable[[str], str] = create_display_url,
    warm_fn: Callable[[list[str]], None] = warm_display_urls,
) -> list[RecentAsset]:
    """Filter, sort, deduplicate, and convert Library rows into RecentAsset cards."""
    matches = _STUDIO_FILTERS.get(studio)
    if matches is None or limit <= 0:
        return []

    default_aspect = _DEFAULT_ASPECTS.get(studio, "")
    candidates: list[tuple[str, dict]] = []
    seen_uris: set[str] = set()

    for row in sorted(rows, key=_when, reverse=True):
        if row.get("error_message"):
            continue
        status = str(row.get("status") or "").lower()
        if status in _INCOMPLETE_STATUSES:
            continue
        if not matches(row):
            continue
        for uri in _extract_gcs_uris(row):
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            candidates.append((uri, row))
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    if not candidates:
        return []

    uris = [uri for uri, _ in candidates]
    warm_fn(uris)

    assets: list[RecentAsset] = []
    for uri, row in candidates:
        display_url = url_fn(uri)
        if not display_url:
            continue
        assets.append(
            RecentAsset(
                url=display_url,
                prompt=_prompt_text(row),
                meta=_format_meta(row, studio),
                aspect=str(row.get("aspect") or default_aspect),
            )
        )
    return assets


def _query_owner_rows(owner: str) -> list[dict]:
    from google.cloud import firestore

    from common.metadata import config, db

    if not db:
        return []
    coll = db.collection(config.GENMEDIA_COLLECTION_NAME).where(
        "user_email", "==", owner
    )
    try:
        query = coll.order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(SCAN)
        return [d.to_dict() or {} for d in query.stream()]
    except Exception:  # no composite index on (user_email, timestamp)
        logger.info(
            "studio_history: ordered query failed, falling back to unordered scan",
            exc_info=True,
        )
        fallback = db.collection(config.GENMEDIA_COLLECTION_NAME).where(
            "user_email", "==", owner
        )
        return [d.to_dict() or {} for d in fallback.limit(SCAN * 3).stream()]


def load_recent_assets(
    owner: str,
    studio: str,
    limit: int = LIMIT,
) -> list[RecentAsset]:
    """Fetch the user's recent Library assets for a studio tab.

    Fails closed (returns ``[]`` without touching Firestore) when ``owner`` is
    empty or ``studio`` is unknown.
    """
    if not owner or studio not in _STUDIO_FILTERS:
        return []
    try:
        rows = _query_owner_rows(owner)
        return extract_recent_assets(rows, studio, limit=limit)
    except Exception:
        logger.exception("studio_history: could not load recent assets for %s", studio)
        return []


def apply_recent_assets(
    state: object,
    assets: list[RecentAsset],
    *,
    prompt_field: str = "history_prompts",
    include_aspect: bool = True,
) -> None:
    """Populate a studio PageState's ``history_*`` lists from ``assets``.

    Leaves existing state untouched when ``assets`` is empty so in-session or
    mock-mode items are never wiped out on navigation.
    """
    if not assets:
        return
    state.history_urls = [a.url for a in assets]
    setattr(state, prompt_field, [a.prompt for a in assets])
    state.history_meta = [a.meta for a in assets]
    if include_aspect:
        state.history_aspects = [a.aspect for a in assets]
