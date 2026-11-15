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

import mesop as me
import mesop.labs as mel

from common.analytics import log_ui_click, track_click

from components.header import header
from components.library.events import LibrarySelectionChangeEvent
from components.library.library_chooser_button import library_chooser_button
from components.page_scaffold import page_frame, page_scaffold
from state.starter_pack_state import StarterPackState
from state.state import AppState
import common.storage as storage
import models.starter_pack as model
from common.metadata import add_media_item
from config.default import Default

cfg = Default()

from common.utils import create_display_url
from config.default import Default

from dataclasses import field  # noqa: E402

from common.mock_generation import (  # noqa: E402
    fake_wait,
    is_mock_uri,
    mock_enabled,
    mock_uri,
    placeholder_image,
    uploaded_image_url,
)
from components.demo_flow.demo_flow import (  # noqa: E402
    DEMO_STYLESHEETS,
    cicon,
    ctext,
    demo_alert,
    demo_segmented,
    demo_steps,
)
from components.edit_button.edit_button import edit_button  # noqa: E402
from components.generation_progress.generation_progress import (  # noqa: E402
    friendly_error,
    generation_progress,
    progress_clear,
    progress_done,
    progress_fail,
    progress_start,
    progress_step,
)
from components.veo_button.veo_button import veo_button  # noqa: E402

KIT_STEPS = ["Add a look photo", "Create the kit", "See the result"]
LOOK_STEPS = ["Add a brand kit", "Choose a model", "See the result"]


@me.stateclass
class BrandKitState:
    """Layout state for the Brand kit page; the flow keeps StarterPackState."""

    alert: str = ""
    progress_stages: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    progress_stage: int = 0
    progress_status: str = ""
    progress_run_id: str = ""
    progress_error: str = ""


@me.page(
    path="/starter-pack",
    title="Brand kit - GenMedia Studio",
    stylesheets=DEMO_STYLESHEETS,
)
def page():
    state = me.state(StarterPackState)
    with page_scaffold(page_name="starter-pack"):  # pylint: disable=E1129
        with page_frame():  # pylint: disable=E1129
            header(
                "Brand kit",
                "style",
                description=(
                    "Generate a set of on-brand images for a product or "
                    "campaign from one idea."
                ),
                centered=True,
            )
            with me.box(classes="gm-studio gm-demo"):
                demo_segmented(
                    value=str(state.selected_tab_index),
                    options=[
                        me.ButtonToggleButton(label="From a look", value="0"),
                        me.ButtonToggleButton(label="From a kit", value="1"),
                    ],
                    on_change=on_brand_mode_change,
                    key="brand_kit_mode",
                )
                if state.selected_tab_index == 1:
                    _look_from_kit_flow()
                else:
                    _kit_from_look_flow()


def _image_well(url: str, alt: str, empty_icon: str, empty_text: str, busy: bool = False):
    with me.box(classes="gm-demo-drop"):
        if busy:
            me.progress_spinner(diameter=36)
            ctext("Working on it…", "gm-demo-drop-text")
        elif url:
            with me.box(classes="gm-demo-img"):
                me.image(src=url, alt=alt)
        else:
            cicon(empty_icon, "gm-demo-drop-icon")
            ctext(empty_text, "gm-demo-drop-text")


@me.component
def _card_head(number: str, title: str, hint: str):
    with me.box(classes="gm-demo-card-head"):
        ctext(number, "gm-demo-card-num")
        with me.box(classes="gm-demo-card-titles"):
            ctext(title, "gm-demo-card-title")
            ctext(hint, "gm-demo-card-hint")


def _result_actions(uri: str):
    if uri and not is_mock_uri(uri):
        with me.box(classes="gm-demo-result-actions"):
            edit_button(gcs_uri=uri)
            veo_button(gcs_uri=uri)


def _kit_from_look_flow():
    bk = me.state(BrandKitState)
    state = me.state(StarterPackState)
    busy = bk.progress_status == "running"
    if state.generated_starter_pack_display_url:
        step = len(KIT_STEPS) + 1
    elif state.look_image_display_url:
        step = 2
    else:
        step = 1
    demo_steps(steps=KIT_STEPS, current=step)
    if bk.alert:
        demo_alert(message=bk.alert, on_dismiss=on_dismiss_brand_alert)

    with me.box(classes="gm-demo-pair"):
        with me.box(classes="gm-demo-card"):
            _card_head("1", "Look", "A photo of a product, outfit or campaign shot.")
            _image_well(state.look_image_display_url, "Chosen look", "add_photo_alternate", "No photo yet")
            with me.box(classes="gm-demo-actions"):
                me.uploader(
                    label="Upload photo",
                    on_upload=on_brand_upload_look,
                    accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                    type="stroked",
                    key="brand_look_uploader",
                    disabled=busy,
                )
                library_chooser_button(
                    key="library_look",
                    on_library_select=on_library_chooser,
                    button_label="From library",
                    disabled=busy,
                )
                if mock_enabled():
                    me.button("Use a sample", on_click=on_brand_mock_sample, key="look", type="stroked")
        with me.box(classes="gm-demo-card"):
            _card_head("2", "Brand kit", "A collage of matching pieces, colours and props.")
            _image_well(
                state.generated_starter_pack_display_url,
                "Generated brand kit",
                "auto_awesome_mosaic",
                "Your kit appears here",
                busy=state.is_generating_starter_pack,
            )
            _result_actions(state.generated_starter_pack_uri)

    with me.box(classes="gm-demo-bar"):
        with me.box(classes="gm-demo-bar-actions"):
            me.button("Start over", on_click=on_brand_start_over, type="stroked", disabled=busy)
            with me.box(classes="gm-demo-primary"):
                me.button(
                    "Create brand kit",
                    on_click=on_brand_generate_kit,
                    type="flat",
                    disabled=busy or not state.look_image_uri,
                )

    generation_progress(
        state=bk,
        typical_seconds=20,
        work_stage=1,
        aspect="1:1",
        count=1,
        media_label="brand kit",
        on_retry=on_brand_progress_retry,
        on_dismiss=on_brand_progress_dismiss,
    )


def _look_from_kit_flow():
    bk = me.state(BrandKitState)
    state = me.state(StarterPackState)
    busy = bk.progress_status == "running"
    if state.generated_look_display_url:
        step = len(LOOK_STEPS) + 1
    elif not state.starter_pack_image_display_url:
        step = 1
    elif not state.model_image_display_url:
        step = 2
    else:
        step = 3
    demo_steps(steps=LOOK_STEPS, current=step)
    if bk.alert:
        demo_alert(message=bk.alert, on_dismiss=on_dismiss_brand_alert)

    with me.box(classes="gm-demo-pair"):
        with me.box(classes="gm-demo-card"):
            _card_head("1", "Brand kit", "A mood board or kit collage.")
            _image_well(
                state.starter_pack_image_display_url, "Chosen brand kit", "auto_awesome_mosaic", "No kit yet"
            )
            with me.box(classes="gm-demo-actions"):
                me.uploader(
                    label="Upload kit",
                    on_upload=on_brand_upload_kit,
                    accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                    type="stroked",
                    key="brand_kit_uploader",
                    disabled=busy,
                )
                library_chooser_button(
                    key="library_starter_pack",
                    on_library_select=on_library_chooser,
                    button_label="From library",
                    disabled=busy,
                )
                if mock_enabled():
                    me.button("Use a sample", on_click=on_brand_mock_sample, key="kit", type="stroked")
        with me.box(classes="gm-demo-card"):
            _card_head("2", "Model", "Who should wear or hold the look.")
            _image_well(
                state.model_image_display_url,
                "Chosen model",
                "person_outline",
                "No model yet",
                busy=state.is_generating_virtual_model,
            )
            with me.box(classes="gm-demo-actions"):
                me.uploader(
                    label="Upload photo",
                    on_upload=on_brand_upload_model,
                    accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                    type="stroked",
                    key="brand_model_uploader",
                    disabled=busy,
                )
                library_chooser_button(
                    key="library_model",
                    on_library_select=on_library_chooser,
                    button_label="From library",
                    disabled=busy,
                )
                me.button(
                    "Create virtual model",
                    on_click=on_brand_create_model,
                    type="stroked",
                    disabled=busy or state.is_generating_virtual_model,
                )

    with me.box(classes="gm-demo-bar"):
        with me.box(classes="gm-demo-bar-actions"):
            me.button("Start over", on_click=on_brand_start_over, type="stroked", disabled=busy)
            with me.box(classes="gm-demo-primary"):
                me.button(
                    "Create the look",
                    on_click=on_brand_generate_look,
                    type="flat",
                    disabled=busy
                    or not (state.starter_pack_image_uri and state.model_image_uri),
                )

    generation_progress(
        state=bk,
        typical_seconds=20,
        work_stage=1,
        aspect="3:4",
        count=1,
        media_label="look",
        on_retry=on_brand_progress_retry,
        on_dismiss=on_brand_progress_dismiss,
    )

    if state.generated_look_display_url and not busy:
        with me.box(classes="gm-results"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## Result")
            with me.box(classes="gm-demo-media"):
                me.image(src=state.generated_look_display_url, alt="Generated look")
            _result_actions(state.generated_look_uri)


# ---- Brand kit handlers: wrap the upstream ones with progress, errors and mock mode.


def on_brand_mode_change(e: me.ButtonToggleChangeEvent):
    me.state(StarterPackState).selected_tab_index = int(e.value or 0)
    me.state(BrandKitState).alert = ""
    progress_clear(me.state(BrandKitState))
    yield


def on_dismiss_brand_alert(e: me.ClickEvent):  # pylint: disable=unused-argument
    me.state(BrandKitState).alert = ""
    yield


def _brand_upload(e: me.UploadEvent, uri_field: str, url_field: str, upstream):
    bk = me.state(BrandKitState)
    state = me.state(StarterPackState)
    bk.alert = ""
    if mock_enabled():
        setattr(state, uri_field, mock_uri(uri_field))
        setattr(state, url_field, uploaded_image_url(e.file))
        yield
        return
    try:
        yield from upstream(e)
    except Exception as ex:  # noqa: BLE001 - show any upload failure plainly
        print(f"Brand kit upload failed: {ex}")
        bk.alert = "Couldn't upload the photo. " + friendly_error(ex)
        yield


def on_brand_upload_look(e: me.UploadEvent):
    yield from _brand_upload(e, "look_image_uri", "look_image_display_url", on_upload_look_image)


def on_brand_upload_kit(e: me.UploadEvent):
    yield from _brand_upload(
        e, "starter_pack_image_uri", "starter_pack_image_display_url", on_upload_starter_pack_image
    )


def on_brand_upload_model(e: me.UploadEvent):
    yield from _brand_upload(e, "model_image_uri", "model_image_display_url", on_upload_model_image)


def on_brand_mock_sample(e: me.ClickEvent):
    """Mock mode only: a placeholder input, so the flow can be clicked through."""
    state = me.state(StarterPackState)
    if e.key == "kit":
        state.starter_pack_image_uri = mock_uri("sample-kit")
        state.starter_pack_image_display_url = placeholder_image("Sample kit", "1:1", 0)
    else:
        state.look_image_uri = mock_uri("sample-look")
        state.look_image_display_url = placeholder_image("Sample look", "4:3", 0)
    yield


def on_brand_create_model(e: me.ClickEvent):
    bk = me.state(BrandKitState)
    state = me.state(StarterPackState)
    bk.alert = ""
    try:
        if mock_enabled():
            state.is_generating_virtual_model = True
            yield
            fake_wait(1.5)
            state.model_image_uri = mock_uri("virtual-model")
            state.model_image_display_url = placeholder_image("Virtual model", "3:4", 1)
            state.is_generating_virtual_model = False
            yield
            return
        yield from on_click_generate_virtual_model(e)
    except Exception as ex:  # noqa: BLE001
        print(f"Brand kit virtual model failed: {ex}")
        state.is_generating_virtual_model = False
        bk.alert = "Couldn't create a virtual model. " + friendly_error(ex)
        yield


def _brand_run(stages: list[str], flag: str, upstream, e: me.ClickEvent, mock_result):
    """Run an upstream generate handler with stage-by-stage progress."""
    bk = me.state(BrandKitState)
    state = me.state(StarterPackState)
    bk.alert = ""
    progress_start(bk, stages)
    yield
    try:
        progress_step(bk, 1)
        yield
        if mock_enabled():
            setattr(state, flag, True)
            yield
            fake_wait(2.5)
            mock_result(state)
            setattr(state, flag, False)
        else:
            for _ in upstream(e):
                yield
        progress_done(bk)
        yield
    except Exception as ex:  # noqa: BLE001
        print(f"Brand kit generation failed: {ex}")
        setattr(state, flag, False)
        progress_fail(bk, friendly_error(ex))
        yield


def _mock_kit(state: StarterPackState):
    state.generated_starter_pack_uri = mock_uri("brand-kit")
    state.generated_starter_pack_display_url = placeholder_image("Brand kit", "1:1", 2)


def _mock_look(state: StarterPackState):
    state.generated_look_uri = mock_uri("brand-look")
    state.generated_look_display_url = placeholder_image("On-brand look", "3:4", 3)


def on_brand_generate_kit(e: me.ClickEvent):
    yield from _brand_run(
        ["Reading the look", "Designing the kit with Gemini", "Done"],
        "is_generating_starter_pack",
        on_click_generate_starter_pack,
        e,
        _mock_kit,
    )


def on_brand_generate_look(e: me.ClickEvent):
    yield from _brand_run(
        ["Reading the kit and model", "Styling the look with Gemini", "Done"],
        "is_generating_look",
        on_click_generate_look,
        e,
        _mock_look,
    )


def on_brand_progress_retry(e: me.WebEvent):  # pylint: disable=unused-argument
    click = me.ClickEvent(key="", is_target=False)
    if me.state(StarterPackState).selected_tab_index == 1:
        yield from on_brand_generate_look(click)
    else:
        yield from on_brand_generate_kit(click)


def on_brand_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    progress_clear(me.state(BrandKitState))
    yield


def on_brand_start_over(e: me.ClickEvent):
    progress_clear(me.state(BrandKitState))
    me.state(BrandKitState).alert = ""
    if me.state(StarterPackState).selected_tab_index == 1:
        yield from on_click_clear_look(e)
    else:
        yield from on_click_clear_starter_pack(e)


@me.component
def look_to_starter_pack_content():
    with me.box(style=me.Style(padding=me.Padding.all(16))):
        me.text(
            "Upload an image of a person wearing an outfit (a 'look') to generate a starter pack collage.",
            style=me.Style(margin=me.Margin(bottom=16)),
        )
        with me.box(style=me.Style(display="flex", align_items="center", justify_content="center", gap=8, margin=me.Margin(top=16))):
            me.uploader(
                label="Upload Look Image",
                on_upload=on_upload_look_image,
                style=me.Style(width="100%"),
                accepted_file_types=["image/jpeg", "image/png", "image/webp"],
            )
            library_chooser_button(
                key="library_look",
                on_library_select=on_library_chooser,
                button_type="icon",
            )
        if me.state(StarterPackState).look_image_display_url:
            me.image(
                src=me.state(StarterPackState).look_image_display_url,
                style=me.Style(
                    width="100%",
                    margin=me.Margin(top=16),
                    border_radius=8,
                ),
            )
        me.button(
            "Generate Starter Pack",
            on_click=on_click_generate_starter_pack,
            type="raised",
            style=me.Style(margin=me.Margin(top=16)),
        )

@me.component
def starter_pack_to_look_content():
    with me.box(style=me.Style(padding=me.Padding.all(16))):
        me.text(
            "Upload a starter pack/mood board and a model image to generate an image of the model wearing the outfit.",
            style=me.Style(margin=me.Margin(bottom=16)),
        )
        with me.box(style=me.Style(display="flex", align_items="center", justify_content="center", gap=8, margin=me.Margin(top=16))):
            me.uploader(
                label="Upload Starter Pack Image",
                on_upload=on_upload_starter_pack_image,
                style=me.Style(width="100%"),
                accepted_file_types=["image/jpeg", "image/png"],
            )
            library_chooser_button(
                key="library_starter_pack",
                on_library_select=on_library_chooser,
                button_type="icon",
            )
        if me.state(StarterPackState).starter_pack_image_display_url:
            me.image(
                src=me.state(StarterPackState).starter_pack_image_display_url,
                style=me.Style(
                    width="100%",
                    margin=me.Margin(top=16),
                    border_radius=8,
                ),
            )
        with me.box(style=me.Style(display="flex", align_items="center",justify_content="center", gap=8, margin=me.Margin(top=16))):
            me.uploader(
                label="Upload Model Image",
                on_upload=on_upload_model_image,
                style=me.Style(width="100%"),
                accepted_file_types=["image/jpeg", "image/png"],
            )
            library_chooser_button(
                key="library_model",
                on_library_select=on_library_chooser,
                button_type="icon",
            )
            me.button("Create Virtual Model", on_click=on_click_generate_virtual_model)

        if me.state(StarterPackState).is_generating_virtual_model:
            with me.box(style=me.Style(display="flex", justify_content="center", margin=me.Margin(top=16))):
                me.progress_spinner()
        elif me.state(StarterPackState).model_image_display_url:
            me.image(
                src=me.state(StarterPackState).model_image_display_url,
                style=me.Style(
                    width="100%",
                    margin=me.Margin(top=16),
                    border_radius=8,
                ),
            )

        me.button(
            "Generate Look",
            on_click=on_click_generate_look,
            type="raised",
            style=me.Style(margin=me.Margin(top=16)),
        )

def on_tab_click(e: me.ClickEvent):
    app_state = me.state(AppState)
    log_ui_click(
        element_id="starter_pack_tab",
        page_name=app_state.current_page,
        session_id=app_state.session_id,
        extras={"key": e.key},
    )
    state = me.state(StarterPackState)
    _, tab_index = e.key.split("-")
    state.selected_tab_index = int(tab_index)
    yield

def on_upload_look_image(e: me.UploadEvent):
    state = me.state(StarterPackState)
    uploaded_file = e.file
    gcs_uri = storage.store_to_gcs(
        folder="starter_pack_uploads",
        file_name=uploaded_file.name,
        mime_type=uploaded_file.mime_type,
        contents=uploaded_file.getvalue(),
    )
    state.look_image_uri = gcs_uri
    state.look_image_display_url = create_display_url(gcs_uri)
    print(f"Look image URI: {state.look_image_uri}")
    yield


def on_library_chooser(e: LibrarySelectionChangeEvent):
    state = me.state(StarterPackState)
    print(f"EVENT: {e}")

    if e.chooser_id == "library_look":
        state.look_image_uri = e.gcs_uri
        state.look_image_display_url = create_display_url(e.gcs_uri)
    elif e.chooser_id == "library_starter_pack":
        state.starter_pack_image_uri = e.gcs_uri
        state.starter_pack_image_display_url = create_display_url(e.gcs_uri)
    elif e.chooser_id == "library_model":
        state.model_image_uri = e.gcs_uri
        state.model_image_display_url = create_display_url(e.gcs_uri)
    yield


def on_upload_starter_pack_image(e: me.UploadEvent):

    state = me.state(StarterPackState)
    uploaded_file = e.file
    gcs_uri = storage.store_to_gcs(
        folder="starter_pack_uploads",
        file_name=uploaded_file.name,
        mime_type=uploaded_file.mime_type,
        contents=uploaded_file.getvalue(),
    )

    state.starter_pack_image_uri = gcs_uri
    state.starter_pack_image_display_url = create_display_url(gcs_uri)
    yield





def on_upload_model_image(e: me.UploadEvent):
    state = me.state(StarterPackState)
    uploaded_file = e.file
    gcs_uri = storage.store_to_gcs(
        folder="starter_pack_uploads",
        file_name=uploaded_file.name,
        mime_type=uploaded_file.mime_type,
        contents=uploaded_file.getvalue(),
    )

    state.model_image_uri = gcs_uri
    state.model_image_display_url = create_display_url(gcs_uri)

    yield





def on_click_generate_virtual_model(e: me.ClickEvent):
    state = me.state(StarterPackState)
    app_state = me.state(AppState)
    state.is_generating_virtual_model = True
    yield

    gcs_uri = model.generate_virtual_model()
    state.model_image_uri = gcs_uri
    state.model_image_display_url = create_display_url(gcs_uri)
    #add_media_item(
    #    user_email=app_state.user_email,
    #    model=cfg.MODEL_IMAGEN4_FAST,
    #    mime_type="image/png",
    #    gcs_uris=[gcs_uri],
    #    comment="virtual model",
    #    source_images_gcs=[]
    #)
    state.is_generating_virtual_model = False
    yield





@track_click(element_id="starter_pack_generate_starter_pack_button")
def on_click_generate_starter_pack(e: me.ClickEvent):
    state = me.state(StarterPackState)
    app_state = me.state(AppState)
    state.is_generating_starter_pack = True
    yield

    gcs_uri = model.generate_starter_pack_from_look(
        look_image_uri=state.look_image_uri
    )

    state.generated_starter_pack_uri = gcs_uri
    state.generated_starter_pack_display_url = create_display_url(gcs_uri)

    add_media_item(
        user_email=app_state.user_email,
        model=cfg.GEMINI_IMAGE_GEN_MODEL,
        mime_type="image/png",
        gcs_uris=[gcs_uri],
        comment="look to starter pack",
        source_images_gcs=[state.look_image_uri]
    )

    state.is_generating_starter_pack = False

    yield





@track_click(element_id="starter_pack_generate_look_button")

def on_click_generate_look(e: me.ClickEvent):

    state = me.state(StarterPackState)

    app_state = me.state(AppState)

    state.is_generating_look = True

    yield



    gcs_uri = model.generate_look_from_starter_pack(

        starter_pack_uri=state.starter_pack_image_uri,

        model_image_uri=state.model_image_uri,

    )

    state.generated_look_uri = gcs_uri

    state.generated_look_display_url = create_display_url(gcs_uri)
    add_media_item(
        user_email=app_state.user_email,
        model=cfg.GEMINI_IMAGE_GEN_MODEL,
        mime_type="image/png",
        gcs_uris=[gcs_uri],
        comment="starter pack to look",
        source_images_gcs=[state.starter_pack_image_uri, state.model_image_uri]
    )
    state.is_generating_look = False
    yield

@track_click(element_id="starter_pack_clear_starter_pack_button")
def on_click_clear_starter_pack(e: me.ClickEvent):
    state = me.state(StarterPackState)
    state.look_image_uri = ""
    state.look_image_display_url = ""
    state.generated_starter_pack_uri = ""
    state.generated_starter_pack_display_url = ""
    yield

@track_click(element_id="starter_pack_clear_look_button")
def on_click_clear_look(e: me.ClickEvent):
    state = me.state(StarterPackState)
    state.starter_pack_image_uri = ""
    state.starter_pack_image_display_url = ""
    state.model_image_uri = ""
    state.model_image_display_url = ""
    state.generated_look_uri = ""
    state.generated_look_display_url = ""
    yield
