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
"""Story Studio downloads that are text, made on request: subtitle files.

``GET /api/story/{story_id}/subtitles/{variant}.{srt|vtt}`` returns the
film's subtitles ("en", "ar" or "en+ar"). The story is looked up with the
caller as owner, so nobody can read another person's story; a missing story
and someone else's story answer the same 404.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from common.identity import ANONYMOUS_USER_EMAIL, require_authenticated_user
from config.default import Default

router = APIRouter(prefix="/api/story", tags=["story"])

_SAFE = re.compile(r"[^A-Za-z0-9 _-]+")


def _caller(request: Request) -> str:
    email = request.scope.get("MESOP_USER_EMAIL") or ""
    if email and email != ANONYMOUS_USER_EMAIL:
        return email
    if require_authenticated_user(Default.APP_ENV):
        raise HTTPException(status_code=403, detail="Forbidden")
    return ANONYMOUS_USER_EMAIL


def subtitle_file(story, variant: str, ext: str) -> str | None:
    """The subtitle file text, or None when a language is not ready yet."""
    from services import story_subtitles as subs

    if variant not in subs.VARIANTS or variant == "none" or ext not in ("srt", "vtt"):
        return None
    lines = {}
    for code in subs.variant_langs(variant):
        got = subs.lines_for(story, code)
        if got is None:
            return None
        lines[code] = got
    items = subs.variant_cues(story, story.timeline_json, variant, lines)
    return subs.to_srt(items) if ext == "srt" else subs.to_vtt(items)


@router.get("/{story_id}/subtitles/{name}")
def subtitles(story_id: str, name: str, request: Request):
    from services.story_store import get_store

    owner = _caller(request)
    variant, _, ext = name.rpartition(".")
    story = get_store().get(story_id[:64], owner)
    text = subtitle_file(story, variant, ext) if story is not None else None
    if text is None:
        raise HTTPException(status_code=404, detail="Not found")
    title = _SAFE.sub("", story.title or "film").strip()[:60] or "film"
    filename = f"{title} ({variant}).{ext}".replace("+", "-")
    media = "application/x-subrip" if ext == "srt" else "text/vtt"
    return Response(
        content=text.encode("utf-8"),
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
