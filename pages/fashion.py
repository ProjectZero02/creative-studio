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
"""Fashion (/fashion): Virtual Try-On and Shop the Look in one demo flow.

The page reuses the upstream handlers and state from pages/vto.py and the
Shop the Look components; it only owns the outer layout, the step indicator
and the progress card. /vto and /shop_the_look render this same page on the matching tab.
"""

import json
import time
from dataclasses import field

import mesop as me

import models.shop_the_look_workflow as shop_the_look_workflow
import pages.vto as vto
from common.mock_generation import (
    fake_wait,
    is_mock_uri,
    mock_enabled,
    mock_uri,
    placeholder_image,
    uploaded_image_url,
)
from components.demo_flow.demo_flow import (
    DEMO_STYLESHEETS,
    cicon,
    ctext,
    demo_alert,
    demo_segmented,
    demo_steps,
)
from components.edit_button.edit_button import edit_button
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
from components.library.library_chooser_button import library_chooser_button
from components.omni_button.omni_button import omni_button
from components.page_scaffold import page_frame, page_scaffold
from components.shop_the_look.config_panel import config_panel
from components.shop_the_look.look_selection import look_selection
from components.shop_the_look.model_selection import model_selection
from components.shop_the_look.results_display import results_display
from components.snackbar import snackbar
from components.veo_button.veo_button import veo_button
from state.shop_the_look_state import PageState as LookState

TAB_TRY_ON = "tryon"
TAB_LOOK = "look"
_TAB_ALIASES = {
    "tryon": TAB_TRY_ON,
    "vto": TAB_TRY_ON,
    "look": TAB_LOOK,
    "shop": TAB_LOOK,
}

STEPS = ["Choose a model", "Choose clothing", "See the result"]
TRY_ON_STAGES = [
    "Preparing the photos",
    "Dressing the model with Virtual Try-On",
    "Checking the fit with Gemini",
    "Done",
]


@me.stateclass
class FashionState:
    """Layout state for /fashion. The flows keep their own upstream state."""

    mode: str = TAB_TRY_ON
    alert: str = ""
    show_settings: bool = False
    # Shared progress card fields (components/generation_progress).
    progress_stages: list[str] = field(default_factory=list)  # pylint: disable=invalid-field-call
    progress_stage: int = 0
    progress_status: str = ""
    progress_run_id: str = ""
    progress_error: str = ""
    # Shop the look: data loaded from Firestore once per session.
    look_loaded: bool = False
    look_error: str = ""
    show_look_config: bool = False


def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    """Open the tab named in ?tab= (tryon or look)."""
    state = me.state(FashionState)
    tab = _TAB_ALIASES.get((me.query_params.get("tab") or "").lower())
    if tab:
        state.mode = tab
    yield


def on_load_try_on(e: me.LoadEvent):  # pylint: disable=unused-argument
    """Old /vto links open Fashion on the Try on tab."""
    me.state(FashionState).mode = TAB_TRY_ON
    yield


def on_load_shop_the_look(e: me.LoadEvent):  # pylint: disable=unused-argument
    """Old /shop_the_look links open Fashion on the Shop the look tab."""
    me.state(FashionState).mode = TAB_LOOK
    yield


@me.page(
    path="/fashion",
    title="Fashion - GenMedia Studio",
    on_load=on_load,
    stylesheets=DEMO_STYLESHEETS,
)
def page():
    """Fashion demo."""
    fashion_content()


@me.page(
    path="/vto",
    title="Fashion - GenMedia Studio",
    on_load=on_load_try_on,
    stylesheets=DEMO_STYLESHEETS,
)
def vto_page():
    """Old Virtual Try-On route: same page, Try on tab."""
    fashion_content()


@me.page(
    path="/shop_the_look",
    title="Fashion - GenMedia Studio",
    on_load=on_load_shop_the_look,
    stylesheets=DEMO_STYLESHEETS,
)
def shop_the_look_page():
    """Old Shop the Look route: same page, Shop the look tab."""
    fashion_content()


def fashion_content():
    state = me.state(FashionState)
    with page_scaffold(page_name="fashion"):  # pylint: disable=E1129
        with page_frame():  # pylint: disable=E1129
            header(
                "Fashion",
                "checkroom",
                description=(
                    "Dress a model in any piece of clothing, or style a whole "
                    "look from a catalog."
                ),
                centered=True,
            )
            with me.box(classes="gm-studio gm-demo"):
                demo_segmented(
                    value=state.mode,
                    options=[
                        me.ButtonToggleButton(label="Try on", value=TAB_TRY_ON),
                        me.ButtonToggleButton(label="Shop the look", value=TAB_LOOK),
                    ],
                    on_change=on_mode_change,
                    key="fashion_mode",
                )
                if state.mode == TAB_LOOK:
                    _shop_the_look_flow()
                else:
                    _try_on_flow()
        vto_state = me.state(vto.PageState)
        snackbar(is_visible=vto_state.show_snackbar, label=vto_state.snackbar_message)


def on_mode_change(e: me.ButtonToggleChangeEvent):
    state = me.state(FashionState)
    state.mode = e.value or TAB_TRY_ON
    state.alert = ""
    yield


# ---------------------------------------------------------------- Try on


def _try_on_step(vs: vto.PageState) -> int:
    if vs.result_display_urls:
        return len(STEPS) + 1
    if not vs.person_image_display_url:
        return 1
    if not vs.product_image_display_url:
        return 2
    return 3


def _try_on_flow():
    state = me.state(FashionState)
    vs = me.state(vto.PageState)
    busy = state.progress_status == "running"

    demo_steps(steps=STEPS, current=_try_on_step(vs))
    if state.alert:
        demo_alert(message=state.alert, on_dismiss=on_dismiss_alert)

    with me.box(classes="gm-demo-pair"):
        with me.box(classes="gm-demo-card"):
            _card_head("1", "Model", "A full-body photo works best.")
            with me.box(classes="gm-demo-drop gm-demo-drop-tall"):
                if vs.is_generating_person_image:
                    me.progress_spinner(diameter=36)
                    ctext("Creating a virtual model…", "gm-demo-drop-text")
                elif vs.person_image_display_url:
                    with me.box(classes="gm-demo-img"):
                        me.image(src=vs.person_image_display_url, alt="Chosen model")
                else:
                    cicon("person_outline", "gm-demo-drop-icon")
                    ctext("No model yet", "gm-demo-drop-text")
            with me.box(classes="gm-demo-actions"):
                me.uploader(
                    label="Upload photo",
                    on_upload=on_upload_person,
                    accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                    type="stroked",
                    key="fashion_person_uploader",
                    disabled=busy,
                )
                library_chooser_button(
                    key="person_library_chooser",
                    on_library_select=vto.on_library_chooser,
                    button_label="From library",
                    disabled=busy,
                )
                me.button(
                    "Create virtual model",
                    on_click=on_create_virtual_model,
                    type="stroked",
                    disabled=busy or vs.is_generating_person_image,
                )

        with me.box(classes="gm-demo-card"):
            _card_head("2", "Clothing", "One garment on a plain background.")
            with me.box(classes="gm-demo-drop gm-demo-drop-tall"):
                if vs.product_image_display_url:
                    with me.box(classes="gm-demo-img"):
                        me.image(
                            src=vs.product_image_display_url, alt="Chosen clothing"
                        )
                else:
                    cicon("checkroom", "gm-demo-drop-icon")
                    ctext("No clothing yet", "gm-demo-drop-text")
            with me.box(classes="gm-demo-actions"):
                me.uploader(
                    label="Upload photo",
                    on_upload=on_upload_product,
                    accepted_file_types=["image/jpeg", "image/png", "image/webp"],
                    type="stroked",
                    key="fashion_product_uploader",
                    disabled=busy,
                )
                library_chooser_button(
                    key="product_library_chooser",
                    on_library_select=vto.on_library_chooser,
                    button_label="From library",
                    disabled=busy,
                )
                if mock_enabled():
                    me.button(
                        "Use a sample", on_click=on_mock_sample_product, type="stroked"
                    )

    with me.box(classes="gm-demo-bar"):
        with me.box(classes="gm-demo-bar-settings"):
            with me.box(classes="gm-demo-select-sm"):
                me.select(
                    label="Images",
                    options=[
                        me.SelectOption(label=str(n), value=str(n)) for n in range(1, 5)
                    ],
                    value=str(vs.vto_sample_count),
                    on_selection_change=on_count_change,
                    appearance="outline",
                )
            me.button(
                "Hide settings" if state.show_settings else "More settings",
                on_click=on_toggle_settings,
            )
        with me.box(classes="gm-demo-bar-actions"):
            me.button(
                "Start over", on_click=on_start_over, type="stroked", disabled=busy
            )
            with me.box(classes="gm-demo-primary"):
                me.button(
                    "Try it on",
                    on_click=on_try_on,
                    type="flat",
                    disabled=busy
                    or not (
                        vs.person_image_display_url and vs.product_image_display_url
                    ),
                )

    if state.show_settings:
        with me.box(classes="gm-demo-settings"):
            me.select(
                label="People in results",
                options=[
                    me.SelectOption(label="Allow all ages", value="allow_all"),
                    me.SelectOption(label="Adults only", value="allow_adult"),
                ],
                appearance="outline",
                value=vs.person_generation,
                on_selection_change=vto.on_person_generation_change,
            )
            me.select(
                label="Safety filter",
                options=[
                    me.SelectOption(label="Block most", value="block_low_and_above"),
                    me.SelectOption(label="Block some", value="block_medium_and_above"),
                    me.SelectOption(label="Block few", value="block_only_high"),
                ],
                appearance="outline",
                value=vs.safety_filter_level,
                on_selection_change=vto.on_safety_filter_change,
            )

    generation_progress(
        state=state,
        typical_seconds=25,
        work_stage=1,
        aspect="3:4",
        count=vs.vto_sample_count,
        media_label="try-on",
        on_retry=on_progress_retry,
        on_dismiss=on_progress_dismiss,
    )

    if vs.result_display_urls and not busy:
        _try_on_results(vs)


@me.component
def _card_head(number: str, title: str, hint: str):
    with me.box(classes="gm-demo-card-head"):
        ctext(number, "gm-demo-card-num")
        with me.box(classes="gm-demo-card-titles"):
            ctext(title, "gm-demo-card-title")
            ctext(hint, "gm-demo-card-hint")


def _try_on_results(vs: vto.PageState):
    try:
        critiques = json.loads(vs.critique_results_json or "{}")
    except json.JSONDecodeError:
        critiques = {}
    with me.box(classes="gm-results"):
        with me.box(classes="gm-results-head"):
            with me.box(classes="gm-title gm-title-section"):
                me.markdown("## Result")
            if vs.is_analyzing:
                ctext("Checking the fit…", "gm-demo-muted")
        with me.box(classes="gm-demo-results"):
            for i, url in enumerate(vs.result_display_urls):
                uri = vs.result_gcs_uris[i] if i < len(vs.result_gcs_uris) else ""
                critique = critiques.get(uri)
                with me.box(classes="gm-demo-result"):
                    with me.box(classes="gm-demo-result-img"):
                        me.image(src=url, alt=f"Try-on result {i + 1}")
                    if uri and not is_mock_uri(uri):
                        with me.box(classes="gm-demo-result-actions"):
                            edit_button(gcs_uri=uri)
                            omni_button(gcs_uri=uri)
                            veo_button(gcs_uri=uri)
                    if critique:
                        accurate = bool(critique.get("accurate", True))
                        with me.box(classes="gm-demo-critique"):
                            with me.box(classes="gm-demo-critique-head"):
                                me.icon("verified" if accurate else "info")
                                me.text("Good fit" if accurate else "Check the fit")
                            me.markdown(
                                str(critique.get("placement_analysis", "No notes."))
                            )


def on_dismiss_alert(e: me.ClickEvent):  # pylint: disable=unused-argument
    me.state(FashionState).alert = ""
    yield


def on_toggle_settings(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(FashionState)
    state.show_settings = not state.show_settings
    yield


def on_count_change(e: me.SelectSelectionChangeEvent):
    me.state(vto.PageState).vto_sample_count = int(e.value)
    yield


def _upload(e: me.UploadEvent, kind: str, upstream):
    state = me.state(FashionState)
    vs = me.state(vto.PageState)
    state.alert = ""
    if mock_enabled():
        url = uploaded_image_url(e.file)
        if kind == "person":
            vs.person_image_gcs, vs.person_image_display_url = mock_uri("person"), url
        else:
            vs.product_image_gcs, vs.product_image_display_url = (
                mock_uri("product"),
                url,
            )
        yield
        return
    try:
        yield from upstream(e)
    except Exception as ex:  # noqa: BLE001 - show any upload failure plainly
        print(f"Fashion upload failed: {ex}")
        state.alert = "Couldn't upload the photo. " + friendly_error(ex)
        yield


def on_upload_person(e: me.UploadEvent):
    yield from _upload(e, "person", vto.on_upload_person)


def on_upload_product(e: me.UploadEvent):
    yield from _upload(e, "product", vto.on_upload_product)


def on_create_virtual_model(e: me.ClickEvent):
    state = me.state(FashionState)
    vs = me.state(vto.PageState)
    state.alert = ""
    if mock_enabled():
        vs.is_generating_person_image = True
        yield
        fake_wait(1.5)
        vs.person_image_gcs = mock_uri("virtual-model")
        vs.person_image_display_url = placeholder_image("Virtual model", "3:4", 1)
        vs.is_generating_person_image = False
        yield
        return
    vs.error_message = ""
    try:
        yield from vto.on_click_generate_person(e)
    except Exception as ex:  # noqa: BLE001
        vs.error_message = str(ex)
        vs.is_generating_person_image = False
    if vs.error_message:
        state.alert = "Couldn't create a virtual model. " + friendly_error(
            vs.error_message
        )
        vs.error_message = ""
    yield


def on_mock_sample_product(e: me.ClickEvent):  # pylint: disable=unused-argument
    """Mock mode only: a placeholder garment, so the flow can be clicked through."""
    vs = me.state(vto.PageState)
    vs.product_image_gcs = mock_uri("product")
    vs.product_image_display_url = placeholder_image("Sample garment", "4:5", 2)
    yield


def on_start_over(e: me.ClickEvent):
    progress_clear(me.state(FashionState))
    me.state(FashionState).alert = ""
    yield from vto.on_clear(e)


def on_try_on(e: me.ClickEvent):
    state = me.state(FashionState)
    vs = me.state(vto.PageState)
    state.alert = ""
    if not (vs.person_image_gcs and vs.product_image_gcs):
        state.alert = "Choose a model and a piece of clothing first."
        yield
        return
    progress_start(state, TRY_ON_STAGES)
    vs.result_gcs_uris, vs.result_display_urls = [], []
    yield
    if mock_enabled():
        yield from _mock_try_on(state, vs)
        return
    progress_step(state, 1)
    vs.error_dialog_open = False
    yield
    try:
        for _ in vto.on_generate(e):
            if vs.error_dialog_open:
                progress_fail(state, friendly_error(vs.error_message))
                vs.error_dialog_open = False
            elif vs.is_analyzing:
                progress_step(state, 2)
            yield
    except Exception as ex:  # noqa: BLE001
        print(f"Fashion try-on failed: {ex}")
        progress_fail(state, friendly_error(ex))
        yield
        return
    if state.progress_status == "running":
        if vs.result_display_urls:
            progress_done(state)
        else:
            progress_fail(state, "The model returned no pictures. Try another photo.")
    yield


def _mock_try_on(state: FashionState, vs: vto.PageState):
    """Dev-only walk through the stages with placeholder results."""
    try:
        time.sleep(0.5)
        progress_step(state, 1)
        yield
        fake_wait(2.0)
        count = max(1, vs.vto_sample_count)
        vs.result_gcs_uris = [mock_uri("vto", i) for i in range(count)]
        vs.result_display_urls = [
            placeholder_image("Try-on result", "3:4", i) for i in range(count)
        ]
        progress_step(state, 2)
        yield
        time.sleep(1.0)
        vs.critique_results_json = json.dumps(
            {
                uri: {
                    "accurate": True,
                    "placement_analysis": "Mock check: the garment sits naturally "
                    "on the shoulders and the colour matches the product photo.",
                }
                for uri in vs.result_gcs_uris
            }
        )
        progress_done(state)
        yield
    except Exception as ex:  # noqa: BLE001
        progress_fail(state, friendly_error(ex))
        yield


def on_progress_retry(e: me.WebEvent):  # pylint: disable=unused-argument
    yield from on_try_on(me.ClickEvent(key="", is_target=False))


def on_progress_dismiss(e: me.WebEvent):  # pylint: disable=unused-argument
    progress_clear(me.state(FashionState))
    yield


# ---------------------------------------------------------- Shop the look


def _look_step(ls: LookState) -> int:
    if not ls.reference_image_gcs_model:
        return 1
    if not ls.look:
        return 2
    return 3 if not ls.result_display_urls else len(STEPS) + 1


def _load_look_data(state: FashionState, ls: LookState) -> None:
    """Load models and the catalog once, like the upstream tab, but safely."""
    if state.look_loaded or state.look_error:
        return
    try:
        if not ls.catalog:
            ls.catalog = shop_the_look_workflow.load_look_data()
        if not ls.models:
            models = shop_the_look_workflow.load_model_data()
            if models is None:
                raise RuntimeError("Could not read the model list from Firestore.")
            ls.models = models
            shop_the_look_workflow.load_article_data()
        state.look_loaded = True
    except Exception as ex:  # noqa: BLE001
        print(f"Shop the look data load failed: {ex}")
        if shop_the_look_workflow.db is None:
            state.look_error = (
                "The studio couldn't connect to Firestore. "
                "Check the Google Cloud sign-in."
            )
        else:
            state.look_error = friendly_error(ex)


def _shop_the_look_flow():
    state = me.state(FashionState)
    ls = me.state(LookState)
    _load_look_data(state, ls)

    demo_steps(steps=STEPS, current=_look_step(ls))

    if state.look_error:
        with me.box(classes="gm-empty"):
            with me.box(classes="gm-empty-icon"):
                me.icon("cloud_off")
            ctext("The catalog isn't available", "gm-demo-card-title")
            ctext(
                "Shop the look reads its models and clothing from Firestore. "
                + state.look_error,
                "gm-demo-muted",
            )
            me.button("Try again", on_click=on_retry_look_load, type="stroked")
        return

    if ls.is_loading and ls.current_status:
        with me.box(classes="gm-demo-status", key="look_status"):
            me.progress_spinner(diameter=20)
            me.text(ls.current_status)

    with me.box(classes="gm-demo-look"):
        if not ls.reference_image_gcs_model:
            model_selection()
        elif not ls.look:
            look_selection()
        else:
            results_display()

    with me.box(classes="gm-demo-manage"):
        me.button(
            "Hide catalog settings"
            if state.show_look_config
            else "Manage models and catalog",
            on_click=on_toggle_look_config,
        )
    if state.show_look_config:
        with me.box(classes="gm-demo-card"):
            config_panel()


def on_retry_look_load(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(FashionState)
    state.look_error = ""
    state.look_loaded = False
    yield


def on_toggle_look_config(e: me.ClickEvent):  # pylint: disable=unused-argument
    state = me.state(FashionState)
    state.show_look_config = not state.show_look_config
    if state.show_look_config:
        ls = me.state(LookState)
        try:
            ls.models = shop_the_look_workflow.load_model_data() or []
        except Exception as ex:  # noqa: BLE001
            print(f"Shop the look model load failed: {ex}")
    yield
