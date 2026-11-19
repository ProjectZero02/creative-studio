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
"""Story Studio "AI fix": describe what you dislike, Gemini picks the fix.

The user types plain text in the Edit step ("the end of scene 3 goes
blank"), optionally pointing at a scene or a time. Gemini reads the request
against the story (scenario, each scene's visual, narration and camera, the
storyboard frames and the timeline) and returns one small change as JSON:

    {"summary": str, "reason": str, "question": str,
     "action": "rewrite_scene" | "repaint_frame" | "music" | "timeline" | "none",
     "scene": int (1-based),
     "narration": str, "visual": str, "camera": str, "spoken": bool,
     "music_prompt": str,
     "timeline": [{"op": "trim", "scene": int, "cut_start": s, "cut_end": s},
                  {"op": "remove", "scene": int},
                  {"op": "move", "scene": int, "to": int}]}

:func:`parse_fix_plan` turns that into a :class:`FixPlan` checked against the
story, :func:`plan_steps` lists what will run (and which steps cost money),
and :func:`start_fix` runs it with the existing jobs after the user confirms.

Everything above ``start_fix`` is pure and unit tested.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field

from services import story_jobs
from services import story_timeline as tlm
from services.story_models import (
    CAMERA_IDS,
    ScenarioError,
    Story,
    _strip_fences,
    normalize_camera,
)
from services.story_service import get_backend
from services.story_store import StoryAccessError, get_store

ACTIONS = ("rewrite_scene", "repaint_frame", "music", "timeline", "none")
TIMELINE_OPS = ("trim", "remove", "move")
# A trimmed clip keeps at least this much picture (or all of it when shorter).
TRIM_MIN_KEEP = 1.0
# Most seconds one trim may take off a clip edge.
TRIM_MAX_CUT = 10.0


@dataclass
class FixPlan:
    """One small change to the story, checked against it."""

    action: str = "none"
    summary: str = ""
    reason: str = ""
    # Set when the request is unclear: Gemini asks instead of guessing.
    question: str = ""
    scene: int = -1  # 0-based; -1 = none
    narration: str | None = None
    visual: str | None = None
    camera: str | None = None
    spoken: bool | None = None
    music_prompt: str = ""
    timeline: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FixPlan:
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def runnable(self) -> bool:
        return self.action != "none"


@dataclass
class FixStep:
    """One thing the fix will do, for the preview."""

    label: str
    paid: bool = False


# ---------------------------------------------------------------------------
# What Gemini sees
# ---------------------------------------------------------------------------


def scene_spans(timeline: dict) -> list[tuple[int, float, float]]:
    """(scene index, start, end) of each video clip on the film, in order."""
    return [
        (int(c.get("scene", -1)), float(c["start"]), tlm.clip_end(c))
        for c in tlm.track(timeline, "video")["clips"]
    ]


def scene_at(timeline: dict, seconds: float) -> int:
    """The scene on screen at `seconds` of the film (-1 when none)."""
    spans = scene_spans(timeline)
    for scene, start, end in spans:
        if start - 0.001 <= seconds < end:
            return scene
    if spans and seconds >= spans[-1][2]:
        return spans[-1][0]
    return -1


def _focus_text(story: Story, timeline: dict, scene: int, seconds: float | None) -> str:
    lines = []
    if seconds is not None and seconds >= 0:
        at = scene_at(timeline, seconds)
        where = ""
        for sc, start, end in scene_spans(timeline):
            if sc == at and start - 0.001 <= seconds < end + 0.001:
                where = (
                    f", {seconds - start:.1f} s into it and {max(0.0, end - seconds):.1f} s "
                    "before it ends"
                )
                break
        if at >= 0:
            lines.append(
                f"The viewer points at {seconds:.1f} s of the film, which is in "
                f"scene {at + 1}{where}."
            )
        else:
            lines.append(f"The viewer points at {seconds:.1f} s of the film.")
    if 0 <= scene < len(story.scenes):
        lines.append(f"The viewer selected scene {scene + 1}.")
    return "\n".join(lines) or "The viewer did not select a scene or time."


def _scenes_text(story: Story) -> str:
    rows = []
    for i, sc in enumerate(story.scenes):
        take = (
            f" Continues the take of scene {story.take_start(i) + 1} (same shot)."
            if story.continues_take(i)
            else ""
        )
        rows.append(
            f"Scene {i + 1} ({sc.duration} s, camera {sc.camera}, "
            f"{'spoken on camera' if sc.spoken else 'narrated over the picture'}, "
            f"storyboard frame: {'yes' if sc.frame_uri else 'missing'}, "
            f"clip: {'yes' if sc.clip_uri else 'missing'}).{take}\n"
            f"  Visual: {sc.visual}\n"
            f"  Narration: {sc.narration or '(none)'}"
        )
    return "\n".join(rows)


def _timeline_text(timeline: dict) -> str:
    rows = []
    for c in tlm.track(timeline, "video")["clips"]:
        rows.append(
            f"  scene {int(c.get('scene', -1)) + 1}: on the film {c['start']:.2f}"
            f"-{tlm.clip_end(c):.2f} s, plays its clip {c['in']:.2f}-{c['out']:.2f} s"
            + (f", crossfade {c['fade_in']:.2f} s" if c.get("fade_in") else "")
        )
    titles = [c["text"] for c in tlm.track(timeline, "text")["clips"]]
    music = tlm.track(timeline, "music")["clips"]
    rows.append(f"  music clips: {len(music)}; titles: {titles or 'none'}")
    rows.append(f"  film length: {tlm.duration(timeline):.2f} s")
    return "\n".join(rows)


def fix_media(story: Story) -> list[str]:
    """What the fix planner looks at, in the order the prompt names them:
    the rendered film (when there is one), then each scene's storyboard
    frame."""
    film = [story.final_uri] if story.final_uri else []
    return film + [sc.frame_uri for sc in story.scenes if sc.frame_uri]


def _media_text(story: Story) -> str:
    frames = [i + 1 for i, sc in enumerate(story.scenes) if sc.frame_uri]
    lines = []
    if story.final_uri:
        lines.append(
            "The rendered film is attached first. Watch it: judge what is really "
            "on screen and in the sound (people, screens, cuts, speech), not only "
            "the text below."
        )
    if frames:
        lines.append(
            "Then the storyboard frames of scenes "
            + ", ".join(str(n) for n in frames)
            + ", in that order."
        )
    return "\n".join(lines) or "No film or frames are attached yet."


def fix_prompt(
    story: Story, request: str, scene: int = -1, seconds: float | None = None
) -> str:
    """The prompt that asks Gemini for the smallest fix (see module doc)."""
    timeline = tlm.normalize(story.timeline_json)
    return f"""You are the editor of a short AI-generated film. The viewer
describes what they dislike. Pick the SMALLEST single change that fixes it.

Film: "{story.title}". Idea: {story.idea}
Style: {story.style}. Aspect ratio: {story.aspect_ratio}. Narration language: {story.language}.
Music: {"on" if story.music_on else "off"}; prompt: {story.music_prompt or "(default)"}

Scenes:
{_scenes_text(story)}

Timeline (the edited film):
{_timeline_text(timeline)}

{_media_text(story)}

{_focus_text(story, timeline, scene, seconds)}

Viewer's request: {request.strip()}

Choose exactly one action:
- "timeline": cut or rearrange what is already made, no new generation (free).
  Best for a blank, black or frozen moment at the start or end of a clip,
  a scene that runs too long, a scene to drop, or the wrong order. Ops:
  {{"op": "trim", "scene": n, "cut_start": seconds, "cut_end": seconds}},
  {{"op": "remove", "scene": n}}, {{"op": "move", "scene": n, "to": position}}.
- "repaint_frame": the scene's picture looks wrong (character, place, style)
  but its idea is right. Give an improved "visual" (English) for scene n.
  Its storyboard frame is painted again and its clip re-rendered (paid).
- "rewrite_scene": what happens or is said in scene n is wrong. Give the new
  "narration" (in {story.language}, at most about 2.5 words per second of the
  scene), "visual" (English), "camera" (one of: {", ".join(CAMERA_IDS)}) and
  "spoken" (true when the person on screen says the line). Only include the
  fields that change. The clip is rendered again (paid).
- "music": the music is wrong. Give the new "music_prompt" (paid).
- "none": the request is unclear or nothing should change. Ask one short
  "question" back.

Prefer "timeline" when cutting fixes it. Scene numbers start at 1.
Return only JSON: {{"action": str, "summary": str (one plain sentence of what
will change), "reason": str (why it fixes the request), "question": str,
"scene": int, "narration": str, "visual": str, "camera": str, "spoken": bool,
"music_prompt": str, "timeline": [ops]}}"""


# ---------------------------------------------------------------------------
# Gemini's JSON -> a checked plan
# ---------------------------------------------------------------------------


def _scene_index(raw, story: Story) -> int:
    """A 1-based scene number from the model -> 0-based index (or -1)."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return -1
    return n - 1 if 1 <= n <= len(story.scenes) else -1


def _seconds(raw, hi: float = TRIM_MAX_CUT) -> float:
    try:
        v = float(raw or 0)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return round(min(hi, max(0.0, v)), 3)


def _text(raw, limit: int = 600) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()[:limit]
    return text or None


def _timeline_ops(raw, story: Story) -> list[dict]:
    ops = []
    for op in raw if isinstance(raw, list) else []:
        if not isinstance(op, dict) or op.get("op") not in TIMELINE_OPS:
            continue
        scene = _scene_index(op.get("scene"), story)
        if scene < 0:
            continue
        if op["op"] == "trim":
            cut_start, cut_end = _seconds(op.get("cut_start")), _seconds(op.get("cut_end"))
            if cut_start or cut_end:
                ops.append(
                    {"op": "trim", "scene": scene, "cut_start": cut_start, "cut_end": cut_end}
                )
        elif op["op"] == "remove":
            ops.append({"op": "remove", "scene": scene})
        else:
            to = _scene_index(op.get("to"), story)
            if to >= 0:
                ops.append({"op": "move", "scene": scene, "to": to})
    return ops


def _none(summary: str, question: str = "") -> FixPlan:
    return FixPlan(action="none", summary=summary, question=question)


def parse_fix_plan(text: str, story: Story) -> FixPlan:
    """Gemini's JSON -> a FixPlan that only names scenes and edits that exist.

    A plan that would change nothing becomes action "none" with a question,
    so the preview never offers an empty (or paid but pointless) run.
    """
    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The fix plan was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ScenarioError("The fix plan must be a JSON object.")
    action = str(data.get("action") or "none").strip().lower()
    summary = _text(data.get("summary"), 300) or ""
    reason = _text(data.get("reason"), 400) or ""
    question = _text(data.get("question"), 300) or ""
    if action not in ACTIONS:
        return _none(summary, question or "What should change?")
    plan = FixPlan(action=action, summary=summary, reason=reason, question=question)
    scene = _scene_index(data.get("scene"), story)

    if action == "timeline":
        plan.timeline = _timeline_ops(data.get("timeline"), story)
        if not story.timeline_json:
            return _none(summary, "Render the film once before editing its timeline.")
        if not plan.timeline:
            return _none(summary, question or "Which part of the film should be cut or moved?")
        return plan

    if action == "music":
        plan.music_prompt = _text(data.get("music_prompt"), 400) or ""
        if not plan.music_prompt:
            return _none(summary, question or "What kind of music would you like?")
        return plan

    if action in ("rewrite_scene", "repaint_frame"):
        if scene < 0:
            return _none(summary, question or "Which scene should change?")
        plan.scene = scene
        cur = story.scenes[scene]
        visual = _text(data.get("visual"))
        plan.visual = visual if visual and visual != cur.visual else None
        if action == "rewrite_scene":
            narration = _text(data.get("narration"))
            plan.narration = (
                narration if narration is not None and narration != cur.narration else None
            )
            if data.get("camera"):
                camera = normalize_camera(str(data["camera"]), cur.camera)
                plan.camera = camera if camera != cur.camera else None
            if isinstance(data.get("spoken"), bool) and data["spoken"] != cur.spoken:
                plan.spoken = data["spoken"]
            if not any(
                v is not None for v in (plan.narration, plan.visual, plan.camera, plan.spoken)
            ):
                return _none(summary, question or "What should change in that scene?")
        return plan

    plan.question = question or "What should change?"
    return plan


# ---------------------------------------------------------------------------
# What the fix will do
# ---------------------------------------------------------------------------


def repaint_indices(story: Story, plan: FixPlan) -> list[int]:
    """Storyboard frames the fix paints again: the scene, plus the later
    scenes of its continuous take (they are painted from the take's first
    frame, so they would no longer match it)."""
    if plan.action == "repaint_frame" or (
        plan.action == "rewrite_scene" and plan.visual is not None
    ):
        return with_take(story, plan.scene)
    return []


def with_take(story: Story, index: int) -> list[int]:
    """`index` and the later scenes that continue its take."""
    out = [index]
    j = index + 1
    while j < len(story.scenes) and story.continues_take(j):
        out.append(j)
        j += 1
    return out


def _clip_changes(story: Story, plan: FixPlan) -> bool:
    """A rewrite that needs the scene's clip rendered again. A new narrated
    line alone only needs a new voiceover; the picture stays."""
    if plan.action != "rewrite_scene":
        return False
    cur = story.scenes[plan.scene]
    spoken = cur.spoken if plan.spoken is None else plan.spoken
    return (
        plan.visual is not None
        or plan.camera is not None
        or plan.spoken is not None
        or (plan.narration is not None and spoken)
    )


def plan_steps(story: Story, plan: FixPlan) -> list[FixStep]:
    """What will run, in order, for the preview (paid steps are marked)."""
    if not plan.runnable:
        return []
    steps: list[FixStep] = []
    if plan.action == "timeline":
        for op in plan.timeline:
            n = op["scene"] + 1
            if op["op"] == "trim":
                parts = []
                if op["cut_start"]:
                    parts.append(f"{op['cut_start']:g} s off the start")
                if op["cut_end"]:
                    parts.append(f"{op['cut_end']:g} s off the end")
                steps.append(FixStep(f"Trim scene {n}: {' and '.join(parts)}"))
            elif op["op"] == "remove":
                steps.append(FixStep(f"Remove scene {n} from the film"))
            else:
                steps.append(FixStep(f"Move scene {n} to position {op['to'] + 1}"))
        steps.append(FixStep("Export the edited film"))
        return steps
    if plan.action == "music":
        steps.append(FixStep(f'New music: "{plan.music_prompt}"', paid=True))
        steps.append(FixStep("Export the film with the new music"))
        return steps
    n = plan.scene + 1
    if plan.action == "rewrite_scene":
        changed = [
            name
            for name, v in (
                ("narration", plan.narration),
                ("visual", plan.visual),
                ("camera", plan.camera),
                ("speech", plan.spoken),
            )
            if v is not None
        ]
        steps.append(FixStep(f"Change scene {n}: {', '.join(changed)}"))
    elif plan.visual is not None:
        steps.append(FixStep(f"New picture description for scene {n}"))
    frames = repaint_indices(story, plan)
    if frames:
        names = ", ".join(str(i + 1) for i in frames)
        steps.append(
            FixStep(
                f"Paint the storyboard frame of scene{'s' if len(frames) > 1 else ''} {names}",
                paid=True,
            )
        )
    if frames or _clip_changes(story, plan):
        # Later clips of a continuous take continue this one: made again too.
        clips = sorted(set(frames) | set(with_take(story, plan.scene)))
        names = ", ".join(str(i + 1) for i in clips)
        steps.append(
            FixStep(
                f"Render the video clip of scene{'s' if len(clips) > 1 else ''} {names}",
                paid=True,
            )
        )
    if story.voice_on and any(
        sc.narration.strip() and not sc.spoken for sc in story.scenes
    ):
        steps.append(FixStep("Record the voiceover lines again", paid=True))
    if story.makes_alt:
        steps.append(FixStep(f"Update the {story.alt_language} version", paid=True))
    steps.append(FixStep("Stitch the film again (other scenes are kept)"))
    return steps


def costs_money(story: Story, plan: FixPlan) -> bool:
    return any(s.paid for s in plan_steps(story, plan))


# ---------------------------------------------------------------------------
# Timeline edits (pure)
# ---------------------------------------------------------------------------


def apply_timeline_ops(timeline: dict | str, ops: list[dict]) -> dict:
    """Trim, remove and move scenes on the video track. Voice lines move with
    their scene and full-length music keeps reaching the end (follow_scenes).
    Raises ValueError when an op would empty the film."""
    before = tlm.normalize(timeline)
    tl = copy.deepcopy(before)
    clips = tlm.track(tl, "video")["clips"]
    for op in ops:
        mine = [c for c in clips if int(c.get("scene", -1)) == op["scene"]]
        if not mine:
            continue
        if op["op"] == "trim":
            first, last = mine[0], mine[-1]
            for clip, cut, edge in ((first, op["cut_start"], "in"), (last, op["cut_end"], "out")):
                if not cut:
                    continue
                length = clip["out"] - clip["in"]
                keep = min(TRIM_MIN_KEEP, length)
                cut = min(cut, max(0.0, length - keep))
                if edge == "in":
                    clip["in"] = round(clip["in"] + cut, 3)
                else:
                    clip["out"] = round(clip["out"] - cut, 3)
        elif op["op"] == "remove":
            if len(mine) == len(clips):
                raise ValueError("The film needs at least one scene.")
            clips[:] = [c for c in clips if c not in mine]
        else:
            order: list[int] = []
            for c in clips:
                if c["scene"] not in order:
                    order.append(c["scene"])
            order.remove(op["scene"])
            order.insert(min(op["to"], len(order)), op["scene"])
            clips.sort(key=lambda c: order.index(c["scene"]))
    clean = tlm.normalize(tl)
    return tlm.follow_scenes(before, clean)


# ---------------------------------------------------------------------------
# Planning and running
# ---------------------------------------------------------------------------


def plan_fix(
    story_id: str,
    owner: str,
    request: str,
    scene: int = -1,
    seconds: float | None = None,
) -> FixPlan:
    """Ask Gemini (one short JSON call) for the fix. Nothing is changed yet."""
    if not request.strip():
        raise ScenarioError("Describe what you would like to change.")
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    backend = get_backend()
    last: Exception | None = None
    for _ in range(2):  # one automatic retry on malformed JSON
        try:
            return parse_fix_plan(
                backend.plan_fix(story, request, scene, seconds), story
            )
        except ScenarioError as exc:
            last = exc
    raise last or ScenarioError("No fix plan.")


def _apply_edit(story_id: str, owner: str, plan: FixPlan) -> str:
    """Write the plan's text, music or timeline change to the story."""
    if plan.action == "timeline":
        story = get_store().get(story_id, owner)
        if story is None:
            raise StoryAccessError("Story not found.")
        story_jobs.save_timeline(
            story_id, owner, apply_timeline_ops(story.timeline_json, plan.timeline)
        )
        return ""

    if plan.action == "music":

        def music(s: Story) -> None:
            s.music_prompt = plan.music_prompt
            s.music_on = True

        story_jobs.mutate_story(story_id, owner, music)
        return ""

    def scene(s: Story) -> None:
        if plan.scene >= len(s.scenes):
            raise StoryAccessError("That scene is gone.")
        clip = _clip_changes(s, plan)
        frames = repaint_indices(s, plan)
        sc = s.scenes[plan.scene]
        if plan.narration is not None:
            sc.narration = plan.narration
            sc.narration_alt = ""
        if plan.visual is not None:
            sc.visual = plan.visual
        if plan.camera is not None:
            sc.camera = plan.camera
        if plan.spoken is not None:
            sc.spoken = plan.spoken
        for i in frames:
            s.scenes[i].frame_uri = ""
            s.scenes[i].clear_clip()
        if clip:
            sc.clear_clip()
        s.clear_films()

    story_jobs.mutate_story(story_id, owner, scene)
    return ""


def _follow_ups(story: Story, plan: FixPlan) -> list[tuple[str, list[int]]]:
    if plan.action == "timeline":
        return [("export", [])]
    if plan.action == "music":
        return [("music", []), ("export", [])]
    frames = repaint_indices(story, plan)
    return ([("storyboard", frames)] if frames else []) + [("video", [])]


def _start(kind: str, story_id: str, owner: str, indices: list[int]):
    if kind == "storyboard":
        return story_jobs.start_storyboard(story_id, owner, indices or None)
    if kind == "music":
        return story_jobs.start_music(story_id, owner)
    if kind == "export":
        return story_jobs.start_export(story_id, owner)
    return story_jobs.start_video(story_id, owner)


def _run_chain(job, story_id: str, owner: str, steps: list[tuple[str, list[int]]]) -> None:
    """Run existing jobs one after another inside `job`. Their tasks are
    shown as the fix job's own, so the page draws one progress panel."""
    for kind, indices in steps:
        sub = _start(kind, story_id, owner, indices)
        with story_jobs._jobs_lock:
            job.tasks.extend(sub.tasks)
        sub = story_jobs.wait(sub.id, owner, timeout=4 * 3600)
        if sub is None or sub.status != story_jobs.DONE:
            if sub is not None and sub.message:
                job.message = sub.message
            return


def start_fix(story_id: str, owner: str, plan: FixPlan):
    """Run a confirmed plan with the existing jobs (one "fix" job)."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if not plan.runnable:
        raise ScenarioError(plan.question or "Nothing to change.")
    if plan.action in ("rewrite_scene", "repaint_frame") and not (
        0 <= plan.scene < len(story.scenes)
    ):
        raise ScenarioError("That scene is gone. Describe the fix again.")
    steps = _follow_ups(story, plan)
    job = story_jobs._new_job(owner, story_id, "fix", {"plan": plan.to_dict()})
    edit = story_jobs._add_task(job, plan.summary or "Applying the change", "fix", plan.scene)

    def work(job) -> None:
        if story_jobs._run_task(edit, lambda: _apply_edit(story_id, owner, plan)):
            _run_chain(job, story_id, owner, steps)

    return story_jobs._spawn(job, work)


def resume_fix(story_id: str, owner: str):
    """Retry a failed fix: the change is already saved, so make what is
    still missing (frames first, then the film)."""
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    if any(not sc.frame_uri for sc in story.scenes):
        job = story_jobs._new_job(owner, story_id, "fix", {})

        def work(job) -> None:
            _run_chain(job, story_id, owner, [("storyboard", []), ("video", [])])

        return story_jobs._spawn(job, work)
    if not story.final_uri:
        return story_jobs.start_video(story_id, owner)
    return story_jobs.start_export(story_id, owner)

