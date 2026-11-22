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
"""Film versions: remember, relabel, restore."""

from services import story_versions as sv
from services.story_models import Story


def _film(story, uri, timeline):
    story.final_uri = uri
    story.timeline_json = timeline


def test_versions_are_kept_newest_first_and_capped():
    story = Story(id="s", owner="o")
    for n in range(sv.MAX_VERSIONS + 3):
        _film(story, f"gs://b/{n}.mp4", f'{{"n": {n}}}')
        sv.remember(story, "render", now=1000 + n)
    rows = sv.versions(story)
    assert len(rows) == sv.MAX_VERSIONS
    assert rows[0]["uri"] == f"gs://b/{sv.MAX_VERSIONS + 2}.mp4"
    assert rows[0]["label"] == "New film"


def test_remember_does_not_move_a_known_film():
    story = Story(id="s", owner="o")
    _film(story, "gs://b/a.mp4", "A")
    sv.remember(story, "render", now=1)
    _film(story, "gs://b/b.mp4", "B")
    sv.remember(story, "export", now=2)
    _film(story, "gs://b/a.mp4", "A")
    sv.remember(story, "before_fix", now=3)
    assert [r["uri"] for r in sv.versions(story)] == ["gs://b/b.mp4", "gs://b/a.mp4"]
    sv.relabel_latest(story, "gs://b/b.mp4", "After fix: brighter")
    assert sv.versions(story)[0]["label"] == "After fix: brighter"
    sv.relabel_latest(story, "gs://b/a.mp4", "nope")
    assert sv.versions(story)[1]["label"] == "New film"


def test_restore_brings_back_film_and_timeline():
    story = Story(id="s", owner="o")
    _film(story, "gs://b/a.mp4", "A")
    sv.remember(story, "render")
    _film(story, "gs://b/b.mp4", "B")
    story.film_edited = True
    assert sv.restore(story, "gs://b/a.mp4")
    assert (story.final_uri, story.timeline_json, story.film_edited) == ("gs://b/a.mp4", "A", False)
    assert not sv.restore(story, "gs://b/zzz.mp4")


def test_ago():
    assert sv.ago(100, now=130) == "just now"
    assert sv.ago(0, now=600) == "10 min ago"
    assert sv.ago(0, now=7200) == "2 h ago"
    assert sv.ago(0, now=86400) == "1 day ago"


def test_undo_keeps_the_version_list():
    from services.story_fix import _KEEP_ON_UNDO

    assert "film_versions_json" in _KEEP_ON_UNDO
