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
"""Director's Desk UI for Story Studio (/story)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from components.story_studio.set_cards import SetHandlers, asset_card, card_key
from services.story_models import (
    CAMERA_IDS,
    CAMERA_PRESETS,
    SHOT_SIZE_IDS,
    SHOT_SIZES,
    VOICES,
    Story,
    default_music_prompt,
    supported_durations,
)
from services.story_service import display_url
from services.story_sets import StorySet
from state.story_state import StoryState

JOIN_PILLS: list[tuple[str, str]] = [
    ("auto", "Auto"),
    ("cut", "Cut"),
    ("bridge", "Bridge"),
    ("extend", "Extend"),
    ("dissolve", "Dissolve"),
    ("fade_black", "Fade black"),
]


@dataclass
class DeskHandlers:
    on_title_blur: Callable
    on_brief_blur: Callable
    on_visual_grammar_blur: Callable
    on_desk_tab: Callable
    on_seq_filter: Callable
    on_toggle_soundtrack: Callable
    on_make_set: Callable
    on_paint_all_frames: Callable
    on_render: Callable
    on_cancel_job: Callable
    on_rewrite_all: Callable
    on_rewrite_scene: Callable
    on_regen_frame: Callable
    on_animate_shot: Callable
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
    on_toggle_shot_details: Callable
    on_scene_transition: Callable
    on_scene_narration_alt: Callable
    on_toggle_music: Callable
    on_music_prompt: Callable
    on_toggle_voice: Callable
    on_voice: Callable
    on_speaker_voice: Callable
    on_toggle_continuous_takes: Callable
    on_toggle_second: Callable
    on_translate_again: Callable
    on_toggle_continuity: Callable
    on_toggle_seamless_joins: Callable
    on_toggle_color_match: Callable
    on_update_set: Callable
    on_save_set_as_new: Callable
    on_add_asset: Callable
    on_set_field: Callable
    on_animatic_prev: Callable
    on_animatic_next: Callable
    on_animatic_select: Callable
    on_animatic_open_shot: Callable
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


def _sequences(story: Story) -> list[tuple[str, str]]:
    """Return [(match_key, display_title), ...] for sequence filtering."""
    out: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    if story.sequences_json:
        try:
            raw = json.loads(story.sequences_json)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        key = str(item.get("key") or item.get("title") or "").strip()
                        title = str(item.get("title") or key).strip()
                    else:
                        key = title = str(item or "").strip()
                    if key and key not in seen_keys:
                        seen_keys.add(key)
                        out.append((key, title))
        except ValueError:
            pass
    known_titles = {t for _, t in out}
    for sc in story.scenes:
        seq = (sc.sequence or "").strip()
        if seq and seq not in seen_keys and seq not in known_titles:
            seen_keys.add(seq)
            out.append((seq, seq))
    return out


def _seq_matches(sc, active_filter: str, seq_map: dict[str, str]) -> bool:
    if active_filter == "all":
        return True
    val = (sc.sequence or "").strip()
    return val == active_filter or val == seq_map.get(active_filter, "")


def _expanded_ids(s: StoryState) -> set[str]:
    try:
        raw = json.loads(s.expanded_shots_json or "[]")
        return set(raw) if isinstance(raw, list) else set()
    except ValueError:
        return set()


def render_desk(
    s: StoryState,
    story: Story,
    story_set: StorySet | None,
    *,
    is_demo: bool,
    h: DeskHandlers,
) -> None:
    """Render the unified Director's Desk (Shots & Storyboard | Cast & Set | Animatic)."""
    busy_scenario = h.job_active_for("scenario")
    busy_any = h.job_active_for(
        "scenario", "scene", "set", "storyboard", "clips", "video", "translate"
    )
    all_frames = bool(story.scenes) and all(sc.frame_uri for sc in story.scenes)
    total_secs = sum(sc.duration for sc in story.scenes)
    seqs = _sequences(story)
    seq_map = dict(seqs)
    valid_filters = {k for k, _ in seqs} | set(seq_map.values())
    active_filter = s.seq_filter if s.seq_filter in valid_filters else "all"
    tab = s.desk_tab if s.desk_tab in ("shots", "set", "animatic") else "shots"

    with me.box(classes="ss-desk"):
        # Header bar
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
                    with me.box(classes="ss-desk-title-meta"):
                        me.text(
                            f"{len(story.scenes)} shots · ≈ {h.fmt_secs(total_secs)} · {story.aspect_ratio}",
                        )
                with me.box(classes="ss-desk-actions"):
                    me.button(
                        "Soundtrack",
                        type="stroked",
                        on_click=h.on_toggle_soundtrack,
                        key="ss-desk-soundtrack",
                    )
                    me.button(
                        "Making set…" if h.job_active_for("set") else "Make set",
                        type="stroked",
                        disabled=busy_any
                        or (story_set is not None and story_set.missing_images() == 0),
                        on_click=h.on_make_set,
                        key="ss-desk-make-set",
                    )
                    me.button(
                        "Painting…"
                        if h.job_active_for("storyboard")
                        else (
                            "Paint all frames" if not all_frames else "Repaint frames"
                        ),
                        type="stroked",
                        disabled=busy_any or not story.scenes,
                        on_click=h.on_paint_all_frames,
                        key="ss-desk-paint-all",
                    )
                    me.button(
                        "Rendering…" if h.job_active_for("video") else "Render film",
                        type="flat",
                        color="primary",
                        disabled=busy_any or not all_frames,
                        on_click=h.on_render,
                        key="ss-desk-render",
                    )
                    if s.job_running:
                        me.button(
                            "Cancel",
                            type="stroked",
                            color="warn",
                            on_click=h.on_cancel_job,
                            key="ss-desk-cancel",
                        )

            if seqs:
                with me.box(classes="ss-seq-row"):
                    with me.box(
                        classes="ss-seq-pill"
                        + (" is-on" if active_filter == "all" else "")
                    ):
                        me.button(
                            f"All shots ({len(story.scenes)})",
                            type="stroked",
                            on_click=h.on_seq_filter,
                            key="seq|all",
                        )
                    for idx, (skey, stitle) in enumerate(seqs):
                        count = sum(
                            1 for sc in story.scenes if _seq_matches(sc, skey, seq_map)
                        )
                        is_on = active_filter in (skey, stitle)
                        with me.box(
                            classes="ss-seq-pill" + (" is-on" if is_on else "")
                        ):
                            me.button(
                                f"Seq {idx + 1}: {stitle} ({count})" if count else stitle,
                                type="stroked",
                                on_click=h.on_seq_filter,
                                key=f"seq|{skey}",
                            )

        # Collapsible Soundtrack & Continuity drawer
        if s.soundtrack_open:
            _render_soundtrack_drawer(story, busy_any, h)

        # Desk Sub-bar
        with me.box(classes="gm-segmented ss-desk-tabs"):
            me.button_toggle(
                value=tab,
                buttons=[
                    me.ButtonToggleButton(label="Shots & Storyboard", value="shots"),
                    me.ButtonToggleButton(label="Cast & Set", value="set"),
                    me.ButtonToggleButton(label="Animatic Preview", value="animatic"),
                ],
                multiple=False,
                hide_selection_indicator=True,
                on_change=h.on_desk_tab,
                key="ss-desk-tabs",
            )

        # Active job progress panel
        h.render_progress_panel(
            "Working on your film",
            ("scenario", "scene", "set", "storyboard", "clips", "video", "translate"),
        )

        if tab == "set":
            _render_set_tab(s, story, story_set, busy_any, is_demo, h)
        elif tab == "animatic":
            _render_animatic_tab(s, story, busy_any, h)
        else:
            _render_shots_tab(
                s, story, active_filter, seq_map, busy_scenario, busy_any, h
            )


def _render_soundtrack_drawer(story: Story, busy: bool, h: DeskHandlers) -> None:
    alt = story.alt_language
    with me.box(classes="ss-card ss-sound-drawer"):
        me.text(
            "Soundtrack, Voice & Continuity",
            style=me.Style(font_size=15, font_weight=600),
        )
        with me.box(classes="ss-sound-grid"):
            with me.box(classes="ss-sound-col"):
                me.slide_toggle(
                    "Music (Lyria)",
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
                me.slide_toggle(
                    "Narrator voiceover (Gemini TTS)",
                    checked=story.voice_on,
                    disabled=busy,
                    on_change=h.on_toggle_voice,
                    key="ss-voice-on",
                )
                if story.voice_on:
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
                        placeholder="e.g. a calm, confident male voice, mid-30s",
                        appearance="outline",
                        disabled=busy,
                        on_blur=h.on_speaker_voice,
                        style=me.Style(width="100%"),
                        key="ss-speaker-voice",
                    )

            with me.box(classes="ss-sound-col"):
                me.slide_toggle(
                    "Color-match adjacent cuts",
                    checked=story.color_match,
                    disabled=busy,
                    on_change=h.on_toggle_color_match,
                    key="ss-color-match",
                )
                me.slide_toggle(
                    "Continuity: start each clip from the last frame of the one before",
                    checked=story.continuity,
                    disabled=busy,
                    on_change=h.on_toggle_continuity,
                    key="ss-continuity",
                )
                if story.continuity:
                    me.slide_toggle(
                        "Seamless joins: cut between continued scenes",
                        checked=story.seamless_joins,
                        disabled=busy,
                        on_change=h.on_toggle_seamless_joins,
                        key="ss-seamless-joins",
                    )
                if story.has_spoken:
                    me.slide_toggle(
                        "One take for back-to-back spoken scenes",
                        checked=story.continuous_takes,
                        disabled=busy,
                        on_change=h.on_toggle_continuous_takes,
                        key="ss-takes",
                    )
                if story.voice_on or story.has_spoken:
                    me.slide_toggle(
                        f"Also make an {alt} version",
                        checked=story.second_on,
                        disabled=busy,
                        on_change=h.on_toggle_second,
                        key="ss-second-on",
                    )
                    if story.second_on:
                        me.button(
                            "Translating…"
                            if h.job_active_for("translate")
                            else f"Translate again into {alt}",
                            type="stroked",
                            disabled=busy,
                            on_click=h.on_translate_again,
                            key="ss-translate",
                        )


def _render_shots_tab(
    s: StoryState,
    story: Story,
    active_filter: str,
    seq_map: dict[str, str],
    busy_scenario: bool,
    busy_any: bool,
    h: DeskHandlers,
) -> None:
    if busy_scenario or not story.scenes:
        with me.box(classes="ss-scenes"):
            for i in range(max(1, story.scene_count)):
                with me.box(classes="ss-card ss-scene ss-skeleton-card"):
                    me.text(f"Shot {i + 1}", style=me.Style(font_weight=600))
                    me.box(classes="ss-skel ss-skel-line")
                    me.box(classes="ss-skel ss-skel-line short")
                    me.box(classes="ss-skel ss-skel-block")
        return

    if story.brief or story.visual_grammar:
        with me.box(classes="ss-card ss-desk-brief"):
            with me.box(classes="ss-desk-brief-head"):
                me.text(
                    "Brief & Visual Grammar",
                    style=me.Style(font_size=14, font_weight=600),
                )
                with me.content_button(
                    type="stroked",
                    on_click=h.on_rewrite_all,
                    disabled=busy_any,
                    key="ss-desk-rewrite-all",
                ):
                    with me.box(classes="ss-btn-inner"):
                        me.icon(
                            "autorenew",
                            style=me.Style(font_size=18, width=18, height=18),
                        )
                        me.text("Rewrite breakdown")
            if story.brief:
                me.textarea(
                    label="Film brief",
                    value=story.brief,
                    rows=2,
                    appearance="outline",
                    disabled=busy_any,
                    on_blur=h.on_brief_blur,
                    style=me.Style(width="100%"),
                    key=f"brief-{story.id}",
                )
            if story.visual_grammar:
                me.input(
                    label="Visual grammar lock",
                    value=story.visual_grammar,
                    appearance="outline",
                    disabled=busy_any,
                    on_blur=h.on_visual_grammar_blur,
                    style=me.Style(width="100%"),
                    key=f"vg-{story.id}",
                )

    job = h.job_dict()
    job_kind = (job or {}).get("kind", "")
    alt = story.alt_language
    expanded = _expanded_ids(s)
    visible_indices = [
        i
        for i, sc in enumerate(story.scenes)
        if _seq_matches(sc, active_filter, seq_map)
    ]

    with me.box(classes="ss-editor-list"):
        for pos, i in enumerate(visible_indices):
            sc = story.scenes[i]
            frame_task = (
                h.scene_task("frame", i) if job_kind == "storyboard" else None
            )
            clip_task = (
                h.scene_task("clip", i) if job_kind in ("video", "clips") else None
            )
            rewriting = h.job_active_for("scene") and (
                h.scene_task("scenario", i) or {}
            ).get("status") in ("queued", "running")
            active_task = (
                clip_task
                if clip_task and clip_task.get("status") in ("running", "queued", "failed")
                else (
                    frame_task
                    if frame_task
                    and frame_task.get("status") in ("running", "queued", "failed")
                    else None
                )
            )
            media_uri = sc.clip_uri or sc.frame_uri
            show_video = bool(sc.clip_uri) and not (
                clip_task and clip_task.get("status") in ("running", "queued")
            )

            with me.box(classes="ss-card ss-row" + (" is-busy" if rewriting else "")):
                with me.box(classes="ss-row-media"):
                    h.render_media_box(
                        media_uri,
                        story.aspect_ratio,
                        active_task,
                        f"Shot {i + 1}",
                        video=show_video,
                    )
                    with me.box(classes="ss-shot-media-actions"):
                        me.button(
                            "Paint frame",
                            type="stroked",
                            disabled=busy_any,
                            on_click=h.on_regen_frame,
                            key=f"rf-{i}",
                        )
                        me.button(
                            "Animate shot",
                            type="stroked",
                            disabled=busy_any or not sc.frame_uri,
                            on_click=h.on_animate_shot,
                            key=f"ac-{i}",
                        )
                    if sc.clip_uri:
                        h.chip(
                            f"Clip ready · {sc.video_model_used}"
                            if sc.video_model_used
                            else "Clip ready",
                            "ss-chip-done",
                        )

                with me.box(classes="ss-row-body"):
                    with me.box(classes="ss-row-head"):
                        with me.box(classes="ss-badge"):
                            me.text(f"Shot {i + 1}")
                        if sc.sequence:
                            h.chip(seq_map.get(sc.sequence, sc.sequence), "")
                        with me.box(classes="ss-row-selects"):
                            me.select(
                                label="Shot size",
                                options=[
                                    me.SelectOption(label=SHOT_SIZES[k], value=k)
                                    for k in SHOT_SIZE_IDS
                                ],
                                value=sc.shot_size
                                if sc.shot_size in SHOT_SIZES
                                else "medium",
                                appearance="outline",
                                disabled=busy_any,
                                on_selection_change=h.on_scene_shot_size,
                                style=me.Style(width=148),
                                key=f"sz-{sc.id}",
                            )
                            me.select(
                                label="Camera",
                                options=[
                                    me.SelectOption(
                                        label=CAMERA_PRESETS[c]["label"], value=c
                                    )
                                    for c in CAMERA_IDS
                                ],
                                value=sc.camera,
                                appearance="outline",
                                disabled=busy_any,
                                on_selection_change=h.on_scene_camera,
                                style=me.Style(width=140),
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
                                disabled=busy_any,
                                on_selection_change=h.on_scene_duration,
                                style=me.Style(width=110),
                                key=f"dur-{sc.id}",
                            )
                        with me.box(classes="ss-row-tools"):
                            for icon, label, handler, dis, k in [
                                (
                                    "autorenew",
                                    "Rewrite shot",
                                    h.on_rewrite_scene,
                                    busy_any,
                                    f"rw-{i}",
                                ),
                                (
                                    "add",
                                    "Add shot after",
                                    h.on_add_shot,
                                    busy_any,
                                    f"addshot-{sc.id}",
                                ),
                                (
                                    "arrow_upward",
                                    "Move up",
                                    h.on_move_up,
                                    busy_any or i == 0,
                                    f"moveup-{sc.id}",
                                ),
                                (
                                    "arrow_downward",
                                    "Move down",
                                    h.on_move_down,
                                    busy_any or i == len(story.scenes) - 1,
                                    f"movedown-{sc.id}",
                                ),
                                (
                                    "delete_outline",
                                    "Delete shot",
                                    h.on_remove_scene,
                                    busy_any or len(story.scenes) <= 1,
                                    f"removeseq-{sc.id}",
                                ),
                            ]:
                                with me.tooltip(message=label):
                                    with me.content_button(
                                        type="icon",
                                        disabled=dis,
                                        on_click=handler,
                                        key=k,
                                    ):
                                        me.icon(icon)
                                        h.sr(f"{label}: shot {i + 1}")

                    if rewriting:
                        with me.box(classes="ss-busy-line"):
                            me.box(classes="ss-spinner")
                            me.text("Rewriting this shot…", style=me.Style(font_size=13))

                    h.render_line_fields(story, sc, "e", disabled=busy_any)
                    if story.makes_alt and sc.narration.strip():
                        with me.box(classes=h.dir_class(alt)):
                            me.textarea(
                                label=f"Line spoken on camera ({alt})"
                                if sc.spoken
                                else f"Narration ({alt})",
                                value=sc.narration_alt,
                                placeholder="Translated when you render",
                                rows=2,
                                appearance="outline",
                                disabled=busy_any,
                                on_blur=h.on_scene_narration_alt,
                                style=me.Style(width="100%"),
                                key=f"anar-{sc.id}",
                            )
                    me.textarea(
                        label="Keyframe visual",
                        value=sc.visual,
                        rows=3,
                        appearance="outline",
                        disabled=busy_any,
                        on_blur=h.on_scene_visual,
                        style=me.Style(width="100%"),
                        key=f"evis-{sc.id}",
                    )
                    is_exp = sc.id in expanded
                    with me.box(classes="ss-details-toggle"):
                        me.button(
                            "Hide motion & sound cue"
                            if is_exp
                            else "Motion prompt & sound cue",
                            type="stroked",
                            on_click=h.on_toggle_shot_details,
                            key=f"det-{sc.id}",
                        )
                    if is_exp:
                        with me.box(classes="ss-shot-details"):
                            me.textarea(
                                label="Motion prompt (action over time)",
                                value=sc.motion_prompt,
                                rows=2,
                                appearance="outline",
                                disabled=busy_any,
                                on_blur=h.on_scene_motion_prompt,
                                style=me.Style(width="100%"),
                                key=f"mot-{sc.id}",
                            )
                            me.input(
                                label="Sound cue",
                                value=sc.audio_cue,
                                appearance="outline",
                                disabled=busy_any,
                                on_blur=h.on_scene_audio_cue,
                                style=me.Style(width="100%"),
                                key=f"aud-{sc.id}",
                            )

            # Join Connector Pill between shot i and shot i+1
            if i + 1 < len(story.scenes) and (
                pos + 1 < len(visible_indices) and visible_indices[pos + 1] == i + 1
            ):
                next_sc = story.scenes[i + 1]
                cur_trans = next_sc.transition or "auto"
                with me.box(classes="ss-join-bar"):
                    with me.box(classes="ss-join-label"):
                        me.text(f"Join {i + 1} → {i + 2}")
                    for tid, tlabel in JOIN_PILLS:
                        with me.box(
                            classes="ss-join-pill"
                            + (" is-on" if cur_trans == tid else "")
                        ):
                            me.button(
                                tlabel,
                                type="stroked",
                                disabled=busy_any,
                                on_click=h.on_scene_transition,
                                key=f"tr|{next_sc.id}|{tid}",
                            )


def _render_set_tab(
    s: StoryState,
    story: Story,
    st: StorySet | None,
    busy: bool,
    is_demo: bool,
    h: DeskHandlers,
) -> None:
    if st is None:
        with me.box(classes="ss-card ss-set-empty"):
            me.text("Cast & Set", style=me.Style(font_size=18, font_weight=600))
            me.text(
                "Characters, places and props, made once and reused in every shot.",
                style=me.Style(font_size=14, color=me.theme_var("on-surface-variant")),
            )
            with me.box(classes="ss-set-tools"):
                me.button(
                    "Making…" if h.job_active_for("set") else "Make set",
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
            me.text(
                meta,
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        with me.box(classes="ss-set-tools"):
            me.button(
                "Making…" if h.job_active_for("set") else "Make set",
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
        ("prop", "Props", st.props, "Add prop"),
    ):
        with me.box(classes="ss-set-section"):
            with me.box(classes="ss-set-section-head"):
                me.text(
                    title,
                    type="headline-6",
                    style=me.Style(
                        margin=me.Margin.all(0), font_size=18, font_weight=600
                    ),
                )
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


def _render_animatic_tab(
    s: StoryState, story: Story, busy: bool, h: DeskHandlers
) -> None:
    if not story.scenes:
        with me.box(classes="ss-card"):
            me.text("No shots yet. Write a breakdown first.")
        return
    idx = max(0, min(s.animatic_index, len(story.scenes) - 1))
    sc = story.scenes[idx]
    ar = "ss-ar-916 ss-player-portrait" if story.aspect_ratio == "9:16" else "ss-ar-169"
    with me.box(classes="ss-card"):
        with me.box(classes="ss-animatic"):
            with me.box(classes="ss-animatic-stage"):
                with me.box(classes=f"ss-animatic-frame ss-media {ar}"):
                    if sc.clip_uri:
                        me.video(
                            src=display_url(sc.clip_uri),
                            style=me.Style(width="100%", height="100%"),
                        )
                    elif sc.frame_uri:
                        me.image(
                            src=display_url(sc.frame_uri),
                            alt=f"Shot {idx + 1}",
                            style=me.Style(
                                width="100%", height="100%", object_fit="cover"
                            ),
                        )
                    else:
                        with me.box(classes="ss-media-overlay"):
                            me.icon(
                                "image",
                                style=me.Style(font_size=28, width=28, height=28),
                            )
                            me.text("No frame painted yet")
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
                    me.button(
                        f"Shot {idx + 1} of {len(story.scenes)}",
                        type="stroked",
                        on_click=h.on_animatic_open_shot,
                        key="ss-anim-open",
                    )
                    me.button(
                        "Next",
                        type="stroked",
                        disabled=idx >= len(story.scenes) - 1,
                        on_click=h.on_animatic_next,
                        key="ss-anim-next",
                    )

            with me.box(classes="ss-animatic-info"):
                me.text(
                    f"Shot {idx + 1}" + (f" · {sc.sequence}" if sc.sequence else ""),
                    style=me.Style(font_size=16, font_weight=600),
                )
                me.text(
                    f"{SHOT_SIZES.get(sc.shot_size, 'Medium shot')} · "
                    f"{CAMERA_PRESETS.get(sc.camera, CAMERA_PRESETS['static'])['label']} · "
                    f"{sc.duration}s",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
                if sc.narration.strip():
                    me.text(
                        ("On camera: " if sc.spoken else "Voiceover: ")
                        + sc.narration.strip(),
                        style=me.Style(font_size=14),
                    )
                me.text(
                    sc.visual,
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
                if sc.audio_cue:
                    me.text(
                        f"Audio cue: {sc.audio_cue}",
                        style=me.Style(
                            font_size=13, color=me.theme_var("on-surface-variant")
                        ),
                    )
                if not sc.frame_uri:
                    me.button(
                        "Paint this frame",
                        type="flat",
                        color="primary",
                        disabled=busy,
                        on_click=h.on_regen_frame,
                        key=f"rf-{idx}",
                    )

        with me.box(classes="ss-animatic-strip"):
            for i, item in enumerate(story.scenes):
                with me.box(
                    classes="ss-animatic-thumb" + (" is-on" if i == idx else ""),
                    on_click=h.on_animatic_select,
                    key=f"anim-{i}",
                ):
                    with me.box(
                        classes="ss-media "
                        + ("ss-ar-916" if story.aspect_ratio == "9:16" else "ss-ar-169")
                    ):
                        if item.frame_uri:
                            me.image(
                                src=display_url(item.frame_uri),
                                alt=f"Shot {i + 1}",
                                style=me.Style(
                                    width="100%", height="100%", object_fit="cover"
                                ),
                            )
                        else:
                            with me.box(classes="ss-media-overlay"):
                                me.icon("image")
                    me.text(
                        f"Shot {i + 1} · {item.duration}s",
                        style=me.Style(font_size=12, font_weight=600),
                    )
