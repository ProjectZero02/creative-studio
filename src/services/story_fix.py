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

The user types plain text at the Edit step ("the slide goes blank at the end
of scene 3", "make the ending happier"), optionally pointing at a scene or a
moment. Gemini watches the rendered film, looks at the storyboard frames and
reads the story (scenario, scenes, set and timeline), then returns the
smallest set of changes that fixes it, going back only as far as it must:

    {"summary": str, "reason": str, "question": str,
     "changes": [
       {"action": "timeline", "timeline": [ops]},              # free
       {"action": "repaint_frame", "scene": n, "visual": str},
       {"action": "rewrite_scene", "scene": n, "narration": str,
        "visual": str, "camera": str, "spoken": bool},
       {"action": "set", "asset": name, "description": str,
        "outfit": str, "voice": str},
       {"action": "music", "music_prompt": str},
       {"action": "scenario", "direction": str}]}           # alone

Timeline ops: {"op": "trim", "scene": n, "cut_start": s, "cut_end": s},
{"op": "remove", "scene": n}, {"op": "move", "scene": n, "to": n}. Scene
numbers are 1-based in the JSON and 0-based here.

:func:`parse_fix_plan` checks that against the story, :func:`plan_steps`
lists what will run (and which steps cost money), and :func:`start_fix`
applies it and re-runs only the affected steps after the user confirms. The
story (and its set) as it was before is kept, so :func:`undo_fix` can put the
previous film back.

Everything above ``plan_fix`` is pure and unit tested.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field

from common.lang_detect import lang_name, resolve_lang
from services import story_jobs, story_versions
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

ACTIONS = (
    "timeline",
    "repaint_frame",
    "rewrite_scene",
    "set",
    "music",
    "scenario",
    "none",
)
TIMELINE_OPS = ("trim", "remove", "move", "transition")
TRANSITION_JOINS = ("cut", "bridge", "dissolve", "fade_black")
# A trimmed clip keeps at least this much picture (or all of it when shorter).
TRIM_MIN_KEEP = 1.0
# Most seconds one trim may take off a clip edge.
TRIM_MAX_CUT = 10.0
# Most changes one request may make (a longer list is cut).
MAX_CHANGES = 6


@dataclass
class FixChange:
    """One change of a fix, checked against the story."""

    action: str = "none"
    summary: str = ""
    scene: int = -1  # 0-based; -1 = none
    narration: str | None = None
    visual: str | None = None
    camera: str | None = None
    spoken: bool | None = None
    music_prompt: str = ""
    timeline: list[dict] = field(default_factory=list)
    # "set": the asset that changes, and its new look or voice.
    asset_kind: str = ""
    asset_id: str = ""
    asset_name: str = ""
    description: str | None = None
    outfit: str | None = None
    voice: str | None = None
    # "scenario": what the rewritten scenario must do.
    direction: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> FixChange:
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class FixPlan:
    """What Gemini proposes for one request: a few changes, or a question."""

    summary: str = ""
    reason: str = ""
    # Set when the request is unclear: Gemini asks instead of guessing.
    question: str = ""
    changes: list[FixChange] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> FixPlan:
        data = dict(data or {})
        if "changes" not in data and data.get("action"):
            # A plan saved before multi-change fixes: one change.
            data["changes"] = [] if data["action"] == "none" else [dict(data)]
        changes = [
            FixChange.from_dict(c)
            for c in data.get("changes") or []
            if isinstance(c, dict)
        ]
        return cls(
            summary=str(data.get("summary") or ""),
            reason=str(data.get("reason") or ""),
            question=str(data.get("question") or ""),
            changes=changes,
        )

    @property
    def runnable(self) -> bool:
        return bool(self.changes)

    def of(self, action: str) -> list[FixChange]:
        return [c for c in self.changes if c.action == action]


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


def asset_scenes(
    story: Story, kind: str, asset_id: str, voice: bool = False
) -> list[int]:
    """Scenes a set asset is in. `voice`: the scenes where it speaks."""
    out = []
    for i, sc in enumerate(story.scenes):
        if voice:
            hit = kind == "character" and sc.speaker_id == asset_id
        elif kind == "character":
            hit = asset_id in sc.cast or sc.speaker_id == asset_id
        elif kind == "location":
            hit = sc.location_id == asset_id
        else:
            hit = asset_id in sc.prop_ids
        if hit:
            out.append(i)
    return out


def _set_text(story: Story, story_set) -> str:
    if story_set is None:
        return "(no set: the characters and places are only described in the scenes)"
    rows = []
    for kind in ("character", "location", "prop"):
        for a in story_set.assets(kind):
            scenes = (
                ", ".join(str(i + 1) for i in asset_scenes(story, kind, a.id)) or "none"
            )
            line = f'- {kind} "{a.name}": {a.look()}; in scenes {scenes}'
            if kind == "character" and a.voice.description:
                line += f"; on-camera voice: {a.voice.description}"
            rows.append(line)
    return "\n".join(rows) or "(empty set)"


def fix_prompt(
    story: Story,
    request: str,
    scene: int = -1,
    seconds: float | None = None,
    story_set=None,
) -> str:
    """The prompt that asks Gemini for the smallest fix (see module doc)."""
    timeline = tlm.normalize(story.timeline_json)
    # The plan's summary, reason and question are read by the person: write
    # them in the language of their request.
    reader = lang_name(resolve_lang(request, story.idea))
    return f"""You are the editor of a short AI-generated film. The viewer
describes what they dislike. Fix it with the SMALLEST changes that work,
going back in the making of the film only as far as you must.

Film: "{story.title}". Idea: {story.idea}
Style: {story.style}. Aspect ratio: {story.aspect_ratio}. Narration language: {story.language}.
Music: {"on" if story.music_on else "off"}; prompt: {story.music_prompt or "(default)"}

Set (people, places and props reused across scenes):
{_set_text(story, story_set)}

Scenes:
{_scenes_text(story)}

Timeline (the edited film):
{_timeline_text(timeline)}

{_media_text(story)}

{_focus_text(story, timeline, scene, seconds)}

Viewer's request: {request.strip()}

Changes, from the smallest step back to the largest:
- "timeline": cut or rearrange what is already made, no new generation (free).
  Best for a blank, black or frozen moment at the start or end of a clip,
  a scene that runs too long, a scene to drop, or the wrong order. Give
  "timeline": a list of {{"op": "trim", "scene": n, "cut_start": seconds,
  "cut_end": seconds}}, {{"op": "remove", "scene": n}}, {{"op": "move",
  "scene": n, "to": position}}, or {{"op": "transition", "scene": n,
  "join": "cut"|"bridge"|"dissolve"|"fade_black"}}.
- "repaint_frame": scene n's picture looks wrong (who or what is on screen,
  the place, the screen content, the framing) but what happens is right.
  Give an improved "visual" (English). Its storyboard frame is painted again
  and its clip made again (paid).
- "rewrite_scene": what happens or is said in scene n is wrong. Give only the
  fields that change: "narration" (in {story.language}, at most about 2.5
  words per second of the scene), "visual" (English), "camera" (one of:
  {", ".join(CAMERA_IDS)}) and "spoken" (true when the person on screen says
  the line). The clip is made again (paid).
- "set": a person, place or prop from the set looks or sounds wrong in every
  scene it is in. Give "asset" (its name exactly as in the set) and only what
  changes: "description", "outfit" (people only) or "voice" (how a person
  sounds on camera). Its reference pictures are painted again, then the
  scenes it is in (paid).
- "music": the music is wrong. Give the new "music_prompt" (paid).
- "scenario": the story itself is wrong (the plot, tone, message, ending or
  who is in it) and scene rewrites would not fix it. Give "direction": what
  the new scenario must do differently. The scenario is written again and
  the whole film is made again from it (paid). Use it alone, never with
  other changes.

Use as few changes as you can (most often one, at most {MAX_CHANGES}); never
regenerate what a free timeline cut fixes. Scene numbers start at 1. When the
request is unclear, make no changes and ask one short "question" back.
Write "summary", "reason", "question" and each change's "summary" in {reader}.
Return only JSON: {{"summary": str (one plain sentence of what will change),
"reason": str (why it fixes the request), "question": str, "changes": [{{
"action": str, "summary": str, "scene": int, "narration": str, "visual": str,
"camera": str, "spoken": bool, "asset": str, "description": str, "outfit": str,
"voice": str, "music_prompt": str, "direction": str, "timeline": [ops]}}]}}"""


# ---------------------------------------------------------------------------
# Gemini's JSON -> a checked plan
# ---------------------------------------------------------------------------


def _scene_index(raw, story: Story) -> int:
    """A 1-based scene number from the model -> 0-based index (or -1)."""
    try:
        n = int(raw)
    except TypeError, ValueError:
        return -1
    return n - 1 if 1 <= n <= len(story.scenes) else -1


def _seconds(raw, hi: float = TRIM_MAX_CUT) -> float:
    try:
        v = float(raw or 0)
    except TypeError, ValueError:
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
            cut_start, cut_end = (
                _seconds(op.get("cut_start")),
                _seconds(op.get("cut_end")),
            )
            if cut_start or cut_end:
                ops.append(
                    {
                        "op": "trim",
                        "scene": scene,
                        "cut_start": cut_start,
                        "cut_end": cut_end,
                    }
                )
        elif op["op"] == "remove":
            ops.append({"op": "remove", "scene": scene})
        elif op["op"] == "transition":
            join = str(op.get("join") or "").strip().lower()
            if join in TRANSITION_JOINS:
                ops.append({"op": "transition", "scene": scene, "join": join})
        else:
            to = _scene_index(op.get("to"), story)
            if to >= 0:
                ops.append({"op": "move", "scene": scene, "to": to})
    return ops


def _find_asset(story_set, raw) -> tuple[str, object] | None:
    """(kind, asset) for a name (or id) Gemini gave, matched loosely."""
    if story_set is None or not raw:
        return None
    want = str(raw).strip().strip('"').lower()
    for kind in ("character", "location", "prop"):
        for a in story_set.assets(kind):
            if want in (a.id.lower(), a.name.strip().lower()):
                return kind, a
    return None


def _parse_change(data: dict, story: Story, story_set=None) -> FixChange | str:
    """One change from Gemini -> a checked FixChange, or the question to ask
    when it names nothing that exists or would change nothing."""
    action = str(data.get("action") or "none").strip().lower()
    summary = _text(data.get("summary"), 300) or ""
    if action not in ACTIONS or action == "none":
        return "What should change?"
    change = FixChange(action=action, summary=summary)

    if action == "timeline":
        if not story.timeline_json:
            return "Render the film once before editing its timeline."
        change.timeline = _timeline_ops(data.get("timeline"), story)
        return (
            change
            if change.timeline
            else "Which part of the film should be cut or moved?"
        )

    if action == "music":
        change.music_prompt = _text(data.get("music_prompt"), 400) or ""
        return change if change.music_prompt else "What kind of music would you like?"

    if action == "scenario":
        change.direction = _text(data.get("direction"), 800) or ""
        return change if change.direction else "What should the story do differently?"

    if action == "set":
        found = _find_asset(story_set, data.get("asset"))
        if found is None:
            return "Which person, place or prop should change?"
        kind, asset = found
        change.asset_kind, change.asset_id, change.asset_name = (
            kind,
            asset.id,
            asset.name,
        )
        description = _text(data.get("description"))
        change.description = (
            description if description and description != asset.description else None
        )
        if kind == "character":
            outfit = _text(data.get("outfit"), 300)
            change.outfit = outfit if outfit and outfit != asset.outfit else None
            voice = _text(data.get("voice"), 300)
            change.voice = voice if voice and voice != asset.voice.description else None
        if all(v is None for v in (change.description, change.outfit, change.voice)):
            return f"What should change about {asset.name}?"
        return change

    scene = _scene_index(data.get("scene"), story)
    if scene < 0:
        return "Which scene should change?"
    change.scene = scene
    cur = story.scenes[scene]
    visual = _text(data.get("visual"))
    change.visual = visual if visual and visual != cur.visual else None
    if action == "repaint_frame":
        return change if change.visual is not None else "What should the picture show?"
    narration = _text(data.get("narration"))
    change.narration = (
        narration if narration is not None and narration != cur.narration else None
    )
    if data.get("camera"):
        camera = normalize_camera(str(data["camera"]), cur.camera)
        change.camera = camera if camera != cur.camera else None
    if isinstance(data.get("spoken"), bool) and data["spoken"] != cur.spoken:
        change.spoken = data["spoken"]
    if all(
        v is None
        for v in (change.narration, change.visual, change.camera, change.spoken)
    ):
        return "What should change in that scene?"
    return change


def parse_fix_plan(text: str, story: Story, story_set=None) -> FixPlan:
    """Gemini's JSON -> a FixPlan whose changes only name scenes, assets and
    edits that exist. A plan that would change nothing has no changes and a
    question, so the preview never offers an empty (or paid but pointless)
    run. A scenario rewrite redoes everything, so it always runs alone."""
    try:
        data = json.loads(_strip_fences(text))
    except ValueError as exc:
        raise ScenarioError("The fix plan was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ScenarioError("The fix plan must be a JSON object.")
    plan = FixPlan(
        summary=_text(data.get("summary"), 300) or "",
        reason=_text(data.get("reason"), 400) or "",
        question=_text(data.get("question"), 300) or "",
    )
    raw = data.get("changes")
    if not isinstance(raw, list):
        # One change at the top level (older prompt, or the demo planner).
        raw = [data] if data.get("action") else []
    asks = []
    for item in raw[:MAX_CHANGES]:
        if not isinstance(item, dict):
            continue
        got = _parse_change(item, story, story_set)
        if isinstance(got, FixChange):
            plan.changes.append(got)
        else:
            asks.append(got)
    scenario = plan.of("scenario")
    if scenario:
        plan.changes = scenario[:1]
    if not plan.changes:
        plan.question = plan.question or (asks[0] if asks else "What should change?")
    return plan


# ---------------------------------------------------------------------------
# What the fix will do
# ---------------------------------------------------------------------------


def _clip_changes(story: Story, change: FixChange) -> bool:
    """A rewrite that needs the scene's clip rendered again. A new narrated
    line alone only needs a new voiceover; the picture stays."""
    if change.action != "rewrite_scene":
        return False
    cur = story.scenes[change.scene]
    spoken = cur.spoken if change.spoken is None else change.spoken
    return (
        change.visual is not None
        or change.camera is not None
        or change.spoken is not None
        or (change.narration is not None and spoken)
    )


@dataclass
class FixEffects:
    """Everything a plan makes again, worked out once."""

    frames: list[int] = field(default_factory=list)  # storyboard frames to paint
    clips: list[int] = field(default_factory=list)  # clips to make again
    set_targets: list[list[str]] = field(default_factory=list)  # [kind, id, view]
    lines: bool = False  # a narrated line changes (new voiceover)
    music: bool = False
    timeline: list[dict] = field(default_factory=list)
    scenario: bool = False

    @property
    def remakes_film(self) -> bool:
        """The video job runs (it also stitches the film)."""
        return bool(self.frames or self.clips or self.set_targets or self.lines)


def effects(story: Story, plan: FixPlan, story_set=None) -> FixEffects:
    from services.story_sets import views_for

    out = FixEffects(scenario=bool(plan.of("scenario")))
    if out.scenario:
        return out
    frames: set[int] = set()
    clips: set[int] = set()
    for c in plan.changes:
        if c.action == "repaint_frame" or (
            c.action == "rewrite_scene" and c.visual is not None
        ):
            frames.update(with_take(story, c.scene))
        if _clip_changes(story, c):
            clips.update(with_take(story, c.scene))
        if (
            c.action == "rewrite_scene"
            and c.narration is not None
            and not _clip_changes(story, c)
        ):
            out.lines = True
        if c.action == "set":
            asset = (
                story_set.asset(c.asset_kind, c.asset_id)
                if story_set is not None
                else None
            )
            if c.description is not None or c.outfit is not None:
                views = views_for(asset) if asset is not None else []
                out.set_targets += [[c.asset_kind, c.asset_id, v] for v in views]
                for i in asset_scenes(story, c.asset_kind, c.asset_id):
                    frames.update(with_take(story, i))
            if c.voice is not None:
                out.set_targets.append([c.asset_kind, c.asset_id, "voice"])
                for i in asset_scenes(story, c.asset_kind, c.asset_id, voice=True):
                    if story.scenes[i].spoken:
                        clips.update(with_take(story, i))
                    else:
                        out.lines = True
        if c.action == "music":
            out.music = True
        if c.action == "timeline":
            out.timeline += c.timeline
    out.frames = sorted(frames)
    out.clips = sorted(clips | frames)
    return out


def _numbers(indices: list[int]) -> str:
    word = "scenes" if len(indices) > 1 else "scene"
    return f"{word} {', '.join(str(i + 1) for i in indices)}"


def _change_label(story: Story, c: FixChange) -> str:
    if c.action == "rewrite_scene":
        changed = [
            name
            for name, v in (
                ("line", c.narration),
                ("picture", c.visual),
                ("camera", c.camera),
                ("speech", c.spoken),
            )
            if v is not None
        ]
        return f"Change scene {c.scene + 1}: {', '.join(changed)}"
    if c.action == "repaint_frame":
        return f"New picture description for scene {c.scene + 1}"
    if c.action == "set":
        changed = [
            name
            for name, v in (
                ("look", c.description),
                ("outfit", c.outfit),
                ("voice", c.voice),
            )
            if v is not None
        ]
        return f"Change {c.asset_name}: {', '.join(changed)}"
    if c.action == "music":
        return f'New music: "{c.music_prompt}"'
    return c.summary or c.action


def _timeline_labels(ops: list[dict]) -> list[str]:
    out = []
    for op in ops:
        n = op["scene"] + 1
        if op["op"] == "trim":
            parts = []
            if op["cut_start"]:
                parts.append(f"{op['cut_start']:g} s off the start")
            if op["cut_end"]:
                parts.append(f"{op['cut_end']:g} s off the end")
            out.append(f"Trim scene {n}: {' and '.join(parts)}")
        elif op["op"] == "remove":
            out.append(f"Remove scene {n} from the film")
        elif op["op"] == "transition":
            out.append(f"Change scene {n} transition to {op['join']}")
        else:
            out.append(f"Move scene {n} to position {op['to'] + 1}")
    return out


def plan_steps(story: Story, plan: FixPlan, story_set=None) -> list[FixStep]:
    """What will run, in order, for the preview (paid steps are marked)."""
    if not plan.runnable:
        return []
    fx = effects(story, plan, story_set)
    if fx.scenario:
        direction = plan.changes[0].direction
        return [
            FixStep(f"Write the scenario again: {direction}"),
            FixStep("Paint any new people, places or props", paid=True),
            FixStep("Paint every storyboard frame", paid=True),
            FixStep("Make every clip and the film again", paid=True),
        ]
    steps = [
        FixStep(_change_label(story, c)) for c in plan.changes if c.action != "timeline"
    ]
    if fx.set_targets:
        names = sorted({c.asset_name for c in plan.of("set")})
        steps.append(
            FixStep(
                f"Paint the set pictures of {', '.join(names)} again (locked pictures are kept)",
                paid=True,
            )
        )
    if fx.frames:
        steps.append(
            FixStep(f"Paint the storyboard frame of {_numbers(fx.frames)}", paid=True)
        )
    if fx.clips:
        steps.append(
            FixStep(f"Make the video clip of {_numbers(fx.clips)} again", paid=True)
        )
    if fx.remakes_film:
        if story.voice_on and any(
            sc.narration.strip() and not sc.spoken for sc in story.scenes
        ):
            steps.append(FixStep("Record the voiceover lines again", paid=True))
        if fx.music:
            steps.append(FixStep("Make the new music", paid=True))
        if story.makes_alt:
            steps.append(FixStep(f"Update the {story.alt_language} version", paid=True))
        steps.append(FixStep("Stitch the film again (other scenes are kept)"))
    elif fx.music:
        steps.append(FixStep("Make the new music", paid=True))
    steps += [FixStep(label) for label in _timeline_labels(fx.timeline)]
    if fx.timeline or (fx.music and not fx.remakes_film):
        steps.append(FixStep("Export the edited film"))
    return steps


def costs_money(story: Story, plan: FixPlan, story_set=None) -> bool:
    return any(s.paid for s in plan_steps(story, plan, story_set))


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
            for clip, cut, edge in (
                (first, op["cut_start"], "in"),
                (last, op["cut_end"], "out"),
            ):
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
        elif op["op"] == "transition":
            join = str(op.get("join") or "cut").strip().lower()
            if join not in TRANSITION_JOINS:
                continue
            mine[0]["join"] = join
            mine[0]["fade_in"] = 0.5 if join in ("dissolve", "fade_black") else 0.0
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


def with_take(story: Story, index: int) -> list[int]:
    """`index` and the later scenes that continue its take."""
    out = [index]
    j = index + 1
    while j < len(story.scenes) and story.continues_take(j):
        out.append(j)
        j += 1
    return out


# ---------------------------------------------------------------------------
# Planning and running
# ---------------------------------------------------------------------------


def story_set_of(story: Story):
    """The story's set (owner-only), or None."""
    if not story.set_id:
        return None
    from services.story_sets import get_set_store

    try:
        return get_set_store().get(story.set_id, story.owner)
    except Exception:
        return None


def _load(story_id: str, owner: str) -> Story:
    story = get_store().get(story_id, owner)
    if story is None:
        raise StoryAccessError("Story not found.")
    return story


def plan_fix(
    story_id: str,
    owner: str,
    request: str,
    scene: int = -1,
    seconds: float | None = None,
) -> FixPlan:
    """Ask Gemini (one JSON call that watches the film) for the fix. Nothing
    is changed yet."""
    if not request.strip():
        raise ScenarioError("Describe what you would like to change.")
    story = _load(story_id, owner)
    story_set = story_set_of(story)
    backend = get_backend()
    last: Exception | None = None
    for _ in range(2):  # one automatic retry on malformed JSON
        try:
            return parse_fix_plan(
                backend.plan_fix(story, request, scene, seconds), story, story_set
            )
        except ScenarioError as exc:
            last = exc
    raise last or ScenarioError("No fix plan.")


# Story fields an undo never puts back.
# film_versions_json: the films made by the fix stay listed after an undo.
_KEEP_ON_UNDO = (
    "id", "owner", "created_at", "updated_at", "fix_undo_json", "film_versions_json"
)
_KEEP_SET_ON_UNDO = ("id", "owner", "created_at", "updated_at", "version")


def snapshot(story: Story, story_set=None) -> str:
    """The story (and its set) as they are, for undo_fix."""
    data = story.to_dict()
    data.pop("fix_undo_json", None)
    return json.dumps(
        {"story": data, "set": story_set.to_dict() if story_set else None}
    )


def _apply_edits(story_id: str, owner: str, plan: FixPlan) -> str:
    """Keep the story as it was (for undo), then write the plan's text, set,
    music and scene changes. What they make stale is cleared, so the jobs
    that follow make exactly that again."""
    story = _load(story_id, owner)
    story_set = story_set_of(story)
    fx = effects(story, plan, story_set)
    before = snapshot(story, story_set)

    for c in plan.of("set"):
        if story_set is None:
            break

        def change_asset(st, c=c) -> None:
            a = st.asset(c.asset_kind, c.asset_id)
            if a is None:
                return
            if c.description is not None:
                a.description = c.description
            if c.outfit is not None:
                a.outfit = c.outfit
            if c.voice is not None:
                a.voice.description = c.voice

        story_jobs.mutate_set(story_set.id, owner, change_asset)

    def apply(s: Story) -> None:
        s.fix_undo_json = before
        for c in plan.changes:
            if c.action == "scenario":
                s.idea = f"{s.idea.strip()}\n\nRevision: {c.direction}"
                s.brief = ""
            if c.action in ("rewrite_scene", "repaint_frame"):
                if c.scene >= len(s.scenes):
                    raise StoryAccessError("That scene is gone.")
                sc = s.scenes[c.scene]
                if c.narration is not None:
                    sc.narration = c.narration
                    sc.narration_alt = ""
                if c.visual is not None:
                    sc.visual = c.visual
                if c.camera is not None:
                    sc.camera = c.camera
                if c.spoken is not None:
                    sc.spoken = c.spoken
            if c.action == "music":
                s.music_prompt = c.music_prompt
                s.music_on = True
        for i in fx.frames:
            s.scenes[i].frame_uri = ""
        for i in fx.clips:
            s.scenes[i].clear_clip()
        if fx.music and fx.remakes_film:
            s.music_uri = ""  # the video job makes the new music
        if fx.remakes_film or fx.music or fx.scenario:
            s.clear_films()

    story_jobs.mutate_story(story_id, owner, apply)
    return ""


def _follow_ups(story: Story, plan: FixPlan, story_set=None) -> list[tuple[str, list]]:
    """The existing jobs to run after the edit, in order."""
    fx = effects(story, plan, story_set)
    if fx.scenario:
        return [("scenario", []), ("set", []), ("storyboard", []), ("video", [])]
    steps: list[tuple[str, list]] = []
    if fx.set_targets:
        steps.append(("set", fx.set_targets))
    if fx.frames:
        steps.append(("storyboard", fx.frames))
    if fx.remakes_film:
        steps.append(("video", []))
    elif fx.music:
        steps.append(("music", []))
    if fx.timeline:
        steps.append(("timeline", fx.timeline))
    if fx.timeline or (fx.music and not fx.remakes_film):
        steps.append(("export", []))
    return steps


def _start(kind: str, story_id: str, owner: str, args: list):
    if kind == "scenario":
        return story_jobs.start_scenario(story_id, owner)
    if kind == "set":
        return story_jobs.start_set(story_id, owner, args or None)
    if kind == "storyboard":
        return story_jobs.start_storyboard(story_id, owner, args or None)
    if kind == "music":
        return story_jobs.start_music(story_id, owner)
    if kind == "export":
        return story_jobs.start_export(story_id, owner)
    return story_jobs.start_video(story_id, owner)


def _cut(story_id: str, owner: str, ops: list[dict]) -> str:
    story = _load(story_id, owner)
    story_jobs.save_timeline(
        story_id, owner, apply_timeline_ops(story.timeline_json, ops)
    )
    return ""


def _run_chain(job, story_id: str, owner: str, steps: list[tuple[str, list]]) -> None:
    """Run existing jobs one after another inside `job`. Their tasks are
    shown as the fix job's own, so the page draws one progress panel."""
    for kind, args in steps:
        if kind == "timeline":
            task = story_jobs._add_task(job, "Cutting the film", "fix")
            if not story_jobs._run_task(task, lambda a=args: _cut(story_id, owner, a)):
                return
            continue
        sub = _start(kind, story_id, owner, args)
        with story_jobs._jobs_lock:
            job.tasks.extend(sub.tasks)
        sub = story_jobs.wait(sub.id, owner, timeout=4 * 3600)
        if sub is None or sub.status != story_jobs.DONE:
            if sub is not None and sub.message:
                job.message = sub.message
            return


def start_fix(story_id: str, owner: str, plan: FixPlan):
    """Apply a confirmed plan and re-run only what it affects (one "fix" job)."""
    story = _load(story_id, owner)
    if not plan.runnable:
        raise ScenarioError(plan.question or "Nothing to change.")
    for c in plan.changes:
        if c.action in ("rewrite_scene", "repaint_frame") and not 0 <= c.scene < len(
            story.scenes
        ):
            raise ScenarioError("That scene is gone. Describe the fix again.")
    story_set = story_set_of(story)
    steps = _follow_ups(story, plan, story_set)
    job = story_jobs._new_job(owner, story_id, "fix", {"plan": plan.to_dict()})
    first = plan.changes[0].scene if len(plan.changes) == 1 else -1
    edit = story_jobs._add_task(
        job, plan.summary or "Applying the change", "fix", first
    )

    def keep_current(s: Story) -> None:
        # Stories made before versions existed: keep the film being fixed.
        story_versions.remember(s, "before_fix")

    def work(job) -> None:
        before = story.final_uri
        story_jobs.mutate_story(story_id, owner, keep_current)
        if story_jobs._run_task(edit, lambda: _apply_edits(story_id, owner, plan)):
            _run_chain(job, story_id, owner, steps)

            def label(s: Story) -> None:
                if s.final_uri and s.final_uri != before:
                    story_versions.relabel_latest(
                        s, s.final_uri, f"After fix: {plan.summary or 'AI fix'}"
                    )

            story_jobs.mutate_story(story_id, owner, label)

    return story_jobs._spawn(job, work)


def resume_fix(story_id: str, owner: str):
    """Retry a failed fix: the change is already saved, so make what is
    still missing (set pictures, frames, then the film)."""
    story = _load(story_id, owner)
    steps: list[tuple[str, list]] = []
    story_set = story_set_of(story)
    if story_set is not None:
        from services.story_jobs import _set_work

        if _set_work(story_set, None):
            steps.append(("set", []))
    if any(not sc.frame_uri for sc in story.scenes):
        steps.append(("storyboard", []))
    if steps:
        job = story_jobs._new_job(owner, story_id, "fix", {})

        def work(job) -> None:
            _run_chain(job, story_id, owner, steps + [("video", [])])

        return story_jobs._spawn(job, work)
    if not story.final_uri:
        return story_jobs.start_video(story_id, owner)
    return story_jobs.start_export(story_id, owner)


def can_undo(story: Story) -> bool:
    return bool(story.fix_undo_json)


def undo_fix(story_id: str, owner: str) -> Story:
    """Put the story (and its set) back as they were before the last fix:
    its scenes, frames, clips, music, timeline and film. Nothing is made
    again; the earlier media are still stored."""
    story = _load(story_id, owner)
    if not story.fix_undo_json:
        raise ScenarioError("There is no fix to undo.")
    saved = json.loads(story.fix_undo_json)
    old = Story.from_dict(saved.get("story") or {})
    if saved.get("set") and story.set_id:
        from services.story_sets import StorySet

        old_set = StorySet.from_dict(saved["set"])

        def put_set(st) -> None:
            for name in st.__dataclass_fields__:
                if name not in _KEEP_SET_ON_UNDO:
                    setattr(st, name, copy.deepcopy(getattr(old_set, name)))

        story_jobs.mutate_set(story.set_id, owner, put_set)

    def put(s: Story) -> None:
        for name in s.__dataclass_fields__:
            if name not in _KEEP_ON_UNDO:
                setattr(s, name, copy.deepcopy(getattr(old, name)))
        s.fix_undo_json = ""

    return story_jobs.mutate_story(story_id, owner, put)
