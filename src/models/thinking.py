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

"""Thinking settings each Gemini text model accepts."""

from google.genai import types

# Gemini 4 models (Neon, Argon) take a thinking level, not a token budget:
# `thinking_budget` is a 400 INVALID_ARGUMENT error. They think by default.
_LEVEL_MODELS = ("gemini-4",)


def uses_thinking_level(model: str) -> bool:
    """`model` is set with a thinking level instead of a token budget."""
    return (model or "").strip().lower().startswith(_LEVEL_MODELS)


def dynamic_thinking(model: str) -> types.ThinkingConfig | None:
    """Let `model` think as much as the task needs: a dynamic budget for
    older models, the model's own default thinking for Gemini 4."""
    if uses_thinking_level(model):
        return None
    return types.ThinkingConfig(thinking_budget=-1)
