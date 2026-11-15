# Copyright 2025 Google LLC
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
"""Gemini 2.5 Flash Image Generation - nano-banana."""

import json
import time
from dataclasses import field

import mesop as me

from common.analytics import analytics_logger, log_ui_click
from common.metadata import MediaItem, add_media_item_to_firestore
from common.mock_generation import fake_wait, mock_enabled, placeholder_image
from common.prompt_prefill import prefill_prompt
from common.prompt_template_service import prompt_template_service
from common.storage import store_to_gcs
from common.utils import create_display_url, https_url_to_gcs_uri
from components.composer.chip_menu import change_value, chip_menu, chip_options
from components.composer.composer import composer, composer_attachment
from components.content_credentials.content_credentials import (
    content_credentials_viewer,
)
from components.dialog import dialog
from components.generation_progress.generation_progress import (
    friendly_error,
    generation_progress,
    progress_clear,
    progress_done,
    progress_fail,
    progress_start,
    progress_step,
)
from components.lightbox_dialog.lightbox_dialog import lightbox_dialog
from components.result_grid.result_card import (
    card_action,
    empty_results,
    result_card,
    result_grid,
)
from components.gemini_image.events import (
    get_on_aspect_ratio_change,
    get_on_image_search_change,
    get_on_image_size_change,
    get_on_include_thoughts_change,
    get_on_model_select,
    get_on_num_images_change,
    get_on_prompt_blur,
    get_on_search_change,
    get_on_thinking_level_change,
    get_on_thumbnail_click,
)
from components.header import header
from components.library.events import LibrarySelectionChangeEvent
from components.library.library_chooser_button import library_chooser_button
from components.page_scaffold import page_frame, page_scaffold
from components.pill import pill
from components.search_entry_point.search_entry_point import search_entry_point
from components.snackbar import snackbar
from components.svg_icon.svg_icon import svg_icon
from config.banana_presets import IMAGE_ACTION_PRESETS
from config.gemini_image_models import get_gemini_image_model_config
from config.rewriters import REWRITER_PROMPT
from models.gemini import (
    generate_image_from_prompt_and_images,
    generate_transformation_prompts,
    rewriter,
)
from models.upscale import get_image_resolution
from services.c2pa_service import c2pa_service
from state.state import AppState

CHIP_STYLE = me.Style(
    padding=me.Padding(top=4, right=12, bottom=4, left=12),
    border_radius=8,
    font_size=14,
    height=32,
)


def get_all_image_presets():
    """Loads dynamic templates and merges them with static presets."""
    # Start with a deep copy of the hardcoded presets
    # to ensure backward compatibility and avoid mutating the original
    all_presets = {k: [p.copy() for p in v] for k, v in IMAGE_ACTION_PRESETS.items()}

    try:
        # Load dynamic templates of type 'image'
        dynamic_templates = prompt_template_service.load_templates(
            config_path="config/image_prompt_templates.json",
            template_type="image",
        )

        for template in dynamic_templates:
            t_dict = template.model_dump()
            # Normalize category to lowercase to match keys in IMAGE_ACTION_PRESETS
            category = t_dict.get("category", "custom").lower()

            if category not in all_presets:
                all_presets[category] = []

            # Check for duplicates by key to avoid showing the same action twice
            existing_keys = {p["key"] for p in all_presets[category]}
            if t_dict["key"] not in existing_keys:
                all_presets[category].append(t_dict)

    except Exception as e:
        analytics_logger.error(f"Error loading dynamic prompt templates: {e}")

    return all_presets


@me.stateclass
class PageState:
    """Gemini Image Generation Page State"""

    selected_model: str = "gemini-nano-banana-2.1"
    uploaded_image_gcs_uris: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    uploaded_image_display_urls: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    prompt: str = ""
    generated_image_urls: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    generated_image_captions: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    generated_resolution: str = ""
    is_generating: bool = False
    generation_complete: bool = False
    generation_time: float = 0.0
    selected_image_url: str = ""
    show_snackbar: bool = False
    snackbar_message: str = ""
    previous_media_item_id: str | None = None  # For linking generation sequences
    aspect_ratio: str = "1:1"
    image_size: str = "1K"
    num_images_to_generate: int = 0
    suggested_transformations: list[dict] = field(default_factory=list)  # pylint: disable=invalid-field-call
    is_suggesting_transformations: bool = False
    use_search: bool = False
    use_image_search: bool = False
    include_thoughts: bool = False
    thinking_level: str = "HIGH"
    thoughts: str = ""
    grounding_info: str = ""
    c2pa_manifests: dict[str, str] = field(
        default_factory=dict,
    )  # Store as dict of strings (url -> json_str)

    info_dialog_open: bool = False
    initial_load_complete: bool = False
    prompt_prefill_seen: str = ""  # last ?prompt= applied on load

    # Image Studio layout (composer, progress card, recent grid)
    prompt_key: int = 0
    is_enhancing: bool = False
    lightbox_url: str = ""
    last_prompt: str = ""
    last_input_uris: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    # Step-by-step progress (components/generation_progress)
    progress_stages: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    progress_stage: int = 0
    progress_status: str = ""
    progress_run_id: str = ""
    progress_error: str = ""
    # Session history for the "Recent" grid (display URLs, newest first)
    history_urls: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    history_prompts: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    history_meta: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    history_aspects: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call


on_aspect_ratio_change = get_on_aspect_ratio_change(PageState)
on_image_size_change = get_on_image_size_change(PageState)
on_num_images_change = get_on_num_images_change(PageState)
on_search_change = get_on_search_change(PageState)
on_image_search_change = get_on_image_search_change(PageState)
on_include_thoughts_change = get_on_include_thoughts_change(PageState)
on_thinking_level_change = get_on_thinking_level_change(PageState)
on_model_select = get_on_model_select(PageState)
on_prompt_blur = get_on_prompt_blur(PageState)
on_thumbnail_click = get_on_thumbnail_click(PageState)


with open("config/about_content.json") as f:
    about_content = json.load(f)
    NANO_BANANA_INFO = next(
        (
            s
            for s in about_content["sections"]
            if s.get("id") == "gemini_image_generation"
        ),
        None,
    )


def _render_grounding_info(grounding_info_str: str, theme_mode: str):
    """Renders the grounding information (search entry point and sources)."""
    if not grounding_info_str:
        return

    try:
        info = json.loads(grounding_info_str)
        if not info:
            return

        # Render Search Entry Point
        if (
            info.get("search_entry_point")
            and "rendered_content" in info["search_entry_point"]
        ):
            search_entry_point(
                html_content=info["search_entry_point"]["rendered_content"],
                theme_mode=theme_mode,
            )

        # Render Grounding Chunks as Links
        if "grounding_chunks" in info and isinstance(info["grounding_chunks"], list):
            me.text(
                "Sources",
                style=me.Style(font_weight="bold", margin=me.Margin(bottom=8)),
            )
            with me.box(
                style=me.Style(
                    display="flex",
                    flex_direction="column",
                    gap=4,
                    margin=me.Margin(bottom=16),
                ),
            ):
                for chunk in info["grounding_chunks"]:
                    if "web" in chunk:
                        web = chunk["web"]
                        title = web.get("title", "Source")
                        uri = web.get("uri", "#")
                        me.link(
                            text=title,
                            url=uri,
                            # target="_blank", # Removed due to error
                            style=me.Style(
                                color=me.theme_var("primary"),
                                text_decoration="underline",
                                font_size=14,
                            ),
                        )

    except Exception as e:
        me.text(f"Error parsing grounding info: {e}")
        me.text(grounding_info_str)


_ASPECT_NAMES = {
    "1:1": "Square",
    "16:9": "Landscape",
    "9:16": "Portrait",
    "4:3": "Classic",
    "3:4": "Classic portrait",
    "21:9": "Cinematic",
}


def _image_stages(has_inputs: bool) -> list[str]:
    return [
        "Reading your references" if has_inputs else "Preparing prompt",
        "Sending to Gemini",
        "Generating image",
        "Saving to library",
        "Done",
    ]


def _render_attachments():
    """Uploaded reference images, shown inside the composer above the prompt."""
    state = me.state(PageState)
    if not state.uploaded_image_display_urls:
        return
    with me.box(classes="gm-attach-row"):
        for i, uri in enumerate(state.uploaded_image_display_urls):
            composer_attachment(
                src=uri,
                label=f"reference image {i + 1}",
                index=i,
                on_remove=on_remove_image,
            )


def _image_chips(state: "PageState", model_config):
    """Setting chips and attach buttons in the composer row."""
    from config.gemini_image_models import GEMINI_IMAGE_MODELS

    chip_menu(
        key="img_chip_model",
        label="Model",
        icon="model",
        value=state.selected_model,
        options=chip_options(
            (
                m.model_name,
                m.display_name,
                f"Usually ~{m.typical_generation_seconds}s",
            )
            for m in GEMINI_IMAGE_MODELS
        ),
        on_change=on_chip_image_model,
    )
    aspects = (
        model_config.supported_aspect_ratios
        if model_config
        else ["1:1", "16:9", "9:16"]
    )
    chip_menu(
        key="img_chip_aspect",
        label="Aspect ratio",
        icon="aspect",
        value=state.aspect_ratio,
        options=chip_options(
            (a, a, _ASPECT_NAMES[a]) if a in _ASPECT_NAMES else a for a in aspects
        ),
        on_change=on_chip_image_aspect,
    )
    if model_config and model_config.supported_image_sizes:
        chip_menu(
            key="img_chip_size",
            label="Image size",
            icon="quality",
            value=state.image_size,
            options=chip_options(model_config.supported_image_sizes),
            on_change=on_chip_image_size,
        )
    max_output_images = model_config.max_output_images if model_config else 1
    if max_output_images > 1:
        chip_menu(
            key="img_chip_count",
            label="Number of images",
            icon="count",
            value=str(state.num_images_to_generate),
            options=chip_options(
                [("0", "Auto")]
                + [(str(i), f"{i} images") for i in range(1, max_output_images + 1)]
            ),
            on_change=on_chip_image_count,
        )
    if model_config and model_config.supports_search:
        chip_menu(
            key="img_chip_search",
            label="Ground with Google Search",
            icon="search",
            kind="toggle",
            value="Search",
            checked=state.use_search,
            on_change=on_chip_image_search,
        )

    max_input_images = model_config.max_input_images if model_config else 3
    upload_disabled = len(state.uploaded_image_gcs_uris) >= max_input_images
    with me.box(classes="gm-composer-attach"):
        with me.box(classes="gm-composer-btn"):
            with (
                me.tooltip(message="Attach reference images or files"),
                me.content_uploader(
                    on_upload=on_upload,
                    multiple=True,
                    accepted_file_types=model_config.supported_input_mime_types
                    if model_config
                    else ["image/jpeg", "image/png", "image/webp", "application/pdf"],
                    disabled=upload_disabled,
                    type="icon",
                    key="img_attach",
                ),
            ):
                me.icon("attach_file")
                with me.box(classes="gm-sr-only"):
                    me.text("Attach reference images or files")
        with me.box(classes="gm-composer-btn"):
            library_chooser_button(
                on_library_select=on_library_select,
                button_type="icon",
                disabled=upload_disabled,
                key="img_library",
            )


def _render_latest(state: "PageState", app_state):
    """The newest result, large, with credentials, resolution and sources."""
    if not state.generated_image_urls:
        return
    selected = (
        state.selected_image_url
        if state.selected_image_url in state.generated_image_urls
        else state.generated_image_urls[0]
    )
    selected_index = state.generated_image_urls.index(selected)
    caption = (
        state.generated_image_captions[selected_index]
        if selected_index < len(state.generated_image_captions)
        else ""
    )
    with me.box(classes="gm-latest-media"):
        with me.box(
            style=me.Style(
                position="relative",
                width="100%",
                display="flex",
                justify_content="center",
            ),
        ):
            with me.box(
                key=selected,
                on_click=on_open_latest,
                classes="gm-zoom",
                style=me.Style(width="100%", display="flex", justify_content="center"),
            ):
                me.image(
                    src=selected,
                    alt=caption or state.prompt[:120] or "Generated image",
                    style=me.Style(
                        width="100%",
                        max_height="72vh",
                        object_fit="contain",
                        border_radius=16,
                    ),
                )
            # Content Credentials (C2PA) Viewer
            with me.box(style=me.Style(position="absolute", top=16, right=16)):
                manifest_json = state.c2pa_manifests.get(selected)
                if manifest_json:
                    content_credentials_viewer(manifest=manifest_json)

        with me.box(classes="gm-latest-meta"):
            if state.generated_resolution:
                pill(
                    label=f"Resolution: {state.generated_resolution}",
                    pill_type="resolution",
                )
            if state.generation_time > 0:
                me.text(
                    f"Made in {state.generation_time:.1f}s",
                    style=me.Style(
                        font_size=13, color=me.theme_var("on-surface-variant")
                    ),
                )

        # Thumbnail strip when one prompt returned several images
        if len(state.generated_image_urls) > 1:
            with me.box(
                style=me.Style(
                    display="flex",
                    flex_direction="row",
                    flex_wrap="wrap",
                    gap=12,
                    justify_content="center",
                ),
            ):
                for i, url in enumerate(state.generated_image_urls):
                    is_selected = url == selected
                    thumb_caption = (
                        state.generated_image_captions[i]
                        if i < len(state.generated_image_captions)
                        else ""
                    )
                    with me.box(
                        key=url,
                        on_click=on_thumbnail_click,
                        style=me.Style(
                            padding=me.Padding.all(3),
                            border=me.Border.all(
                                me.BorderSide(
                                    width=3,
                                    style="solid",
                                    color=me.theme_var("primary")
                                    if is_selected
                                    else "transparent",
                                ),
                            ),
                            border_radius=14,
                            cursor="pointer",
                        ),
                    ):
                        me.image(
                            src=url,
                            alt=thumb_caption,
                            style=me.Style(
                                width=88,
                                height=88,
                                object_fit="cover",
                                border_radius=10,
                            ),
                        )

        if state.grounding_info:
            with me.box(style=me.Style(width="100%")):
                _render_grounding_info(state.grounding_info, app_state.theme_mode)


def _render_next_steps(state: "PageState"):
    """Follow-up actions for the selected image: continue, video, presets."""
    with me.box(classes="gm-next"):
        if state.generated_image_urls:
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## Keep going")
            with me.box(classes="gm-next-actions"):
                with me.content_button(on_click=on_continue_click, type="stroked"):
                    with me.box(classes="gm-btn-row"):
                        me.icon("edit")
                        me.text("Edit this image")
                omni_button(gcs_uri=https_url_to_gcs_uri(state.selected_image_url))
                veo_button(gcs_uri=https_url_to_gcs_uri(state.selected_image_url))

        # Image presets
        if state.generated_image_urls or state.uploaded_image_gcs_uris:
            all_presets = get_all_image_presets()
            for category_name, presets in all_presets.items():
                if not presets:
                    continue
                me.text(
                    f"{category_name.capitalize()} actions",
                    style=me.Style(
                        font_size=13,
                        font_weight=500,
                        color=me.theme_var("on-surface-variant"),
                        margin=me.Margin(top=8),
                    ),
                )
                with me.box(classes="gm-preset-row"):
                    for preset in presets:
                        label = preset.get("label") or preset["key"]
                        me.button(
                            label,
                            on_click=on_image_action_click,
                            type="stroked",
                            key=preset["key"],
                            style=CHIP_STYLE,
                        )

        # Suggest transformations button
        if (
            state.generation_complete
            and not state.suggested_transformations
            and state.generated_image_urls
        ):
            with me.box(style=me.Style(margin=me.Margin(top=8))):
                if state.is_suggesting_transformations:
                    with me.content_button(disabled=True, style=CHIP_STYLE):
                        with me.box(classes="gm-btn-row"):
                            me.progress_spinner(diameter=18, stroke_width=3)
                            me.text("Suggesting…")
                else:
                    with me.content_button(
                        on_click=on_suggest_transformations_click,
                        type="stroked",
                        style=CHIP_STYLE,
                    ):
                        with me.box(classes="gm-btn-row"):
                            svg_icon(icon_name="image_edit_auto")
                            me.text("Suggest edits")

        # Suggested transformations
        if state.suggested_transformations:
            with me.box(classes="gm-preset-row"):
                for transformation in state.suggested_transformations:
                    with me.content_button(
                        on_click=on_transformation_click,
                        key=json.dumps(transformation),
                        type="stroked",
                        style=CHIP_STYLE,
                    ):
                        with me.box(classes="gm-btn-row"):
                            svg_icon(icon_name="image_edit_auto")
                            me.text(transformation["title"])


def gemini_image_gen_page_content():
    """Renders the Image Studio: hero, composer, progress, latest, recent."""
    state = me.state(PageState)
    app_state = me.state(AppState)
    current_model_name = state.selected_model
    model_config = get_gemini_image_model_config(current_model_name)

    if state.info_dialog_open:
        with dialog(is_open=state.info_dialog_open):  # pylint: disable=not-context-manager
            me.text(f"About {NANO_BANANA_INFO['title']}", type="headline-6")
            me.markdown(NANO_BANANA_INFO["description"])
            me.divider()
            me.text("Current Settings", type="headline-6")
            me.text(f"Model: {model_config.model_name}")
            with me.box(style=me.Style(margin=me.Margin(top=16))):
                me.button("Close", on_click=close_info_dialog, type="flat")

    with page_frame():  # pylint: disable=E1129
        header(
            "Image Studio",
            "spark",
            show_info_button=True,
            on_info_click=open_info_dialog,
            description="Create and edit images from a prompt and your own pictures with Gemini.",
            centered=True,
        )

        with me.box(classes="gm-studio"):
            with composer(
                value=state.prompt,
                placeholder="Describe the image you want to generate…",
                on_blur=on_prompt_blur,
                on_submit=on_image_prompt_enter,
                on_click_send=generate_images,
                on_enhance=on_click_enhance_image_prompt,
                enhance_label="Enhance prompt with Gemini",
                enhancing=state.is_enhancing,
                busy=state.is_generating,
                send_label="Generate image",
                textarea_key=f"img_prompt_{state.prompt_key}",
                render_top=_render_attachments,
                on_clear=on_clear_click,
            ):
                _image_chips(state, model_config)

            generation_progress(
                state=state,
                typical_seconds=model_config.typical_generation_seconds
                if model_config
                else 15,
                work_stage=2,
                aspect=state.aspect_ratio,
                count=max(1, state.num_images_to_generate),
                media_label="image",
                on_retry=on_image_progress_retry,
                on_dismiss=on_image_progress_dismiss,
            )

            if state.generated_image_urls and not state.is_generating:
                with me.box(classes="gm-latest"):
                    with me.box(classes="gm-title gm-title-section"):
                        me.markdown("## Latest")
                    with me.box(classes="gm-latest-split"):
                        _render_latest(state, app_state)
                        _render_next_steps(state)
            elif (
                state.generation_complete
                and not state.generated_image_urls
                and not state.is_generating
                and state.progress_status != "error"
            ):
                empty_results(
                    "image_not_supported",
                    "No images came back",
                    "Try a different prompt or another model.",
                )
            elif state.uploaded_image_gcs_uris and not state.is_generating:
                _render_next_steps(state)
            elif (
                not state.is_generating
                and not state.history_urls
                and state.progress_status != "error"
            ):
                empty_results(
                    "image",
                    "Your images will show up here",
                    "Describe a picture, or attach your own to edit, then press Enter.",
                )

            if state.history_urls:
                with result_grid(title="Recent", count=len(state.history_urls)):
                    for i, url in enumerate(state.history_urls):
                        result_card(
                            key=f"img_hist_{i}_{url[-24:]}",
                            src=url,
                            kind="image",
                            prompt=state.history_prompts[i]
                            if i < len(state.history_prompts)
                            else "",
                            meta=state.history_meta[i]
                            if i < len(state.history_meta)
                            else "",
                            aspect=state.history_aspects[i]
                            if i < len(state.history_aspects)
                            else "1:1",
                            actions="open,download,reuse,edit,video",
                            selected=url == state.selected_image_url,
                            on_action=on_recent_image_action,
                        )

        with lightbox_dialog(  # pylint: disable=E1129:not-context-manager
            is_open=bool(state.lightbox_url),
            on_close=on_close_image_lightbox,
        ):
            if state.lightbox_url:
                me.image(
                    src=state.lightbox_url,
                    alt="Generated image, full size",
                    style=me.Style(
                        width="100%",
                        height="100%",
                        object_fit="contain",
                    ),
                )

        snackbar(is_visible=state.show_snackbar, label=state.snackbar_message)


def on_chip_image_model(e: me.WebEvent):
    """Model chip: switch model and keep settings it supports."""
    state = me.state(PageState)
    value = change_value(e)
    cfg = get_gemini_image_model_config(value)
    if not cfg:
        yield
        return
    state.selected_model = cfg.model_name
    if state.aspect_ratio not in cfg.supported_aspect_ratios:
        state.aspect_ratio = "1:1"
    if state.image_size not in cfg.supported_image_sizes:
        state.image_size = (
            "1K" if "1K" in cfg.supported_image_sizes else cfg.supported_image_sizes[0]
        )
    if not cfg.supports_search:
        state.use_search = False
    yield


def on_chip_image_aspect(e: me.WebEvent):
    """Aspect ratio chip."""
    me.state(PageState).aspect_ratio = change_value(e)
    yield


def on_chip_image_size(e: me.WebEvent):
    """Image size chip."""
    me.state(PageState).image_size = change_value(e)
    yield


def on_chip_image_count(e: me.WebEvent):
    """Number-of-images chip."""
    me.state(PageState).num_images_to_generate = int(change_value(e) or 0)
    yield


def on_chip_image_search(e: me.WebEvent):
    """Search grounding toggle chip."""
    me.state(PageState).use_search = change_value(e) == "true"
    yield


def on_image_prompt_enter(e: me.TextareaShortcutEvent):
    """Enter in the prompt box: store the prompt and generate."""
    state = me.state(PageState)
    state.prompt = e.value
    if state.is_generating:
        yield
        return
    yield from generate_images(e)


def on_click_enhance_image_prompt(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Rewrite the prompt with Gemini (uses attached images as context)."""
    state = me.state(PageState)
    if not state.prompt:
        yield from show_snackbar(state, "Write a prompt first, then enhance it.")
        return
    state.is_enhancing = True
    yield
    try:
        images = [
            (uri, _guess_mime(uri))
            for uri in state.uploaded_image_gcs_uris
            if _guess_mime(uri).startswith("image/")
        ]
        state.prompt = rewriter(state.prompt, REWRITER_PROMPT, images=images)
        state.prompt_key += 1
    except Exception as ex:  # pylint: disable=broad-except
        analytics_logger.error(f"Prompt enhancement failed: {ex}")
        state.is_enhancing = False
        yield from show_snackbar(
            state, f"Couldn't enhance the prompt. {friendly_error(ex)}"
        )
        return
    state.is_enhancing = False
    yield


def _guess_mime(uri: str) -> str:
    lowered = uri.lower()
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith((".mp4", ".mov", ".webm", ".mkv")):
        return "video/mp4"
    return "image/png"


def on_image_progress_retry(e: me.WebEvent):
    """'Try again' on the progress card repeats the last request."""
    state = me.state(PageState)
    yield from _generate_and_save(
        base_prompt=state.last_prompt or state.prompt,
        input_gcs_uris=list(state.last_input_uris)
        if state.last_prompt
        else state.uploaded_image_gcs_uris,
    )


def on_image_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    """Hide the progress card after an error."""
    progress_clear(me.state(PageState))
    yield


def on_open_latest(e: me.ClickEvent):
    """Open the latest image in the lightbox."""
    me.state(PageState).lightbox_url = e.key
    yield


def on_close_image_lightbox(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the lightbox."""
    me.state(PageState).lightbox_url = ""
    yield


def on_recent_image_action(e: me.WebEvent):
    """Actions from a card in the Recent grid."""
    state = me.state(PageState)
    action, src = card_action(e)
    if action == "open":
        state.lightbox_url = src
    elif action == "reuse":
        if src in state.history_urls:
            i = state.history_urls.index(src)
            if i < len(state.history_prompts):
                state.prompt = state.history_prompts[i]
                state.prompt_key += 1
    elif action == "edit":
        state.selected_image_url = src
        yield from on_continue_click(e)
        return
    elif action == "video":
        gcs_uri = https_url_to_gcs_uri(src)
        if gcs_uri.startswith("gs://"):
            me.navigate(
                url="/veo",
                query_params={"image_path": gcs_uri.replace("gs://", "")},
            )
        else:
            yield from show_snackbar(
                state, "This image isn't saved in Cloud Storage yet."
            )
            return
    yield


def _remember_images(state: "PageState", prompt: str):
    """Put new images at the front of the Recent grid."""
    cfg = get_gemini_image_model_config(state.selected_model)
    name = cfg.display_name if cfg else state.selected_model
    meta = f"{name} · {state.aspect_ratio} · {state.image_size}"
    for url in reversed(state.generated_image_urls):
        state.history_urls.insert(0, url)
        state.history_prompts.insert(0, prompt)
        state.history_meta.insert(0, meta)
        state.history_aspects.insert(0, state.aspect_ratio)


def _mock_image_run(final_prompt: str):
    """Dev-only: walk the stages with fake waits and placeholder pictures."""
    state = me.state(PageState)
    start_time = time.time()
    progress_step(state, 1)
    yield
    time.sleep(0.6)
    progress_step(state, 2)
    yield
    fake_wait(2.5, final_prompt)
    progress_step(state, 3)
    yield
    time.sleep(0.5)
    count = max(1, state.num_images_to_generate)
    state.generated_image_urls = [
        placeholder_image(final_prompt, state.aspect_ratio, i) for i in range(count)
    ]
    state.generated_image_captions = [final_prompt] * count
    state.generated_resolution = state.image_size
    state.selected_image_url = state.generated_image_urls[0]
    state.generation_time = time.time() - start_time
    _remember_images(state, final_prompt)
    progress_done(state)
    yield


def on_upload(e: me.UploadEvent):
    """Handles file uploads, stores them in GCS, and updates the state."""
    state = me.state(PageState)
    current_model_name = state.selected_model
    model_config = get_gemini_image_model_config(current_model_name)
    max_input_images = model_config.max_input_images if model_config else 3

    # Determine how many new images can be uploaded
    upload_slots_available = max_input_images - len(state.uploaded_image_gcs_uris)
    files_to_upload = e.files[:upload_slots_available]

    if not files_to_upload:
        yield from show_snackbar(
            state,
            f"You can upload a maximum of {max_input_images} images.",
        )
        return

    if len(e.files) > len(files_to_upload):
        yield from show_snackbar(
            state,
            f"You can upload a maximum of {max_input_images} images. Some files were not uploaded.",
        )

    for file in files_to_upload:
        gcs_url = store_to_gcs(
            "gemini_image_gen_references",
            file.name,
            file.mime_type,
            file.getvalue(),
        )
        state.uploaded_image_gcs_uris.append(gcs_url)
        state.uploaded_image_display_urls.append(create_display_url(gcs_url))
    yield


def on_library_select(e: LibrarySelectionChangeEvent):
    """Appends a selected library image's GCS URI to the list of uploaded images."""
    state = me.state(PageState)
    current_model_name = state.selected_model
    model_config = get_gemini_image_model_config(current_model_name)
    max_input_images = model_config.max_input_images if model_config else 3

    if len(state.uploaded_image_gcs_uris) >= max_input_images:
        yield from show_snackbar(
            state,
            f"You can upload a maximum of {max_input_images} images.",
        )
        return

    state.uploaded_image_gcs_uris.append(e.gcs_uri)
    state.uploaded_image_display_urls.append(create_display_url(e.gcs_uri))
    yield


def on_remove_image(e: me.ClickEvent):
    """Removes an image from the `uploaded_image_gcs_uris` list based on its index."""
    state = me.state(PageState)
    del state.uploaded_image_gcs_uris[int(e.key)]
    del state.uploaded_image_display_urls[int(e.key)]
    yield


def on_clear_click(e: me.ClickEvent):
    """Resets the entire page state to its initial values, clearing all inputs and outputs."""
    state = me.state(PageState)
    state.generated_image_urls = []
    state.generated_image_captions = []
    state.generated_resolution = ""
    state.prompt = ""
    state.uploaded_image_gcs_uris = []
    state.uploaded_image_display_urls = []
    state.selected_image_url = ""
    state.generation_time = 0.0
    state.generation_complete = False
    state.previous_media_item_id = None  # Reset the chain
    state.num_images_to_generate = 0
    state.suggested_transformations = []
    state.prompt_key += 1  # redraw the prompt box empty
    progress_clear(state)
    yield


def on_transformation_click(e: me.ClickEvent):
    """Handles clicks on suggested transformation buttons."""
    state = me.state(PageState)
    app_state = me.state(AppState)

    if not state.selected_image_url:
        yield from show_snackbar(state, "Please select an image to transform.")
        return

    try:
        transformation = json.loads(e.key)
        title = transformation["title"]
        prompt = transformation["prompt"]
    except (json.JSONDecodeError, KeyError):
        yield from show_snackbar(state, "Invalid transformation data.")
        return

    # Log the click event for analytics
    element_id = f"suggested_transformation_{title.replace(' ', '_').lower()}"
    log_ui_click(
        element_id=element_id,
        page_name=app_state.current_page,
        session_id=app_state.session_id,
    )

    input_gcs_uri = https_url_to_gcs_uri(state.selected_image_url)

    # The transformation uses the selected image as the sole input
    # and the button's key as the prompt.
    state.prompt = prompt  # Update the main prompt box for clarity
    yield from _generate_and_save(base_prompt=prompt, input_gcs_uris=[input_gcs_uri])


def on_suggest_transformations_click(e: me.ClickEvent):
    """Generates and displays suggested transformations for the primary generated image."""
    state = me.state(PageState)

    if not state.generated_image_urls:
        yield from show_snackbar(
            state,
            "No image available to suggest transformations for.",
        )
        return

    state.is_suggesting_transformations = True
    yield

    try:
        # Use the first generated image to get suggestions
        gcs_uri = f"gs://{state.generated_image_urls[0].replace('/media/', '')}"
        raw_transformations = generate_transformation_prompts(image_uris=[gcs_uri])
        # Convert Pydantic objects to dicts for state
        state.suggested_transformations = [t.model_dump() for t in raw_transformations]
    except Exception as ex:
        analytics_logger.error(f"Could not generate transformation prompts: {ex}")
        state.suggested_transformations = []
        yield from show_snackbar(state, f"Failed to get suggestions: {ex}")
    finally:
        state.is_suggesting_transformations = False
        yield


def on_image_action_click(e: me.ClickEvent):
    """Handles clicks on image action buttons, triggering a new generation."""
    state = me.state(PageState)
    app_state = me.state(AppState)

    # Find the preset that was clicked
    preset = None
    all_presets = get_all_image_presets()
    for category in all_presets.values():
        found = next((p for p in category if p["key"] == e.key), None)
        if found:
            preset = found
            break

    if not preset:
        yield from show_snackbar(state, f"Unknown action: {e.key}")
        return

    # Assemble the list of input URIs, starting with the user's image
    input_gcs_uris = []
    user_image_uri = ""

    # Prioritize the selected generated image
    if state.selected_image_url:
        user_image_uri = https_url_to_gcs_uri(state.selected_image_url)
    # Fallback to the first uploaded image
    elif state.uploaded_image_gcs_uris:
        user_image_uri = state.uploaded_image_gcs_uris[0]

    if user_image_uri:
        input_gcs_uris.append(user_image_uri)

    # Add reference images from the preset, if they exist
    preset_references = preset.get("references", [])
    if preset_references:
        input_gcs_uris.extend(preset_references)

    # If there are no images at all (neither from user nor preset), show an error
    if not input_gcs_uris:
        yield from show_snackbar(state, "Please upload or select an image first.")
        return

    # Log the click event for analytics
    log_ui_click(
        element_id=f"preset_action_{preset['key']}",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
    )

    # The action now uses the combined list of images
    yield from _generate_and_save(
        base_prompt=preset["prompt"],
        input_gcs_uris=input_gcs_uris,
    )


def on_continue_click(e: me.ClickEvent):
    """Uses the currently selected generated image as the input for a subsequent generation."""
    state = me.state(PageState)
    if not state.selected_image_url:
        yield from show_snackbar(state, "Please select an image to continue with.")
        return

    gcs_uri = https_url_to_gcs_uri(state.selected_image_url)
    state.uploaded_image_gcs_uris = [gcs_uri]
    state.uploaded_image_display_urls = [
        create_display_url(gcs_uri),
    ]  # This line is the fix
    state.generated_image_urls = []
    state.generated_image_captions = []
    state.generated_resolution = ""
    state.selected_image_url = ""
    state.generation_time = 0.0
    state.generation_complete = False
    # Keep state.previous_media_item_id to maintain the chain
    yield


def show_snackbar(state: PageState, message: str):
    """Displays a snackbar message at the bottom of the page."""
    state.snackbar_message = message
    state.show_snackbar = True
    yield
    time.sleep(3)
    state.show_snackbar = False
    yield
    # The snackbar will be hidden on the next interaction.


def _get_appended_prompt(base_prompt: str, num_images: int) -> str:
    """Appends the number of images prompt to the base prompt."""
    if num_images <= 1:
        return base_prompt

    suffix = f"Give me {num_images} images."

    if not base_prompt:
        return suffix

    # Avoid double punctuation
    if base_prompt.endswith((".", "!", "?")):
        return f"{base_prompt} {suffix}"
    return f"{base_prompt}. {suffix}"


def _generate_and_save(base_prompt: str, input_gcs_uris: list[str]):
    """Core logic to generate images and save results to Firestore."""
    state = me.state(PageState)
    app_state = me.state(AppState)

    # Clear previous suggestions before generating new ones
    state.suggested_transformations = []

    final_prompt = _get_appended_prompt(base_prompt, state.num_images_to_generate)
    # final_prompt = base_prompt

    state.is_generating = True
    state.generation_complete = False
    state.last_prompt = base_prompt
    state.last_input_uris = list(input_gcs_uris)
    progress_start(state, _image_stages(bool(input_gcs_uris)))
    yield

    start_time = time.time()
    try:
        if mock_enabled():
            yield from _mock_image_run(final_prompt)
            return
        progress_step(state, 1)
        yield
        progress_step(state, 2)
        yield
        gcs_uris, execution_time, captions, grounding_info, all_thoughts = (
            generate_image_from_prompt_and_images(
                prompt=final_prompt,
                images=input_gcs_uris,
                aspect_ratio=state.aspect_ratio,
                gcs_folder="gemini_image_generations",
                file_prefix="gemini_image",
                candidate_count=1,
                image_size=state.image_size,
                use_search=state.use_search,
                use_image_search=state.use_image_search,
                thinking_level=state.thinking_level,
                include_thoughts=state.include_thoughts,
                model_name=state.selected_model,
            )
        )

        progress_step(state, 3)
        yield
        state.generation_time = execution_time
        state.grounding_info = json.dumps(grounding_info) if grounding_info else ""
        state.thoughts = all_thoughts[0] if all_thoughts else ""

        if grounding_info:
            analytics_logger.info(
                f"Grounding Metadata Keys: {list(grounding_info.keys())}",
            )

        if not gcs_uris:
            item = MediaItem(
                prompt=final_prompt,
                mime_type="image/png",
                aspect=state.aspect_ratio,
                user_email=app_state.user_email,
                source_images_gcs=input_gcs_uris,
                comment="generated by gemini image generation",
                model=state.selected_model,
                related_media_item_id=state.previous_media_item_id,
                error_message="No images returned.",
                generation_time=execution_time,
                grounding_info=state.grounding_info,
            )
            add_media_item_to_firestore(item)
            state.previous_media_item_id = item.id
            progress_done(state)
            yield from show_snackbar(
                state,
                "No images were generated, but the attempt was logged to the library.",
            )
        else:
            state.generated_image_urls = [create_display_url(uri) for uri in gcs_uris]
            state.generated_image_captions = captions
            # Measure the actual resolution of the first generated image
            state.generated_resolution = get_image_resolution(gcs_uris[0])

            # Read C2PA Manifests for all images
            state.c2pa_manifests = {}
            for i, uri in enumerate(gcs_uris):
                manifest = c2pa_service.read_manifest(uri)
                display_url = state.generated_image_urls[i]
                if manifest:
                    state.c2pa_manifests[display_url] = json.dumps(manifest)
                    if i == 0:
                        analytics_logger.info(
                            "C2PA manifest found and loaded for image 0.",
                        )

            if state.generated_image_urls:
                state.selected_image_url = state.generated_image_urls[0]

            item = MediaItem(
                gcs_uris=gcs_uris,
                captions=captions,
                prompt=final_prompt,
                mime_type="image/png",
                aspect=state.aspect_ratio,
                resolution=state.generated_resolution,
                image_size=state.image_size,
                user_email=app_state.user_email,
                source_images_gcs=input_gcs_uris,
                comment="generated by gemini image generation",
                model=state.selected_model,
                related_media_item_id=state.previous_media_item_id,
                generation_time=execution_time,
                grounding_info=state.grounding_info,
            )
            add_media_item_to_firestore(item)
            state.previous_media_item_id = item.id
            _remember_images(state, final_prompt)
            progress_done(state)
            state.is_generating = False
            state.generation_complete = True
            yield from show_snackbar(state, "Automatically saved to library.")

    except Exception as ex:
        execution_time = time.time() - start_time
        analytics_logger.error(f"Failed to generate images. Details: {ex}")
        progress_fail(state, friendly_error(ex))
        item = MediaItem(
            prompt=final_prompt,
            mime_type="image/png",
            aspect=state.aspect_ratio,
            user_email=app_state.user_email,
            source_images_gcs=input_gcs_uris,
            comment="generated by gemini image generation",
            model=state.selected_model,
            related_media_item_id=state.previous_media_item_id,
            error_message=str(ex),
            generation_time=execution_time,
        )
        try:
            add_media_item_to_firestore(item)
            state.previous_media_item_id = item.id
        except Exception as log_ex:  # pylint: disable=broad-except
            # Keep the error card on screen even if the library is unreachable.
            analytics_logger.error(f"Could not log the failed attempt: {log_ex}")
        state.is_generating = False
        state.generation_complete = True
        yield from show_snackbar(state, f"An error occurred: {ex}")

    finally:
        state.is_generating = False
        state.generation_complete = True
        yield


def generate_images(e: me.ClickEvent):
    """Event handler for the main 'Generate Images' button."""
    state = me.state(PageState)
    yield from _generate_and_save(
        base_prompt=state.prompt,
        input_gcs_uris=state.uploaded_image_gcs_uris,
    )


def open_info_dialog(e: me.ClickEvent):
    """Open the info dialog."""
    state = me.state(PageState)
    state.info_dialog_open = True
    yield


def close_info_dialog(e: me.ClickEvent):
    """Close the info dialog."""
    state = me.state(PageState)
    state.info_dialog_open = False
    yield


from components.omni_button.omni_button import omni_button
from components.veo_button.veo_button import veo_button


def on_load(e: me.LoadEvent):
    """Handles the initial load of the page, checking for an image URI in the query parameters."""
    state = me.state(PageState)
    # This flag ensures the logic runs only once on initial page load,
    # not on subsequent yields or interactions.
    image_uri = me.query_params.get("image_uri")
    if image_uri:
        final_gcs_uri = image_uri
        # If a signed URL is passed, convert it back to a GCS URI.
        if image_uri.startswith("https://"):
            # Strip the query parameters from the signed URL.
            base_url = image_uri.split("?")[0]
            final_gcs_uri = https_url_to_gcs_uri(base_url)

        if final_gcs_uri and final_gcs_uri not in state.uploaded_image_gcs_uris:
            state.uploaded_image_gcs_uris.append(final_gcs_uri)
            state.uploaded_image_display_urls.append(
                create_display_url(final_gcs_uri),
            )
    if prefill_prompt(state, "prompt"):
        state.prompt_key += 1  # redraw the composer with the idea
    yield


@me.page(
    path="/gemini_image_generation",
    title="Image Studio - GenMedia Creative Studio",
    on_load=on_load,
)
@me.page(
    path="/nano-banana",
    title="Image Studio - GenMedia Creative Studio",
    on_load=on_load,
)
def page():
    """Define the Mesop page route for Gemini Image Generation."""
    with page_scaffold(page_name="gemini_image_generation"):  # pylint: disable=E1129
        gemini_image_gen_page_content()
