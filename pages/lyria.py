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
"""Music page (/lyria): Lyria with the studio hero and composer layout."""

import datetime  # Required for timestamp
import json
import time

import mesop as me

from common.metadata import MediaItem, add_media_item_to_firestore  # Updated import
from common.mock_generation import fake_wait, mock_enabled, sample_audio
from common.utils import create_display_url
from components.composer.chip_menu import change_value, chip_menu, chip_options
from components.composer.composer import composer, composer_attachment
from components.content_credentials.content_credentials import (
    content_credentials_viewer,
)
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
from components.library.library_chooser_button import library_chooser_button
from components.lyria.audio_critic import audio_critic
from components.lyria.technical_metrics import technical_metrics
from components.page_scaffold import (
    page_frame,
    page_scaffold,
)
from components.result_grid.result_card import (
    card_action,
    empty_results,
    result_card,
    result_grid,
)
from config.default import ABOUT_PAGE_CONTENT, Default
from config.lyria_models import LYRIA_MODELS, get_lyria_model_config
from config.rewriters import MUSIC_REWRITER
from models.audio_analysis import analyze_audio_file
from models.gemini import analyze_audio_with_gemini, rewriter
from models.lyria import generate_music_with_lyria
from state.lyria_state import PageState
from state.state import AppState

cfg = Default()


@me.page(
    path="/lyria",
    title="Music - GenMedia Creative Studio",
    stylesheets=["/ui/audio-studio.css"],
)
def lyria_page():
    """Main Page."""
    state = me.state(AppState)
    with page_scaffold(page_name="lyria"):  # pylint: disable=not-context-manager
        lyria_content(state)


PURPOSE = "Compose music and songs from a description, with optional lyrics."

# Model chip order: newest first.
_MODEL_ORDER = ["3-pro-preview", "3-clip-preview", "2"]


def _ordered_models():
    rank = {v: i for i, v in enumerate(_MODEL_ORDER)}
    return sorted(LYRIA_MODELS, key=lambda m: rank.get(m.version_id, len(rank)))


def lyria_content(app_state: me.state):
    """Music page: hero, composer with chips, progress, tracks."""
    pagestate = me.state(PageState)

    if pagestate.info_dialog_open:
        with dialog(is_open=pagestate.info_dialog_open):  # pylint: disable=not-context-manager
            me.text("About Lyria", type="headline-6")
            me.markdown(
                next(
                    (
                        s["description"]
                        for s in ABOUT_PAGE_CONTENT.get("sections", [])
                        if s.get("id") == "lyria"
                    ),
                    "",
                ),
            )
            me.divider()
            me.text("Current Settings", type="headline-6")
            me.text(f"Prompt: {pagestate.music_prompt_input}")
            with dialog_actions():  # pylint: disable=not-context-manager
                me.button("Close", on_click=close_info_dialog, type="flat")

    model_config = get_lyria_model_config(pagestate.selected_model_id)
    supports_lyrics = bool(model_config and model_config.supports_lyrics)
    supports_images = bool(model_config and model_config.supports_images)

    with page_frame():  # pylint: disable=not-context-manager
        header(
            "Music",
            "music_note",
            show_info_button=True,
            on_info_click=open_info_dialog,
            description=PURPOSE,
            centered=True,
        )
        with me.box(classes="gm-studio gm-music"):
            with composer(
                value=pagestate.music_prompt_placeholder,
                placeholder="Describe the music: genre, mood, instruments, tempo…",
                on_blur=on_blur_lyria_prompt,
                on_submit=on_music_prompt_enter,
                on_click_send=on_click_lyria,
                on_enhance=on_click_enhance_music_prompt,
                enhance_label="Rewrite prompt with Gemini",
                enhancing=pagestate.is_rewriting,
                busy=pagestate.is_loading or pagestate.is_analyzing,
                send_label="Generate music",
                textarea_key=f"music_prompt_{pagestate.music_prompt_textarea_key}",
                render_top=_render_music_references if supports_images else None,
                on_clear=clear_music,
                clear_label="Clear prompt, lyrics and results",
            ):
                _music_chips(pagestate, model_config)

            if supports_lyrics and pagestate.show_lyrics:
                _lyrics_panel(pagestate)

            generation_progress(
                state=pagestate,
                typical_seconds=40,
                work_stage=2,
                aspect="8:1",
                count=max(1, pagestate.sample_count),
                media_label="music",
                on_retry=on_music_progress_retry,
                on_dismiss=on_music_progress_dismiss,
            )

            has_latest = bool(pagestate.music_display_urls) and not pagestate.is_loading
            if has_latest:
                with result_grid(title="Latest", wide=True):
                    for i, url in enumerate(pagestate.music_display_urls):
                        result_card(
                            key=f"music_latest_{i}_{url[-24:]}",
                            src=url,
                            kind="audio",
                            prompt=pagestate.music_prompt_input,
                            meta=_track_meta(pagestate, i),
                            actions="download,reuse",
                            on_action=on_music_card_action,
                        )
                _latest_extras(pagestate)
            elif not pagestate.is_loading and pagestate.progress_status != "error":
                empty_results(
                    "music_note",
                    "Your music will show up here",
                    "Describe a sound or a song, then press Enter.",
                )

            older = pagestate.history_urls[
                len(pagestate.music_display_urls) if has_latest else 0 :
            ]
            if older:
                offset = len(pagestate.history_urls) - len(older)
                with result_grid(title="Recent", count=len(older), wide=True):
                    for j, url in enumerate(older):
                        i = offset + j
                        result_card(
                            key=f"music_hist_{i}_{url[-24:]}",
                            src=url,
                            kind="audio",
                            prompt=pagestate.history_prompts[i]
                            if i < len(pagestate.history_prompts)
                            else "",
                            meta=pagestate.history_meta[i]
                            if i < len(pagestate.history_meta)
                            else "",
                            actions="download,reuse",
                            on_action=on_music_card_action,
                        )

        # Error dialog for prompt rewriting and lyrics writing.
        with dialog(is_open=pagestate.show_error_dialog):  # pylint: disable=not-context-manager
            me.text(
                "Something went wrong",
                type="headline-6",
                style=me.Style(color=me.theme_var("error"), font_weight="bold"),
            )
            me.text(pagestate.error_message, style=me.Style(margin=me.Margin(top=16)))
            with dialog_actions():  # pylint: disable=not-context-manager
                me.button("Close", on_click=on_close_error_dialog, type="flat")


def _track_meta(pagestate: PageState, index: int) -> str:
    model_config = get_lyria_model_config(pagestate.selected_model_id)
    name = model_config.display_name if model_config else pagestate.selected_model_id
    if len(pagestate.music_display_urls) > 1:
        return f"{name} · Track {index + 1}"
    return name


def _latest_extras(pagestate: PageState):
    """Credentials, text outputs, analysis for the latest generation."""
    with me.box(classes="gm-music-extras"):
        if pagestate.timing:
            me.text(
                pagestate.timing,
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        if pagestate.c2pa_manifest_json:
            content_credentials_viewer(manifest=pagestate.c2pa_manifest_json)
        if pagestate.generated_text:
            with me.expansion_panel(title="Generated text", icon="notes"):
                for text_output in pagestate.generated_text:
                    me.markdown(text_output)
                    me.divider()
        if pagestate.is_analyzing:
            with me.box(
                style=me.Style(display="flex", align_items="center", gap=10),
            ):
                me.progress_spinner(diameter=20, stroke_width=3)
                me.text("Analyzing the track with Gemini…")
        audio_critic()
        technical_metrics()


def _render_music_references():
    """Reference images inside the composer (Lyria 3)."""
    pagestate = me.state(PageState)
    if not pagestate.uploaded_image_display_urls:
        return
    with me.box(classes="gm-attach-row"):
        for i, uri in enumerate(pagestate.uploaded_image_display_urls):
            composer_attachment(
                src=uri,
                label=f"reference image {i + 1}",
                index=i,
                on_remove=on_remove_image,
            )


def _music_chips(pagestate: PageState, model_config):
    """Setting chips in the composer row."""
    chip_menu(
        key="music_chip_model",
        label="Model",
        icon="model",
        value=pagestate.selected_model_id,
        options=chip_options(
            (
                m.version_id,
                m.display_name,
                "Songs with lyrics" if m.supports_lyrics else "Instrumental clips",
            )
            for m in _ordered_models()
        ),
        on_change=on_chip_music_model,
    )
    if model_config and model_config.max_samples > 1:
        chip_menu(
            key="music_chip_count",
            label="Number of tracks",
            icon="count",
            value=str(pagestate.sample_count),
            options=chip_options(
                (str(i), f"{i} track" + ("s" if i > 1 else ""))
                for i in range(1, model_config.max_samples + 1)
            ),
            on_change=on_chip_music_count,
        )
    if model_config and model_config.supports_lyrics:
        chip_menu(
            key="music_chip_lyrics",
            label="Lyrics: add words to sing (optional)",
            icon="lyrics",
            kind="toggle",
            value="Lyrics",
            checked=pagestate.show_lyrics,
            on_change=on_chip_music_lyrics,
        )
    if model_config and model_config.supports_images:
        busy = pagestate.is_loading or pagestate.is_analyzing
        with me.box(classes="gm-composer-attach"):
            with me.box(classes="gm-composer-btn"):
                with (
                    me.tooltip(message="Attach a reference image"),
                    me.content_uploader(
                        on_upload=on_upload_lyria_image,
                        multiple=True,
                        accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                        disabled=busy,
                        type="icon",
                        key="music_attach",
                    ),
                ):
                    me.icon("add_photo_alternate")
                    with me.box(classes="gm-sr-only"):
                        me.text("Attach a reference image")
            with me.box(classes="gm-composer-btn"):
                library_chooser_button(
                    on_library_select=on_library_select,
                    button_type="icon",
                    disabled=busy,
                    key="music_library",
                )


def _lyrics_panel(pagestate: PageState):
    """Optional lyrics, a second field under the prompt."""
    with me.box(classes="gm-advanced gm-music-panel"):
        with me.box(classes="gm-advanced-head"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## Lyrics (optional)")
            with (
                me.content_button(type="icon", on_click=on_close_lyrics),
                me.tooltip(message="Hide lyrics"),
            ):
                me.icon("close")
                with me.box(classes="gm-sr-only"):
                    me.text("Hide lyrics")
        with me.box(classes="gm-music-lyrics"):
            me.native_textarea(
                key=f"music_lyrics_{pagestate.lyrics_key}",
                value=pagestate.lyrics_placeholder,
                placeholder="Write the words to sing, or leave this empty for music without words.",
                style=me.Style(height=150),
                on_blur=on_blur_lyria_lyrics,
            )
        with me.box(classes="gm-music-actions"):
            me.text(
                "Gemini can draft lyrics from your music prompt.",
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
            if pagestate.is_generating_lyrics:
                with me.box(style=me.Style(display="flex", align_items="center", gap=8)):
                    me.progress_spinner(diameter=20, stroke_width=3)
                    me.text("Writing lyrics…")
            else:
                with me.content_button(
                    type="stroked",
                    on_click=on_click_write_lyrics,
                    disabled=pagestate.is_loading,
                ):
                    with me.box(
                        style=me.Style(display="flex", align_items="center", gap=6),
                    ):
                        me.icon("auto_awesome")
                        me.text("Write lyrics with Gemini")


def on_chip_music_model(e: me.WebEvent):
    """Model chip."""
    value = change_value(e)
    if value:
        _apply_lyria_model(value)
    yield


def on_chip_music_count(e: me.WebEvent):
    """Number-of-tracks chip."""
    me.state(PageState).sample_count = int(change_value(e) or 1)
    yield


def on_chip_music_lyrics(e: me.WebEvent):
    """Show or hide the lyrics field."""
    me.state(PageState).show_lyrics = change_value(e) == "true"
    yield


def on_close_lyrics(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Hide the lyrics field (keeps what was written)."""
    me.state(PageState).show_lyrics = False
    yield


def on_music_prompt_enter(e: me.TextareaShortcutEvent):
    """Enter in the prompt box: store the prompt and generate."""
    state = me.state(PageState)
    if state.is_loading or state.is_analyzing:
        yield
        return
    state.music_prompt_input = e.value
    state.music_prompt_placeholder = e.value
    state.original_user_prompt = e.value
    yield from on_click_lyria(e)


def on_click_enhance_music_prompt(e: me.ClickEvent):
    """Rewrite the prompt with Gemini, with a spinner on the button."""
    state = me.state(PageState)
    state.is_rewriting = True
    yield
    try:
        yield from on_click_lyria_rewriter(e)
        state.music_prompt_textarea_key += 1
    finally:
        state.is_rewriting = False
        yield


def on_click_write_lyrics(e: me.ClickEvent):
    """Draft lyrics with Gemini, then refresh the lyrics field."""
    yield from on_click_lyria_lyrics_generate(e)
    me.state(PageState).lyrics_key += 1
    yield


def on_music_progress_retry(e: me.WebEvent):
    """'Try again' on the progress card."""
    yield from on_click_lyria(e)


def on_music_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    """Hide the progress card after an error."""
    progress_clear(me.state(PageState))
    yield


def on_music_card_action(e: me.WebEvent):
    """Actions from a track card."""
    state = me.state(PageState)
    action, src = card_action(e)
    if action == "reuse" and src in state.history_urls:
        i = state.history_urls.index(src)
        if i < len(state.history_prompts):
            prompt = state.history_prompts[i]
            state.music_prompt_input = prompt
            state.music_prompt_placeholder = prompt
            state.original_user_prompt = prompt
            state.music_prompt_textarea_key += 1
    yield


def _remember_tracks(state: PageState, prompt: str):
    """Put the new tracks at the front of the Recent list."""
    for i in reversed(range(len(state.music_display_urls))):
        state.history_urls.insert(0, state.music_display_urls[i])
        state.history_prompts.insert(0, prompt)
        state.history_meta.insert(0, _track_meta(state, i))


def _apply_lyria_model(value: str):
    """Switch model; drop lyrics and images the new model can't use."""
    state = me.state(PageState)
    state.selected_model_id = value
    model_config = get_lyria_model_config(value)
    if model_config and not model_config.supports_lyrics:
        state.lyrics_input = ""
        state.lyrics_placeholder = ""
        state.show_lyrics = False
        state.lyrics_key += 1
    if model_config and not model_config.supports_images:
        state.uploaded_image_gcs_uris = []
        state.uploaded_image_mime_types = []
        state.uploaded_image_display_urls = []
    if model_config and state.sample_count > model_config.max_samples:
        state.sample_count = model_config.max_samples


def on_lyria_model_change(e: me.SelectSelectionChangeEvent):
    _apply_lyria_model(e.value)


def on_blur_lyria_lyrics(e: me.InputBlurEvent):
    state = me.state(PageState)
    state.lyrics_input = e.value
    state.lyrics_placeholder = e.value


def on_clear_lyria_image(e: me.ClickEvent):
    state = me.state(PageState)
    state.uploaded_image_gcs_uris = []
    state.uploaded_image_mime_types = []
    state.uploaded_image_display_urls = []


def on_library_select(e: LibrarySelectionChangeEvent):
    state = me.state(PageState)
    # We could restrict max images based on Lyria config here if needed, but for now we'll just append
    state.uploaded_image_gcs_uris.append(e.gcs_uri)

    # MIME type is hard to guess from just GCS URI in this event,
    # but we can assume jpeg or png based on extension or fallback to jpeg.
    ext = e.gcs_uri.split(".")[-1].lower() if "." in e.gcs_uri else "jpeg"
    mime_type = f"image/{ext}" if ext in ["png", "webp"] else "image/jpeg"
    state.uploaded_image_mime_types.append(mime_type)

    from common.utils import create_display_url

    state.uploaded_image_display_urls.append(create_display_url(e.gcs_uri))
    yield


def on_remove_image(e: me.ClickEvent):
    state = me.state(PageState)
    index_to_remove = int(e.key)

    if 0 <= index_to_remove < len(state.uploaded_image_gcs_uris):
        state.uploaded_image_gcs_uris.pop(index_to_remove)
        state.uploaded_image_mime_types.pop(index_to_remove)
        state.uploaded_image_display_urls.pop(index_to_remove)
    yield


def on_upload_lyria_image(e: me.UploadEvent):
    state = me.state(PageState)
    if not e.files:
        return
    import shortuuid

    from common.storage import store_to_gcs
    from common.utils import create_display_url
    from config.default import Default

    cfg = Default()

    for file in e.files:
        mime_type = file.mime_type
        ext = "jpg" if "jpeg" in mime_type else "png"
        file_name = f"lyria_image_{shortuuid.uuid()}.{ext}"

        # Store to GCS
        gcs_uri = store_to_gcs(
            "images",
            file_name,
            mime_type,
            file.getvalue(),
            False,
            bucket_name=cfg.MEDIA_BUCKET,
        )
        state.uploaded_image_gcs_uris.append(gcs_uri)
        state.uploaded_image_mime_types.append(mime_type)
        state.uploaded_image_display_urls.append(create_display_url(gcs_uri))


def on_blur_lyria_prompt(e: me.InputBlurEvent):
    state = me.state(PageState)
    if not state.is_loading and not state.is_analyzing:
        state.music_prompt_input = e.value
        state.music_prompt_placeholder = e.value
        state.original_user_prompt = e.value
        state.audio_analysis_result_json = None
        state.analysis_error_message = ""
        state.loading_operation_message = ""


def on_click_lyria_rewriter(e: me.ClickEvent):
    state = me.state(PageState)
    prompt_to_rewrite = state.music_prompt_input
    if not prompt_to_rewrite:
        state.error_message = "Please enter a prompt before rewriting."
        state.show_error_dialog = True
        yield
        return
    if not state.original_user_prompt:
        state.original_user_prompt = prompt_to_rewrite

    state.is_loading = True
    state.loading_operation_message = (
        "Music rewriter in progress..."  # Set specific message
    )
    state.show_error_dialog = False
    state.error_message = ""
    state.audio_analysis_result_json = None
    state.analysis_error_message = ""
    yield

    try:
        rewritten_prompt = rewriter(prompt_to_rewrite, MUSIC_REWRITER)
        state.music_prompt_input = rewritten_prompt
        state.music_prompt_placeholder = rewritten_prompt
    except Exception as err:
        print(f"Error during prompt rewriting: {err}")
        state.error_message = str(err)
        state.show_error_dialog = True
    finally:
        state.is_loading = False
        state.loading_operation_message = ""  # Clear message
        yield


def on_click_lyria(e: me.ClickEvent):
    """Generate music with Lyria handler"""
    app_state = me.state(AppState)
    state = me.state(PageState)
    prompt_for_api = state.music_prompt_input
    if state.is_loading or state.is_analyzing:
        yield
        return
    progress_start(
        state,
        ["Preparing", "Sending to Lyria", "Composing", "Saving to library", "Done"],
    )
    if not prompt_for_api.strip():
        progress_fail(state, "Describe the music first, then press Enter.")
        yield
        return

    state.is_loading = True
    state.loading_operation_message = (
        "Generating music with Lyria..."  # Set specific message
    )
    state.music_upload_uri = ""
    state.show_error_dialog = False
    state.error_message = ""
    state.audio_analysis_result_json = None
    state.analysis_error_message = ""
    state.has_audio_metrics = False
    state.c2pa_manifest_json = ""
    state.timing = ""
    yield
    progress_step(state, 1)
    yield

    if mock_enabled():
        yield from _mock_music_job(state, prompt_for_api)
        return

    print(
        f"Let's make music with: {prompt_for_api} (Model: {state.selected_model_id}, Samples: {state.sample_count}, Images: {len(state.uploaded_image_gcs_uris)})",
    )
    if state.original_user_prompt and state.original_user_prompt != prompt_for_api:
        print(f"Original user prompt was: {state.original_user_prompt}")

    start_time = time.time()
    generated_successfully = False
    lyria_error_message_for_metadata = ""
    gcs_uri_for_analysis_and_metadata = ""
    analysis_dict_for_metadata = None

    progress_step(state, 2)
    yield
    try:
        destination_blob_paths, c2pa_data, text_outputs = generate_music_with_lyria(
            prompt=prompt_for_api,
            model_name=get_lyria_model_config(state.selected_model_id).model_name,
            lyrics=state.lyrics_input,
            image_gcs_uri=state.uploaded_image_gcs_uris[0]
            if state.uploaded_image_gcs_uris
            else None,
            image_mime_type=state.uploaded_image_mime_types[0]
            if state.uploaded_image_mime_types
            else None,
            sample_count=state.sample_count,
        )
        if c2pa_data:
            state.c2pa_manifest_json = (
                json.dumps(c2pa_data) if isinstance(c2pa_data, dict) else c2pa_data
            )

        state.music_gcs_uris = destination_blob_paths
        state.music_display_urls = [
            create_display_url(p) for p in destination_blob_paths
        ]

        # Use the first one for analysis and metadata for now
        gcs_uri_for_analysis_and_metadata = (
            destination_blob_paths[0] if destination_blob_paths else ""
        )

        state.generated_text = list(text_outputs or [])
        state.selected_track_index = 0

        print(f"Music generated: {state.music_display_urls}")
        generated_successfully = True
        progress_step(state, 3)
        _remember_tracks(state, prompt_for_api)
        progress_done(state)
    except Exception as err:
        print(f"Error during music generation: {err}")
        state.error_message = str(err)
        lyria_error_message_for_metadata = str(err)
        progress_fail(state, friendly_error(err))
    finally:
        state.is_loading = False
        state.loading_operation_message = ""  # Clear message
        yield

    if generated_successfully and gcs_uri_for_analysis_and_metadata:
        state.is_analyzing = True
        yield

        # --- Technical Audio Analysis ---
        try:
            print(
                f"Starting technical audio analysis for: {gcs_uri_for_analysis_and_metadata}",
            )
            metrics = analyze_audio_file(gcs_uri_for_analysis_and_metadata)
            state.audio_metrics.mean_pitch_hz = metrics.mean_pitch_hz
            state.audio_metrics.pitch_std_hz = metrics.pitch_std_hz
            state.audio_metrics.pitch_range_hz = metrics.pitch_range_hz
            state.audio_metrics.jitter_percent = metrics.jitter_percent
            state.audio_metrics.shimmer_db = metrics.shimmer_db
            state.audio_metrics.hnr_db = metrics.hnr_db
            state.audio_metrics.estimated_tempo_bpm = metrics.estimated_tempo_bpm
            state.audio_metrics.duration_sec = metrics.duration_sec
            state.has_audio_metrics = True
            print("Technical audio analysis successful.")
        except Exception as tech_err:
            print(f"Warning: Technical audio analysis failed: {tech_err}")
            # Don't fail the whole process, just log it.

        # --- Gemini Analysis ---
        try:
            print(
                f"Starting analysis with GCS URI: {gcs_uri_for_analysis_and_metadata}",
            )
            analysis_result_dict = analyze_audio_with_gemini(
                audio_uri=gcs_uri_for_analysis_and_metadata,
                music_generation_prompt=prompt_for_api,
            )
            if analysis_result_dict:
                state.audio_analysis_result_json = json.dumps(analysis_result_dict)
                analysis_dict_for_metadata = analysis_result_dict
                print(
                    f"Analysis successful, stored as JSON. Dict: {analysis_result_dict}",
                )
            else:
                state.analysis_error_message = "Analysis returned no result."
                print(state.analysis_error_message)

        except Exception as analysis_err:
            print(f"Error during audio analysis: {analysis_err}")
            state.analysis_error_message = f"Analysis failed: {analysis_err!s}"
        finally:
            state.is_analyzing = False
            yield

    end_time = time.time()
    execution_time = end_time - start_time
    state.timing = f"Generation time: {round(execution_time)} seconds"
    print(
        f"Total process (generation + analysis attempt) took: {execution_time:.2f} seconds",
    )

    logged_original_prompt = state.original_user_prompt
    logged_rewritten_prompt = ""
    if state.original_user_prompt and prompt_for_api != state.original_user_prompt:
        logged_rewritten_prompt = prompt_for_api
    elif not state.original_user_prompt and prompt_for_api:
        logged_original_prompt = prompt_for_api

    try:
        print(
            f"Logging to metadata: API Prompt='{prompt_for_api}', Original='{logged_original_prompt}', Rewritten='{logged_rewritten_prompt}'",
        )
        item = MediaItem(
            user_email=app_state.user_email,
            timestamp=datetime.datetime.now(datetime.UTC),
            prompt=prompt_for_api,
            original_prompt=logged_original_prompt,
            rewritten_prompt=logged_rewritten_prompt
            if logged_rewritten_prompt
            else None,
            model=get_lyria_model_config(state.selected_model_id).model_name,
            mime_type="audio/wav",  # Lyria generates WAV
            generation_time=execution_time,
            error_message=lyria_error_message_for_metadata
            if lyria_error_message_for_metadata
            else None,
            gcs_uris=state.music_gcs_uris if generated_successfully else [],
            generated_text=state.generated_text if generated_successfully else [],
            audio_analysis=json.dumps(analysis_dict_for_metadata)
            if analysis_dict_for_metadata
            else None,
            # duration might be available if analysis_dict_for_metadata contains it, or if Lyria API provides it
        )
        add_media_item_to_firestore(item)
    except Exception as meta_err:
        print(f"CRITICAL: Failed to store metadata: {meta_err}")


def _mock_music_job(state: PageState, prompt: str):
    """Dev-only: walk the stages with fake waits and a placeholder chime."""
    start = time.time()
    try:
        time.sleep(0.6)
        progress_step(state, 2)
        yield
        fake_wait(2.0, prompt)
        progress_step(state, 3)
        yield
        time.sleep(0.4)
        state.music_gcs_uris = []
        state.music_display_urls = [
            sample_audio(len(state.history_urls) + i)
            for i in range(max(1, state.sample_count))
        ]
        state.generated_text = []
        state.timing = f"Generation time: {round(time.time() - start)} seconds (mock)"
        _remember_tracks(state, prompt)
        progress_done(state)
    except Exception as err:  # pylint: disable=broad-except
        progress_fail(state, friendly_error(err))
    finally:
        state.is_loading = False
        state.loading_operation_message = ""
        yield


def clear_music(e: me.ClickEvent):
    state = me.state(PageState)
    state.lyrics_input = ""
    state.lyrics_placeholder = ""
    state.lyrics_key += 1
    state.history_urls = []
    state.history_prompts = []
    state.history_meta = []
    state.c2pa_manifest_json = ""
    progress_clear(state)
    state.music_prompt_input = ""
    state.music_prompt_placeholder = ""
    state.original_user_prompt = ""
    state.music_prompt_textarea_key += 1
    state.music_gcs_uris = []
    state.music_display_urls = []
    state.selected_track_index = 0
    state.generated_text = []
    state.is_loading = False
    state.is_analyzing = False
    state.show_error_dialog = False
    state.error_message = ""
    state.timing = ""
    state.audio_analysis_result_json = None
    state.analysis_error_message = ""
    state.loading_operation_message = ""  # Clear loading message
    state.has_audio_metrics = False
    # Reset metrics
    state.audio_metrics.mean_pitch_hz = 0.0
    state.audio_metrics.pitch_std_hz = 0.0
    state.audio_metrics.pitch_range_hz = 0.0
    state.audio_metrics.jitter_percent = 0.0
    state.audio_metrics.shimmer_db = 0.0
    state.audio_metrics.hnr_db = 0.0
    state.audio_metrics.estimated_tempo_bpm = 0.0
    state.audio_metrics.duration_sec = 0.0
    yield


def on_close_error_dialog(e: me.ClickEvent):
    state = me.state(PageState)
    state.show_error_dialog = False
    state.error_message = ""
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


def on_click_lyria_lyrics_generate(e: me.ClickEvent):
    state = me.state(PageState)
    prompt_to_use = state.music_prompt_input
    if not prompt_to_use:
        state.error_message = "Please enter a music prompt to generate lyrics from."
        state.show_error_dialog = True
        yield
        return

    state.is_generating_lyrics = True
    yield

    try:
        from config.rewriters import LYRICS_GENERATOR
        from models.gemini import rewriter

        # Handle seed lyrics if the user already started typing something
        seed_lyrics = state.lyrics_input.strip()

        prompt_with_seed = LYRICS_GENERATOR.format(user_prompt=prompt_to_use)
        if seed_lyrics:
            prompt_with_seed += f"\n\nSeed Ideas/Partial Lyrics:\n{seed_lyrics}"

        generated_lyrics = rewriter(
            prompt_with_seed,
            "",
        )  # The rewriter function appends the second param to the first if it's not a template. Since we manually formatted it, we can just pass empty string for the template. Actually, `rewriter(user_prompt, system_prompt)` where system_prompt is the rule.

        # Let's adjust how we use the rewriter. `rewriter(prompt, template)` does:
        # prompt = template + "\n\n" + user_prompt if template is string.
        # So we can pass prompt_to_use as the user_prompt, and build a custom template.

        custom_template = LYRICS_GENERATOR
        if seed_lyrics:
            custom_template += f"\n\nSeed Ideas/Partial Lyrics:\n{seed_lyrics}"

        generated_lyrics = rewriter(prompt_to_use, custom_template)

        state.lyrics_input = generated_lyrics
        state.lyrics_placeholder = generated_lyrics
    except Exception as err:
        print(f"Error during lyrics generation: {err}")
        state.error_message = str(err)
        state.show_error_dialog = True
    finally:
        state.is_generating_lyrics = False
        yield


def on_lyria_sample_count_change(e: me.SelectSelectionChangeEvent):
    state = me.state(PageState)
    state.sample_count = int(e.value)


def on_track_selection_change(e: me.SelectSelectionChangeEvent):
    state = me.state(PageState)
    state.selected_track_index = int(e.value)

    # Update analysis if available? We probably want to keep the analysis tied to the first track or explicitly run it again.
    # For now, just change the active track.
