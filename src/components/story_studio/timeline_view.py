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
"""Timeline & Export stage UI for Story Studio (/story)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from components.story_studio.widgets import story_ticker, story_timeline
from services import story_export as export_mod
from services import story_jobs, story_subtitles
from services import story_timeline as timeline_mod
from services.story_models import STYLE_BY_ID, STYLES, Story, default_music_prompt
from services.story_service import AUDIO_MIME_TYPES, display_url
from services.story_sets import StorySet
from state.story_export_state import StoryExportState
from state.story_state import StoryState


@dataclass
class TimelineHandlers:
    on_back_editor: Callable
    on_toggle_edit_music: Callable
    on_export: Callable
    on_export_menu: Callable
    on_export_size: Callable
    on_export_format: Callable
    on_export_subs: Callable
    on_export_lang: Callable
    on_export_branding: Callable
    on_subtitle_style: Callable
    on_proxy_tick: Callable
    on_cancel_job: Callable
    on_music_prompt: Callable
    on_make_music: Callable
    on_upload_music: Callable
    on_timeline_change: Callable
    on_fix_point: Callable
    render_fix_panel: Callable
    render_alt_film: Callable
    on_make_alt: Callable
    alt_cost: Callable[[Story], float]
    on_upscale: Callable
    upscale_options: Callable[[Story], list[tuple[str, float]]]
    render_versions_panel: Callable
    render_progress_panel: Callable
    media_map: Callable[[Story], dict[str, str]]
    job_active_for: Callable
    job_dict: Callable
    scene_task: Callable
    fmt_secs: Callable[[float], str]


def download_url(story: Story, what: str) -> str:
    """A real download (Content-Disposition), see routers/story_router.py."""
    return f"/api/story/{story.id}/download/{what}"


def download_link(label: str, url: str, key: str, primary: bool = False) -> None:
    """A link styled as a button that downloads the file."""
    with me.box(classes="ss-dl-btn" + (" is-primary" if primary else ""), key=key):
        me.link(text=label, url=url)


def render_timeline(
    s: StoryState,
    story: Story,
    story_set: StorySet | None,
    *,
    is_demo: bool,
    h: TimelineHandlers,
) -> None:
    """Render Timeline & Export (editable timeline or active render view)."""
    job = h.job_dict()
    rendering = h.job_active_for("video")
    if story.timeline_json and not rendering:
        _render_edit_view(s, story, story_set, job, h)
        return

    with me.box(classes="ss-video"):
        with me.box(classes="ss-card ss-player"):
            if story.final_uri and not rendering:
                with me.box(
                    classes="ss-media "
                    + (
                        "ss-ar-916 ss-player-portrait"
                        if story.aspect_ratio == "9:16"
                        else "ss-ar-169"
                    )
                ):
                    me.video(
                        src=display_url(story.final_uri),
                        style=me.Style(width="100%", height="100%"),
                    )
                with me.box(classes="ss-player-meta"):
                    with me.box():
                        me.text(
                            story.title or "Your film",
                            style=me.Style(font_size=20, font_weight=600),
                        )
                        me.text(
                            f"{len(story.scenes)} shots · {STYLE_BY_ID.get(story.style, STYLES[0])['label']} · {story.aspect_ratio}",
                            style=me.Style(
                                font_size=14, color=me.theme_var("on-surface-variant")
                            ),
                        )
                    with me.box(classes="ss-player-actions"):
                        download_link(
                            "Download", download_url(story, "film"), "ss-dl-film", primary=True
                        )
                        if not is_demo:
                            me.markdown("[Open library](/library)")
                        me.button(
                            "Takes",
                            type="stroked",
                            on_click=h.on_back_editor,
                        )
                if story.final_alt_uri:
                    h.render_alt_film(story)
                _film_offers(story, h)
            else:
                with me.box(classes="ss-media ss-ar-169 ss-player-wait"):
                    if rendering:
                        me.box(classes="ss-spinner ss-spinner-lg")
                        me.text(
                            "Making your film…",
                            style=me.Style(font_size=18, font_weight=600),
                        )
                        me.text(
                            "Clips, music and voiceover are generated in parallel, then stitched.",
                            style=me.Style(
                                font_size=14,
                                color=me.theme_var("on-surface-variant"),
                                text_align="center",
                            ),
                        )
                        if s.job_running:
                            me.button(
                                "Cancel",
                                type="stroked",
                                color="warn",
                                on_click=h.on_cancel_job,
                                key="ss-video-cancel",
                            )
                    else:
                        me.icon(
                            "movie", style=me.Style(font_size=36, width=36, height=36)
                        )
                        me.text(
                            "No film yet. Render it from Director's Desk.",
                            style=me.Style(font_size=15),
                        )
                        me.button(
                            "Go to Director's Desk",
                            type="flat",
                            color="primary",
                            on_click=h.on_back_editor,
                        )

        with me.box(classes="ss-filmstrip", key="ss-strip"):
            for i, sc in enumerate(story.scenes):
                task = (
                    h.scene_task("clip", i)
                    if job and job.get("kind") == "video"
                    else None
                )
                status = (task or {}).get("status") or ("done" if sc.clip_uri else "")
                with me.box(classes=f"ss-strip-item ss-strip-{status or 'idle'}"):
                    with me.box(
                        classes="ss-media "
                        + ("ss-ar-916" if story.aspect_ratio == "9:16" else "ss-ar-169")
                    ):
                        if sc.frame_uri:
                            me.image(
                                src=display_url(sc.frame_uri),
                                alt=f"Shot {i + 1}",
                                style=me.Style(
                                    width="100%", height="100%", object_fit="cover"
                                ),
                            )
                        if status == "running":
                            with me.box(classes="ss-media-overlay"):
                                me.box(classes="ss-spinner")
                                me.text(
                                    h.fmt_secs(task.get("elapsed", 0)),
                                    style=me.Style(font_size=12),
                                )
                    with me.box(classes="ss-strip-label"):
                        me.text(
                            f"Shot {i + 1}",
                            style=me.Style(font_size=12, font_weight=600),
                        )
                        me.text(
                            {
                                "done": "Clip ready",
                                "running": "Animating",
                                "queued": "Queued",
                                "failed": "Failed",
                                "skipped": "Skipped",
                            }.get(status, "Waiting"),
                            style=me.Style(font_size=12),
                        )
        h.render_progress_panel("Rendering your film", ("video",))


def _film_offers(story: Story, h: TimelineHandlers) -> None:
    """A sharper version (AI upscale of every take) and the second-language
    version, each with about what it costs."""
    upscales = h.upscale_options(story)
    if upscales:
        with me.box(classes="ss-alt-offer"):
            for res, _cost in upscales:
                me.button(
                    f"AI upscale to {res}",
                    type="stroked",
                    disabled=h.job_active_for("video", "clips"),
                    on_click=h.on_upscale,
                    key=f"ss-upscale-{res}",
                )
            me.text(
                "About "
                + " / ".join(f"{cost:.2f}" for _, cost in upscales)
                + " USD",
                style=me.Style(
                    font_size=13, color=me.theme_var("on-surface-variant")
                ),
            )
    if not story.final_alt_uri and any(
        sc.narration.strip() for sc in story.scenes
    ):
        with me.box(classes="ss-alt-offer"):
            me.button(
                f"Make {story.alt_language} version",
                type="stroked",
                disabled=h.job_active_for("video", "clips", "translate"),
                on_click=h.on_make_alt,
                key="ss-make-alt",
            )
            me.text(
                f"About {h.alt_cost(story):.2f} USD",
                style=me.Style(
                    font_size=13, color=me.theme_var("on-surface-variant")
                ),
            )


def _render_edit_view(
    s: StoryState,
    story: Story,
    used: StorySet | None,
    job: dict | None,
    h: TimelineHandlers,
) -> None:
    # The editor's place in the page never changes: everything that comes
    # and goes sits inside a slot box above or below it, so Mesop keeps the
    # same <story-timeline> (its undo, playhead and zoom) across updates.
    busy = h.job_active_for("export", "music", "video", "fix", "subtitles")
    exporting = h.job_active_for("export")
    making_music = h.job_active_for("music")
    job_open = (job or {}).get("status") not in (None, "done")
    tl = timeline_mod.normalize(story.timeline_json)
    ex = me.state(StoryExportState)
    preview_uri, preview_state = story_jobs.preview(story)

    with me.box(classes="ss-video"):
        with me.box(classes="ss-card ss-edit-head", key="ss-edit-head"):
            with me.box(classes="ss-edit-name"):
                me.text(
                    story.title or "Your film",
                    style=me.Style(font_size=18, font_weight=600),
                )
                me.text(
                    f"{h.fmt_secs(timeline_mod.duration(tl))} · {story.aspect_ratio}"
                    + (f" · Set: {used.name}" if used else ""),
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )
                if used and story.set_version and story.set_version != used.version:
                    me.text(
                        "Set changed since this film was made",
                        style=me.Style(font_size=13, color=me.theme_var("error")),
                    )
                if story.film_edited and story.final_uri and not exporting:
                    me.text(
                        "Edited since the last export",
                        style=me.Style(font_size=13, color=me.theme_var("primary")),
                    )
            with me.box(classes="ss-edit-tools"):
                me.button(
                    "Takes",
                    type="stroked",
                    disabled=busy,
                    on_click=h.on_back_editor,
                    key="ss-back-scenes",
                )
                me.button(
                    "Music",
                    type="stroked",
                    disabled=busy and not making_music,
                    on_click=h.on_toggle_edit_music,
                    key="ss-music-toggle",
                )
                me.button(
                    "Exporting…" if exporting else "Export",
                    type="flat",
                    color="primary",
                    on_click=h.on_export_menu,
                    key="ss-export-menu",
                )
                if s.job_running:
                    me.button(
                        "Cancel",
                        type="stroked",
                        color="warn",
                        on_click=h.on_cancel_job,
                        key="ss-edit-cancel",
                    )

        with me.box(classes="ss-slot", key="ss-slot-above"):
            if ex.open:
                _export_menu(story, tl, ex, busy, exporting, h)
            if job_open:
                h.render_progress_panel("Exporting", ("export",))

        with me.box(classes="ss-card ss-edit-main", key="ss-edit-main"):
            story_timeline(
                timeline_json=story.timeline_json,
                media=h.media_map(story),
                aspect=story.aspect_ratio,
                busy=busy,
                on_change=h.on_timeline_change,
                on_point=h.on_fix_point,
                preview_url=display_url(preview_uri),
                preview_state=preview_state,
                key="ss-timeline",
            )

        with me.box(classes="ss-slot", key="ss-slot-below"):
            story_ticker(
                active=preview_state == "making",
                on_tick=h.on_proxy_tick,
                interval_ms=1200,
                key="ss-proxy-ticker",
            )
            if s.edit_music_open or making_music:
                _music_bar(story, busy, making_music, h)
                if job_open:
                    h.render_progress_panel("Making music", ("music",))
            h.render_fix_panel(story, busy)
            if job_open:
                h.render_progress_panel("Applying the fix", ("fix",))
                h.render_progress_panel("Adding subtitles", ("subtitles",))
            if story.final_alt_uri:
                with me.box(classes="ss-card ss-player"):
                    h.render_alt_film(story)
            h.render_versions_panel(story, busy)


def _music_bar(
    story: Story, busy: bool, making_music: bool, h: TimelineHandlers
) -> None:
    with me.box(classes="ss-card ss-edit-music"):
        with me.box(classes="ss-edit-music-input"):
            me.input(
                placeholder="Describe the music",
                value=story.music_prompt or default_music_prompt(story),
                appearance="outline",
                disabled=busy,
                on_blur=h.on_music_prompt,
                style=me.Style(width="100%"),
                key="ss-edit-music",
            )
        me.button(
            "Making…" if making_music else "Make music",
            type="stroked",
            disabled=busy,
            on_click=h.on_make_music,
            key="ss-make-music",
        )
        me.uploader(
            label="Upload",
            accepted_file_types=AUDIO_MIME_TYPES,
            type="stroked",
            disabled=busy,
            on_upload=h.on_upload_music,
            key="ss-upload-music",
        )


def _select(
    label: str,
    options: list[tuple[str, str]],
    value: str,
    disabled: bool,
    handler: Callable,
    key: str,
) -> None:
    with me.box(classes="ss-export-field"):
        me.text(
            label,
            style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
        )
        me.select(
            options=[me.SelectOption(label=text, value=v) for v, text in options],
            value=value,
            disabled=disabled,
            on_selection_change=handler,
            appearance="outline",
            key=key,
        )


def _export_menu(
    story: Story,
    tl: dict,
    ex: StoryExportState,
    busy: bool,
    exporting: bool,
    h: TimelineHandlers,
) -> None:
    """Size, format (or audio only), subtitles, logo, then Export or Download."""
    opts = export_mod.clean(ex.options(), tl)
    video = export_mod.is_video(opts)
    has_logo = bool(story_jobs.logo_of(story))
    with me.box(classes="ss-card ss-export", key="ss-export"):
        with me.box(classes="ss-export-grid"):
            _select(
                "Size",
                [
                    (str(r["short"]), r["label"] + (" (upscaled)" if r["upscale"] else ""))
                    for r in timeline_mod.resolution_options(tl)
                ],
                str(opts["short"] or timeline_mod.source_short_side(tl)),
                busy or not video,
                h.on_export_size,
                "ss-export-size",
            )
            _select(
                "Format",
                [
                    (k, f["label"] if f["video"] else f"Audio only · {f['label']}")
                    for k, f in timeline_mod.EXPORT_FORMATS.items()
                ],
                opts["fmt"],
                busy,
                h.on_export_format,
                "ss-export-format",
            )
            _select(
                "Subtitles",
                list(export_mod.SUB_LABELS.items()),
                opts["subs"],
                busy or not video,
                h.on_export_subs,
                "ss-export-subs",
            )
            _select(
                "Language",
                [
                    (v, story_subtitles.VARIANT_LABELS[v].removesuffix(" subtitles"))
                    for v in story_subtitles.VARIANTS
                    if v != "none"
                ],
                opts["lang"],
                busy or opts["subs"] == "none",
                h.on_export_lang,
                "ss-export-lang",
            )
        with me.box(classes="ss-export-row"):
            with me.box(classes="ss-export-logo"):
                me.slide_toggle(
                    label="Brand logo",
                    checked=opts["branding"] and has_logo,
                    disabled=busy or not has_logo,
                    on_change=h.on_export_branding,
                    key="ss-export-branding",
                )
            if export_mod.burns_subtitles(opts):
                me.button_toggle(
                    value=story.subtitle_style
                    if story.subtitle_style in story_subtitles.STYLES
                    else "clean",
                    buttons=[
                        me.ButtonToggleButton(
                            label=story_subtitles.STYLE_LABELS[k], value=k
                        )
                        for k in story_subtitles.STYLES
                    ],
                    disabled=busy,
                    on_change=h.on_subtitle_style,
                    key="ss-export-style",
                )
        _export_actions(story, tl, opts, has_logo, busy, exporting, h)
        _film_offers(story, h)


def _export_actions(
    story: Story,
    tl: dict,
    opts: dict,
    has_logo: bool,
    busy: bool,
    exporting: bool,
    h: TimelineHandlers,
) -> None:
    ready = export_mod.ready(story, opts)
    film_ready = (
        export_mod.makes_film(opts, has_logo)
        and bool(story.final_uri)
        and not story.film_edited
    )
    srt_ready = export_mod.wants_srt(opts) and all(
        story_subtitles.lines_for(story, c) is not None
        for c in export_mod.sub_langs(opts)
    )
    with me.box(classes="ss-export-actions"):
        with me.box(classes="ss-export-what"):
            me.text(
                export_mod.label(opts, tl),
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        if srt_ready:
            download_link(
                "Download SRT",
                f"/api/story/{story.id}/subtitles/{opts['lang']}.srt",
                "ss-export-srt",
            )
        if ready:
            download_link(
                "Download",
                download_url(story, "export-" + export_mod.key(opts)),
                "ss-export-dl",
                primary=True,
            )
        elif film_ready:
            download_link(
                "Download", download_url(story, "film"), "ss-export-dl", primary=True
            )
        else:
            me.button(
                "Exporting…" if exporting else "Export",
                type="flat",
                color="primary",
                disabled=busy,
                on_click=h.on_export,
                key="ss-export",
            )
