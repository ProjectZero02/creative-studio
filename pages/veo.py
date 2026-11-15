# Copyright 2024 Google LLC
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
"""Veo mesop UI page."""

import datetime  # Required for timestamp
import json
import time

import mesop as me

from common.analytics import log_ui_click, track_click
from common.error_handling import AsyncVeoPollingFailedError, GenerationError
from common.metadata import (
    MediaItem,
    add_media_item_to_firestore,
    get_media_item_by_id,
)
from common.storage import store_to_gcs
from common.utils import create_display_url, get_image_dimensions_from_base64
from common.veo_utils import start_async_veo_job
from common.mock_generation import fake_wait, mock_enabled, sample_video
from components.composer.chip_menu import change_value, chip_menu, chip_options
from components.composer.composer import composer
from components.dialog import dialog, dialog_actions
from components.generation_progress.generation_progress import (
    friendly_error,
    generation_progress,
    progress_clear,
    progress_done,
    progress_fail,
    progress_start,
    progress_step,
)
from components.header import header
from components.library.events import LibrarySelectionChangeEvent
from components.lightbox_dialog.lightbox_dialog import lightbox_dialog
from components.omni_hint.omni_hint import omni_hint
from components.page_scaffold import page_frame, page_scaffold
from components.result_grid.result_card import (
    card_action,
    empty_results,
    result_card,
    result_grid,
)
from components.veo.veo_modes import veo_mode_toggle, veo_reference_inputs
from components.veo.video_display import video_display
from config.default import ABOUT_PAGE_CONTENT, Default
from config.rewriters import VIDEO_REWRITER
from config.veo_models import VEO_MODELS, get_veo_model_config
from models.gemini import rewriter
from models.model_setup import VeoModelSetup
from models.veo import APIReferenceImage, VideoGenerationRequest, generate_video
from state.state import AppState
from state.veo_state import PageState

config = Default()

veo_model = VeoModelSetup.init()


def on_veo_load(e: me.LoadEvent):
    """Handles page load events, including query parameters for deep linking."""
    state = me.state(PageState)
    image_path = me.query_params.get("image_path")  # Changed from image_uri
    veo_model_param = me.query_params.get("veo_model")

    if veo_model_param:
        _update_state_for_new_model(veo_model_param)

    if image_path:
        # When an image is passed, default to the i2v mode and Veo 3.1 Fast model.
        _update_state_for_new_model("3.1-fast")

        image_uri = ""
        if image_path.startswith("https://"):
            from common.utils import https_url_to_gcs_uri

            image_uri = https_url_to_gcs_uri(image_path)
        else:
            # Reconstruct the full GCS URI from the path for backward compatibility
            image_uri = f"gs://{image_path}"

        # Set the image from the query parameter
        state.reference_image_gcs = image_uri
        state.reference_image_uri = create_display_url(image_uri)
        # Switch to the Image-to-Video tab
        state.veo_mode = "i2v"
        # Provide a default prompt for a better user experience
        state.veo_prompt_input = "Animate this image with subtle motion."

    yield


@me.page(
    path="/veo",
    title="Video Studio - GenMedia Creative Studio",
    on_load=on_veo_load,
)
def veo_page():
    """Main Page."""
    state = me.state(AppState)
    with page_scaffold(page_name="veo"):  # pylint: disable=not-context-manager
        veo_content(state)


def on_selection_change_person_generation(e: me.SelectSelectionChangeEvent):
    """Handles changes to the person generation setting."""
    app_state = me.state(AppState)
    log_ui_click(
        element_id="veo_person_generation",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
        extras={"value": e.value},
    )
    state = me.state(PageState)
    state.person_generation = e.value
    yield


def on_change_video_length_select(e: me.SelectSelectionChangeEvent):
    """Handles changes to the video length select dropdown."""
    state = me.state(PageState)
    state.video_length = int(e.value)
    yield


def on_selection_change_aspect_ratio(e: me.SelectSelectionChangeEvent):
    """Handles changes to the aspect ratio setting."""
    state = me.state(PageState)
    state.aspect_ratio = e.value
    yield


def on_selection_change_resolution(e: me.SelectSelectionChangeEvent):
    """Handles changes to the resolution setting."""
    state = me.state(PageState)
    state.resolution = e.value
    yield


def on_selection_change_video_count(e: me.SelectSelectionChangeEvent):
    """Handles changes to the video count slider."""
    state = me.state(PageState)
    state.video_count = int(e.value)
    yield


def _update_state_for_new_model(model_version_id: str):
    """Update state when the model changes."""
    state = me.state(PageState)
    state.veo_model = model_version_id

    # Get the config for the NEW model
    new_model_config = get_veo_model_config(model_version_id)
    if new_model_config:
        # If the current mode is not supported by the new model, reset to default 't2v'.
        if state.veo_mode not in new_model_config.supported_modes:
            state.veo_mode = "t2v"

        # If the new model has a specific list of supported durations (discontinuous values)
        if new_model_config.supported_durations:
            # Check if the current video length is in the allowed list.
            if state.video_length not in new_model_config.supported_durations:
                # If not, reset to the model's default duration.
                state.video_length = new_model_config.default_duration
        # Otherwise, use the continuous min/max range
        else:
            min_dur = new_model_config.min_duration
            max_dur = new_model_config.max_duration
            if not (min_dur <= state.video_length <= max_dur):
                state.video_length = new_model_config.default_duration

        # Check for aspect ratio override for the current mode
        if (
            new_model_config.mode_overrides
            and state.veo_mode in new_model_config.mode_overrides
        ):
            override = new_model_config.mode_overrides[state.veo_mode]
            if (
                override.supported_aspect_ratios
                and state.aspect_ratio not in override.supported_aspect_ratios
            ):
                state.aspect_ratio = override.supported_aspect_ratios[0]

        # Ensure selected resolution is supported by the new model
        if state.resolution not in new_model_config.resolutions:
            state.resolution = new_model_config.resolutions[0]

        # Force auto-enhance prompt if required
        if new_model_config.requires_prompt_enhancement:
            state.auto_enhance_prompt = True


def on_selection_change_veo_model(e: me.SelectSelectionChangeEvent):
    """Handle changes to the Veo model selection."""
    _update_state_for_new_model(e.value)
    yield


def on_change_auto_enhance_prompt(e: me.CheckboxChangeEvent):
    """Toggle auto-enhance prompt."""
    app_state = me.state(AppState)
    log_ui_click(
        element_id="veo_auto_enhance_prompt",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
        extras={"checked": e.checked},
    )
    state = me.state(PageState)
    state.auto_enhance_prompt = e.checked
    yield



def on_blur_veo_seed(e: me.InputBlurEvent):
    """Handles blur event for the Veo seed input."""
    state = me.state(PageState)
    try:
        seed_value = int(e.value)
        state.veo_seed = seed_value if seed_value >= 0 else 0
    except ValueError:
        state.veo_seed = 0
    yield


def on_change_generate_audio(e: me.CheckboxChangeEvent):
    """Toggle audio generation."""
    app_state = me.state(AppState)
    log_ui_click(
        element_id="veo_generate_audio",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
        extras={"checked": e.checked},
    )
    state = me.state(PageState)
    state.generate_audio = e.checked
    yield


def veo_content(app_state: me.state):
    """Veo Mesop Page."""
    state = me.state(PageState)

    if state.info_dialog_open:
        with dialog(is_open=state.info_dialog_open):  # pylint: disable=E1129:not-context-manager
            me.text("About Veo", type="headline-6")
            me.markdown(ABOUT_PAGE_CONTENT["sections"][1]["description"])
            me.divider()
            me.text("Current Settings", type="headline-6")
            me.text(f"Prompt: {state.veo_prompt_input}")
            me.text(f"Negative Prompt: {state.negative_prompt}")
            me.text(f"Model: {state.veo_model}")
            me.text(f"Duration: {state.video_length}s")

            # Mode-specific settings display
            if state.veo_mode == "i2v":
                if state.reference_image_gcs:
                    me.text(f"Input Image: {state.reference_image_gcs}")
            elif state.veo_mode == "interpolation":
                if state.reference_image_gcs:
                    me.text(f"First Frame: {state.reference_image_gcs}")
                if state.last_reference_image_gcs:
                    me.text(f"Last Frame: {state.last_reference_image_gcs}")
            elif state.veo_mode == "r2v":
                if state.r2v_reference_images:
                    me.text(f"Asset Images: {len(state.r2v_reference_images)} selected")
                if state.r2v_style_image:
                    me.text(f"Style Image: {state.r2v_style_image}")

            with dialog_actions():  # pylint: disable=E1129:not-context-manager
                me.button("Close", on_click=close_info_dialog, type="flat")

    model_config = get_veo_model_config(state.veo_model)

    with page_frame():  # pylint: disable=E1129:not-context-manager
        header(
            "Video Studio",
            "movie",
            show_info_button=True,
            on_info_click=open_info_dialog,
            description="Turn a prompt, a picture or two frames into a video clip with Veo.",
            centered=True,
        )
        with me.box(classes="gm-studio"):
            with me.box(classes="gm-omni-slot"):
                omni_hint()
            veo_mode_toggle()
            with composer(
                value=state.veo_prompt_input,
                placeholder=_VEO_PLACEHOLDERS.get(
                    state.veo_mode, _VEO_PLACEHOLDERS["t2v"]
                ),
                on_blur=on_blur_veo_prompt,
                on_submit=on_veo_prompt_enter,
                on_click_send=on_click_veo,
                on_enhance=on_click_enhance_prompt,
                enhance_label="Enhance prompt with Gemini",
                enhancing=state.is_enhancing,
                busy=state.is_loading,
                send_label="Generate video",
                textarea_key=f"veo_prompt_{state.veo_prompt_textarea_key}",
                render_top=_render_veo_references if state.veo_mode != "t2v" else None,
                on_clear=on_click_clear,
            ):
                _veo_chips(state, model_config)

            if state.show_advanced:
                _veo_advanced_panel(state, model_config)

            generation_progress(
                state=state,
                typical_seconds=model_config.typical_generation_seconds
                if model_config
                else 60,
                work_stage=2,
                aspect=state.aspect_ratio,
                count=state.video_count,
                media_label="video",
                on_retry=on_progress_retry,
                on_dismiss=on_progress_dismiss,
            )

            if state.result_display_urls and not state.is_loading:
                with me.box(classes="gm-latest"):
                    with me.box(classes="gm-title gm-title-section"):
                        me.markdown("## Latest")
                    video_display(
                        on_thumbnail_click=on_thumbnail_click,
                        on_click_extend=on_click_extend_video,
                    )
            elif (
                not state.is_loading
                and not state.history_urls
                and state.progress_status != "error"
            ):
                empty_results(
                    "movie",
                    "Your videos will show up here",
                    "Pick a mode, describe the shot, then press Enter.",
                )

            if state.history_urls:
                extend_ok = bool(model_config and model_config.supports_video_extension)
                with result_grid(title="Recent", count=len(state.history_urls)):
                    for i, url in enumerate(state.history_urls):
                        result_card(
                            key=f"veo_hist_{i}_{url[-24:]}",
                            src=url,
                            kind="video",
                            prompt=state.history_prompts[i]
                            if i < len(state.history_prompts)
                            else "",
                            meta=state.history_meta[i]
                            if i < len(state.history_meta)
                            else "",
                            aspect=state.history_aspects[i]
                            if i < len(state.history_aspects)
                            else "16:9",
                            actions="open,download,reuse"
                            + (",extend" if extend_ok else ""),
                            selected=url == state.selected_video_url,
                            on_action=on_recent_video_action,
                        )

    with lightbox_dialog(  # pylint: disable=E1129:not-context-manager
        is_open=bool(state.lightbox_url),
        on_close=on_close_lightbox,
    ):
        if state.lightbox_url:
            me.video(
                key=f"lightbox_{state.lightbox_url}",
                src=state.lightbox_url,
                style=me.Style(width="100%", max_height="78vh", border_radius=12),
            )

    with dialog(is_open=state.show_error_dialog):  # pylint: disable=E1129:not-context-manager
        me.text(
            "Generation Error",
            type="headline-6",
            style=me.Style(color=me.theme_var("error")),
        )
        me.text(state.error_message, style=me.Style(margin=me.Margin(top=16)))
        with dialog_actions():  # pylint: disable=E1129:not-context-manager
            me.button("Close", on_click=on_close_error_dialog, type="flat")


_VEO_PLACEHOLDERS = {
    "t2v": "Describe the video you want to create…",
    "i2v": "Describe how the image should move…",
    "interpolation": "Describe what happens between the first and last frame…",
    "r2v": "Describe a scene using your reference images…",
}

_ASPECT_NAMES = {"16:9": "Landscape", "9:16": "Portrait", "1:1": "Square"}


def _render_veo_references():
    """Reference image slots inside the composer (i2v, first/last, r2v)."""
    veo_reference_inputs(
        on_upload_image=on_upload_image,
        on_upload_last_image=on_upload_last_image,
        on_library_select=on_veo_image_from_library,
        on_r2v_asset_add=on_r2v_asset_add,
        on_r2v_asset_remove=on_r2v_asset_remove,
        on_r2v_style_add=on_r2v_style_add,
        on_r2v_style_remove=on_r2v_style_remove,
        on_clear_first_image=on_clear_first_image,
        on_clear_last_image=on_clear_last_image,
    )


def _mode_limits(state: PageState, model_config):
    """Durations and aspect ratios for the current model and mode."""
    durations = model_config.supported_durations or list(
        range(model_config.min_duration, model_config.max_duration + 1)
    )
    aspects = model_config.supported_aspect_ratios
    override = (model_config.mode_overrides or {}).get(state.veo_mode)
    if override:
        durations = override.supported_durations or durations
        aspects = override.supported_aspect_ratios or aspects
    return durations, aspects


def _veo_chips(state: PageState, model_config):
    """Setting chips in the composer row."""
    if not model_config:
        return
    durations, aspects = _mode_limits(state, model_config)
    chip_menu(
        key="veo_chip_model",
        label="Model",
        icon="model",
        value=state.veo_model,
        options=chip_options(
            (m.version_id, m.display_name, f"Usually ~{m.typical_generation_seconds}s")
            for m in VEO_MODELS
        ),
        on_change=on_chip_veo_model,
    )
    chip_menu(
        key="veo_chip_aspect",
        label="Aspect ratio",
        icon="aspect",
        value=state.aspect_ratio,
        options=chip_options(
            (a, a, _ASPECT_NAMES.get(a, "")) if a in _ASPECT_NAMES else a
            for a in aspects
        ),
        on_change=on_chip_veo_aspect,
    )
    chip_menu(
        key="veo_chip_resolution",
        label="Resolution",
        icon="quality",
        value=state.resolution,
        options=chip_options(
            (r, r.upper() if r == "4k" else r) for r in model_config.resolutions
        ),
        on_change=on_chip_veo_resolution,
    )
    chip_menu(
        key="veo_chip_duration",
        label="Length",
        icon="timer",
        value=str(state.video_length),
        options=chip_options((str(d), f"{d}s") for d in durations),
        on_change=on_chip_veo_duration,
    )
    chip_menu(
        key="veo_chip_count",
        label="Number of videos",
        icon="count",
        value=str(state.video_count),
        options=chip_options(
            (str(i), f"{i} video" + ("s" if i > 1 else ""))
            for i in range(1, model_config.max_samples + 1)
        ),
        on_change=on_chip_veo_count,
    )
    if "3." in state.veo_model:
        chip_menu(
            key="veo_chip_audio",
            label="Generate audio",
            icon="audio",
            kind="toggle",
            value="Audio",
            checked=state.generate_audio,
            on_change=on_chip_veo_audio,
        )
    chip_menu(
        key="veo_chip_advanced",
        label="Advanced settings: seed, things to avoid, people",
        icon="tune",
        kind="toggle",
        value="Advanced",
        checked=state.show_advanced,
        on_change=on_chip_veo_advanced,
    )


def _veo_advanced_panel(state: PageState, model_config):
    """Seed, negative prompt, people and prompt enhancement."""
    with me.box(classes="gm-advanced"):
        with me.box(classes="gm-advanced-head"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## Advanced settings")
            with (
                me.content_button(type="icon", on_click=on_close_advanced),
                me.tooltip(message="Close advanced settings"),
            ):
                me.icon("close")
                with me.box(classes="gm-sr-only"):
                    me.text("Close advanced settings")
        with me.box(classes="gm-controls gm-advanced-grid"):
            me.textarea(
                label="Avoid in the video (negative prompt)",
                value=state.negative_prompt,
                on_blur=on_blur_negative_prompt,
                autosize=True,
                min_rows=1,
                max_rows=4,
                appearance="outline",
                style=me.Style(width="100%"),
            )
            with me.box(style=me.Style(display="flex", flex_direction="column")):
                me.input(
                    label="Seed (0 = random)",
                    value=str(state.veo_seed),
                    on_blur=on_blur_veo_seed,
                    type="number",
                    appearance="outline",
                    style=me.Style(width="100%"),
                )
                me.text(
                    "Steers the result. Veo 3.x can't repeat a result exactly "
                    "while prompt enhancement is on.",
                    style=me.Style(
                        font_size=12,
                        line_height="1.4",
                        color=me.theme_var("on-surface-variant"),
                        margin=me.Margin(top=-12),
                    ),
                )
            me.select(
                label="People in video",
                appearance="outline",
                options=[
                    me.SelectOption(label="Allow (All ages)", value="Allow (All ages)"),
                    me.SelectOption(
                        label="Allow (Adults only)", value="Allow (Adults only)"
                    ),
                    me.SelectOption(label="Don't Allow", value="Don't Allow"),
                ],
                value=state.person_generation,
                on_selection_change=on_selection_change_person_generation,
            )
        if model_config and model_config.supports_prompt_enhancement:
            is_required = model_config.requires_prompt_enhancement
            me.checkbox(
                label="Let Veo enhance the prompt"
                + (" (always on for this model)" if is_required else ""),
                on_change=on_change_auto_enhance_prompt,
                checked=True if is_required else state.auto_enhance_prompt,
                disabled=is_required,
            )


def on_chip_veo_model(e: me.WebEvent):
    """Model chip."""
    value = change_value(e)
    if value:
        _update_state_for_new_model(value)
    yield


def on_chip_veo_aspect(e: me.WebEvent):
    """Aspect ratio chip."""
    me.state(PageState).aspect_ratio = change_value(e)
    yield


def on_chip_veo_resolution(e: me.WebEvent):
    """Resolution chip."""
    me.state(PageState).resolution = change_value(e)
    yield


def on_chip_veo_duration(e: me.WebEvent):
    """Length chip."""
    me.state(PageState).video_length = int(change_value(e) or 8)
    yield


def on_chip_veo_count(e: me.WebEvent):
    """Number-of-videos chip."""
    me.state(PageState).video_count = int(change_value(e) or 1)
    yield


def on_chip_veo_audio(e: me.WebEvent):
    """Audio toggle chip."""
    me.state(PageState).generate_audio = change_value(e) == "true"
    yield


def on_chip_veo_advanced(e: me.WebEvent):
    """Show or hide the advanced settings panel."""
    me.state(PageState).show_advanced = change_value(e) == "true"
    yield


def on_close_advanced(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the advanced settings panel."""
    me.state(PageState).show_advanced = False
    yield


def on_veo_prompt_enter(e: me.TextareaShortcutEvent):
    """Enter in the prompt box: store the prompt and generate."""
    state = me.state(PageState)
    state.veo_prompt_input = e.value
    if state.is_loading:
        yield
        return
    yield from on_click_veo(e)


def on_click_enhance_prompt(e: me.ClickEvent):
    """Rewrite the prompt with Gemini, showing a spinner on the button."""
    state = me.state(PageState)
    if not state.veo_prompt_input:
        state.error_message = "Write a prompt first, then enhance it."
        state.show_error_dialog = True
        yield
        return
    state.is_enhancing = True
    yield
    try:
        yield from on_click_custom_rewriter(e)
        state.veo_prompt_textarea_key += 1
    except Exception as ex:  # pylint: disable=broad-except
        print(f"Prompt enhancement failed: {ex}")
        state.error_message = f"Couldn't enhance the prompt. {friendly_error(ex)}"
        state.show_error_dialog = True
    finally:
        state.is_enhancing = False
        yield


def on_progress_retry(e: me.WebEvent):
    """'Try again' on the progress card repeats the last action."""
    state = me.state(PageState)
    if state.last_action == "extend":
        yield from on_click_extend_video(e)
    else:
        yield from on_click_veo(e)


def on_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    """Hide the progress card after an error."""
    progress_clear(me.state(PageState))
    yield


def on_recent_video_action(e: me.WebEvent):
    """Actions from a card in the Recent grid."""
    state = me.state(PageState)
    action, src = card_action(e)
    if action == "open":
        state.lightbox_url = src
    elif action == "reuse":
        if src in state.history_urls:
            i = state.history_urls.index(src)
            if i < len(state.history_prompts):
                state.veo_prompt_input = state.history_prompts[i]
                state.veo_prompt_textarea_key += 1
    elif action == "extend":
        state.selected_video_url = src
        yield from on_click_extend_video(e)
        return
    yield


def on_close_lightbox(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the lightbox."""
    me.state(PageState).lightbox_url = ""
    yield


def _video_stages(first: str, work: str) -> list[str]:
    return [first, "Sending to Veo", work, "Saving to library", "Done"]


def _remember_results(state: PageState, prompt: str):
    """Put the new results at the front of the Recent grid."""
    model_config = get_veo_model_config(state.veo_model)
    name = model_config.display_name if model_config else state.veo_model
    meta = f"{name} · {state.resolution} · {state.video_length}s"
    for url in reversed(state.result_display_urls):
        state.history_urls.insert(0, url)
        state.history_prompts.insert(0, prompt)
        state.history_meta.insert(0, meta)
        state.history_aspects.insert(0, state.aspect_ratio)


def _mock_video_job(state: PageState, start_time: float, prompt: str):
    """Dev-only: walk the stages with fake waits and a sample clip."""
    progress_step(state, 1)
    yield
    time.sleep(0.8)
    progress_step(state, 2)
    yield
    for _ in range(4):
        time.sleep(1.5)
        yield
    fake_wait(0.2, prompt)
    progress_step(state, 3)
    yield
    time.sleep(0.6)
    state.result_gcs_uris = []
    state.result_display_urls = [sample_video()] * max(1, state.video_count)
    state.selected_video_url = state.result_display_urls[0]
    state.timing = f"Generation time: {round(time.time() - start_time)} seconds (mock)"
    _remember_results(state, prompt)
    state.is_loading = False
    progress_done(state)
    yield


def on_click_extend_video(e: me.ClickEvent):
    """Handles the click event for the Veo video extension."""
    state = me.state(PageState)
    app_state = me.state(AppState)

    # --- Input Validation ---
    if not state.veo_prompt_input:
        state.error_message = "Please enter a prompt for the extension."
        state.show_error_dialog = True
        yield
        return

    # --- Model Validation ---
    model_config = get_veo_model_config(state.veo_model)
    if not model_config or not model_config.supports_video_extension:
        state.error_message = "Video extension is not supported by the current model."
        state.show_error_dialog = True
        yield
        return

    # --- Video Selection Validation ---
    video_to_extend_url = state.selected_video_url or (
        state.result_display_urls[0] if state.result_display_urls else ""
    )
    if not video_to_extend_url:
        state.error_message = "No video selected to extend."
        state.show_error_dialog = True
        yield
        return

    # Convert display URL back to GCS URI
    from common.utils import https_url_to_gcs_uri

    video_input_gcs = https_url_to_gcs_uri(video_to_extend_url)

    # --- Reset State for New Generation ---
    state.is_loading = True
    state.error_message = ""
    state.result_video = ""
    state.result_gcs_uris = []
    state.result_display_urls = []
    state.selected_video_url = ""
    state.timing = "Extending video..."
    state.last_action = "extend"
    progress_start(state, _video_stages("Preparing the clip", "Extending video"))
    start_time = time.time()
    yield

    if mock_enabled():
        try:
            yield from _mock_video_job(state, start_time, state.veo_prompt_input)
        except Exception as ex:  # pylint: disable=broad-except
            state.error_message = str(ex)
            state.is_loading = False
            state.selected_video_url = video_to_extend_url
            progress_fail(state, friendly_error(ex))
            yield
        return

    # --- Prepare Request Data ---
    request = VideoGenerationRequest(
        prompt=state.veo_prompt_input,
        negative_prompt=state.negative_prompt,
        model_version_id=state.veo_model,
        aspect_ratio=state.aspect_ratio,
        resolution=state.resolution,
        duration_seconds=state.video_extend_length,  # Use extension length
        video_count=state.video_count,
        enhance_prompt=state.auto_enhance_prompt,
        seed=state.veo_seed if state.veo_seed > 0 else None,
        generate_audio=state.generate_audio,
        person_generation=state.person_generation,
        video_input_gcs=video_input_gcs,
        video_input_mime_type="video/mp4",  # Assumed MP4
    )

    progress_step(state, 1)
    yield

    yield from _run_veo_job(
        state,
        request,
        app_state.user_email,
        mode="extension",
        start_time=start_time,
        timing_label="Extension time",
        start_error="Failed to start extension job",
        unknown_error="Unknown error during extension.",
    )
    if state.progress_status == "error":
        # Keep the source clip selected so "Try again" can extend it again.
        state.selected_video_url = video_to_extend_url


def on_input_prompt(e: me.InputEvent):
    state = me.state(PageState)
    state.prompt = e.value
    yield


def on_blur_negative_prompt(e: me.InputBlurEvent):
    state = me.state(PageState)
    state.negative_prompt = e.value
    yield


@track_click(element_id="veo_clear_button")
def on_click_clear(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Clear prompt and video."""
    state = me.state(PageState)
    state.result_gcs_uris = []
    state.result_display_urls = []
    state.selected_video_url = ""
    state.prompt = None
    state.negative_prompt = ""
    state.veo_prompt_input = None
    state.original_prompt = None
    state.veo_prompt_textarea_key += 1
    state.veo_model = "3.1-fast"
    # Get default duration for the reset model
    model_config = get_veo_model_config(state.veo_model)
    state.video_length = model_config.default_duration if model_config else 8
    state.aspect_ratio = "16:9"
    # Clear all image types
    state.reference_image_gcs = None
    state.reference_image_uri = None
    state.last_reference_image_gcs = None
    state.last_reference_image_uri = None
    state.r2v_reference_images = []
    state.r2v_reference_mime_types = []
    state.r2v_style_image = None
    state.r2v_style_image_mime_type = None
    progress_clear(state)
    yield


def on_clear_first_image(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Clears the first reference image for i2v or interpolation."""
    state = me.state(PageState)
    state.reference_image_gcs = None
    state.reference_image_uri = None
    yield


def on_clear_last_image(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Clears the last reference image for interpolation."""
    state = me.state(PageState)
    state.last_reference_image_gcs = None
    state.last_reference_image_uri = None
    yield


@track_click(element_id="veo_rewrite_button")
def on_click_custom_rewriter(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Veo custom rewriter."""
    state = me.state(PageState)
    if not state.veo_prompt_input:
        print("Prompt is empty, skipping rewrite.")
        yield
        return

    # Gather mode-appropriate reference images so the rewriter has visual
    # context. Each entry is a (gcs_uri, mime_type) pair; empty URIs are skipped
    # by the rewriter. Use the mime types stored in state (not a hardcoded
    # image/png) for correctness.
    images: list[tuple[str, str]] = []
    if state.veo_mode == "i2v":
        if state.reference_image_gcs:
            images.append(
                (state.reference_image_gcs, state.reference_image_mime_type)
            )
    elif state.veo_mode == "interpolation":
        if state.reference_image_gcs:
            images.append(
                (state.reference_image_gcs, state.reference_image_mime_type)
            )
        if state.last_reference_image_gcs:
            images.append(
                (
                    state.last_reference_image_gcs,
                    state.last_reference_image_mime_type,
                )
            )
    elif state.veo_mode == "r2v":
        images.extend(
            zip(state.r2v_reference_images, state.r2v_reference_mime_types)
        )
        # NOTE: r2v_style_image is deliberately NOT included: a style image
        # influences the look, not the content, of the rewrite. This is an
        # easily-changed default if owner preference shifts.

    rewritten_prompt = rewriter(
        state.veo_prompt_input, VIDEO_REWRITER, images=images
    )
    state.veo_prompt_input = rewritten_prompt
    state.veo_prompt_placeholder = rewritten_prompt
    yield


@track_click(element_id="veo_create_button")
def on_click_veo(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Handles the click event for the Veo generation button."""
    state = me.state(PageState)
    app_state = me.state(AppState)

    # --- Input Validation ---
    if not state.veo_prompt_input:
        state.error_message = "Please enter a prompt."
        state.show_error_dialog = True
        yield
        return

    # --- Reset State for New Generation ---
    state.is_loading = True
    state.error_message = ""
    state.result_video = ""
    state.result_gcs_uris = []
    state.result_display_urls = []
    state.selected_video_url = ""
    state.timing = ""
    state.last_action = "generate"
    model_config = get_veo_model_config(state.veo_model)
    enhancing = state.auto_enhance_prompt or bool(
        model_config and model_config.requires_prompt_enhancement
    )
    progress_start(
        state,
        _video_stages(
            "Enhancing prompt" if enhancing else "Preparing request",
            "Generating video",
        ),
    )
    start_time = time.time()
    yield

    if mock_enabled():
        try:
            yield from _mock_video_job(state, start_time, state.veo_prompt_input)
        except Exception as ex:  # pylint: disable=broad-except
            state.error_message = str(ex)
            state.is_loading = False
            progress_fail(state, friendly_error(ex))
            yield
        return

    # --- Prepare Request Data ---
    # (Logic copied from original to maintain parity)
    request = VideoGenerationRequest(
        prompt=state.veo_prompt_input,
        negative_prompt=state.negative_prompt,
        model_version_id=state.veo_model,
        aspect_ratio=state.aspect_ratio,
        resolution=state.resolution,
        duration_seconds=state.video_length,
        video_count=state.video_count,
        enhance_prompt=state.auto_enhance_prompt,
        seed=state.veo_seed if state.veo_seed > 0 else None,
        generate_audio=state.generate_audio,
        person_generation=state.person_generation,
        reference_image_gcs=state.reference_image_gcs
        if state.veo_mode in ["i2v", "r2v", "interpolation"]
        and state.reference_image_gcs
        else None,
        reference_image_mime_type=state.reference_image_mime_type,
        last_reference_image_gcs=state.last_reference_image_gcs
        if state.veo_mode == "interpolation" and state.last_reference_image_gcs
        else None,
        last_reference_image_mime_type=state.last_reference_image_mime_type,
        r2v_references=[
            APIReferenceImage(gcs_uri=uri, mime_type=mime)
            for uri, mime in zip(
                state.r2v_reference_images, state.r2v_reference_mime_types
            )
        ]
        if state.veo_mode == "r2v" and state.r2v_reference_images
        else None,
        r2v_style_image=APIReferenceImage(
            gcs_uri=state.r2v_style_image, mime_type=state.r2v_style_image_mime_type
        )
        if state.veo_mode == "r2v" and state.r2v_style_image
        else None,
    )
    progress_step(state, 1)
    yield

    yield from _run_veo_job(
        state,
        request,
        app_state.user_email,
        mode=state.veo_mode,
        start_time=start_time,
        timing_label="Generation time",
        start_error="Failed to start generation job",
        unknown_error="Unknown error during generation.",
    )


def _run_veo_job(
    state: PageState,
    request: VideoGenerationRequest,
    user_email: str,
    mode: str,
    start_time: float,
    timing_label: str,
    start_error: str,
    unknown_error: str,
):
    """Start an async Veo job and poll it, moving the progress card along.

    Errors go to the progress card (which keeps the prompt and offers
    "Try again") instead of a modal dialog.
    """
    prompt = state.veo_prompt_input
    # --- 1. Initiate Async Job ---
    try:
        data = start_async_veo_job(request, user_email, mode=mode)
        if not data.get("job_id"):
            # create_initial_job returns None when Firestore is unreachable.
            raise RuntimeError(
                "Could not save the job record. Check Firestore access and "
                "Google Cloud credentials."
            )

        state.current_job_id = data["job_id"]
        state.job_status = data["status"]
        progress_step(state, 2)
        yield
    except Exception as e:
        print(f"{start_error}: {e}")
        state.error_message = f"{start_error}: {e}"
        state.is_loading = False
        progress_fail(state, friendly_error(e))
        yield
        return

    # --- 2. Poll for Completion ---
    # NOTE: In a real production app, consider using a more robust polling mechanism
    # or WebSockets if available. For now, this simple loop with yields works
    # within Mesop's generator-based event handlers to keep the UI responsive.
    while state.job_status in ["pending", "processing", "created"]:
        time.sleep(2)
        try:
            item = get_media_item_by_id(state.current_job_id)
            if not item:
                raise AsyncVeoPollingFailedError(
                    f"Job {state.current_job_id} not found in Firestore."
                )

            state.job_status = item.status

            if state.job_status == "complete":
                progress_step(state, 3)
                yield
                # Success! Update state with results.
                state.result_gcs_uris = item.gcs_uris or []
                # If only one URI is returned but we expected a list, handle it.
                if not state.result_gcs_uris and item.gcsuri:
                    state.result_gcs_uris = [item.gcsuri]

                state.result_display_urls = [
                    create_display_url(uri) for uri in state.result_gcs_uris
                ]
                if state.result_display_urls:
                    state.selected_video_url = state.result_display_urls[0]

                end_time = time.time()
                execution_time = end_time - start_time
                state.timing = f"{timing_label}: {round(execution_time)} seconds"
                _remember_results(state, prompt)
                state.is_loading = False
                progress_done(state)
                yield
                break

            elif state.job_status == "failed":
                # Failure. Show error on the progress card.
                state.error_message = item.error_message or unknown_error
                state.is_loading = False
                progress_fail(state, friendly_error(state.error_message))
                yield
                break

            # Still polling...
            yield

        except Exception as e:
            error = AsyncVeoPollingFailedError(f"Polling failed: {e}")
            state.error_message = str(error)
            state.is_loading = False
            progress_fail(state, friendly_error(error))
            yield
            break


def on_blur_veo_prompt(e: me.InputBlurEvent):
    """Veo prompt blur event."""
    state = me.state(PageState)
    state.veo_prompt_input = e.value
    yield


def on_thumbnail_click(e: me.ClickEvent):
    """Sets the clicked thumbnail as the main selected video."""
    state = me.state(PageState)
    state.selected_video_url = e.key
    yield


def on_close_error_dialog(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Handler to close the error dialog."""
    state = me.state(PageState)
    state.show_error_dialog = False
    yield


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


def on_upload_image(e: me.UploadEvent):
    """Upload image to GCS and update state."""
    state = me.state(PageState)
    try:
        # Store the uploaded file to GCS
        gcs_path = store_to_gcs(
            "uploads", e.file.name, e.file.mime_type, e.file.getvalue()
        )
        # Update the state with the new image details
        state.reference_image_gcs = gcs_path
        state.reference_image_uri = create_display_url(gcs_path)
        state.reference_image_mime_type = e.file.mime_type
        print(f"Image uploaded to {gcs_path} with mime type {e.file.mime_type}")
    except Exception as ex:
        state.error_message = f"Failed to upload image: {ex}"
        state.show_error_dialog = True
    yield


def on_upload_last_image(e: me.UploadEvent):
    """Upload last image to GCS and update state."""
    state = me.state(PageState)
    try:
        # Store the uploaded file to GCS
        gcs_path = store_to_gcs(
            "uploads", e.file.name, e.file.mime_type, e.file.getvalue()
        )
        # Update the state with the new image details
        state.last_reference_image_gcs = gcs_path
        state.last_reference_image_uri = create_display_url(gcs_path)
        state.last_reference_image_mime_type = e.file.mime_type
    except Exception as ex:
        state.error_message = f"Failed to upload image: {ex}"
        state.show_error_dialog = True
    yield


def on_r2v_asset_add(e: me.UploadEvent):
    """Adds a new asset reference image for R2V mode."""
    state = me.state(PageState)
    if len(state.r2v_reference_images) >= 3:
        state.error_message = "You can upload a maximum of 3 asset images."
        state.show_error_dialog = True
        yield
        return

    try:
        gcs_path = store_to_gcs(
            "uploads", e.file.name, e.file.mime_type, e.file.getvalue()
        )
        state.r2v_reference_images.append(gcs_path)
        state.r2v_reference_mime_types.append(e.file.mime_type)
    except Exception as ex:
        state.error_message = f"Failed to upload image: {ex}"
        state.show_error_dialog = True
    yield


def on_r2v_asset_remove(e: me.ClickEvent):
    """Removes an asset reference image from the R2V list."""
    state = me.state(PageState)
    index_to_remove = int(e.key)
    if 0 <= index_to_remove < len(state.r2v_reference_images):
        state.r2v_reference_images.pop(index_to_remove)
        state.r2v_reference_mime_types.pop(index_to_remove)
    yield


def on_r2v_style_add(e: me.UploadEvent):
    """Adds a style reference image for R2V mode."""
    state = me.state(PageState)
    try:
        gcs_path = store_to_gcs(
            "uploads", e.file.name, e.file.mime_type, e.file.getvalue()
        )
        state.r2v_style_image = gcs_path
        state.r2v_style_image_mime_type = e.file.mime_type
    except Exception as ex:
        state.error_message = f"Failed to upload image: {ex}"
        state.show_error_dialog = True
    yield


def on_r2v_style_remove(e: me.ClickEvent):
    """Removes the style reference image."""
    state = me.state(PageState)
    state.r2v_style_image = None
    state.r2v_style_image_mime_type = None
    yield


def on_veo_image_from_library(e: LibrarySelectionChangeEvent):
    """VEO image from library handler."""
    state = me.state(PageState)

    # Helper to infer mime type from extension
    def infer_mime(uri: str) -> str:
        if uri.lower().endswith(".png"):
            return "image/png"
        if uri.lower().endswith(".jpg") or uri.lower().endswith(".jpeg"):
            return "image/jpeg"
        if uri.lower().endswith(".webp"):
            return "image/webp"
        return "image/png"  # Default fallback

    if e.chooser_id.startswith("i2v") or e.chooser_id.startswith("first_frame"):
        state.reference_image_gcs = e.gcs_uri
        state.reference_image_uri = create_display_url(e.gcs_uri)
        state.reference_image_mime_type = infer_mime(e.gcs_uri)
    elif e.chooser_id.startswith("interpolation_last"):
        state.last_reference_image_gcs = e.gcs_uri
        state.last_reference_image_uri = create_display_url(e.gcs_uri)
        state.last_reference_image_mime_type = infer_mime(e.gcs_uri)
    elif e.chooser_id.startswith("r2v_asset_library_chooser"):
        if len(state.r2v_reference_images) >= 3:
            state.error_message = "You can upload a maximum of 3 asset images."
            state.show_error_dialog = True
            yield
            return
        state.r2v_reference_images.append(e.gcs_uri)
        state.r2v_reference_mime_types.append(infer_mime(e.gcs_uri))
    elif e.chooser_id.startswith("r2v_style_library_chooser"):
        state.r2v_style_image = e.gcs_uri
        state.r2v_style_image_mime_type = infer_mime(e.gcs_uri)

    yield
