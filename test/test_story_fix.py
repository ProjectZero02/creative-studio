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
"""Story Studio AI fix: Gemini's plan JSON -> checked plan -> existing jobs."""

import json

import pytest

from services import story_fix, story_jobs, story_service, story_store
from services import story_timeline as tlm
from services.story_fix import (
    FixChange,
    FixPlan,
    apply_timeline_ops,
    parse_fix_plan,
    plan_steps,
)
from services.story_models import ScenarioError, Scene, Story

OWNER = "alice@example.com"


def _timeline(lengths=(4.0, 4.0, 4.0)) -> dict:
    tl = tlm.empty_timeline()
    video = tlm.track(tl, "video")["clips"]
    for i, n in enumerate(lengths):
        video.append(
            {"id": f"c{i}", "src": f"local://clip{i}.mp4", "in": 0, "out": n, "scene": i}
        )
    tlm.track(tl, "voice")["clips"].append(
        {"id": "v2", "src": "local://v2.wav", "start": 8.5, "in": 0, "out": 2, "scene": 2}
    )
    total = sum(lengths)
    tlm.track(tl, "music")["clips"].append(
        {"id": "m", "src": "local://m.wav", "start": 0, "in": 0, "out": total}
    )
    return tlm.normalize(tl)


def _story(**kw) -> Story:
    scenes = [
        Scene(
            narration=f"Line {i}.",
            visual=f"Visual {i}",
            camera="static",
            duration=4,
            frame_uri=f"local://f{i}.png",
            clip_uri=f"local://clip{i}.mp4",
        )
        for i in range(3)
    ]
    base = dict(
        title="Fox",
        approved=True,
        scenes=scenes,
        final_uri="local://film.mp4",
        timeline_json=json.dumps(_timeline()),
    )
    base.update(kw)
    return Story(**base)


def _one(**kw) -> FixPlan:
    """A plan with one change."""
    return FixPlan(summary="Fix", changes=[FixChange(**kw)])


# ---------------------------------------------------------------------------
# Parsing Gemini's JSON
# ---------------------------------------------------------------------------


def test_parse_timeline_trim_maps_scene_numbers_and_clamps():
    plan = parse_fix_plan(
        "```json\n"
        + json.dumps(
            {
                "action": "timeline",
                "summary": "Cut the blank end of scene 3.",
                "timeline": [
                    {"op": "trim", "scene": 3, "cut_start": -2, "cut_end": 99},
                    {"op": "trim", "scene": 9, "cut_end": 1},  # no scene 9
                    {"op": "explode", "scene": 1},
                ],
            }
        )
        + "\n```",
        _story(),
    )
    (change,) = plan.changes
    assert change.action == "timeline"
    assert change.timeline == [
        {"op": "trim", "scene": 2, "cut_start": 0.0, "cut_end": story_fix.TRIM_MAX_CUT}
    ]


def test_parse_rewrite_keeps_only_changed_fields():
    story = _story()
    plan = parse_fix_plan(
        json.dumps(
            {
                "action": "rewrite_scene",
                "scene": 2,
                "narration": "A new line.",
                "visual": "Visual 1",  # unchanged
                "camera": "dolly in",
            }
        ),
        story,
    )
    (change,) = plan.changes
    assert change.scene == 1
    assert change.narration == "A new line."
    assert change.visual is None
    assert change.camera == "dolly_in"


def test_parse_empty_or_unknown_plans_become_questions():
    story = _story()
    for raw in (
        {"action": "rewrite_scene", "scene": 2},  # nothing to change
        {"action": "repaint_frame"},  # no scene
        {"action": "timeline", "timeline": []},
        {"action": "music"},
        {"action": "launch_rocket"},
        {"action": "none", "question": "Which scene?"},
    ):
        plan = parse_fix_plan(json.dumps(raw), story)
        assert not plan.runnable and plan.question, raw
        assert plan_steps(story, plan) == []


def test_parse_timeline_without_a_rendered_film_asks():
    plan = parse_fix_plan(
        json.dumps({"action": "timeline", "timeline": [{"op": "remove", "scene": 1}]}),
        _story(timeline_json=""),
    )
    assert not plan.runnable and "Render" in plan.question


def test_parse_rejects_bad_json():
    with pytest.raises(ScenarioError):
        parse_fix_plan("not json", _story())


# ---------------------------------------------------------------------------
# Preview: what runs and what costs money
# ---------------------------------------------------------------------------


def test_timeline_plan_is_free():
    story = _story()
    plan = _one(
        action="timeline",
        timeline=[{"op": "trim", "scene": 2, "cut_start": 0, "cut_end": 1.0}],
    )
    steps = plan_steps(story, plan)
    assert "Trim scene 3: 1 s off the end" in steps[0].label
    assert not story_fix.costs_money(story, plan)


def test_narrated_line_change_keeps_the_clip():
    story = _story(voice_on=True)
    plan = _one(action="rewrite_scene", scene=1, narration="New words.")
    labels = [s.label for s in plan_steps(story, plan)]
    assert not any("video clip" in label for label in labels)
    assert any("voiceover" in label for label in labels)
    assert story_fix.costs_money(story, plan)


def test_repaint_includes_the_rest_of_a_continuous_take():
    story = _story()
    for sc in story.scenes:
        sc.spoken = True
    assert story.continues_take(1) and story.continues_take(2)
    plan = _one(action="repaint_frame", scene=0, visual="Brighter room.")
    assert story_fix.effects(story, plan).frames == [0, 1, 2]
    labels = [s.label for s in plan_steps(story, plan)]
    assert any("frame of scenes 1, 2, 3" in label for label in labels)
    assert any("clip of scenes 1, 2, 3" in label for label in labels)


# ---------------------------------------------------------------------------
# Timeline ops (pure)
# ---------------------------------------------------------------------------


def test_trim_end_moves_nothing_before_and_keeps_a_minimum():
    tl = apply_timeline_ops(
        _timeline(), [{"op": "trim", "scene": 2, "cut_start": 0, "cut_end": 1.5}]
    )
    video = tlm.track(tl, "video")["clips"]
    assert video[2]["out"] == 2.5
    assert tlm.duration(tl) == pytest.approx(10.5)
    # Full-length music follows the new end.
    assert tlm.clip_end(tlm.track(tl, "music")["clips"][0]) == pytest.approx(10.5)
    tl = apply_timeline_ops(
        _timeline(), [{"op": "trim", "scene": 0, "cut_start": 10, "cut_end": 0}]
    )
    first = tlm.track(tl, "video")["clips"][0]
    assert first["out"] - first["in"] == pytest.approx(story_fix.TRIM_MIN_KEEP)


def test_remove_and_move_scenes_carry_voice_lines():
    tl = apply_timeline_ops(_timeline(), [{"op": "remove", "scene": 1}])
    assert [c["scene"] for c in tlm.track(tl, "video")["clips"]] == [0, 2]
    # Scene 3's line moved 4 s earlier with its clip.
    assert tlm.track(tl, "voice")["clips"][0]["start"] == pytest.approx(4.5)

    tl = apply_timeline_ops(_timeline(), [{"op": "move", "scene": 2, "to": 0}])
    assert [c["scene"] for c in tlm.track(tl, "video")["clips"]] == [2, 0, 1]
    assert tlm.track(tl, "voice")["clips"][0]["start"] == pytest.approx(0.5)


def test_remove_last_scene_is_refused():
    one = _timeline((4.0,))
    with pytest.raises(ValueError):
        apply_timeline_ops(one, [{"op": "remove", "scene": 0}])


def test_scene_at_maps_film_time_to_scene():
    tl = _timeline()
    assert story_fix.scene_at(tl, 0.0) == 0
    assert story_fix.scene_at(tl, 9.0) == 2
    assert story_fix.scene_at(tl, 99.0) == 2


def test_prompt_names_the_pointed_time_and_scene():
    story = _story()
    text = story_fix.fix_prompt(story, "the slide goes blank", -1, 11.5)
    assert "11.5 s of the film, which is in scene 3" in text
    assert "0.5 s before it ends" in text
    assert "Visual 2" in text and "Line 2." in text
    assert "the slide goes blank" in text


# ---------------------------------------------------------------------------
# Running with the mock backend
# ---------------------------------------------------------------------------


class _FastMock(story_service.MockStoryBackend):
    def __init__(self):
        super().__init__(speed=0)
        self.frames, self.clips, self.renders, self.music = [], [], [], []

    def generate_frame(self, story, index, reference_uri):
        self.frames.append(index)
        return f"local://{story.id}/frame{index}-{len(self.frames)}.png"

    def generate_clip(self, story, index, start_frame_uri):
        self.clips.append(index)
        return f"local://{story.id}/clip{index}-{len(self.clips)}.mp4"

    def last_frame(self, story, clip_uri, index):
        return f"local://{story.id}/last{index}.png"

    def generate_music(self, story, prompt, seconds):
        self.music.append(prompt)
        return "local://m2.wav"

    def generate_voiceover(self, story, index, text, style="narrator"):
        return f"local://v{index}.wav"

    def stitch(self, story, plan, music_uri, voice_uris):
        return "local://film2.mp4", _timeline()

    def render_timeline(self, story, timeline, **opts):
        self.renders.append(timeline)
        return "local://export.mp4"

    def save_to_library(self, story, final_uri, owner):
        return ""


@pytest.fixture
def backend(tmp_path):
    story_store.set_store(story_store.LocalStoryStore(str(tmp_path / "s.json")))
    b = _FastMock()
    story_service.set_backend(b)
    yield b
    story_service.set_backend(None)
    story_store.set_store(None)


def _saved(**kw) -> Story:
    return story_store.get_store().save(_story(**kw), OWNER)


def _run(job):
    done = story_jobs.wait(job.id, OWNER, timeout=20)
    assert done is not None and done.status != "running"
    return done


def test_mock_planner_end_of_scene_is_a_free_trim(backend):
    s = _saved()
    plan = story_fix.plan_fix(
        s.id, OWNER, "I don't like the end of scene 3, the slide goes blank"
    )
    (change,) = plan.changes
    assert change.action == "timeline"
    assert change.timeline == [{"op": "trim", "scene": 2, "cut_start": 0.0, "cut_end": 1.0}]
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert backend.clips == [] and backend.frames == []  # nothing paid
    after = story_store.get_store().get(s.id, OWNER)
    assert tlm.duration(tlm.normalize(after.timeline_json)) == pytest.approx(11.0)
    assert after.final_uri == "local://export.mp4" and not after.film_edited


def test_mock_planner_uses_the_pointed_time(backend):
    s = _saved()
    plan = story_fix.plan_fix(s.id, OWNER, "it goes black here", seconds=5.0)
    assert plan.changes[0].timeline[0]["scene"] == 1


def test_repaint_fix_paints_then_renders_only_that_scene(backend):
    s = _saved()
    plan = _one(action="repaint_frame", scene=1, visual="Visual 1, at dusk.")
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert backend.frames == [1]
    assert backend.clips == [1]
    kinds = [t.kind for t in job.tasks]
    assert kinds[0] == "fix" and "frame" in kinds and "clip" in kinds and "stitch" in kinds
    after = story_store.get_store().get(s.id, OWNER)
    assert after.scenes[1].visual == "Visual 1, at dusk."
    assert after.final_uri == "local://film2.mp4"


def test_rewrite_fix_re_renders_the_clip_without_a_new_frame(backend):
    s = _saved()
    plan = _one(action="rewrite_scene", scene=2, camera="orbit")
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert backend.frames == [] and backend.clips == [2]
    assert story_store.get_store().get(s.id, OWNER).scenes[2].camera == "orbit"


def test_music_fix_makes_music_and_exports(backend):
    s = _saved()
    plan = _one(action="music", music_prompt="Quiet piano.")
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "done", [(t.label, t.error) for t in job.tasks]
    assert backend.music == ["Quiet piano."]
    after = story_store.get_store().get(s.id, OWNER)
    assert after.music_uri == "local://m2.wav"
    music = tlm.track(tlm.normalize(after.timeline_json), "music")["clips"]
    assert music[0]["src"] == "local://m2.wav"
    assert len(backend.renders) == 1


def test_a_failed_step_fails_the_fix_and_retry_resumes(backend):
    s = _saved()
    calls = {"n": 0}
    real = backend.generate_frame

    def flaky(story, index, ref):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(story, index, ref)

    backend.generate_frame = flaky
    plan = _one(action="repaint_frame", scene=0, visual="New look.")
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "failed"
    assert backend.clips == []  # the render never started
    again = _run(story_jobs.retry(job.id, OWNER))
    assert again.status == "done", [(t.label, t.error) for t in again.tasks]
    assert backend.clips == [0]


def test_question_plans_do_not_run(backend):
    s = _saved()
    with pytest.raises(ScenarioError):
        story_fix.start_fix(s.id, OWNER, FixPlan(question="Which?"))


# ---------------------------------------------------------------------------
# Edit step handlers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("12.5", 12.5), ("12 s", 12.0), ("0:12", 12.0), ("1:05.5", 65.5), ("", None),
     ("soon", None), ("-3", None)],
)
def test_parse_film_time(text, seconds):
    import pages.story_studio as page

    assert page.parse_film_time(text) == seconds


def test_plan_then_apply_from_the_edit_step(backend, monkeypatch):
    import pages.story_studio as page
    from state.story_state import StoryState

    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    monkeypatch.setattr(page, "_owner", lambda: OWNER)
    s = _saved()
    st.story_id = s.id
    st.fix_request = "The end goes blank here"
    st.fix_time = "11"
    list(page.on_plan_fix(None))
    assert not st.fix_planning and not st.error
    plan = page._fix_plan()
    assert plan.changes[0].action == "timeline"
    assert plan.changes[0].timeline[0]["scene"] == 2
    # Nothing changes before the user confirms.
    assert story_store.get_store().get(s.id, OWNER).timeline_json == s.timeline_json
    page.on_apply_fix(None)
    assert st.fix_plan_json == "" and st.job_kind == "fix"
    job = _run(story_jobs.get_job(st.job_id, OWNER))
    assert job.status == "done"


def test_the_planner_watches_the_film_and_the_frames(monkeypatch):
    story = _story(final_uri="gs://b/film.mp4")
    assert story_fix.fix_media(story) == [
        "gs://b/film.mp4",
        "local://f0.png",
        "local://f1.png",
        "local://f2.png",
    ]
    assert "rendered film is attached first" in story_fix.fix_prompt(story, "too dark")
    seen = {}

    def fake(self, prompt, temperature=0.8, task="", model="", media=None, **kw):
        seen.update(task=task, media=media)
        return "{}"

    monkeypatch.setattr(story_service.VertexStoryBackend, "_json_text", fake)
    story_service.VertexStoryBackend().plan_fix(story, "too dark", -1, None)
    assert seen == {"task": "story_fix", "media": story_fix.fix_media(story)}
    assert story_service._media_mime("gs://b/film.mp4") == "video/mp4"
    assert story_service._media_mime("gs://b/f.png") == "image/png"


# ---------------------------------------------------------------------------
# Several changes, going back further, undo
# ---------------------------------------------------------------------------


def _set_story():
    from services.story_sets import Character, Location, StorySet

    lead = Character(id="lead", name="Maya", description="woman in her 30s")
    hall = Location(id="hall", name="Hall", description="dark auditorium")
    story_set = StorySet(id="set1", characters=[lead], locations=[hall])
    story = _story(set_id="set1")
    for i, sc in enumerate(story.scenes):
        sc.cast = ["lead"] if i != 1 else []
        sc.location_id = "hall"
        sc.speaker_id = "lead" if i == 2 else ""
    story.scenes[2].spoken = True
    return story, story_set


def test_parse_keeps_several_changes_and_drops_bad_ones():
    story = _story()
    plan = parse_fix_plan(
        json.dumps(
            {
                "summary": "Cut and brighten.",
                "changes": [
                    {"action": "timeline", "timeline": [{"op": "remove", "scene": 2}]},
                    {"action": "repaint_frame", "scene": 1, "visual": "Brighter room."},
                    {"action": "repaint_frame", "scene": 7, "visual": "No such scene."},
                ],
            }
        ),
        story,
    )
    assert [c.action for c in plan.changes] == ["timeline", "repaint_frame"]
    labels = [s.label for s in plan_steps(story, plan)]
    assert labels[0] == "New picture description for scene 1"
    assert "Remove scene 2 from the film" in labels and labels[-1] == "Export the edited film"


def test_a_scenario_rewrite_runs_alone():
    story = _story()
    plan = parse_fix_plan(
        json.dumps(
            {
                "changes": [
                    {"action": "music", "music_prompt": "Piano."},
                    {"action": "scenario", "direction": "End on a hopeful note."},
                ]
            }
        ),
        story,
    )
    assert [c.action for c in plan.changes] == ["scenario"]
    assert story_fix._follow_ups(story, plan) == [
        ("scenario", []),
        ("set", []),
        ("storyboard", []),
        ("video", []),
    ]
    assert story_fix.costs_money(story, plan)


def test_a_set_look_change_repaints_the_asset_and_its_scenes():
    story, story_set = _set_story()
    plan = parse_fix_plan(
        json.dumps({"changes": [{"action": "set", "asset": "maya", "outfit": "red suit"}]}),
        story,
        story_set,
    )
    (change,) = plan.changes
    assert (change.asset_kind, change.asset_id, change.outfit) == ("character", "lead", "red suit")
    fx = story_fix.effects(story, plan, story_set)
    assert fx.frames == [0, 2] and fx.clips == [0, 2]
    assert ["character", "lead", "front"] in fx.set_targets
    assert ["character", "lead", "voice"] not in fx.set_targets
    assert story_fix._follow_ups(story, plan, story_set)[:3] == [
        ("set", fx.set_targets),
        ("storyboard", [0, 2]),
        ("video", []),
    ]


def test_a_set_voice_change_remakes_only_the_scenes_it_speaks_in():
    story, story_set = _set_story()
    plan = _one(action="set", asset_kind="character", asset_id="lead", asset_name="Maya",
                voice="a deep calm voice")
    fx = story_fix.effects(story, plan, story_set)
    assert fx.frames == [] and fx.clips == [2]
    assert fx.set_targets == [["character", "lead", "voice"]]


def test_an_unknown_asset_asks_back():
    story, story_set = _set_story()
    plan = parse_fix_plan(
        json.dumps({"changes": [{"action": "set", "asset": "Bob", "outfit": "hat"}]}),
        story,
        story_set,
    )
    assert not plan.runnable and "person, place or prop" in plan.question


def test_a_plan_saved_before_multi_change_fixes_still_loads():
    old = {"action": "music", "summary": "New music", "music_prompt": "Jazz", "scene": -1}
    plan = FixPlan.from_dict(old)
    assert plan.summary == "New music" and plan.changes[0].music_prompt == "Jazz"
    assert not FixPlan.from_dict({"action": "none", "question": "Which?"}).runnable


def test_undo_puts_the_previous_film_back(backend):
    s = _saved()
    plan = _one(action="rewrite_scene", scene=2, camera="orbit")
    job = _run(story_fix.start_fix(s.id, OWNER, plan))
    assert job.status == "done"
    after = story_store.get_store().get(s.id, OWNER)
    assert after.final_uri == "local://film2.mp4" and story_fix.can_undo(after)
    back = story_fix.undo_fix(s.id, OWNER)
    assert back.final_uri == "local://film.mp4"
    assert back.scenes[2].camera == "static" and back.scenes[2].clip_uri == "local://clip2.mp4"
    assert back.timeline_json == s.timeline_json and not story_fix.can_undo(back)
    with pytest.raises(ScenarioError):
        story_fix.undo_fix(s.id, OWNER)


def test_pausing_the_film_points_the_fix_and_undo_restores(backend, monkeypatch):
    import pages.story_studio as page
    from state.story_state import StoryState

    st = StoryState()
    monkeypatch.setattr(page.me, "state", lambda cls: st)
    monkeypatch.setattr(page, "_owner", lambda: OWNER)
    page.on_fix_point(type("E", (), {"value": {"time": 7.5}})())
    assert st.fix_time == "7.5"
    page.on_fix_point(type("E", (), {"value": {"time": "soon"}})())
    assert st.fix_time == "7.5"

    s = _saved()
    st.story_id = s.id
    _run(story_fix.start_fix(s.id, OWNER, _one(action="rewrite_scene", scene=0, camera="orbit")))
    page.on_undo_fix(None)
    assert not st.error
    assert story_store.get_store().get(s.id, OWNER).final_uri == "local://film.mp4"


def test_preview_rows_cover_every_change():
    import pages.story_studio as page

    story, story_set = _set_story()
    plan = FixPlan(
        changes=[
            FixChange(action="rewrite_scene", scene=0, narration="Hello."),
            FixChange(action="set", asset_kind="character", asset_id="lead",
                      asset_name="Maya", outfit="red suit"),
            FixChange(action="music", music_prompt="Piano."),
        ]
    )
    rows = page._fix_changes(story, plan, story_set)
    assert [r[0] for r in rows] == ["Scene 1 line", "Maya outfit", "Music"]
    assert rows[1] == ("Maya outfit", "(none)", "red suit")
