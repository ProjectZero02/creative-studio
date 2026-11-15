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
"""Prefill a studio's main prompt from an optional ``?prompt=`` URL parameter.

The home page sends people to a studio with their idea already typed in. Each
studio's ``on_load`` calls :func:`prefill_prompt`, which fills the field once per
arrival and only while it is empty, so a user's own edits are never replaced.
Nothing is generated automatically.
"""

from collections.abc import Iterable, Mapping

import mesop as me

MAX_PROMPT_PREFILL_CHARS = 2000
PREFILL_SEEN_FIELD = "prompt_prefill_seen"


def read_prompt_param(params: Mapping[str, str] | None = None) -> str:
    """Return the ``prompt`` query parameter, trimmed and capped, or ``""``."""
    if params is None:
        params = me.query_params
    raw = params.get("prompt", "")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    text = str(raw or "").replace("\x00", "").strip()
    return text[:MAX_PROMPT_PREFILL_CHARS].strip()


def is_new_prompt_arrival(state: object, prompt: str) -> bool:
    """Report whether ``prompt`` is new for ``state``, and remember it."""
    if not prompt or getattr(state, PREFILL_SEEN_FIELD, "") == prompt:
        return False
    setattr(state, PREFILL_SEEN_FIELD, prompt)
    return True


def prefill_prompt(
    state: object,
    field: str,
    *,
    empty_values: Iterable[str] = (),
    params: Mapping[str, str] | None = None,
) -> bool:
    """Copy ``?prompt=`` into ``state.<field>`` once, if the field is empty.

    ``empty_values`` lists placeholder defaults (for example a sample script)
    that count as empty. Returns True when the field was filled.
    """
    prompt = read_prompt_param(params)
    if not is_new_prompt_arrival(state, prompt):
        return False
    current = (getattr(state, field, "") or "").strip()
    if current and current not in {v.strip() for v in empty_values}:
        return False
    setattr(state, field, prompt)
    return True
