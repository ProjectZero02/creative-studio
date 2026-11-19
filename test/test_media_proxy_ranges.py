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
"""The media proxy answers byte ranges, so video players can seek.

Without ranges a <video> served by /media cannot jump inside a clip: the Story
Studio editor preview then plays each clip from its start whatever the
playhead says.
"""

import io
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("PROJECT_ID", "test-project")
os.environ.setdefault("LOCATION", "us-central1")

for _mod in ("parselmouth", "parselmouth.praat"):
    if _mod not in sys.modules:
        try:  # pragma: no cover - import side effect
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = MagicMock()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

BUCKET = "legit-app-bucket"
DATA = bytes(range(256)) * 4  # 1024 bytes


@pytest.fixture
def client(monkeypatch):
    blob = MagicMock()
    blob.exists.return_value = True
    blob.content_type = "video/mp4"
    blob.size = len(DATA)
    blob.open.side_effect = lambda *_: io.BytesIO(DATA)
    blob.download_as_bytes.side_effect = lambda start, end: DATA[start : end + 1]
    bucket = MagicMock()
    bucket.blob.return_value = blob
    gcs = MagicMock()
    gcs.bucket.return_value = bucket
    monkeypatch.setattr(main, "get_proxy_storage_client", lambda: gcs)
    monkeypatch.setattr(main.config.Default, "GENMEDIA_BUCKET", BUCKET)
    return TestClient(main.app)


def test_whole_file_says_it_accepts_ranges(client):
    resp = client.get(f"/media/{BUCKET}/videos/a.mp4")
    assert resp.status_code == 200
    assert resp.content == DATA
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-length"] == str(len(DATA))


def test_a_range_returns_206_with_just_those_bytes(client):
    resp = client.get(
        f"/media/{BUCKET}/videos/a.mp4", headers={"Range": "bytes=100-199"}
    )
    assert resp.status_code == 206
    assert resp.content == DATA[100:200]
    assert resp.headers["content-range"] == f"bytes 100-199/{len(DATA)}"


def test_open_ended_and_suffix_ranges(client):
    tail = client.get(f"/media/{BUCKET}/videos/a.mp4", headers={"Range": "bytes=1000-"})
    assert tail.status_code == 206 and tail.content == DATA[1000:]
    last = client.get(f"/media/{BUCKET}/videos/a.mp4", headers={"Range": "bytes=-24"})
    assert last.status_code == 206 and last.content == DATA[-24:]


def test_a_range_past_the_end_is_416(client):
    resp = client.get(f"/media/{BUCKET}/videos/a.mp4", headers={"Range": "bytes=5000-"})
    assert resp.status_code == 416
    assert resp.headers["content-range"] == f"bytes */{len(DATA)}"


def test_parse_byte_range_cuts_long_ranges_to_a_chunk():
    size = main.MEDIA_RANGE_CHUNK * 3
    assert main.parse_byte_range("bytes=0-", size) == (0, main.MEDIA_RANGE_CHUNK - 1)
    assert main.parse_byte_range(None, size) is None
    assert main.parse_byte_range("bytes=abc", size) is None
    assert main.parse_byte_range("items=0-1", size) is None


def test_ranges_stream_in_pieces(client, monkeypatch):
    monkeypatch.setattr(main, "MEDIA_STREAM_PIECE", 100)
    resp = client.get(
        f"/media/{BUCKET}/videos/a.mp4", headers={"Range": "bytes=10-509"}
    )
    assert resp.status_code == 206
    assert resp.content == DATA[10:510]
    assert resp.headers["content-length"] == "500"
    whole = client.get(f"/media/{BUCKET}/videos/a.mp4")
    assert whole.content == DATA
