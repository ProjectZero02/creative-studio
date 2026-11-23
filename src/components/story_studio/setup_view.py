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
"""Setup stage UI for Story Studio (/story): one screen.

References first (set, brand, characters, products, places, voices), then
the idea or script, duration, style and the few film settings. The live
blueprint on the right updates while the user types.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from common import brand_kit
from components.composer.composer import prompt_tools
from components.story_studio.widgets import story_idea_watch
from config.default import Default
from services import story_director, story_refs
from services.story_models import (
    ASPECT_RATIOS,
    LANGUAGES,
    PACING_MODES,
    RESOLUTION_LABELS,
    STORY_VIDEO_ENGINES,
    STYLE_BY_ID,
    STYLES,
    VOICES,
    Story,
    resolution_options,
    voice_label,
)
from services.story_service import display_url
from state.story_state import StoryState

# Pacing chips, calm to fast.
PACING_CHIPS = ("documentary", "cinematic", "dynamic")
# Menu order of "Add reference".
REF_MENU = ("character", "object", "location", "voice", "brand")


@dataclass
class SetupHandlers:
    on_input_mode: Callable
    on_idea_live: Callable
    on_idea_blur: Callable
    on_script_blur: Callable
    on_duration_live: Callable
    on_duration_blur: Callable
    on_pacing: Callable
    on_video_model: Callable
    on_aspect: Callable
    on_language: Callable
    on_resolution: Callable
    on_style_chip: Callable
    on_style_blur: Callable
    on_pick_set: Callable
    on_brand: Callable
    on_ref_menu: Callable
    on_add_ref: Callable
    on_ref_tag: Callable
    on_ref_role: Callable
    on_ref_voice: Callable
    on_ref_upload: Callable
    on_ref_mention: Callable
    on_ref_remove: Callable
    on_generate_scenario: Callable
    render_auto_note: Callable
    fmt_secs: Callable[[float], str]


def engine_of(s: StoryState) -> str:
    cfg = Default()
    if s.video_model in STORY_VIDEO_ENGINES:
        return s.video_model
    return (
        cfg.STORY_VIDEO_MODEL
        if cfg.STORY_VIDEO_MODEL in STORY_VIDEO_ENGINES
        else "gemini-omni-1.2-flash"
    )


def _auto_seconds(s: StoryState) -> int:
    try:
        found = json.loads(s.auto_json) if s.auto_json else {}
    except ValueError:
        found = {}
    return int(found.get("film_seconds") or 0)


def film_seconds(s: StoryState) -> tuple[int, str]:
    """(seconds asked for, where it came from: "box", "idea", "script" or
    "auto"). 0 seconds means the default length."""
    asked = story_director.parse_duration_text(s.duration_text)
    if asked:
        return asked, "box"
    if s.input_mode == "script" and (s.raw_script or "").strip():
        words = len(s.raw_script.split())
        return max(6, round(words / 2.4)), "script"
    auto = _auto_seconds(s)
    if auto:
        return auto, "idea"
    return 0, "auto"


def blueprint(s: StoryState) -> dict:
    seconds, source = film_seconds(s)
    bp = story_director.setup_blueprint(
        seconds,
        pacing=s.pacing,
        video_model=engine_of(s),
        resolution=s.resolution,
    )
    bp["source"] = source
    return bp


def picked_brand(s: StoryState) -> dict | None:
    """The brand the dropdown shows (the default one until the user picks)."""
    try:
        rows = json.loads(s.brands_json or "[]")
    except ValueError:
        rows = []
    if s.brand_id == "none":
        return None
    if s.brand_id:
        return next((b for b in rows if b.get("id") == s.brand_id), None)
    return next((b for b in rows if b.get("is_default")), None)


def _t(text: str, cls: str) -> None:
    """Text with a CSS class (me.text takes no classes)."""
    with me.box(classes=cls):
        me.text(text)


def _money(value: float) -> str:
    if 0 < value < 0.01:
        return "<$0.01"
    return f"${value:,.2f}"


def _chip_button(label: str, on: bool, handler: Callable, key: str) -> None:
    with me.box(classes="ss-pill" + (" is-on" if on else "")):
        me.button(label, type="stroked", on_click=handler, key=key)


def _references(s: StoryState, set_rows: list[dict], h: SetupHandlers) -> None:
    refs = story_refs.parse(s.refs_json)
    picked_set = next((r for r in set_rows if r["id"] == s.create_set_id), None)
    try:
        brands = json.loads(s.brands_json or "[]")
    except ValueError:
        brands = []
    brand = picked_brand(s)
    with me.box(classes="ss-refs"):
        with me.box(classes="ss-refs-head"):
            _t("References", "ss-label")
            me.button(
                "Add reference",
                type="stroked",
                on_click=h.on_ref_menu,
                key="ss-ref-menu",
            )
        if s.ref_menu_open:
            with me.box(classes="ss-ref-menu"):
                for kind in REF_MENU:
                    label = "Brand" if kind == "brand" else story_refs.KINDS[kind][0]
                    me.button(
                        label,
                        type="stroked",
                        on_click=h.on_add_ref,
                        key=f"addref-{kind}",
                    )
        with me.box(classes="ss-ref-pickers"):
            me.select(
                label="Set",
                options=[me.SelectOption(label="No set", value="none")]
                + [
                    me.SelectOption(
                        label=f"{r['name']} · {r['summary']}", value=r["id"]
                    )
                    for r in set_rows
                ],
                value=picked_set["id"] if picked_set else "none",
                appearance="outline",
                on_selection_change=h.on_pick_set,
                key="ss-set-pick",
            )
            me.select(
                label="Brand",
                options=[me.SelectOption(label="No brand", value="none")]
                + [
                    me.SelectOption(
                        label=brand_kit.label(b)
                        + (" (default)" if b.get("is_default") else ""),
                        value=b["id"],
                    )
                    for b in brands
                ]
                + [me.SelectOption(label="New brand…", value="new")],
                value=brand["id"] if brand else "none",
                appearance="outline",
                on_selection_change=h.on_brand,
                key="ss-brand",
            )
        for r in refs:
            _ref_row(r, h)


def _ref_row(r: dict, h: SetupHandlers) -> None:
    kind_label = story_refs.KINDS[r["kind"]][0]
    with me.box(classes="ss-ref-item", key=f"ref-{r['id']}"):
        with me.box(classes="ss-ref-thumb"):
            if r["kind"] == "voice":
                me.icon("record_voice_over")
            elif r["uri"]:
                me.image(src=display_url(r["uri"]), alt=r["tag"])
            else:
                me.uploader(
                    label="Image",
                    accepted_file_types=["image/png", "image/jpeg", "image/webp"],
                    type="stroked",
                    on_upload=h.on_ref_upload,
                    key=f"refup-{r['id']}",
                )
        with me.box(classes="ss-ref-fields"):
            me.input(
                label=f"{kind_label} tag",
                value=r["tag"],
                appearance="outline",
                on_blur=h.on_ref_tag,
                key=f"reftag-{r['id']}",
            )
            if r["kind"] == "voice":
                me.select(
                    label="Voice",
                    options=[
                        me.SelectOption(label=voice_label(v), value=v) for v in VOICES
                    ],
                    value=r["voice"] or "Kore",
                    appearance="outline",
                    on_selection_change=h.on_ref_voice,
                    key=f"refvoice-{r['id']}",
                )
            else:
                me.input(
                    label="Role",
                    value=r["role"],
                    appearance="outline",
                    on_blur=h.on_ref_role,
                    key=f"refrole-{r['id']}",
                )
        with me.box(classes="ss-ref-tools"):
            with me.tooltip(message=f"Add @{r['tag']} to the idea"):
                me.button(
                    f"@{r['tag']}",
                    type="stroked",
                    on_click=h.on_ref_mention,
                    key=f"refat-{r['id']}",
                )
            with me.tooltip(message="Remove"):
                with me.content_button(
                    type="icon", on_click=h.on_ref_remove, key=f"refrm-{r['id']}"
                ):
                    me.icon("close")


def _style(s: StoryState, h: SetupHandlers) -> None:
    preset = STYLE_BY_ID.get(s.style, STYLES[0])
    text = s.style_text or preset["prompt"]
    with me.box(classes="ss-style"):
        me.textarea(
            label="Style",
            value=text,
            rows=2,
            appearance="outline",
            on_blur=h.on_style_blur,
            style=me.Style(width="100%"),
            key=f"ss-style-text-{zlib.crc32(text.encode()) & 0xFFFF:x}",
        )
        with me.box(classes="ss-chip-row"):
            for st in STYLES:
                _chip_button(
                    st["label"],
                    text == st["prompt"],
                    h.on_style_chip,
                    f"sty-{st['id']}",
                )


def render_setup(
    s: StoryState,
    story: Story | None,
    *,
    busy: bool,
    set_rows: list[dict],
    h: SetupHandlers,
) -> None:
    """Render the one-screen Setup: form on the left, blueprint on the right."""
    engine = engine_of(s)
    bp = blueprint(s)
    res_opts = resolution_options(engine)
    res_val = s.resolution if s.resolution in res_opts else bp["resolution"]
    if res_val not in res_opts:
        res_val = res_opts[0]

    with me.box(classes="ss-create"):
        with me.box(classes="ss-card ss-create-main"):
            with me.box(classes="ss-create-head"):
                me.text(
                    "Setup",
                    type="headline-6",
                    style=me.Style(margin=me.Margin.all(0), font_weight=600),
                )
                with me.box(classes="gm-segmented"):
                    me.button_toggle(
                        value=s.input_mode
                        if s.input_mode in ("idea", "script")
                        else "idea",
                        buttons=[
                            me.ButtonToggleButton(label="Idea", value="idea"),
                            me.ButtonToggleButton(label="Script", value="script"),
                        ],
                        multiple=False,
                        hide_selection_indicator=True,
                        on_change=h.on_input_mode,
                        key="ss-input-mode",
                    )

            _references(s, set_rows, h)

            if s.input_mode == "script":
                me.textarea(
                    label="Script or voiceover",
                    value=s.raw_script,
                    rows=8,
                    appearance="outline",
                    placeholder="INT. HARBOUR - DUSK / MARA: ... or plain voiceover paragraphs",
                    on_blur=h.on_script_blur,
                    style=me.Style(width="100%"),
                    key="ss-raw-script",
                )
            else:
                story_idea_watch(
                    on_idea=h.on_idea_live, delay_ms=400, key="ss-idea-watch"
                )
                with me.box(classes="ss-idea-field gm-prompt-field"):
                    me.textarea(
                        label="Your idea",
                        value=s.idea,
                        rows=4,
                        appearance="outline",
                        placeholder="A presenter on stage explains @Product; the camera pans slowly left to right.",
                        on_blur=h.on_idea_blur,
                        style=me.Style(width="100%"),
                        key="ss-idea",
                    )
                    # Enhance, mic and Live, like every other prompt box.
                    prompt_tools(
                        kind="film",
                        scope=".gm-prompt-field",
                        key="ss-idea-tools",
                    )
                h.render_auto_note()

            story_idea_watch(
                on_idea=h.on_duration_live,
                selector=".ss-duration-field",
                delay_ms=300,
                key="ss-duration-watch",
            )
            with me.box(classes="ss-fields"):
                with me.box(classes="ss-duration-field"):
                    me.input(
                        label="Duration",
                        value=s.duration_text,
                        appearance="outline",
                        placeholder="Auto",
                        on_blur=h.on_duration_blur,
                        style=me.Style(width="100%"),
                        key="ss-duration",
                    )
                me.select(
                    label="Video engine",
                    options=[
                        me.SelectOption(label=label, value=k)
                        for k, label in STORY_VIDEO_ENGINES.items()
                    ],
                    value=engine,
                    appearance="outline",
                    on_selection_change=h.on_video_model,
                    key="ss-video-model",
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
                    label="Resolution",
                    options=[
                        me.SelectOption(label=RESOLUTION_LABELS.get(r, r), value=r)
                        for r in res_opts
                    ],
                    value=res_val,
                    appearance="outline",
                    on_selection_change=h.on_resolution,
                    key="ss-resolution",
                )
                me.select(
                    label="Language",
                    options=[me.SelectOption(label=k, value=k) for k in LANGUAGES],
                    value=s.language,
                    appearance="outline",
                    on_selection_change=h.on_language,
                    key="ss-lang",
                )
            if s.duration_text.strip() and bp["source"] != "box":
                _t(
                    'Write a length like "30s", "2 min" or "1:30".',
                    "ss-field-error",
                )

            _style(s, h)

            with me.box(classes="ss-pacing"):
                _t("Pacing", "ss-label")
                with me.box(classes="ss-chip-row ss-chip-row-3"):
                    for pid in PACING_CHIPS:
                        _chip_button(
                            PACING_MODES[pid]["label"],
                            s.pacing == pid,
                            h.on_pacing,
                            f"pace-{pid}",
                        )

        _blueprint_card(s, story, bp, res_val, busy, h)


def _blueprint_card(
    s: StoryState, story: Story | None, bp: dict, res: str, busy: bool, h: SetupHandlers
) -> None:
    cost = bp["cost"]
    source = {
        "box": "",
        "script": "from your script",
        "idea": "from your idea",
        "auto": "auto",
    }[bp["source"]]
    brand = picked_brand(s)
    with me.box(classes="ss-card ss-summary", key="ss-blueprint"):
        _t("Blueprint", "ss-label")
        me.text(
            f"≈ {h.fmt_secs(bp['seconds'])}",
            style=me.Style(font_size=40, font_weight=700, line_height="1.1"),
        )
        if source:
            _t(source, "ss-muted")
        with me.box(classes="ss-bp-rows"):
            for label, value in (
                ("Takes", story_director.takes_line(bp["takes"])),
                ("Shots", f"{bp['shots']} × ~{bp['shot_seconds']}s"),
                ("Picture", f"{RESOLUTION_LABELS.get(res, res)} · {s.aspect_ratio}"),
                ("Brand", brand_kit.label(brand) if brand else "None"),
                ("Time", story_director.time_line(bp["time_seconds"])),
            ):
                with me.box(classes="ss-bp-row"):
                    _t(label, "ss-muted")
                    me.text(value)
        with me.box(classes="ss-bp-cost"):
            with me.box(classes="ss-bp-row"):
                _t("Estimated cost", "ss-muted")
                me.text(_money(cost["total"]), style=me.Style(font_weight=700))
            _t(
                f"Video {_money(cost['video'])} · Frames {_money(cost['frames'])} · "
                f"Voice {_money(cost['voice'])} · Music {_money(cost['music'])}",
                "ss-muted ss-small",
            )

        with me.box(classes="ss-summary-cta"):
            if story and story.scenes and not busy:
                _t("Replaces the current shots.", "ss-muted ss-small")
            me.button(
                "Writing…" if busy else "Write breakdown",
                type="flat",
                color="primary",
                disabled=busy,
                on_click=h.on_generate_scenario,
                key="ss-generate",
            )
            _t("Next: start frames paint on their own.", "ss-muted ss-small")
