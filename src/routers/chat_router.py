# Copyright 2025 Google LLC
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
"""The Home chat's API (services/studio_chat.py).

- ``POST /api/chat`` with ``{"message": "..."}`` returns the reply and the
  jobs it started.
- ``GET /api/chat/jobs`` returns the chat's jobs with their status, for the
  page to poll until they finish.
- ``POST /api/chat/reset`` starts a new conversation.
- ``GET /api/chat/options`` lists the type controls (services/studio_options.py)
  and ``POST /api/chat/job`` starts a job with those settings, no model call.
- ``POST /api/chat/film`` runs a film's next step (or all of them).
- ``POST /api/chat/load`` reopens a saved chat (routers/chats_router.py):
  the model gets its earlier turns and its jobs keep reporting.

Everything is per caller (signed-in email). Browser requests must come from
this site (Origin check) and send JSON.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from common.identity import ANONYMOUS_USER_EMAIL, require_authenticated_user
from config.default import Default
from services import studio_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _caller(request: Request) -> str:
    email = request.scope.get("MESOP_USER_EMAIL") or ""
    if email and email != ANONYMOUS_USER_EMAIL:
        return email
    if require_authenticated_user(Default.APP_ENV):
        raise HTTPException(status_code=403, detail="Forbidden")
    return ANONYMOUS_USER_EMAIL


def _same_site(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("")
async def chat(request: Request) -> dict:
    owner = _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    message = str((body or {}).get("message") or "")
    return await run_in_threadpool(studio_chat.send, owner, message)


@router.post("/upload")
async def upload(request: Request) -> dict:
    """Attach a picture: ``{"data": "data:image/png;base64,...", "name": "..."}``."""
    owner = _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    body = body or {}
    try:
        job = await run_in_threadpool(
            studio_chat.attach, owner, str(body.get("data") or ""), str(body.get("name") or "")
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": job}


@router.get("/options")
def options(request: Request) -> dict:
    """The Home box's type controls: ``{"image": [field, ...], ...}``."""
    _caller(request)
    from services.studio_options import all_fields

    return {"kinds": all_fields()}


@router.post("/job")
async def make_job(request: Request) -> dict:
    """Start a job from the type controls:
    ``{"kind", "prompt", "settings": {...}, "source": "image 2"}``."""
    from services.live_jobs import JobLimitError

    owner = _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    body = body if isinstance(body, dict) else {}
    try:
        return await run_in_threadpool(
            studio_chat.make,
            owner,
            str(body.get("kind") or ""),
            str(body.get("prompt") or ""),
            body.get("settings"),
            str(body.get("source") or ""),
        )
    except JobLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/film")
async def film(request: Request) -> dict:
    """A film's next step: ``{"story_id": "...", "all": false}``."""
    from services.live_jobs import JobLimitError

    owner = _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    body = body if isinstance(body, dict) else {}
    try:
        return await run_in_threadpool(
            studio_chat.film_next, owner, str(body.get("story_id") or ""), bool(body.get("all"))
        )
    except JobLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
def jobs(request: Request) -> dict:
    return {"jobs": studio_chat.chat_jobs(_caller(request))}


@router.post("/load")
async def load(request: Request) -> dict:
    """Reopen a saved chat: ``{"messages": [{role, text}], "job_ids": [...]}``."""
    owner = _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    body = body if isinstance(body, dict) else {}
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    job_ids = body.get("job_ids") if isinstance(body.get("job_ids"), list) else []
    kept = studio_chat.load_history(owner, messages[-200:], job_ids)
    return {"ok": True, "turns": kept}


@router.post("/reset")
def reset(request: Request) -> dict:
    owner = _caller(request)
    _same_site(request)
    studio_chat.reset(owner)
    return {"ok": True}
