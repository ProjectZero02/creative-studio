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
"""Story Studio editor: edits survive echoes and re-renders (audit fixes 1-3, 6)."""

import json

from services import story_timeline as T


def _tl(scenes=4, length=6.0):
    tl = T.empty_timeline()
    T.track(tl, "video")["clips"] = [
        {
            "id": f"v{i}",
            "src": f"c{i}",
            "in": 0,
            "out": length,
            "src_max": length,
            "gain": 1.0,
            "level": 1.0,
            "scene": i,
            "label": f"Scene {i + 1}",
        }
        for i in range(scenes)
    ]
    T.track(tl, "voice")["clips"] = [
        {
            "id": f"a{i}",
            "src": f"n{i}",
            "start": i * length + 0.5,
            "in": 0,
            "out": 3,
            "scene": i,
        }
        for i in range(scenes)
    ]
    T.track(tl, "music")["clips"] = [
        {
            "id": "m",
            "src": "m",
            "start": 0,
            "in": 0,
            "out": scenes * length,
            "gain": 0.8,
        }
    ]
    return T.normalize(tl)


def _edit(tl, fn):
    """Apply an edit the way the editor does: change, lay out, follow."""
    before = json.loads(json.dumps(tl))
    cur = json.loads(json.dumps(tl))
    fn(cur)
    T._layout_video(T.track(cur, "video")["clips"])
    return T.normalize(T.follow_scenes(before, cur))


def _split(tl, scene, at):
    v = T.track(tl, "video")["clips"]
    k = next(i for i, c in enumerate(v) if c["scene"] == scene)
    a = v[k]
    b = dict(a, id=a["id"] + "b", **{"in": a["in"] + at})
    a["out"] = a["in"] + at
    v.insert(k + 1, b)


def _delete_scene(tl, scene):
    v = T.track(tl, "video")["clips"]
    for c in [c for c in v if c["scene"] == scene]:
        tl.setdefault("removed", []).append({"scene": scene, "src": c["src"]})
    v[:] = [c for c in v if c["scene"] != scene]


def test_rev_is_kept_only_when_asked():
    tl = dict(_tl(), rev="ab12:7")
    assert T.normalize(tl, keep_rev=True)["rev"] == "ab12:7"
    assert "rev" not in T.normalize(tl)


def test_removed_list_is_validated():
    tl = dict(
        _tl(), removed=[{"scene": 2, "src": "c2"}, {"scene": 2, "src": "c2"}, {"x": 1}]
    )
    assert T.normalize(tl)["removed"] == [{"scene": 2, "src": "c2"}]


def test_ai_fix_of_one_scene_keeps_splits_deletes_gains_voice_and_music():
    old = _tl()
    old = _edit(old, lambda t: _split(t, 1, 2.0))  # scene 2 split at 2 s
    old = _edit(old, lambda t: _delete_scene(t, 2))  # scene 3 deleted
    old = _edit(old, lambda t: T.track(t, "video")["clips"][-1].update(gain=0.5))
    old = _edit(old, lambda t: T.track(t, "voice")["clips"][0].update(gain=0.4))
    old = _edit(
        old, lambda t: T.track(t, "music")["clips"][0].update(gain=0.3, out=12.0)
    )
    # A fresh render after an AI fix that remade scene 1's clip only.
    new = _tl()
    T.track(new, "video")["clips"][0]["src"] = "c0-fixed"
    out = T.keep_edits(new, json.dumps(old))
    vids = T.track(out, "video")["clips"]
    assert [c["scene"] for c in vids] == [0, 1, 1, 3]  # split kept, 3 still gone
    assert vids[0]["src"] == "c0-fixed"
    assert (vids[1]["out"], vids[2]["in"]) == (2.0, 2.0)
    assert vids[3]["gain"] == 0.5
    voice = {c["scene"]: c for c in T.track(out, "voice")["clips"]}
    assert set(voice) == {0, 1, 3}
    assert voice[0]["gain"] == 1.0  # scene 1 was remade: its line starts fresh
    music = T.track(out, "music")["clips"][0]
    assert music["gain"] == 0.3 and music["out"] == 12.0
    assert out["removed"] == [{"scene": 2, "src": "c2"}]


def test_kept_voice_level_survives_when_its_scene_is_unchanged():
    old = _edit(_tl(), lambda t: T.track(t, "voice")["clips"][2].update(gain=0.25))
    new = _tl()
    T.track(new, "video")["clips"][0]["src"] = "c0-fixed"
    out = T.keep_edits(new, json.dumps(old))
    assert {c["scene"]: c["gain"] for c in T.track(out, "voice")["clips"]}[2] == 0.25


def test_a_remade_deleted_scene_comes_back():
    old = _edit(_tl(), lambda t: _delete_scene(t, 2))
    new = _tl()
    T.track(new, "video")["clips"][2]["src"] = "c2-new"
    out = T.keep_edits(new, json.dumps(old))
    assert [c["scene"] for c in T.track(out, "video")["clips"]] == [0, 1, 2, 3]
    assert "removed" not in out


def test_new_music_file_keeps_only_the_level():
    old = _edit(
        _tl(), lambda t: T.track(t, "music")["clips"][0].update(gain=0.2, out=10.0)
    )
    new = _tl()
    T.track(new, "music")["clips"][0]["src"] = "m2"
    out = T.keep_edits(new, json.dumps(old))
    music = T.track(out, "music")["clips"][0]
    assert music["src"] == "m2" and music["gain"] == 0.2 and music["out"] == 24.0


def test_deleting_half_a_split_scene_never_overlaps_two_voices():
    # Audit bug 6: split scene 3 at 0.8 s, delete the second half.
    tl = _tl()
    tl = _edit(tl, lambda t: _split(t, 2, 0.8))
    v = T.track(tl, "video")["clips"]
    half = next(c for c in v if c["scene"] == 2 and c["in"] > 0)
    tl = _edit(
        tl,
        lambda t: T.track(t, "video")["clips"].remove(
            next(c for c in T.track(t, "video")["clips"] if c["id"] == half["id"])
        ),
    )
    lines = sorted(T.track(tl, "voice")["clips"], key=lambda c: c["start"])
    for a, b in zip(lines, lines[1:], strict=False):
        assert T.clip_end(a) <= b["start"] + 1e-6


def test_no_overlap_trims_or_drops():
    lines = [
        {"src": "a", "start": 0.0, "in": 0, "out": 5, "tempo": 1.0},
        {"src": "b", "start": 3.0, "in": 0, "out": 2, "tempo": 1.0},
        {"src": "c", "start": 3.2, "in": 0, "out": 2, "tempo": 1.0},
    ]
    out = T.no_overlap(lines)
    assert [c["src"] for c in out] == ["a", "c"]  # b had no room left
    assert out[0]["out"] == 3.15


def test_build_level_is_the_clip_gain():
    tl = _tl()
    assert all(c["level"] == 1.0 for c in T.track(tl, "video")["clips"])
