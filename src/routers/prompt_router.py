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
"""Your recent prompts in one studio, for the Up/Down keys in the prompt box.

``GET /api/prompts/{page}`` returns ``{"prompts": [...]}``, newest first, read
from the caller's own Library items (common/prompt_history.py). Signed-out
callers on a deployed app get 403; locally they get the anonymous user's.

``POST /api/prompts/enhance`` returns Gemini's richer version of a prompt, for
the Enhance button in the Home box.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from common import prompt_history
from common.identity import ANONYMOUS_USER_EMAIL, require_authenticated_user
from config.default import Default

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

MAX_ENHANCE_CHARS = 2000

# What Enhance asks Gemini for, per kind. Home with no kind picked gets a
# general rewrite that keeps the request's meaning and language.
_GENERAL_REWRITER = (
    "Rewrite this request to a creative AI studio so it is clearer and more "
    "vivid: add concrete detail (subject, setting, style, light, mood) without "
    "changing what is asked for. Keep it under 60 words, in the same language. "
    "Reply with the rewritten request only."
)


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


def _rewriter_for(kind: str) -> str:
    from config import rewriters

    return {
        "image": rewriters.REWRITER_PROMPT,
        "video": rewriters.VIDEO_REWRITER,
        "music": rewriters.MUSIC_REWRITER,
        "voice": rewriters.SPEECH_REWRITER,
    }.get(kind, _GENERAL_REWRITER)


def enhance_text(prompt: str, kind: str = "") -> str:
    """Gemini's richer version of ``prompt`` (the original on any failure)."""
    prompt = (prompt or "").strip()[:MAX_ENHANCE_CHARS]
    if not prompt:
        return ""
    from common.mock_generation import mock_enabled

    if mock_enabled():
        return f"{prompt}, rich detail, soft natural light, cinematic framing"
    from models.gemini import rewriter

    try:
        return (rewriter(prompt, _rewriter_for(kind)) or "").strip() or prompt
    except Exception:  # pylint: disable=broad-except
        logger.warning("enhance: rewrite failed, keeping the original", exc_info=True)
        return prompt


@router.post("/enhance")
async def enhance(request: Request) -> dict:
    """``{"prompt": "...", "kind": "image|video|music|voice|film|"}`` -> ``{"prompt"}``."""
    _caller(request)
    _same_site(request)
    if "application/json" not in (request.headers.get("content-type") or ""):
        raise HTTPException(status_code=415, detail="Send JSON")
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc
    body = body or {}
    text = await run_in_threadpool(
        enhance_text, str(body.get("prompt") or ""), str(body.get("kind") or "")
    )
    return {"prompt": text}


@router.get("/{page}")
def recent_prompts(page: str, request: Request) -> dict:
    owner = _caller(request)
    if page not in prompt_history.STUDIOS:
        raise HTTPException(status_code=404, detail="Unknown studio")
    from common.mock_generation import mock_enabled

    if mock_enabled():
        return {"prompts": []}
    return {"prompts": prompt_history.recent(owner, page)}
