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
"""Every web component define must be guarded.

Mesop loads component modules as ``x.js?v=<hash>``, while a component that
imports another by a relative path loads it with no tag. The browser then runs
the file twice. An unguarded ``customElements.define`` throws on the second
run, and Mesop drops the whole render (the Library stuck on "Loading...").
"""

import re
from collections.abc import Iterator
from pathlib import Path

# conftest.py chdirs into src/.
FOLDERS = ("components", "workflows", "pages")
DEFINE = re.compile(r"customElements\.define\(\s*(['\"])([a-z0-9-]+)\1")


def _js_files() -> Iterator[Path]:
    for folder in FOLDERS:
        for path in Path(folder).rglob("*.js"):
            if "vendor" not in path.parts:
                yield path


def test_every_define_is_guarded() -> None:
    """Each define has a matching customElements.get guard in its file."""
    unguarded = []
    for path in _js_files():
        text = path.read_text(encoding="utf-8")
        for match in DEFINE.finditer(text):
            tag = match.group(2)
            guard = re.compile(
                rf"customElements\.get\(\s*(['\"]){re.escape(tag)}\1\s*\)"
            )
            if not guard.search(text):
                unguarded.append(f"{path}: {tag}")
    assert not unguarded, (
        "Wrap these in `if (!customElements.get(tag))`:\n" + "\n".join(unguarded)
    )


def test_finds_the_components() -> None:
    """The scan sees the components, so the guard test is not vacuous."""
    tags = set()
    for path in _js_files():
        tags.update(
            m.group(2) for m in DEFINE.finditer(path.read_text(encoding="utf-8"))
        )
    assert {"svg-icon", "media-tile", "scroll-sentinel"} <= tags
