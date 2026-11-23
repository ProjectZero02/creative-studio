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
"""Unknown paths show the studio's "Page not found" page.

Mesop answers an unregistered path with a developer error that lists every
route. This swaps in the page registered at NOT_FOUND_PATH instead, for both
full page loads and in-app navigation, and keeps the URL the person typed.
"""

from __future__ import annotations

NOT_FOUND_PATH = "/not-found"


def is_page_path(path: str) -> bool:
    """True for paths that name a page (not a file or a Mesop internal)."""
    if not path or not path.startswith("/") or path.startswith("/__"):
        return False
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in last


def install() -> None:
    """Patch Mesop's runtime so unknown page paths render NOT_FOUND_PATH."""
    from mesop.runtime.runtime import Runtime

    if getattr(Runtime, "_gm_not_found", False):
        return
    original_get = Runtime.get_page_config
    original_run = Runtime.run_path

    def _missing(runtime, path: str) -> bool:
        pages = runtime._path_to_page_config  # noqa: SLF001
        return path not in pages and NOT_FOUND_PATH in pages and is_page_path(path)

    def get_page_config(self, *, path: str):
        if _missing(self, path):
            path = NOT_FOUND_PATH
        return original_get(self, path=path)

    def run_path(self, path: str) -> None:
        if _missing(self, path):
            path = NOT_FOUND_PATH
        return original_run(self, path=path)

    Runtime.get_page_config = get_page_config
    Runtime.run_path = run_path
    Runtime._gm_not_found = True  # noqa: SLF001
