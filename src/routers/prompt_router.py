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
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from common import prompt_history
from common.identity import ANONYMOUS_USER_EMAIL, require_authenticated_user
from config.default import Default

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


def _caller(request: Request) -> str:
    email = request.scope.get("MESOP_USER_EMAIL") or ""
    if email and email != ANONYMOUS_USER_EMAIL:
        return email
    if require_authenticated_user(Default.APP_ENV):
        raise HTTPException(status_code=403, detail="Forbidden")
    return ANONYMOUS_USER_EMAIL


@router.get("/{page}")
def recent_prompts(page: str, request: Request) -> dict:
    owner = _caller(request)
    if page not in prompt_history.STUDIOS:
        raise HTTPException(status_code=404, detail="Unknown studio")
    from common.mock_generation import mock_enabled

    if mock_enabled():
        return {"prompts": []}
    return {"prompts": prompt_history.recent(owner, page)}
