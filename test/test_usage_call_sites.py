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
"""Every billable model call in src/ is tracked for usage.

A call counts as tracked when the function that makes it also opens
``track_model_call`` (or logs with ``log_model_call`` / ``_record_usage``).
"""

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
CALL = re.compile(
    r"\.(generate_content|generate_videos|recontext_image|predict|"
    r"synthesize_speech|connect|create)\("
)
TRACKERS = ("track_model_call", "log_model_call", "_record_usage")

# (file, function) pairs whose calls are not separate model calls: wrappers
# around a tracked call, or helpers whose caller opens track_model_call.
NOT_MODEL_CALLS = {
    ("models/voice.py", "synthesize_voice"),  # wraps gemini_tts
    # gemini_tts.synthesize_speech tracks both of these.
    ("models/gemini_tts.py", "_synthesize_cloud_tts"),
    ("models/gemini_tts.py", "_synthesize_generate_content"),
}


def _attr_chain(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_model_call(call: ast.Call) -> str | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    chain = _attr_chain(call.func)
    name = call.func.attr
    if name in ("generate_content", "generate_videos", "recontext_image"):
        return name
    if name == "create" and chain.endswith("interactions.create"):
        return name
    if name == "connect" and chain.endswith("live.connect"):
        return name
    if name == "predict" and "client" in chain.lower():
        return name
    if name == "synthesize_speech" and chain != "synthesize_speech":
        return name
    return None


def untracked_calls() -> list[str]:
    out = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(("test", "scripts")):
            continue
        text = path.read_text(encoding="utf-8")
        if not CALL.search(text):
            continue
        tree = ast.parse(text)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(text, func) or ""
            tracked = any(t in body for t in TRACKERS)
            for node in ast.walk(func):
                if isinstance(node, ast.Call) and (kind := _is_model_call(node)):
                    if (rel, func.name) in NOT_MODEL_CALLS or tracked:
                        continue
                    out.append(f"{rel}:{node.lineno} {kind} in {func.name}")
    return sorted(set(out))


def test_every_model_call_is_tracked():
    assert untracked_calls() == []
