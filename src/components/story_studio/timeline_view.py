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

from components.story_studio.widgets import story_timeline
from services import story_timeline as timeline_mod
from services.story_models import STYLE_BY_ID, STYLES, Story, default_music_prompt
from services.story_service import AUDIO_MIME_TYPES, display_url
from services.story_sets import StorySet
from state.story_state import StoryState


@dataclass
class TimelineHandlers:
    on_back_editor: Callable
    on_toggle_edit_music: Callable
    on_export: Callable
    on_cancel_job: Callable
    on_music_prompt: Callable
    on_make_music: Callable
    on_upload_music: Callable
    on_timeline_change: Callable
    on_fix_point: Callable
    render_fix_panel: Callable
    render_alt_film: Callable
    render_versions_panel: Callable
    render_downloads_panel: Callable
    render_progress_panel: Callable
    media_map: Callable[[Story], dict[str, str]]
    job_active_for: Callable
    job_dict: Callable
    scene_task: Callable
    fmt_secs: Callable[[float], str]


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
                        me.markdown(f"[Download MP4]({display_url(story.final_uri)})")
                        if not is_demo:
                            me.markdown("[Open library](/library)")
                        me.button(
                            "Director's Desk",
                            type="stroked",
                            on_click=h.on_back_editor,
                        )
                if story.final_alt_uri:
                    h.render_alt_film(story)
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


def _render_edit_view(
    s: StoryState,
    story: Story,
    used: StorySet | None,
    job: dict | None,
    h: TimelineHandlers,
) -> None:
    busy = h.job_active_for("export", "music", "video", "fix", "subtitles")
    exporting = h.job_active_for("export")
    making_music = h.job_active_for("music")
    job_open = (job or {}).get("status") not in (None, "done")
    tl = timeline_mod.normalize(story.timeline_json)

    with me.box(classes="ss-video"):
        with me.box(classes="ss-card ss-edit-head"):
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
                        "Edited since the last export. Export to update the download.",
                        style=me.Style(font_size=13, color=me.theme_var("primary")),
                    )
            with me.box(classes="ss-edit-tools"):
                me.button(
                    "Director's Desk",
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
                with me.box(
                    classes="ss-edit-dl"
                    + ("" if story.final_uri and not exporting else " is-off")
                ):
                    if story.final_uri and not exporting:
                        me.link(
                            text="Download",
                            url=display_url(story.final_uri),
                            open_in_new_tab=True,
                        )
                    else:
                        me.text("Download")
                me.button(
                    "Exporting…" if exporting else "Export",
                    type="flat",
                    color="primary",
                    disabled=busy,
                    on_click=h.on_export,
                    key="ss-export",
                )
                if s.job_running:
                    me.button(
                        "Cancel",
                        type="stroked",
                        color="warn",
                        on_click=h.on_cancel_job,
                        key="ss-edit-cancel",
                    )

        if s.edit_music_open or making_music:
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
            if job_open:
                h.render_progress_panel("Making music", ("music",))
        if job_open:
            h.render_progress_panel("Exporting", ("export",))
        h.render_fix_panel(story, busy)
        if job_open:
            h.render_progress_panel("Applying the fix", ("fix",))
        with me.box(classes="ss-card ss-edit-main"):
            story_timeline(
                timeline_json=story.timeline_json,
                media=h.media_map(story),
                aspect=story.aspect_ratio,
                busy=busy,
                on_change=h.on_timeline_change,
                on_point=h.on_fix_point,
                key="ss-timeline",
            )
        if story.final_alt_uri:
            with me.box(classes="ss-card ss-player"):
                h.render_alt_film(story)
        h.render_versions_panel(story, busy)
        if job_open:
            h.render_progress_panel("Adding subtitles", ("subtitles",))
        h.render_downloads_panel(story, busy)
