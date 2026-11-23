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
"""Story Studio downloads, served as real downloads (Content-Disposition).

- ``GET /api/story/{story_id}/subtitles/{variant}.{srt|vtt}`` returns the
  film's subtitles ("en", "ar" or "en+ar"), made on request.
- ``GET /api/story/{story_id}/download/{what}`` returns a film file:
  "film" (the current film), "alt" (the second-language film),
  "export-<key>" (a file from the Export menu, see services/story_export.py)
  or "version-<n>" (an earlier film).

The story is looked up with the caller as owner, so nobody can read another
person's story; a missing story and someone else's story answer the same 404.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

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


def _title(story) -> str:
    return _SAFE.sub("", story.title or "film").strip()[:60] or "film"


def download_target(story, what: str) -> tuple[str, str] | None:
    """(stored uri, file name) for a download, or None when there is none."""
    from services import story_export, story_versions

    def named(uri: str, suffix: str = "") -> str:
        ext = uri.rsplit(".", 1)[-1].lower() if "." in uri[-6:] else "mp4"
        return f"{_title(story)}{suffix}.{ext}"

    if what == "film" and story.final_uri:
        return story.final_uri, named(story.final_uri)
    if what == "alt" and story.final_alt_uri:
        return story.final_alt_uri, named(story.final_alt_uri, f" ({story.alt_language})")
    if what.startswith("export-"):
        row = story_export.exports(story).get(what.removeprefix("export-"))
        if row and row.get("uri"):
            return row["uri"], str(row.get("name") or named(row["uri"]))
    if what.startswith("version-"):
        try:
            n = int(what.removeprefix("version-"))
        except ValueError:
            return None
        rows = story_versions.versions(story)
        if 0 <= n < len(rows):
            return rows[n]["uri"], named(rows[n]["uri"], f" (version {n + 1})")
    return None


def _disposition(name: str) -> str:
    from urllib.parse import quote

    plain = name.encode("ascii", "ignore").decode().replace('"', "") or "film"
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"


@router.get("/{story_id}/download/{what}")
def download(story_id: str, what: str, request: Request):
    from services.story_service import LOCAL_SCHEME, _media_mime, local_path
    from services.story_store import get_store

    owner = _caller(request)
    story = get_store().get(story_id[:64], owner)
    target = download_target(story, what[:64]) if story is not None else None
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    uri, name = target
    media = _media_mime(uri)
    headers = {"Content-Disposition": _disposition(name)}
    if uri.startswith(LOCAL_SCHEME):
        import os

        path = local_path(uri)
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, media_type=media, headers=headers)
    if uri.startswith("gs://"):
        from google.cloud import storage

        from common.storage import get_storage_client

        blob = storage.Blob.from_string(uri, client=get_storage_client())

        def chunks():
            with blob.open("rb", chunk_size=1024 * 1024) as f:
                while data := f.read(1024 * 1024):
                    yield data

        return StreamingResponse(chunks(), media_type=media, headers=headers)
    raise HTTPException(status_code=404, detail="Not found")
