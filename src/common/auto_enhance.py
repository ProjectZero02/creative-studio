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
"""Improve a prompt with Gemini when it is sent (no Enhance button).

The studios call ``enhance_on_send`` with the prompt they are about to send.
The prompt box keeps what the person typed; only the request gets the richer
prompt. It is skipped when the person turned it off in Settings, when the
prompt is already detailed, in mock mode, and on any error (the run goes on
with the person's own words).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

# Prompts this long are already specific; rewriting them mostly adds drift.
MAX_WORDS = 40


def wanted(prompt: str, enabled: bool = True) -> bool:
    """True when this prompt should be improved before sending."""
    words = len((prompt or "").split())
    return enabled and 0 < words < MAX_WORDS


def setting_on() -> bool:
    """The person's Settings switch ("Improve my prompts"), on by default."""
    try:
        import mesop as me

        from state.state import AppState

        return bool(me.state(AppState).auto_enhance)
    except Exception:  # outside a Mesop request (tests, jobs)
        return True


def enhance_on_send(
    prompt: str,
    instructions: str,
    images: Sequence[tuple[str, str]] | None = None,
    *,
    enabled: bool | None = None,
    rewrite: Callable[..., str] | None = None,
) -> str:
    """The prompt to send: Gemini's richer version, or the original."""
    if not wanted(prompt, setting_on() if enabled is None else enabled):
        return prompt
    from common.mock_generation import mock_enabled

    if rewrite is None:
        if mock_enabled():
            return prompt
        from models.gemini import rewriter as rewrite
    try:
        kwargs = {"images": list(images)} if images else {}
        out = (rewrite(prompt, instructions, **kwargs) or "").strip()
    except Exception:  # pylint: disable=broad-except
        logger.warning("auto_enhance: rewrite failed, sending the original", exc_info=True)
        return prompt
    return out or prompt
