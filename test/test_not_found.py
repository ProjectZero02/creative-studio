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
"""Unknown paths render the Page not found page, not Mesop's route list."""

from mesop.runtime.runtime import Runtime

from common import not_found


class _Config:
    def __init__(self, name):
        self.name = name
        self.page_fn = lambda: ran.append(name)


ran: list[str] = []


def _runtime(pages):
    rt = Runtime.__new__(Runtime)
    rt._path_to_page_config = {p: _Config(p) for p in pages}
    rt.is_hot_reload_in_progress = False
    return rt


def test_is_page_path():
    assert not_found.is_page_path("/story-studio")
    assert not_found.is_page_path("/a/b/")
    assert not not_found.is_page_path("/prod_bundle.js")
    assert not not_found.is_page_path("/__ui__")
    assert not not_found.is_page_path("")


def test_unknown_page_uses_not_found():
    not_found.install()
    rt = _runtime(["/home", not_found.NOT_FOUND_PATH])
    ran.clear()
    rt.run_path(path="/story-studio")
    assert ran == [not_found.NOT_FOUND_PATH]
    assert rt.get_page_config(path="/nope").name == not_found.NOT_FOUND_PATH


def test_known_pages_and_files_are_untouched():
    not_found.install()
    rt = _runtime(["/home", not_found.NOT_FOUND_PATH])
    ran.clear()
    rt.run_path(path="/home")
    assert ran == ["/home"]
    assert rt.get_page_config(path="/prod_bundle.js") is None


def test_install_is_idempotent():
    not_found.install()
    patched = Runtime.run_path
    not_found.install()
    assert Runtime.run_path is patched
