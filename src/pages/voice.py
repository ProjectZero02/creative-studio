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
"""Voice: one page for every speech engine (Gemini TTS models and Chirp 3 HD).

Replaces /gemini-tts and /chirp-3hd, which now redirect here with their
engine preselected (?engine=...). Layout matches Image and Video Studio:
centred hero, the shared composer with setting chips, stage-by-stage
progress and audio result cards.
"""

import datetime
import json
import time
import uuid

import mesop as me

from common import storage
from common.analytics import get_logger
from common.metadata import MediaItem, add_media_item_to_firestore
from common.mock_generation import fake_wait, mock_enabled, sample_audio
from common.prompt_prefill import prefill_prompt
from common.utils import create_display_url
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
from components.page_scaffold import page_frame, page_scaffold
from components.result_grid.result_card import (
    card_action,
    empty_results,
    result_card,
    result_grid,
)
from config.voice import (
    DEFAULT_DIALOGUE,
    DEFAULT_LANGUAGE,
    DEFAULT_SCRIPT,
    ENCODINGS,
    PACES,
    STYLES,
    VOICES,
    engine_label,
    engine_options,
    engine_supports_dialogue,
    is_chirp,
    is_known_engine,
    languages_for,
)
from models.voice import VoiceRequest, describe, synthesize_voice, validate
from state.state import AppState
from state.voice_state import VoiceState

logger = get_logger(__name__)

with open("config/about_content.json", encoding="utf-8") as _f:
    _ABOUT = {s.get("id"): s for s in json.load(_f).get("sections", [])}

PURPOSE = "Turn a script into natural speech in 130+ languages."


def on_voice_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    """Preselect ?engine= (old /gemini-tts and /chirp-3hd links); prefill ?prompt=."""
    state = me.state(VoiceState)
    engine = me.query_params.get("engine", "")
    if engine and is_known_engine(engine):
        _set_engine(state, engine)
    # The sample scripts count as empty; the user's own script never does.
    if prefill_prompt(state, "text", empty_values=(DEFAULT_SCRIPT, DEFAULT_DIALOGUE)):
        state.text_key += 1  # redraw the script box with the idea
    yield


@me.page(
    path="/voice",
    title="Voice - GenMedia Creative Studio",
    on_load=on_voice_load,
    stylesheets=["/ui/audio-studio.css"],
)
def voice_page():
    """The Voice page."""
    with page_scaffold(page_name="voice"):  # pylint: disable=not-context-manager
        voice_content()


def voice_content():
    """Page body."""
    state = me.state(VoiceState)
    chirp = is_chirp(state.engine)
    dialogue = state.multi_speaker and engine_supports_dialogue(state.engine)

    with page_frame():  # pylint: disable=not-context-manager
        header(
            "Voice",
            "record_voice_over",
            show_info_button=True,
            on_info_click=open_info_dialog,
            description=PURPOSE,
            centered=True,
        )
        with me.box(classes="gm-studio gm-voice"):
            with composer(
                value=state.text,
                placeholder=(
                    "Write one line per speaker, like “Host: Hello there”…"
                    if dialogue
                    else "Type or paste the script to read aloud…"
                ),
                on_blur=on_blur_text,
                on_submit=on_text_enter,
                on_click_send=on_click_generate,
                busy=state.is_generating,
                send_label="Generate speech",
                textarea_key=f"voice_text_{state.text_key}",
                hint=(
                    f"Start each line with {state.speaker_a}: or {state.speaker_b}: · "
                    "Enter to generate"
                    if dialogue
                    else "Enter to generate · Shift+Enter for a new line"
                ),
                on_clear=on_click_clear,
                clear_label="Clear script and results",
            ):
                _voice_chips(state, chirp, dialogue)

            if dialogue:
                _dialogue_panel(state)
            if state.show_style_notes and not chirp:
                _direction_panel(state)
            if chirp and state.show_pronunciations:
                _pronunciation_panel(state)

            generation_progress(
                state=state,
                typical_seconds=6 if chirp else 10,
                work_stage=2,
                aspect="8:1",
                count=1,
                media_label="audio",
                on_retry=on_progress_retry,
                on_dismiss=on_progress_dismiss,
            )

            if state.history_urls:
                with result_grid(
                    title="Recent",
                    count=len(state.history_urls),
                    wide=True,
                ):
                    for i, url in enumerate(state.history_urls):
                        result_card(
                            key=f"voice_hist_{i}_{url[-24:]}",
                            src=url,
                            kind="audio",
                            prompt=state.history_texts[i]
                            if i < len(state.history_texts)
                            else "",
                            meta=state.history_meta[i]
                            if i < len(state.history_meta)
                            else "",
                            actions="download,reuse",
                            on_action=on_result_action,
                        )
            elif not state.is_generating and state.progress_status != "error":
                empty_results(
                    "graphic_eq",
                    "Your audio will show up here",
                    "Pick a voice and language, write a script, then press Enter.",
                )

    info = _ABOUT.get("chirp-3hd" if chirp else "gemini-tts")
    with dialog(is_open=state.info_dialog_open):  # pylint: disable=not-context-manager
        me.text(info["title"] if info else "Voice", type="headline-6")
        if info:
            me.markdown(info["description"])
        with dialog_actions():  # pylint: disable=not-context-manager
            me.button("Close", on_click=close_info_dialog, type="flat")


def _voice_chips(state: VoiceState, chirp: bool, dialogue: bool):
    """Setting chips in the composer row. Chirp-only chips appear for Chirp."""
    voice_options = chip_options(VOICES)
    chip_menu(
        key="voice_chip_engine",
        label="Model",
        icon="model",
        value=state.engine,
        options=chip_options(engine_options()),
        on_change=on_chip_engine,
    )
    if dialogue:
        chip_menu(
            key="voice_chip_voice_a",
            label=f"Voice for {state.speaker_a}",
            icon="voice",
            value=state.voice,
            options=chip_options((v, f"{state.speaker_a}: {v}") for v in VOICES),
            on_change=on_chip_voice,
        )
        chip_menu(
            key="voice_chip_voice_b",
            label=f"Voice for {state.speaker_b}",
            icon="voice",
            value=state.voice_b,
            options=chip_options((v, f"{state.speaker_b}: {v}") for v in VOICES),
            on_change=on_chip_voice_b,
        )
    else:
        chip_menu(
            key="voice_chip_voice",
            label="Voice",
            icon="voice",
            value=state.voice,
            options=voice_options,
            on_change=on_chip_voice,
        )
    languages = languages_for(state.engine)
    chip_menu(
        key=f"voice_chip_language_{'chirp' if chirp else 'gemini'}",
        label="Language",
        icon="language",
        value=state.language,
        options=chip_options(
            (code, label) for label, code in sorted(languages.items())
        ),
        on_change=on_chip_language,
    )
    if not chirp:
        chip_menu(
            key="voice_chip_style",
            label="Speaking style",
            icon="style",
            value=state.style,
            options=chip_options((v, lbl) for v, lbl, _ in STYLES),
            on_change=on_chip_style,
        )
    chip_menu(
        key="voice_chip_pace",
        label="Pace",
        icon="speed",
        value=state.pace,
        options=chip_options((v, lbl) for v, lbl, _, _ in PACES),
        on_change=on_chip_pace,
    )
    if engine_supports_dialogue(state.engine):
        chip_menu(
            key="voice_chip_dialogue",
            label="Dialogue: two speakers with their own voices",
            icon="people",
            kind="toggle",
            value="Dialogue",
            checked=state.multi_speaker,
            on_change=on_chip_dialogue,
        )
    if chirp:
        chip_menu(
            key="voice_chip_pron",
            label="Custom pronunciations for names and terms",
            icon="code",
            kind="toggle",
            value="Pronunciations"
            + (f" ({len(state.pronunciations)})" if state.pronunciations else ""),
            checked=state.show_pronunciations,
            on_change=on_chip_pronunciations,
        )
    else:
        chip_menu(
            key="voice_chip_direction",
            label="Direction: describe the delivery in your own words",
            icon="tune",
            kind="toggle",
            value="Direction",
            checked=state.show_style_notes,
            on_change=on_chip_direction,
        )


def _help(text: str):
    """A short help line under a panel."""
    with me.box(classes="gm-voice-help"):
        me.text(text)


def _panel_head(title: str, close_label: str, on_close):
    with me.box(classes="gm-advanced-head"):
        with me.box(classes="gm-title gm-title-section"):
            me.markdown("## " + title)
        with (
            me.content_button(type="icon", on_click=on_close),
            me.tooltip(message=close_label),
        ):
            me.icon("close")
            with me.box(classes="gm-sr-only"):
                me.text(close_label)


def _dialogue_panel(state: VoiceState):
    """Speaker names for a two-person dialogue."""
    with me.box(classes="gm-advanced gm-voice-panel"):
        _panel_head("Speakers", "Turn off dialogue", on_close_dialogue)
        with me.box(classes="gm-controls gm-voice-grid"):
            me.input(
                label="First speaker's name",
                value=state.speaker_a,
                on_blur=on_blur_speaker_a,
                appearance="outline",
                style=me.Style(width="100%"),
            )
            me.input(
                label="Second speaker's name",
                value=state.speaker_b,
                on_blur=on_blur_speaker_b,
                appearance="outline",
                style=me.Style(width="100%"),
            )
        _help(
            "Pick each speaker's voice with the chips above. Lines without a "
            "name continue the previous speaker.",
        )


def _direction_panel(state: VoiceState):
    """Free-text delivery notes, added after the style preset."""
    with me.box(classes="gm-advanced gm-voice-panel"):
        _panel_head("Direction", "Close direction", on_close_direction)
        me.textarea(
            label="How should it sound? e.g. “excited, like announcing a winner”",
            value=state.style_notes,
            on_blur=on_blur_style_notes,
            autosize=True,
            min_rows=2,
            max_rows=5,
            appearance="outline",
            style=me.Style(width="100%"),
        )
        _help("You can also put tags like [laughing] or [sigh] right in the script.")


def _pronunciation_panel(state: VoiceState):
    """Chirp 3 HD custom pronunciations."""
    with me.box(classes="gm-advanced gm-voice-panel"):
        _panel_head("Pronunciations", "Close pronunciations", on_close_pronunciations)
        with me.box(classes="gm-controls gm-voice-grid gm-voice-pron"):
            me.input(
                key=f"voice_phrase_{state.pron_key}",
                label="Word or phrase",
                value=state.phrase_input,
                on_blur=on_blur_phrase,
                appearance="outline",
                style=me.Style(width="100%"),
            )
            me.input(
                key=f"voice_pron_{state.pron_key}",
                label="Say it as",
                value=state.pronunciation_input,
                on_blur=on_blur_pronunciation,
                appearance="outline",
                style=me.Style(width="100%"),
            )
            me.select(
                label="Alphabet",
                appearance="outline",
                options=[
                    me.SelectOption(label=label, value=value)
                    for label, value in ENCODINGS.items()
                ],
                value=state.encoding,
                on_selection_change=on_select_encoding,
                style=me.Style(width="100%"),
            )
            me.button(
                "Add",
                on_click=on_add_pronunciation,
                type="flat",
            )
        if state.pronunciations:
            with me.box(classes="gm-voice-pron-list"):
                for i, p in enumerate(state.pronunciations):
                    with me.box(classes="gm-voice-pron-item"):
                        me.text(f"{p['phrase']} → {p['pronunciation']}")
                        with (
                            me.content_button(
                                type="icon",
                                key=str(i),
                                on_click=on_remove_pronunciation,
                            ),
                            me.tooltip(message=f"Remove {p['phrase']}"),
                        ):
                            me.icon("close")
                            with me.box(classes="gm-sr-only"):
                                me.text(f"Remove {p['phrase']}")
        else:
            _help(
                "Example: “Mesop” → “m e s O p” in X-SAMPA. Applies to this script only.",
            )


# --- engine and chips -------------------------------------------------------


def _set_engine(state: VoiceState, engine: str):
    """Switch engine and keep the language valid for it."""
    state.engine = engine
    if state.language not in languages_for(engine).values():
        state.language = DEFAULT_LANGUAGE
    if not engine_supports_dialogue(engine):
        state.multi_speaker = False
    if not is_chirp(engine):
        state.show_pronunciations = False


def on_chip_engine(e: me.WebEvent):
    """Model chip."""
    value = change_value(e)
    if is_known_engine(value):
        _set_engine(me.state(VoiceState), value)
    yield


def on_chip_voice(e: me.WebEvent):
    """Voice (or first speaker's voice) chip."""
    me.state(VoiceState).voice = change_value(e)
    yield


def on_chip_voice_b(e: me.WebEvent):
    """Second speaker's voice chip."""
    me.state(VoiceState).voice_b = change_value(e)
    yield


def on_chip_language(e: me.WebEvent):
    """Language chip."""
    me.state(VoiceState).language = change_value(e) or DEFAULT_LANGUAGE
    yield


def on_chip_style(e: me.WebEvent):
    """Speaking style chip."""
    me.state(VoiceState).style = change_value(e)
    yield


def on_chip_pace(e: me.WebEvent):
    """Pace chip."""
    me.state(VoiceState).pace = change_value(e)
    yield


def on_chip_dialogue(e: me.WebEvent):
    """Dialogue toggle. Swaps in a sample dialogue if the script is the default."""
    state = me.state(VoiceState)
    state.multi_speaker = change_value(e) == "true"
    if state.multi_speaker and state.text.strip() in ("", DEFAULT_SCRIPT):
        state.text = DEFAULT_DIALOGUE
        state.text_key += 1
    elif not state.multi_speaker and state.text.strip() == DEFAULT_DIALOGUE:
        state.text = DEFAULT_SCRIPT
        state.text_key += 1
    yield


def on_close_dialogue(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the speakers panel (turns dialogue off)."""
    me.state(VoiceState).multi_speaker = False
    yield


def on_chip_direction(e: me.WebEvent):
    """Show or hide the direction panel."""
    me.state(VoiceState).show_style_notes = change_value(e) == "true"
    yield


def on_close_direction(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the direction panel."""
    me.state(VoiceState).show_style_notes = False
    yield


def on_chip_pronunciations(e: me.WebEvent):
    """Show or hide the Chirp pronunciations panel."""
    me.state(VoiceState).show_pronunciations = change_value(e) == "true"
    yield


def on_close_pronunciations(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the pronunciations panel."""
    me.state(VoiceState).show_pronunciations = False
    yield


# --- inputs -----------------------------------------------------------------


def on_blur_text(e: me.InputBlurEvent):
    """Store the script."""
    me.state(VoiceState).text = e.value


def on_text_enter(e: me.TextareaShortcutEvent):
    """Enter in the script box: store it and generate."""
    state = me.state(VoiceState)
    state.text = e.value
    if state.is_generating:
        yield
        return
    yield from on_click_generate(e)


def on_blur_speaker_a(e: me.InputBlurEvent):
    """First speaker's name."""
    me.state(VoiceState).speaker_a = e.value.strip()[:40]


def on_blur_speaker_b(e: me.InputBlurEvent):
    """Second speaker's name."""
    me.state(VoiceState).speaker_b = e.value.strip()[:40]


def on_blur_style_notes(e: me.InputBlurEvent):
    """Free-text direction."""
    me.state(VoiceState).style_notes = e.value


def on_blur_phrase(e: me.InputBlurEvent):
    """Pronunciation: the phrase."""
    me.state(VoiceState).phrase_input = e.value


def on_blur_pronunciation(e: me.InputBlurEvent):
    """Pronunciation: how to say it."""
    me.state(VoiceState).pronunciation_input = e.value


def on_select_encoding(e: me.SelectSelectionChangeEvent):
    """Pronunciation alphabet."""
    me.state(VoiceState).encoding = e.value


def on_add_pronunciation(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Add the typed pronunciation to the list."""
    state = me.state(VoiceState)
    if state.phrase_input.strip() and state.pronunciation_input.strip():
        state.pronunciations.append(
            {
                "phrase": state.phrase_input.strip(),
                "pronunciation": state.pronunciation_input.strip(),
            },
        )
        state.phrase_input = ""
        state.pronunciation_input = ""
        state.pron_key += 1
    yield


def on_remove_pronunciation(e: me.ClickEvent):
    """Remove one pronunciation."""
    state = me.state(VoiceState)
    i = int(e.key)
    if 0 <= i < len(state.pronunciations):
        state.pronunciations.pop(i)
    yield


# --- generation -------------------------------------------------------------


def build_request(state: VoiceState) -> VoiceRequest:
    """The request for the current page settings."""
    dialogue = state.multi_speaker and engine_supports_dialogue(state.engine)
    return VoiceRequest(
        engine=state.engine,
        text=state.text,
        voice=state.voice,
        language_code=state.language,
        style=state.style,
        pace=state.pace,
        style_notes=state.style_notes,
        multi_speaker=dialogue,
        speakers=[(state.speaker_a, state.voice), (state.speaker_b, state.voice_b)]
        if dialogue
        else [],
        pronunciations=list(state.pronunciations) if is_chirp(state.engine) else [],
        phonetic_encoding=state.encoding,
    )


def _stages(engine: str) -> list[str]:
    return [
        "Preparing",
        f"Sending to {engine_label(engine)}",
        "Speaking",
        "Saving to library",
        "Done",
    ]


def on_click_generate(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Generate speech, reporting each stage to the progress card."""
    state = me.state(VoiceState)
    if state.is_generating:
        yield
        return
    request = build_request(state)
    progress_start(state, _stages(request.engine))
    problem = validate(request)
    if problem:
        progress_fail(state, problem)
        yield
        return

    state.is_generating = True
    yield
    try:
        progress_step(state, 1)
        yield
        if mock_enabled():
            time.sleep(0.6)
            progress_step(state, 2)
            yield
            fake_wait(1.4, request.text)
            progress_step(state, 3)
            yield
            time.sleep(0.4)
            url = sample_audio(len(state.history_urls))
        else:
            progress_step(state, 2)
            yield
            audio = synthesize_voice(request)
            progress_step(state, 3)
            yield
            gcs_uri = storage.store_to_gcs(
                folder="voice-audio",
                file_name=f"voice-{uuid.uuid4()}.wav",
                mime_type="audio/wav",
                contents=audio,
            )
            url = create_display_url(gcs_uri)
            _save_to_library(request, gcs_uri)
        state.history_urls.insert(0, url)
        state.history_texts.insert(0, request.text)
        state.history_meta.insert(0, describe(request))
        progress_done(state)
    except Exception as ex:  # pylint: disable=broad-except
        logger.error(f"Voice generation failed ({request.engine}): {ex}")
        progress_fail(state, friendly_error(ex))
    finally:
        state.is_generating = False
        yield


def _save_to_library(request: VoiceRequest, gcs_uri: str):
    """Record the clip in Firestore. A failure here doesn't lose the audio."""
    chirp = is_chirp(request.engine)
    try:
        add_media_item_to_firestore(
            MediaItem(
                user_email=me.state(AppState).user_email,
                timestamp=datetime.datetime.now(datetime.UTC),
                prompt=request.text,
                comment=describe(request),
                model="Chirp3 HD" if chirp else request.engine,
                mime_type="audio/wav",
                gcsuri=gcs_uri,
                voice=", ".join(v for _, v in request.speakers)
                if request.multi_speaker
                else request.voice,
                language_code=request.language_code,
                custom_pronunciations=list(request.pronunciations),
                style_prompt=None
                if chirp
                else (
                    " ".join(
                        x
                        for x in (request.style, request.pace, request.style_notes)
                        if x
                    )
                ),
            ),
        )
    except Exception as ex:  # pylint: disable=broad-except
        logger.error(f"Couldn't save voice clip to the library: {ex}")


def on_progress_retry(e: me.WebEvent):
    """'Try again' on the progress card."""
    yield from on_click_generate(e)


def on_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    """Hide the progress card after an error."""
    progress_clear(me.state(VoiceState))
    yield


def on_result_action(e: me.WebEvent):
    """Actions from an audio card."""
    state = me.state(VoiceState)
    action, src = card_action(e)
    if action == "reuse" and src in state.history_urls:
        i = state.history_urls.index(src)
        if i < len(state.history_texts):
            state.text = state.history_texts[i]
            state.text_key += 1
    yield


def on_click_clear(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Clear the script and this session's results (settings stay)."""
    state = me.state(VoiceState)
    state.text = ""
    state.text_key += 1
    state.history_urls = []
    state.history_texts = []
    state.history_meta = []
    progress_clear(state)
    yield


def open_info_dialog(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Open the about dialog."""
    me.state(VoiceState).info_dialog_open = True
    yield


def close_info_dialog(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Close the about dialog."""
    me.state(VoiceState).info_dialog_open = False
    yield


# --- old routes (/gemini-tts, /chirp-3hd) ------------------------------------


# A full page load of an old route gets an HTTP redirect to /voice?engine= from
# main.py. In-app (client-side) navigation to an old route can't be redirected
# from on_load in Mesop, so those routes render the Voice page themselves with
# their engine preselected.


def legacy_on_load(engine: str):
    """on_load for an old route: preselect its engine on the Voice page."""

    def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
        _set_engine(me.state(VoiceState), engine)
        yield

    return on_load
