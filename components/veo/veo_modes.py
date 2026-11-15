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

import functools

import mesop as me

from common.analytics import log_ui_click
from state.state import AppState
from state.veo_state import PageState
from components.library.library_chooser_button import library_chooser_button
from config.veo_models import get_veo_model_config
from config.video_studio_models import (
    STUDIO_MODE_LABELS,
    StudioSettings,
    is_known_model,
    limits,
    normalise,
    studio_modes,
)


@me.component
def veo_modes(
    on_upload_image,
    on_upload_last_image,
    on_library_select,
    on_r2v_asset_add,
    on_r2v_asset_remove,
    on_r2v_style_add,
    on_r2v_style_remove,
    on_clear_first_image,
    on_clear_last_image,
    on_click_clear,
):
    """File uploader for I2V and interpolation, driven by model configuration."""
    state = me.state(PageState)
    selected_config = get_veo_model_config(state.veo_model)

    if not selected_config:
        return

    veo_mode_toggle()
    with me.box(
        style=me.Style(
            display="flex",
            flex_direction="column",
            align_items="center",
            flex_basis="max(480px, calc(50% - 48px))",
            padding=me.Padding(bottom=15),
            margin=me.Margin(top=6),
        ),
    ):
        if state.veo_mode == "t2v":
            me.image(src=None, style=me.Style(height=250))
        else:
            veo_reference_inputs(
                on_upload_image=on_upload_image,
                on_upload_last_image=on_upload_last_image,
                on_library_select=on_library_select,
                on_r2v_asset_add=on_r2v_asset_add,
                on_r2v_asset_remove=on_r2v_asset_remove,
                on_r2v_style_add=on_r2v_style_add,
                on_r2v_style_remove=on_r2v_style_remove,
                on_clear_first_image=on_clear_first_image,
                on_clear_last_image=on_clear_last_image,
            )


# Plain-language names for the Video Studio modes (values stay t2v/i2v/...).
VEO_MODE_LABELS = STUDIO_MODE_LABELS


@me.component
def veo_mode_toggle():
    """Segmented control for the modes the selected model (Omni or Veo) supports."""
    state = me.state(PageState)
    modes = studio_modes(state.veo_model)
    if not is_known_model(state.veo_model):
        return
    with me.box(classes="gm-segmented" + (" gm-segmented-many" if len(modes) > 4 else "")):
        me.button_toggle(
            value=state.veo_mode,
            buttons=[
                me.ButtonToggleButton(label=VEO_MODE_LABELS.get(mode, mode), value=mode)
                for mode in modes
            ],
            multiple=False,
            hide_selection_indicator=True,
            on_change=on_selection_change_veo_mode,
        )


@me.component
def veo_reference_inputs(
    on_upload_image,
    on_upload_last_image,
    on_library_select,
    on_r2v_asset_add,
    on_r2v_asset_remove,
    on_r2v_style_add,
    on_r2v_style_remove,
    on_clear_first_image,
    on_clear_last_image,
    render_video_input=None,
):
    """Reference slots for the current mode (nothing for t2v).

    Image slots for image, first + last frame and references; the Omni video
    modes (edit, extend, upscale) call `render_video_input` instead.
    """
    state = me.state(PageState)
    if not is_known_model(state.veo_model):
        return
    with me.box(classes="gm-veo-refs"):
        if state.veo_mode in ("edit", "extend", "upscale"):
            if render_video_input:
                render_video_input()
            return
        if state.veo_mode == "i2v":
            _image_uploader(
                last_image=False,
                on_upload_image=on_upload_image,
                on_upload_last_image=on_upload_last_image,
                on_library_select=on_library_select,
                on_clear_first_image=on_clear_first_image,
                on_clear_last_image=on_clear_last_image,
            )
        elif state.veo_mode == "interpolation":
            _image_uploader(
                last_image=True,
                on_upload_image=on_upload_image,
                on_upload_last_image=on_upload_last_image,
                on_library_select=on_library_select,
                on_clear_first_image=on_clear_first_image,
                on_clear_last_image=on_clear_last_image,
            )
        elif state.veo_mode == "r2v":
            _r2v_uploader(
                on_r2v_asset_add=on_r2v_asset_add,
                on_r2v_asset_remove=on_r2v_asset_remove,
                on_r2v_style_add=on_r2v_style_add,
                on_r2v_style_remove=on_r2v_style_remove,
                on_library_select=on_library_select,
            )


from common.utils import create_display_url
from components.image_thumbnail import image_thumbnail


@me.component
def _r2v_uploader(
    on_r2v_asset_add,
    on_r2v_asset_remove,
    on_r2v_style_add,
    on_r2v_style_remove,
    on_library_select,
):
    """Uploader for the Reference-to-Video (r2v) mode."""
    state = me.state(PageState)
    lim = limits(state.veo_model, "r2v")
    MAX_ASSET_IMAGES = lim.max_references if lim else 3
    # Veo takes one style image; Omni uses subject references only.
    show_style_reference = bool(lim and lim.supports_style_reference)

    # Determine if uploaders should be disabled
    style_uploader_disabled = bool(state.r2v_reference_images)
    asset_uploader_disabled = state.r2v_style_image is not None

    with me.box(style=me.Style(display="flex", flex_direction="row", gap=15)):
        # --- Assets Section ---
        with me.box(style=me.Style(display="flex", flex_direction="column", gap=2)):
            me.text(
                f"Subjects (up to {MAX_ASSET_IMAGES})", style=me.Style(font_size="10pt")
            )
            with me.box(
                style=me.Style(
                    display="flex", flex_direction="row", flex_wrap="wrap", gap=5
                )
            ):
                for i in range(MAX_ASSET_IMAGES):
                    if i < len(state.r2v_reference_images):
                        image_uri = state.r2v_reference_images[i]
                        image_thumbnail(
                            image_uri=create_display_url(image_uri),
                            index=i,
                            on_remove=on_r2v_asset_remove,
                            icon_size=16,
                        )
                    elif not asset_uploader_disabled and i == len(
                        state.r2v_reference_images
                    ):
                        _uploader_placeholder(
                            on_upload=on_r2v_asset_add,
                            on_library_select=on_library_select,
                            key_prefix="r2v_asset",
                            disabled=asset_uploader_disabled,
                        )
                    elif MAX_ASSET_IMAGES <= 3:
                        # Long lists (Omni takes 10) show one open slot only.
                        _empty_placeholder()
        # --- Style Section (Conditionally Rendered) ---
        if show_style_reference:
            with me.box(style=me.Style(display="flex", flex_direction="column", gap=2)):
                me.text("Style reference", style=me.Style(font_size="10pt"))
                with me.box(style=me.Style(display="flex", flex_direction="row", gap=5)):
                    if state.r2v_style_image:
                        image_thumbnail(
                            image_uri=create_display_url(state.r2v_style_image),
                            index=0,  # Only one style image
                            on_remove=on_r2v_style_remove,
                            icon_size=16,
                        )
                    else:
                        _uploader_placeholder(
                            on_upload=on_r2v_style_add,
                            on_library_select=on_library_select,
                            key_prefix="r2v_style",
                            disabled=style_uploader_disabled,
                        )


@me.component
def _uploader_placeholder(on_upload, on_library_select, key_prefix: str, disabled: bool):
    """A placeholder box with uploader and library chooser buttons."""
    with me.box(
        classes="gm-ref-slot",
        style=me.Style(
            height=100,
            width=100,
            border=me.Border.all(
                me.BorderSide(
                    width=1,
                    style="dashed",
                    color=me.theme_var("outline"),
                )
            ),
            border_radius=12,
            display="flex",
            flex_direction="row",
            align_items="center",
            justify_content="center",
            gap=4,
            opacity=0.5 if disabled else 1.0,
        ),
    ):
        with me.tooltip(message="Upload an image"):
            with me.content_uploader(
                on_upload=on_upload,
                accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                key=f"{key_prefix}_uploader",
                disabled=disabled,
                type="icon",
            ):
                me.icon("upload")
                with me.box(classes="gm-sr-only"):
                    me.text("Upload an image")
        with me.box(style=me.Style(pointer_events="none" if disabled else "auto")):
            library_chooser_button(
                key=f"{key_prefix}_library_chooser",
                on_library_select=on_library_select,
                button_type="icon",
            )


@me.component
def _empty_placeholder():
    """An empty, non-interactive placeholder box."""
    me.box(
        style=me.Style(
            height=100,
            width=100,
            border=me.Border.all(
                me.BorderSide(
                    width=1, style="dashed", color=me.theme_var("outline")
                )
            ),
            border_radius=8,
            opacity=0.5,
        )
    )




@me.component
def _image_uploader(
    last_image: bool,
    on_upload_image,
    on_upload_last_image,
    on_library_select,
    on_clear_first_image,
    on_clear_last_image,
):
    state = me.state(PageState)
    with me.box(style=me.Style(display="flex", flex_direction="row", gap=15)):
        # First Frame
        with me.box(style=me.Style(display="flex", flex_direction="column", gap=2)):
            me.text("First frame", style=me.Style(font_size="10pt"))
            if state.reference_image_uri:
                image_thumbnail(
                    image_uri=state.reference_image_uri,
                    index=0,
                    on_remove=on_clear_first_image,
                    icon_size=16,
                )
            else:
                _uploader_placeholder(
                    on_upload=on_upload_image,
                    on_library_select=on_library_select,
                    key_prefix="i2v",
                    disabled=False,
                )

        # Last Frame (for interpolation, also known as first/last frame)
        if last_image:
            with me.box(style=me.Style(display="flex", flex_direction="column", gap=2)):
                me.text("Last frame", style=me.Style(font_size="10pt"))
                if state.last_reference_image_uri:
                    image_thumbnail(
                        image_uri=state.last_reference_image_uri,
                        index=0,
                        on_remove=on_clear_last_image,
                        icon_size=16,
                    )
                else:
                    _uploader_placeholder(
                        on_upload=on_upload_last_image,
                        on_library_select=on_library_select,
                        key_prefix="interpolation_last",
                        disabled=False,
                    )


def on_selection_change_veo_mode(e: me.ButtonToggleChangeEvent):
    """toggle veo mode and validate/update settings."""
    app_state = me.state(AppState)
    log_ui_click(
        element_id="veo_mode",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
        extras={"value": e.value},
    )
    state = me.state(PageState)
    state.veo_mode = e.value

    # Yield immediately to allow the UI to rebuild with the new mode.
    yield

    # Keep length and aspect ratio valid for the new mode (e.g. Veo
    # references are 8 s only).
    model_config = get_veo_model_config(state.veo_model)
    override = ((model_config.mode_overrides or {}) if model_config else {}).get(
        e.value
    )
    if override and override.default_duration:
        state.video_length = override.default_duration
    apply_studio_settings(state)
    yield


def apply_studio_settings(state: PageState) -> None:
    """Bring mode, aspect, resolution, length and count in line with the model."""
    fixed = normalise(
        state.veo_model,
        StudioSettings(
            mode=state.veo_mode,
            aspect_ratio=state.aspect_ratio,
            resolution=state.resolution,
            video_length=state.video_length,
            video_count=state.video_count,
        ),
    )
    state.veo_mode = fixed.mode
    state.aspect_ratio = fixed.aspect_ratio
    state.resolution = fixed.resolution
    state.video_length = fixed.video_length
    state.video_count = fixed.video_count

def on_click_clear_reference_image(e: me.ClickEvent):
    """Clear reference image"""
    app_state = me.state(AppState)
    log_ui_click(
        element_id="veo_clear_reference_image",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
    )
    state = me.state(PageState)
    state.reference_image_file = None
    state.reference_image_file_key += 1
    state.reference_image_uri = None
    state.reference_image_gcs = None

    state.last_reference_image_file = None
    state.last_reference_image_file_key += 1
    state.last_reference_image_uri = None
    state.last_reference_image_gcs = None
    state.is_loading = False
    state.r2v_reference_images = []