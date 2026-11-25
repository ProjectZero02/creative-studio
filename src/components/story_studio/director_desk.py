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
"""The film's working steps for Film Studio (/story), one view each:

- Script: the brief, then one card per take with its lines (split into the
  turns Omni makes) and its camera, prompt, action and sound.
- Set: the cast and places the takes are made from.
- Frames: each take's start frame, with redo.
- Takes: each take's clip, its turns, any cut found in one, and a redo per
  turn.
- Music: music and voice.

The header's main button names the next thing to make.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from common.i18n import tx
from components.story_studio.set_cards import SetHandlers, asset_card, card_key
from components.story_studio.widgets import tx_dots
from services.story_models import (
    CAMERA_IDS,
    CAMERA_PRESETS,
    SHOT_SIZE_IDS,
    SHOT_SIZES,
    VOICES,
    DESK_STEPS,
    Story,
    clip_parts,
    default_music_prompt,
    frame_for,
    frames_ready,
    single_clip_max,
    split_narration_parts,
    supported_durations,
    take_groups,
)
from services.story_service import display_url
from services.story_sets import StorySet
from state.story_state import StoryState

JOIN_PILLS: list[tuple[str, str]] = [
    ("auto", "Auto"),
    ("extend", "Continue"),
    ("cut", "Cut"),
    ("bridge", "Bridge"),
    ("dissolve", "Dissolve"),
    ("fade_black", "Fade"),
]
BUSY_KINDS = ("scenario", "scene", "set", "storyboard", "clips", "video", "translate")


@dataclass
class DeskHandlers:
    on_title_blur: Callable
    on_brief_blur: Callable
    on_visual_grammar_blur: Callable
    on_select_shot: Callable
    on_toggle_preview: Callable
    on_make_set: Callable
    on_paint_all_frames: Callable
    on_render: Callable
    on_to_video: Callable
    on_cancel_job: Callable
    on_rewrite_all: Callable
    on_rewrite_scene: Callable
    on_redo_note: Callable
    on_redo_frame: Callable
    on_redo_clip: Callable
    on_redo_turn: Callable
    on_add_shot: Callable
    on_move_up: Callable
    on_move_down: Callable
    on_remove_scene: Callable
    on_scene_shot_size: Callable
    on_scene_camera: Callable
    on_scene_duration: Callable
    on_scene_visual: Callable
    on_scene_motion_prompt: Callable
    on_scene_audio_cue: Callable
    on_scene_transition: Callable
    on_scene_narration_alt: Callable
    on_toggle_music: Callable
    on_music_prompt: Callable
    on_make_music: Callable
    on_add_track: Callable
    on_track_take: Callable
    on_track_prompt: Callable
    on_remove_track: Callable
    on_toggle_voice: Callable
    on_voice: Callable
    on_speaker_voice: Callable
    on_update_set: Callable
    on_save_set_as_new: Callable
    on_add_asset: Callable
    on_set_field: Callable
    on_animatic_prev: Callable
    on_animatic_next: Callable
    on_animatic_select: Callable
    set_handlers: Callable[[], SetHandlers]
    render_line_fields: Callable
    render_media_box: Callable
    render_progress_panel: Callable
    scene_task: Callable
    job_active_for: Callable
    job_dict: Callable
    set_tasks: Callable
    fmt_secs: Callable[[float], str]
    dir_class: Callable[[str], str]
    sr: Callable[[str], None]
    chip: Callable[[str, str], None]


def _t(text: str, cls: str) -> None:
    """Text with a CSS class (me.text takes no classes)."""
    with me.box(classes=cls):
        me.text(tx_dots(text))


def take_of(groups: list[list[int]], index: int) -> int:
    """Number (0-based) of the take scene `index` belongs to."""
    return next((k for k, g in enumerate(groups) if index in g), 0)


def next_step(story: Story, busy: bool, h: DeskHandlers) -> tuple[str, Callable, bool]:
    """(label, handler, enabled) of the header's main button: the next step."""
    if h.job_active_for("scenario", "scene"):
        return "Writing…", h.on_render, False
    if h.job_active_for("storyboard"):
        return "Painting frames…", h.on_render, False
    if h.job_active_for("video", "clips"):
        return "Making film…", h.on_render, False
    if not story.scenes:
        return "Make film", h.on_render, False
    if not frames_ready(story):
        return "Paint start frames", h.on_paint_all_frames, not busy
    if story.final_uri:
        return "Open film", h.on_to_video, True
    return "Make film", h.on_render, not busy


def render_desk(
    s: StoryState,
    story: Story,
    story_set: StorySet | None,
    *,
    is_demo: bool,
    h: DeskHandlers,
) -> None:
    """Render one desk step: Script, Set, Frames, Takes or Music."""
    view = s.step if s.step in DESK_STEPS else "editor"
    busy_scenario = h.job_active_for("scenario")
    busy_any = h.job_active_for(*BUSY_KINDS)
    groups = take_groups(story)
    total_secs = sum(sc.duration for sc in story.scenes)
    sel = max(0, min(s.selected_shot, len(story.scenes) - 1)) if story.scenes else 0
    label, handler, enabled = next_step(story, busy_any, h)

    with me.box(classes="ss-desk"):
        with me.box(classes="ss-card ss-desk-head"):
            with me.box(classes="ss-desk-top"):
                with me.box(classes="ss-desk-title"):
                    with me.box(classes="ss-grow"):
                        me.input(
                            label="Film title",
                            value=story.title,
                            appearance="outline",
                            disabled=busy_scenario,
                            on_blur=h.on_title_blur,
                            style=me.Style(width="100%"),
                            key=f"title-{story.id}",
                        )
                    _t(
                        f"{len(groups)} take{'s' if len(groups) != 1 else ''}"
                        f" · {h.fmt_secs(total_secs)}",
                        "ss-desk-title-meta",
                    )
                with me.box(classes="ss-desk-actions"):
                    if view in ("storyboard", "editor") and story.scenes:
                        with me.box(
                            classes="ss-pill" + (" is-on" if s.preview_open else "")
                        ):
                            me.button(
                                "Preview",
                                type="stroked",
                                on_click=h.on_toggle_preview,
                                key="ss-desk-preview",
                            )
                    if s.job_running:
                        me.button(
                            "Cancel",
                            type="stroked",
                            on_click=h.on_cancel_job,
                            key="ss-desk-cancel",
                        )
                    me.button(
                        label,
                        type="flat",
                        color="primary",
                        disabled=not enabled,
                        on_click=handler,
                        key="ss-desk-next",
                    )

        h.render_progress_panel("Working on your film", BUSY_KINDS)

        if view == "set":
            _render_set_tab(s, story, story_set, busy_any, is_demo, h)
            return
        if view == "music":
            _render_sound(story, busy_any, h)
            return
        if view == "scenario":
            _render_brief(story, busy_any, h)
        if busy_scenario or not story.scenes:
            _skeleton(story)
            return
        if view == "scenario":
            _render_script(story, groups, busy_any, h)
            return
        if s.preview_open:
            _render_animatic(s, story, h)
        _render_strip(story, groups, sel, h)
        with me.box(classes="ss-canvas"):
            _render_stage(s, story, groups, sel, busy_any, h, takes=view == "editor")
            if view == "editor":
                _render_turns(story, sel, busy_any, h)
            else:
                _render_take_facts(story, groups, sel, h)


def _render_script(
    story: Story, groups: list[list[int]], busy: bool, h: DeskHandlers
) -> None:
    """One card per take: each shot's line in a large box, with the turns it
    is split into, then its camera, prompt, action and sound."""
    for k, group in enumerate(groups):
        secs = sum(story.scenes[i].duration for i in group)
        with me.box(classes="ss-script-take"):
            _t(
                f"Take {k + 1} · {secs}s"
                + (f" · {len(group)} shots" if len(group) > 1 else ""),
                "ss-script-take-head",
            )
            for i in group:
                _render_panel(story, groups, i, busy, h)


def turn_rows(story: Story, index: int) -> list[dict]:
    """The turns of scene `index`: what was made (turn records) or, before
    that, the plan. Each: start, end, lines, and the cuts found in it."""
    sc = story.scenes[index]
    made = sc.turns()
    if made:
        rows = [
            {
                "start": int(t.get("start", 0)),
                "end": int(t.get("start", 0)) + int(t.get("seconds", 0)),
                "lines": t.get("lines", ""),
            }
            for t in made
        ]
    else:
        parts = clip_parts(sc.duration, single_clip_max(story.video_model))
        lines = (
            split_narration_parts(sc.narration, parts)
            if len(parts) > 1 and sc.spoken
            else [sc.narration] + [""] * (len(parts) - 1)
        )
        rows, start = [], 0
        for p, line in zip(parts, lines, strict=False):
            rows.append({"start": start, "end": start + p, "lines": line})
            start += p
    cuts = sc.cuts()
    for k, row in enumerate(rows):
        row["cuts"] = [c for c in cuts if int(c.get("turn", -1)) == k]
    return rows


def _render_turn_split(story: Story, index: int) -> None:
    rows = turn_rows(story, index)
    if len(rows) < 2:
        return
    with me.box(classes="ss-turn-split"):
        for row in rows:
            with me.box(classes="ss-turn-split-row"):
                _t(f"{row['start']}–{row['end']}s", "ss-turn-time")
                _t(row["lines"] or "No line", "ss-turn-lines")


def _render_turns(story: Story, sel: int, busy: bool, h: DeskHandlers) -> None:
    """The take's turns as Omni made them, any cut found in one, and a redo
    per turn."""
    sc = story.scenes[sel]
    rows = turn_rows(story, sel)
    with me.box(classes="ss-card ss-turns"):
        me.text("Turns", style=me.Style(font_size=16, font_weight=600))
        cuts = sc.cuts()
        if sc.clip_uri:
            _t(
                f"Cut found in turn {int(cuts[0].get('turn', 0)) + 1}"
                if cuts
                else "No cuts found",
                "ss-turn-status" + (" is-bad" if cuts else ""),
            )
            for flag in sc.sound():
                _t(sound_note(flag), "ss-sound-flag")
        if len(rows) < 2:
            # One turn: "Redo clip" makes it again.
            return
        for k, row in enumerate(rows):
            with me.box(classes="ss-turn" + (" has-cut" if row["cuts"] else "")):
                with me.box(classes="ss-turn-head"):
                    _t(f"Turn {k + 1} · {row['start']}–{row['end']}s", "ss-turn-name")
                    me.button(
                        "Redo",
                        type="stroked",
                        disabled=busy or not sc.clip_uri,
                        on_click=h.on_redo_turn,
                        key=f"redoturn-{sel}-{k}",
                    )
                if row["lines"]:
                    _t(row["lines"], "ss-turn-lines")


def sound_note(flag: dict) -> str:
    """One sound check result in words."""
    if flag.get("kind") == "level":
        db = float(flag.get("db", 0))
        return (
            f"Turn {int(flag.get('turn', 0)) + 1} is {abs(db):.0f} dB "
            + ("louder" if db > 0 else "quieter")
        )
    return "Background noise under the speech"


def _render_take_facts(
    story: Story, groups: list[list[int]], sel: int, h: DeskHandlers
) -> None:
    """Frames step: what the selected take will be."""
    sc = story.scenes[sel]
    k = take_of(groups, sel)
    group = groups[k]
    with me.box(classes="ss-card ss-take-facts"):
        me.text(f"Take {k + 1}", style=me.Style(font_size=16, font_weight=600))
        _t(
            f"{sum(story.scenes[i].duration for i in group)}s · "
            f"{SHOT_SIZES.get(sc.shot_size, 'Medium shot')} · "
            f"{CAMERA_PRESETS.get(sc.camera, CAMERA_PRESETS['static'])['label']}",
            "ss-muted ss-small",
        )
        if sc.narration.strip():
            me.text(
                tx("On camera: " if sc.spoken else "Voiceover: ")
                + sc.narration.strip(),
                style=me.Style(font_size=14),
            )


def _skeleton(story: Story) -> None:
    with me.box(classes="ss-strip"):
        for i in range(max(1, story.scene_count)):
            with me.box(classes="ss-strip-shot ss-skeleton-card"):
                me.box(classes="ss-skel ss-skel-block")
                _t(f"Shot {i + 1}", "ss-strip-label")


def _thumb(uri: str, aspect: str, alt: str) -> None:
    ar = "ss-ar-916" if aspect == "9:16" else "ss-ar-169"
    with me.box(classes=f"ss-media {ar}"):
        if uri:
            me.image(
                src=display_url(uri),
                alt=alt,
                style=me.Style(width="100%", height="100%", object_fit="cover"),
            )
        else:
            with me.box(classes="ss-media-overlay"):
                me.icon("image")


def _render_strip(
    story: Story, groups: list[list[int]], sel: int, h: DeskHandlers
) -> None:
    with me.box(classes="ss-strip", key="ss-strip"):
        for k, group in enumerate(groups):
            secs = sum(story.scenes[i].duration for i in group)
            with me.box(
                classes="ss-take" + (" is-continuous" if len(group) > 1 else "")
            ):
                with me.box(classes="ss-take-head"):
                    _t(f"Take {k + 1}", "ss-take-name")
                    _t(f"continuous · {secs}s", "ss-take-badge")
                with me.box(classes="ss-take-shots"):
                    for pos, i in enumerate(group):
                        sc = story.scenes[i]
                        task = h.scene_task("frame", group[0]) or h.scene_task(
                            "clip", i
                        )
                        running = (task or {}).get("status") in ("running", "queued")
                        with me.box(
                            classes="ss-strip-shot"
                            + (" is-on" if i == sel else "")
                            + (" is-cont" if pos else "")
                            + (" is-busy" if running else ""),
                            on_click=h.on_select_shot,
                            key=f"shot-{i}",
                        ):
                            _thumb(
                                frame_for(story, i), story.aspect_ratio, f"Shot {i + 1}"
                            )
                            _t(
                                f"{i + 1} · {sc.duration}s"
                                + (" · clip" if sc.clip_uri else ""),
                                "ss-strip-label",
                            )


def _render_stage(
    s: StoryState,
    story: Story,
    groups: list[list[int]],
    sel: int,
    busy: bool,
    h: DeskHandlers,
    takes: bool = True,
) -> None:
    """The selected take: its clip (Takes) or start frame (Frames)."""
    sc = story.scenes[sel]
    k = take_of(groups, sel)
    start = groups[k][0]
    continues = sel != start
    frame_task = h.scene_task("frame", start)
    clip_task = h.scene_task("clip", sel)
    task = next(
        (
            t
            for t in (clip_task, frame_task)
            if t and t.get("status") in ("running", "queued", "failed")
        ),
        None,
    )
    show_video = takes and bool(sc.clip_uri) and not (
        clip_task and clip_task.get("status") in ("running", "queued")
    )
    if not takes:
        task = (
            frame_task
            if frame_task and frame_task.get("status") in ("running", "queued", "failed")
            else None
        )
    with me.box(classes="ss-card ss-stage"):
        h.render_media_box(
            sc.clip_uri if show_video else frame_for(story, sel),
            story.aspect_ratio,
            task,
            f"Shot {sel + 1}",
            video=show_video,
        )
        if show_video:
            caption = f"Clip of shot {sel + 1} · take {k + 1}"
        elif continues:
            caption = f"Continues take {k + 1} from shot {start + 1}"
        else:
            caption = f"Start frame of take {k + 1}"
        _t(caption, "ss-muted ss-small")
        me.textarea(
            label="Redo with note",
            value=s.redo_note,
            rows=2,
            appearance="outline",
            placeholder="Warmer light, the speaker a little further left",
            on_blur=h.on_redo_note,
            style=me.Style(width="100%"),
            key=f"redo-note-{sel}",
        )
        with me.box(classes="ss-redo-row"):
            if takes:
                me.button(
                    "Redo clip",
                    type="stroked",
                    disabled=busy or not frame_for(story, sel),
                    on_click=h.on_redo_clip,
                    key=f"redoc-{sel}",
                )
            else:
                me.button(
                    "Redo frame",
                    type="stroked",
                    disabled=busy,
                    on_click=h.on_redo_frame,
                    key=f"redof-{sel}",
                )


def _render_panel(
    story: Story, groups: list[list[int]], sel: int, busy: bool, h: DeskHandlers
) -> None:
    sc = story.scenes[sel]
    i = sel
    rewriting = h.job_active_for("scene") and (h.scene_task("scenario", i) or {}).get(
        "status"
    ) in ("queued", "running")
    alt = story.alt_language
    with me.box(classes="ss-card ss-shot-panel" + (" is-busy" if rewriting else "")):
        with me.box(classes="ss-row-head"):
            with me.box(classes="ss-badge"):
                me.text(f"Shot {i + 1}")
            if sc.sequence:
                h.chip(sc.sequence, "")
            with me.box(classes="ss-row-tools"):
                for icon, label, handler, dis, k in [
                    ("autorenew", "Rewrite shot", h.on_rewrite_scene, busy, f"rw-{i}"),
                    ("add", "Add shot after", h.on_add_shot, busy, f"addshot-{sc.id}"),
                    (
                        "arrow_upward",
                        "Move up",
                        h.on_move_up,
                        busy or i == 0,
                        f"moveup-{sc.id}",
                    ),
                    (
                        "arrow_downward",
                        "Move down",
                        h.on_move_down,
                        busy or i == len(story.scenes) - 1,
                        f"movedown-{sc.id}",
                    ),
                    (
                        "delete_outline",
                        "Delete shot",
                        h.on_remove_scene,
                        busy or len(story.scenes) <= 1,
                        f"removeseq-{sc.id}",
                    ),
                ]:
                    with me.tooltip(message=label):
                        with me.content_button(
                            type="icon", disabled=dis, on_click=handler, key=k
                        ):
                            me.icon(icon)
                            h.sr(f"{tx(label)}: shot {i + 1}")
        if rewriting:
            with me.box(classes="ss-busy-line"):
                me.box(classes="ss-spinner")
                me.text("Rewriting this shot…", style=me.Style(font_size=13))
        with me.box(classes="ss-row-selects"):
            me.select(
                label="Shot size",
                options=[
                    me.SelectOption(label=SHOT_SIZES[k], value=k) for k in SHOT_SIZE_IDS
                ],
                value=sc.shot_size if sc.shot_size in SHOT_SIZES else "medium",
                appearance="outline",
                disabled=busy,
                on_selection_change=h.on_scene_shot_size,
                key=f"sz-{sc.id}",
            )
            me.select(
                label="Camera",
                options=[
                    me.SelectOption(label=CAMERA_PRESETS[c]["label"], value=c)
                    for c in CAMERA_IDS
                ],
                value=sc.camera if sc.camera in CAMERA_IDS else "static",
                appearance="outline",
                disabled=busy,
                on_selection_change=h.on_scene_camera,
                key=f"ecam-{sc.id}",
            )
            me.select(
                label="Length",
                options=[
                    me.SelectOption(label=f"{d}s", value=str(d))
                    for d in supported_durations(story.video_model)
                ],
                value=str(sc.duration),
                appearance="outline",
                disabled=busy,
                on_selection_change=h.on_scene_duration,
                key=f"dur-{sc.id}",
            )
        h.render_line_fields(story, sc, "e", disabled=busy)
        _render_turn_split(story, i)
        if story.makes_alt and sc.narration.strip():
            with me.box(classes=h.dir_class(alt)):
                me.textarea(
                    label=f"Line ({alt})",
                    value=sc.narration_alt,
                    placeholder="Translated when you make the film",
                    rows=2,
                    appearance="outline",
                    disabled=busy,
                    on_blur=h.on_scene_narration_alt,
                    style=me.Style(width="100%"),
                    key=f"anar-{sc.id}",
                )
        me.textarea(
            label="Prompt",
            value=sc.visual,
            rows=3,
            appearance="outline",
            disabled=busy,
            on_blur=h.on_scene_visual,
            style=me.Style(width="100%"),
            key=f"evis-{sc.id}",
        )
        me.textarea(
            label="Action",
            value=sc.motion_prompt,
            rows=2,
            appearance="outline",
            disabled=busy,
            on_blur=h.on_scene_motion_prompt,
            style=me.Style(width="100%"),
            key=f"mot-{sc.id}",
        )
        me.input(
            label="Sound",
            value=sc.audio_cue,
            appearance="outline",
            disabled=busy,
            on_blur=h.on_scene_audio_cue,
            style=me.Style(width="100%"),
            key=f"aud-{sc.id}",
        )
        if i > 0:
            cur = sc.transition or "auto"
            with me.box(classes="ss-join-bar"):
                _t(f"From shot {i}", "ss-join-label")
                for tid, tlabel in JOIN_PILLS:
                    with me.box(
                        classes="ss-join-pill" + (" is-on" if cur == tid else "")
                    ):
                        me.button(
                            tlabel,
                            type="stroked",
                            disabled=busy,
                            on_click=h.on_scene_transition,
                            key=f"tr|{sc.id}|{tid}",
                        )


def _render_brief(story: Story, busy: bool, h: DeskHandlers) -> None:
    """The brief, on top of the script, in a box that grows to 8 lines."""
    if not (story.brief or story.visual_grammar):
        return
    with me.box(classes="ss-card ss-desk-brief"):
        with me.box(classes="ss-desk-brief-head"):
            me.text("Brief", style=me.Style(font_size=14, font_weight=600))
            me.button(
                "Rewrite breakdown",
                type="stroked",
                on_click=h.on_rewrite_all,
                disabled=busy,
                key="ss-desk-rewrite-all",
            )
        if story.brief:
            me.textarea(
                label="Film brief",
                value=story.brief,
                autosize=True,
                min_rows=2,
                max_rows=8,
                appearance="outline",
                disabled=busy,
                on_blur=h.on_brief_blur,
                style=me.Style(width="100%"),
                key=f"brief-{story.id}",
            )
        if story.visual_grammar:
            me.input(
                label="Look",
                value=story.visual_grammar,
                appearance="outline",
                disabled=busy,
                on_blur=h.on_visual_grammar_blur,
                style=me.Style(width="100%"),
                key=f"vg-{story.id}",
            )


def _render_sound(story: Story, busy: bool, h: DeskHandlers) -> None:
    """Music step: the film's music and voices, then extra music tracks."""
    _render_voices_and_music(story, busy, h)
    if story.music_on:
        _render_tracks(story, busy, h)


def _render_tracks(story: Story, busy: bool, h: DeskHandlers) -> None:
    """Extra music tracks, each under the takes picked for it. The film's
    music plays wherever no track does."""
    groups = take_groups(story)
    tracks = story.music_tracks()
    making = h.job_active_for("music")
    used = {k for t in tracks for k in t.get("takes", [])}
    free = [k for k in range(len(groups)) if k not in used]
    with me.box(classes="ss-card ss-tracks"):
        with me.box(classes="ss-tracks-head"):
            me.text("Tracks", style=me.Style(font_size=16, font_weight=600))
            with me.box(classes="ss-tracks-tools"):
                me.button(
                    "Add track",
                    type="stroked",
                    disabled=busy or not free,
                    on_click=h.on_add_track,
                    key="ss-add-track",
                )
                me.button(
                    "Making…" if making else "Make music",
                    type="flat",
                    color="primary",
                    disabled=busy,
                    on_click=h.on_make_music,
                    key="ss-make-music",
                )
        _t(
            "Film music: every take"
            if not tracks
            else "Film music: takes " + ", ".join(str(k + 1) for k in free)
            if free
            else "Film music: none",
            "ss-muted ss-small",
        )
        for n, t in enumerate(tracks):
            tid = t.get("id", "")
            with me.box(classes="ss-track"):
                with me.box(classes="ss-track-head"):
                    _t(
                        f"Track {n + 1} · " + ("made" if t.get("uri") else "not made yet"),
                        "ss-track-name",
                    )
                    me.button(
                        "Remove",
                        type="stroked",
                        disabled=busy,
                        on_click=h.on_remove_track,
                        key=f"trdel|{tid}",
                    )
                with me.box(classes="ss-chip-row ss-track-takes"):
                    for k in range(len(groups)):
                        on = k in (t.get("takes") or [])
                        with me.box(classes="ss-pill" + (" is-on" if on else "")):
                            me.button(
                                f"Take {k + 1}",
                                type="stroked",
                                disabled=busy,
                                on_click=h.on_track_take,
                                key=f"trtake|{tid}|{k}",
                            )
                me.textarea(
                    label="Music prompt",
                    value=t.get("prompt", ""),
                    placeholder=story.music_prompt or default_music_prompt(story),
                    autosize=True,
                    min_rows=2,
                    max_rows=5,
                    appearance="outline",
                    disabled=busy,
                    on_blur=h.on_track_prompt,
                    style=me.Style(width="100%"),
                    key=f"trprompt|{tid}",
                )


def _render_voices_and_music(story: Story, busy: bool, h: DeskHandlers) -> None:
    with me.box(classes="ss-card ss-sound-drawer"):
        with me.box(classes="ss-sound-grid"):
            with me.box(classes="ss-sound-col"):
                me.slide_toggle(
                    "Music",
                    checked=story.music_on,
                    disabled=busy,
                    on_change=h.on_toggle_music,
                    key="ss-music-on",
                )
                if story.music_on:
                    me.textarea(
                        label="Music prompt",
                        value=story.music_prompt or default_music_prompt(story),
                        rows=2,
                        appearance="outline",
                        disabled=busy,
                        on_blur=h.on_music_prompt,
                        style=me.Style(width="100%"),
                        key="ss-music",
                    )
                # A film spoken entirely on camera has no narrator.
                all_on_camera = bool(story.scenes) and all(
                    sc.spoken for sc in story.scenes
                )
                if not all_on_camera:
                    me.slide_toggle(
                        "Narrator voice",
                        checked=story.voice_on,
                        disabled=busy,
                        on_change=h.on_toggle_voice,
                        key="ss-voice-on",
                    )
                if story.voice_on and not all_on_camera:
                    me.select(
                        label="Voice",
                        options=[me.SelectOption(label=v, value=v) for v in VOICES],
                        value=story.voice_name,
                        appearance="outline",
                        disabled=busy,
                        on_selection_change=h.on_voice,
                        style=me.Style(width="100%"),
                        key="ss-voice",
                    )
                if story.has_spoken:
                    me.input(
                        label="Voice of the person on screen",
                        value=story.speaker_voice,
                        placeholder="A calm, confident voice, mid-30s",
                        appearance="outline",
                        disabled=busy,
                        on_blur=h.on_speaker_voice,
                        style=me.Style(width="100%"),
                        key="ss-speaker-voice",
                    )


def _render_set_tab(
    s: StoryState,
    story: Story,
    st: StorySet | None,
    busy: bool,
    is_demo: bool,
    h: DeskHandlers,
) -> None:
    """The References tray: the story's cast, places and props."""
    if st is None:
        with me.box(classes="ss-card ss-set-empty"):
            me.text("Set", style=me.Style(font_size=18, font_weight=600))
            with me.box(classes="ss-set-tools"):
                me.button(
                    "Making…" if h.job_active_for("set") else "Make cast and set",
                    type="flat",
                    color="primary",
                    disabled=busy,
                    on_click=h.on_make_set,
                    key="ss-make-set",
                )
        return

    missing = st.missing_images()
    tasks = h.set_tasks() if busy or (h.job_dict() or {}).get("kind") == "set" else {}
    with me.box(classes="ss-card ss-set-head"):
        with me.box(classes="ss-set-name"):
            me.input(
                label="Set name",
                value=st.name,
                appearance="outline",
                disabled=busy,
                on_blur=h.on_set_field,
                style=me.Style(width="100%"),
                key=card_key("setname", "", st.id),
            )
            meta = f"{st.summary()} · version {st.version}"
            if missing:
                meta += f" · {missing} image{'s' if missing != 1 else ''} to make"
            if s.set_dirty:
                meta += " · unsaved"
            _t(meta, "ss-muted ss-small")
        with me.box(classes="ss-set-tools"):
            me.button(
                "Making…" if h.job_active_for("set") else "Make images",
                type="flat",
                color="primary",
                disabled=busy or not missing,
                on_click=h.on_make_set,
                key="ss-make-set",
            )
            me.button(
                "Update set",
                type="stroked",
                disabled=busy or not s.set_dirty,
                on_click=h.on_update_set,
                key="ss-update-set",
            )
            me.button(
                "Save as new",
                type="stroked",
                disabled=busy,
                on_click=h.on_save_set_as_new,
                key="ss-save-new-set",
            )

    sh = h.set_handlers()
    for kind, title, assets, add in (
        ("character", "Characters", st.characters, "Add character"),
        ("location", "Locations", st.locations, "Add location"),
        ("prop", "Objects", st.props, "Add object"),
    ):
        with me.box(classes="ss-set-section"):
            with me.box(classes="ss-set-section-head"):
                me.text(title, style=me.Style(font_size=16, font_weight=600))
                me.button(
                    add,
                    type="stroked",
                    disabled=busy,
                    on_click=h.on_add_asset,
                    key=f"add|{kind}",
                )
            if assets:
                with me.box(classes="ss-set-grid"):
                    for asset in assets:
                        asset_card(
                            kind,
                            asset,
                            tasks=tasks,
                            h=sh,
                            busy=busy,
                            playing=s.play_sample_id,
                            demo=is_demo,
                        )


def _render_animatic(s: StoryState, story: Story, h: DeskHandlers) -> None:
    """Preview: the shots one after another with their lines."""
    idx = max(0, min(s.animatic_index, len(story.scenes) - 1))
    sc = story.scenes[idx]
    ar = "ss-ar-916 ss-player-portrait" if story.aspect_ratio == "9:16" else "ss-ar-169"
    uri = frame_for(story, idx)
    with me.box(classes="ss-card ss-preview"):
        with me.box(classes="ss-animatic"):
            with me.box(classes="ss-animatic-stage"):
                with me.box(classes=f"ss-animatic-frame ss-media {ar}"):
                    if sc.clip_uri:
                        me.video(
                            src=display_url(sc.clip_uri),
                            style=me.Style(width="100%", height="100%"),
                        )
                    elif uri:
                        me.image(
                            src=display_url(uri),
                            alt=f"Shot {idx + 1}",
                            style=me.Style(
                                width="100%", height="100%", object_fit="cover"
                            ),
                        )
                    else:
                        with me.box(classes="ss-media-overlay"):
                            me.icon("image")
                    if sc.narration.strip():
                        with me.box(classes="ss-animatic-caption"):
                            me.text(sc.narration.strip())
                with me.box(classes="ss-animatic-controls"):
                    me.button(
                        "Previous",
                        type="stroked",
                        disabled=idx <= 0,
                        on_click=h.on_animatic_prev,
                        key="ss-anim-prev",
                    )
                    _t(f"{idx + 1} / {len(story.scenes)}", "ss-animatic-count")
                    me.button(
                        "Next",
                        type="stroked",
                        disabled=idx >= len(story.scenes) - 1,
                        on_click=h.on_animatic_next,
                        key="ss-anim-next",
                    )
            with me.box(classes="ss-animatic-info"):
                me.text(
                    f"Shot {idx + 1}", style=me.Style(font_size=16, font_weight=600)
                )
                _t(
                    f"{SHOT_SIZES.get(sc.shot_size, 'Medium shot')} · "
                    f"{CAMERA_PRESETS.get(sc.camera, CAMERA_PRESETS['static'])['label']} · "
                    f"{sc.duration}s",
                    "ss-muted ss-small",
                )
                if sc.narration.strip():
                    me.text(
                        tx("On camera: " if sc.spoken else "Voiceover: ")
                        + sc.narration.strip(),
                        style=me.Style(font_size=14),
                    )
                _t(sc.visual, "ss-muted ss-small")
