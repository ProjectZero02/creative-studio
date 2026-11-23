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
"""Saved Home chats and projects (services/chat_store.py).

Chats:
- ``GET /api/chats`` lists the caller's chats, newest first, without
  messages. ``?project=<id>`` limits to one project; ``?project=`` (empty)
  to chats in no project.
- ``POST /api/chats`` creates one: ``{"id"?, "title"?, "project_id"?,
  "pinned"?, "messages"?, "job_ids"?}``. A page-chosen ``id`` (12 hex
  characters) makes the call safe to repeat: the same chat is updated.
- ``GET /api/chats/{id}`` returns it with messages.
- ``PATCH /api/chats/{id}`` changes ``title``, ``project_id``, ``pinned``,
  ``messages`` or ``job_ids``. A chat with no user-set title gets one from
  its first user message.
- ``DELETE /api/chats/{id}``.

Projects:
- ``GET /api/projects``, ``POST /api/projects`` (``{"name"}``),
  ``PATCH /api/projects/{id}`` (``{"name"}``), ``DELETE /api/projects/{id}``
  (its chats move back to no project).
- ``GET /api/projects/{id}`` returns what the project page shows:
  ``{"project", "chats" (no messages), "media"}``, where media is every
  finished job with a picture, video or sound across its chats.

Everything is per caller (signed-in email); another owner's id is 404.
Writes must come from this site and send JSON (same guards as /api/chat).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from routers.chat_router import _caller, _same_site
from services import chat_store

router = APIRouter(prefix="/api", tags=["chats"])

CHAT_FIELDS = ("title", "project_id", "pinned", "messages", "job_ids")
# Ids a page may choose for a new chat (same shape as chat_store.new_id()).
CLIENT_ID = re.compile(r"[0-9a-f]{12}")


async def _body(request: Request) -> dict:
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Send a JSON object")
    return body


def _save_chat(chat: dict, owner: str, touch: bool = True) -> dict:
    try:
        return chat_store.get_store().save_chat(chat, owner, touch=touch)
    except chat_store.ChatAccessError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _with_title(chat: dict) -> dict:
    """Fill an empty auto title from the first user message (may call Gemini)."""
    if chat.get("title_source") != "user" and not chat.get("title"):
        text = chat_store.first_user_text(
            chat_store.clean_messages(chat.get("messages") or [])
        )
        if text:
            chat["title"] = chat_store.auto_title(text)
            chat["title_source"] = "auto"
    return chat


def _apply(chat: dict, body: dict) -> bool:
    """Copy allowed fields from ``body``; True when the thread changed."""
    changed = False
    for field in CHAT_FIELDS:
        if field not in body:
            continue
        value = body[field]
        if field == "title":
            title = " ".join(str(value or "").split())
            chat["title"] = title
            # An empty title hands naming back to the auto-title.
            chat["title_source"] = "user" if title else "auto"
        elif field == "pinned":
            chat["pinned"] = bool(value)
        elif field == "project_id":
            chat["project_id"] = str(value or "")
        else:
            if not isinstance(value, list):
                raise HTTPException(status_code=400, detail=f"{field} must be a list")
            chat[field] = value
            changed = True
    return changed


# -- chats ---------------------------------------------------------------


@router.get("/chats")
def list_chats(request: Request, project: str | None = None) -> dict:
    owner = _caller(request)
    rows = chat_store.get_store().list_chats(owner, project)
    return {"chats": [chat_store.summary(c) for c in rows]}


@router.post("/chats")
async def create_chat(request: Request) -> dict:
    owner = _caller(request)
    body = await _body(request)
    # The page may pick the id itself, so a repeated create (two saves racing
    # before the first answer, a double click) updates one chat instead of
    # making two.
    wanted = str(body.get("id") or "")
    chat: dict = {"id": wanted if CLIENT_ID.fullmatch(wanted) else chat_store.new_id()}
    if wanted and chat["id"] == wanted:
        chat = chat_store.get_store().get_chat(wanted, owner) or chat
    _apply(chat, body)
    chat = await run_in_threadpool(_with_title, chat)
    return {"chat": await run_in_threadpool(_save_chat, chat, owner)}


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str, request: Request) -> dict:
    owner = _caller(request)
    chat = chat_store.get_store().get_chat(chat_id, owner)
    if not chat:
        raise HTTPException(status_code=404, detail="Not found")
    return {"chat": chat}


@router.patch("/chats/{chat_id}")
async def update_chat(chat_id: str, request: Request) -> dict:
    owner = _caller(request)
    body = await _body(request)
    chat = chat_store.get_store().get_chat(chat_id, owner)
    if not chat:
        raise HTTPException(status_code=404, detail="Not found")
    changed = _apply(chat, body)
    chat = await run_in_threadpool(_with_title, chat)
    # Renaming, pinning or filing a chat keeps its place in Recents.
    return {"chat": await run_in_threadpool(_save_chat, chat, owner, changed)}


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str, request: Request) -> dict:
    owner = _caller(request)
    _same_site(request)
    if not chat_store.get_store().delete_chat(chat_id, owner):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# -- projects ------------------------------------------------------------


def _save_project(project: dict, owner: str) -> dict:
    try:
        return chat_store.get_store().save_project(project, owner)
    except chat_store.ChatAccessError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects")
def list_projects(request: Request) -> dict:
    return {"projects": chat_store.get_store().list_projects(_caller(request))}


@router.post("/projects")
async def create_project(request: Request) -> dict:
    owner = _caller(request)
    body = await _body(request)
    project = {"id": chat_store.new_id(), "name": body.get("name")}
    return {"project": await run_in_threadpool(_save_project, project, owner)}


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request) -> dict:
    owner = _caller(request)
    store = chat_store.get_store()
    project = store.get_project(project_id, owner)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")
    chats = store.list_chats(owner, project_id)
    return {
        "project": project,
        "chats": [chat_store.summary(c) for c in chats],
        "media": chat_store.chat_media(chats),
    }


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request) -> dict:
    owner = _caller(request)
    body = await _body(request)
    project = chat_store.get_store().get_project(project_id, owner)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")
    if "name" in body:
        project["name"] = body.get("name")
    return {"project": await run_in_threadpool(_save_project, project, owner)}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, request: Request) -> dict:
    owner = _caller(request)
    _same_site(request)
    ok = await run_in_threadpool(
        chat_store.get_store().delete_project, project_id, owner
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
