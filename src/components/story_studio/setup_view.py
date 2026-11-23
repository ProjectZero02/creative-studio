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
"""Setup stage UI for Story Studio (/story)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from components.story_studio.widgets import story_idea_watch, story_style_picker
from config.default import Default
from services import story_director
from services.story_models import (
    ASPECT_RATIOS,
    CAMERA_PRESETS,
    LANGUAGES,
    PACING_MODES,
    SPEECH_HINTS,
    SPEECH_MODES,
    STORY_VIDEO_ENGINES,
    STYLE_BY_ID,
    STYLES,
    Story,
    apply_caps,
    supported_durations,
)
from services.story_service import display_url
from state.story_state import StoryState

DURATION_PRESETS: list[tuple[int, str]] = [
    (30, "30s"),
    (60, "1m"),
    (120, "2m"),
    (180, "3m"),
    (300, "5m"),
    (600, "10m"),
    (0, "Custom"),
]


@dataclass
class SetupHandlers:
    on_input_mode: Callable
    on_idea_live: Callable
    on_idea_blur: Callable
    on_script_blur: Callable
    on_example: Callable
    on_target_preset: Callable
    on_pacing: Callable
    on_video_model: Callable
    on_pick_set: Callable
    on_character_blur: Callable
    on_language: Callable
    on_speech_mode: Callable
    on_scene_count: Callable
    on_duration: Callable
    on_aspect: Callable
    on_camera: Callable
    on_use_brand: Callable
    on_style: Callable
    on_upload_reference: Callable
    on_remove_reference: Callable
    on_generate_scenario: Callable
    render_auto_note: Callable
    fmt_secs: Callable[[float], str]


def _compute_blueprint(s: StoryState) -> tuple[int, int, int, int, list[str], str]:
    """Return (est_seconds, seq_count, shot_count, shot_dur, notes, res)."""
    caps = apply_caps(s.scene_count, s.duration, model_id=s.video_model)
    if s.input_mode == "script" and (s.raw_script or "").strip():
        try:
            parsed = story_director.parse_user_script(
                s.raw_script,
                language=s.language,
                speech_mode=s.speech_mode,
                pacing=s.pacing,
                target_seconds=s.target_seconds,
            )
            scenes = parsed.get("scenes") or []
            seqs = parsed.get("sequences") or []
            est = sum(int(sc.get("seconds") or s.duration) for sc in scenes)
            avg_d = max(4, round(est / max(1, len(scenes))))
            return est, max(1, len(seqs)), len(scenes), avg_d, [], caps.resolution
        except Exception:
            words = len((s.raw_script or "").split())
            est = max(6, round(words / 2.4))
            shots = max(1, round(est / max(4, caps.duration)))
            return est, max(1, (shots + 5) // 6), shots, caps.duration, [], caps.resolution
    if s.target_seconds > 0:
        try:
            bp = story_director.plan_film_blueprint(
                s.target_seconds, pacing=s.pacing, video_model=s.video_model
            )
            return (
                int(bp["estimated_seconds"]),
                int(bp["sequence_count"]),
                int(bp["scene_count"]),
                int(bp["duration"]),
                [],
                caps.resolution,
            )
        except Exception:
            pass
    est = caps.scene_count * caps.duration
    seq_count = 1 if caps.scene_count <= 8 else max(2, (caps.scene_count + 5) // 6)
    return est, seq_count, caps.scene_count, caps.duration, caps.notes, caps.resolution


def render_setup(
    s: StoryState,
    story: Story | None,
    *,
    busy: bool,
    set_rows: list[dict],
    example_ideas: list[str],
    example_labels: list[str],
    h: SetupHandlers,
) -> None:
    """Render the 2-column equal-height Setup stage."""
    cfg = Default()
    est_secs, seq_count, shot_count, shot_dur, notes, resolution = _compute_blueprint(s)
    engine_val = s.video_model if s.video_model in STORY_VIDEO_ENGINES else (
        cfg.STORY_VIDEO_MODEL
        if cfg.STORY_VIDEO_MODEL in STORY_VIDEO_ENGINES
        else "gemini-omni-1.2-flash"
    )
    picked = next((r for r in set_rows if r["id"] == s.create_set_id), None)

    with me.box(classes="ss-create"):
        with me.box(classes="ss-card ss-create-main"):
            with me.box(classes="ss-create-head"):
                with me.box(classes="ss-section-title"):
                    me.text(
                        "Setup",
                        type="headline-6",
                        style=me.Style(margin=me.Margin.all(0), font_weight=600),
                    )
                    me.text(
                        "Start from a short idea or paste a full script.",
                        style=me.Style(
                            font_size=14, color=me.theme_var("on-surface-variant")
                        ),
                    )
                with me.box(classes="gm-segmented"):
                    me.button_toggle(
                        value=s.input_mode if s.input_mode in ("idea", "script") else "idea",
                        buttons=[
                            me.ButtonToggleButton(label="From idea", value="idea"),
                            me.ButtonToggleButton(label="From script", value="script"),
                        ],
                        multiple=False,
                        hide_selection_indicator=True,
                        on_change=h.on_input_mode,
                        key="ss-input-mode",
                    )

            if s.input_mode == "script":
                me.textarea(
                    label="Script or voiceover",
                    value=s.raw_script,
                    rows=8,
                    appearance="outline",
                    placeholder=(
                        "Paste a screenplay (INT. HARBOUR - DUSK / MARA: ...) "
                        "or voiceover paragraphs..."
                    ),
                    on_blur=h.on_script_blur,
                    style=me.Style(width="100%"),
                    key="ss-raw-script",
                )
                words = len((s.raw_script or "").split())
                script_est = max(0, round(words / 2.4))
                with me.box(classes="ss-script-meta"):
                    me.text(
                        f"{words} words · ≈ {h.fmt_secs(script_est)} estimated runtime"
                        if words
                        else "Supports screenplay sluglines (INT./EXT.), CHARACTER: dialogue, or plain voiceover paragraphs."
                    )
            else:
                story_idea_watch(on_idea=h.on_idea_live, key="ss-idea-watch")
                with me.box(classes="ss-idea-field"):
                    me.textarea(
                        label="Your idea",
                        value=s.idea,
                        rows=4,
                        appearance="outline",
                        placeholder="A lighthouse keeper befriends a lost baby whale…",
                        on_blur=h.on_idea_blur,
                        style=me.Style(width="100%"),
                        key="ss-idea",
                    )
                h.render_auto_note()
                with me.box(classes="ss-examples"):
                    me.text(
                        "Try:",
                        style=me.Style(
                            font_size=13, color=me.theme_var("on-surface-variant")
                        ),
                    )
                    for i, _idea in enumerate(example_ideas):
                        me.button(
                            example_labels[i],
                            type="stroked",
                            on_click=h.on_example,
                            key=f"ex-{i}",
                        )
                with me.box(classes="ss-preset-block"):
                    with me.box(classes="ss-preset-label"):
                        me.text("Target duration")
                    with me.box(classes="ss-preset-pills"):
                        for sec, label in DURATION_PRESETS:
                            active = s.target_seconds == sec
                            with me.box(classes="ss-pill" + (" is-on" if active else "")):
                                me.button(
                                    label,
                                    type="stroked",
                                    on_click=h.on_target_preset,
                                    key=f"pres-{sec}",
                                )

            story_style_picker(
                options=[
                    {
                        "id": st["id"],
                        "label": st["label"],
                        "src": f"/ui/story/{st['id']}.svg",
                    }
                    for st in STYLES
                ],
                value=s.style,
                label="Style",
                on_change=h.on_style,
                key="ss-style",
            )

            with me.box(classes="ss-fields"):
                me.select(
                    label="Video engine",
                    options=[
                        me.SelectOption(label=label, value=k)
                        for k, label in STORY_VIDEO_ENGINES.items()
                    ],
                    value=engine_val,
                    appearance="outline",
                    on_selection_change=h.on_video_model,
                    key="ss-video-model",
                )
                me.select(
                    label="Pacing",
                    options=[
                        me.SelectOption(label=v["label"], value=k)
                        for k, v in PACING_MODES.items()
                    ],
                    value=s.pacing if s.pacing in PACING_MODES else "cinematic",
                    appearance="outline",
                    on_selection_change=h.on_pacing,
                    key="ss-pacing",
                )
                me.select(
                    label="Aspect ratio",
                    options=[
                        me.SelectOption(
                            label=f"{a} {'landscape' if a == '16:9' else 'portrait'}",
                            value=a,
                        )
                        for a in ASPECT_RATIOS
                    ],
                    value=s.aspect_ratio,
                    appearance="outline",
                    on_selection_change=h.on_aspect,
                    key="ss-aspect",
                )
                me.select(
                    label="Language",
                    options=[me.SelectOption(label=k, value=k) for k in LANGUAGES],
                    value=s.language,
                    appearance="outline",
                    on_selection_change=h.on_language,
                    key="ss-lang",
                )
                me.select(
                    label="Who speaks",
                    options=[
                        me.SelectOption(label=label, value=k)
                        for k, label in SPEECH_MODES.items()
                    ],
                    value=s.speech_mode,
                    appearance="outline",
                    on_selection_change=h.on_speech_mode,
                    key="ss-speech",
                )
                me.select(
                    label="Camera",
                    options=[
                        me.SelectOption(label=v["label"], value=k)
                        for k, v in CAMERA_PRESETS.items()
                    ],
                    value=s.camera,
                    appearance="outline",
                    on_selection_change=h.on_camera,
                    key="ss-camera",
                )
                if s.input_mode != "script" and s.target_seconds == 0:
                    me.select(
                        label="Scenes",
                        options=[
                            me.SelectOption(label=f"{n} scenes", value=str(n))
                            for n in range(cfg.STORY_MIN_SCENES, cfg.STORY_MAX_SCENES + 1)
                        ],
                        value=str(s.scene_count),
                        appearance="outline",
                        on_selection_change=h.on_scene_count,
                        key="ss-count",
                    )
                    me.select(
                        label="Scene length",
                        options=[
                            me.SelectOption(label=f"{d} seconds", value=str(d))
                            for d in supported_durations(s.video_model)
                        ],
                        value=str(s.duration),
                        appearance="outline",
                        on_selection_change=h.on_duration,
                        key="ss-dur",
                    )

            me.text(
                SPEECH_HINTS.get(s.speech_mode, ""),
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )

            me.select(
                label="Set",
                options=[
                    me.SelectOption(label="None (make one from my story)", value="none")
                ]
                + [
                    me.SelectOption(
                        label=f"{r['name']} · {r['summary']}", value=r["id"]
                    )
                    for r in set_rows
                ],
                value=picked["id"] if picked else "none",
                appearance="outline",
                on_selection_change=h.on_pick_set,
                style=me.Style(width="100%"),
                key="ss-set-pick",
            )
            if picked is None:
                me.input(
                    label="Main character (optional)",
                    value=s.character,
                    appearance="outline",
                    placeholder="e.g. an old keeper with a grey beard and a yellow raincoat",
                    on_blur=h.on_character_blur,
                    style=me.Style(width="100%"),
                    key="ss-character",
                )
            with me.box(classes="ss-brand-row"):
                me.slide_toggle(
                    "Use my brand",
                    checked=s.use_brand,
                    on_change=h.on_use_brand,
                    key="ss-use-brand",
                )
                me.link(text="Edit my brand", url="/brand", open_in_new_tab=True)
            with me.box(classes="ss-ref" + (" is-hidden" if picked else "")):
                with me.box(classes="ss-ref-text"):
                    me.text(
                        "Character reference (optional)",
                        style=me.Style(font_weight=600, font_size=14),
                    )
                    me.text(
                        "Upload a photo or drawing to keep the same look in every frame.",
                        style=me.Style(
                            font_size=13, color=me.theme_var("on-surface-variant")
                        ),
                    )
                if s.reference_uri:
                    me.image(
                        src=display_url(s.reference_uri),
                        alt="Character reference",
                        style=me.Style(
                            width=72, height=72, object_fit="cover", border_radius=10
                        ),
                    )
                    me.button("Remove", type="stroked", on_click=h.on_remove_reference)
                else:
                    me.uploader(
                        label="Upload image",
                        accepted_file_types=["image/png", "image/jpeg", "image/webp"],
                        type="stroked",
                        on_upload=h.on_upload_reference,
                        key="ss-upload",
                    )

        with me.box(classes="ss-card ss-summary"):
            me.text(
                "Production Blueprint",
                style=me.Style(
                    font_size=14,
                    font_weight=600,
                    color=me.theme_var("on-surface-variant"),
                ),
            )
            me.text(
                f"≈ {h.fmt_secs(est_secs)}",
                style=me.Style(font_size=40, font_weight=700, line_height="1.1"),
            )
            with me.box(classes="ss-summary-lines"):
                me.text(
                    f"{seq_count} sequence{'s' if seq_count != 1 else ''} · "
                    f"{shot_count} shot{'s' if shot_count != 1 else ''} × ~{shot_dur}s"
                )
                me.text(
                    f"{s.aspect_ratio} · {resolution} · "
                    f"{STYLE_BY_ID.get(s.style, STYLES[0])['label']}"
                )
                me.text(
                    f"Engine: {STORY_VIDEO_ENGINES.get(engine_val, engine_val)}"
                )
                me.text(
                    f"Camera: {CAMERA_PRESETS.get(s.camera, CAMERA_PRESETS['auto'])['label']}"
                )
            for note in notes:
                me.text(
                    note,
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
            with me.box(classes="ss-next"):
                me.text(
                    "Continuity & pipeline",
                    style=me.Style(font_size=13, font_weight=600),
                )
                for icon, line in [
                    ("movie_filter", "Keyframe bridges + J/L audio cuts"),
                    (
                        "center_focus_strong",
                        "30° shot-size pacing & visual grammar lock",
                    ),
                    (
                        "view_carousel",
                        "Inspect cast, frames, animatic & clips in Director's Desk",
                    ),
                ]:
                    with me.box(classes="ss-next-row"):
                        me.icon(
                            icon,
                            style=me.Style(
                                font_size=18, width=18, height=18, flex_shrink=0
                            ),
                        )
                        me.text(line, style=me.Style(font_size=13))

            with me.box(classes="ss-summary-cta"):
                if story and story.scenes and not busy:
                    me.text(
                        "Writing a new breakdown replaces the current shots.",
                        style=me.Style(
                            font_size=13, color=me.theme_var("on-surface-variant")
                        ),
                    )
                me.button(
                    "Writing breakdown…" if busy else "Write breakdown",
                    type="flat",
                    color="primary",
                    disabled=busy,
                    on_click=h.on_generate_scenario,
                    key="ss-generate",
                )
