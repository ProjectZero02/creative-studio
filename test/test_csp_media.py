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
"""The page CSP must let the Live Avatar's MediaSource play.

Chrome loads a MediaSource (from a worker handle or a blob URL) as a blob:
media source. Without blob: in media-src it refuses it ("Media load from
MediaSourceHandle rejected by safety check") and the call falls back to
voice only. main.py is not imported here: it needs a configured project.
"""

import re
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "src" / "main.py"


def _directive(name: str) -> list[str]:
    text = MAIN.read_text(encoding="utf-8")
    m = re.search(rf'"{name} ([^;"]*);', text)
    assert m, f"{name} not found in the CSP"
    return m.group(1).split()


def test_media_src_allows_blob_for_the_live_avatar():
    assert "blob:" in _directive("media-src")


def test_worker_src_allows_blob_for_the_avatar_worker():
    assert "blob:" in _directive("worker-src")
