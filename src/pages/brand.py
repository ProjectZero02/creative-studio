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
"""My brand page (/brand): name, colours, tone of voice and logo.

Saved with common/brand_kit.py. Story Studio ("Use my brand kit") and Image
Studio ("Apply brand") read it.
"""

from __future__ import annotations

import json
import logging
import uuid

import mesop as me

from common import brand_kit
from common.storage import store_to_gcs
from common.utils import create_display_url
from components.header import header
from components.page_scaffold import page_frame, page_scaffold
from state.state import AppState

logger = logging.getLogger(__name__)

LOGO_TYPES = ["image/png", "image/webp", "image/jpeg"]
CORNER_LABELS = {"br": "Bottom right", "bl": "Bottom left", "tr": "Top right", "tl": "Top left"}


def _label(text: str, cls: str) -> None:
    """Text with a CSS class (me.text itself takes no classes)."""
    with me.box(classes=cls):
        me.text(text)


@me.stateclass
class BrandState:
    kit_json: str = ""
    loaded: bool = False
    saved: bool = False
    error: str = ""
    form_key: int = 0  # re-mounts the inputs after a load


def _kit(s: BrandState) -> dict:
    return brand_kit.from_json(s.kit_json)


def _set(s: BrandState, kit: dict) -> None:
    s.kit_json = json.dumps(brand_kit.clean(kit))
    s.saved = False


def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    s.kit_json = json.dumps(brand_kit.load(me.state(AppState).user_email))
    s.loaded = True
    s.saved = False
    s.form_key += 1


def on_name(e: me.InputBlurEvent):
    s = me.state(BrandState)
    _set(s, {**_kit(s), "name": e.value})


def on_tone(e: me.InputBlurEvent):
    s = me.state(BrandState)
    _set(s, {**_kit(s), "tone": e.value})


def on_color(e: me.InputBlurEvent):
    s = me.state(BrandState)
    kit = _kit(s)
    index = int(e.key.rsplit("-", 1)[-1])
    colors = list(kit["colors"])
    value = brand_kit.clean_color(e.value)
    if value and index < len(colors):
        colors[index] = value
    _set(s, {**kit, "colors": colors})


def on_add_color(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    kit = _kit(s)
    if len(kit["colors"]) < brand_kit.MAX_COLORS:
        # A new swatch starts from a neutral grey that is not in the list yet.
        for c in ("#1a73e8", "#202124", "#fbbc04", "#34a853", "#ea4335", "#9aa0a6"):
            if c not in kit["colors"]:
                _set(s, {**kit, "colors": [*kit["colors"], c]})
                break
    s.form_key += 1


def on_remove_color(e: me.ClickEvent):
    s = me.state(BrandState)
    kit = _kit(s)
    index = int(e.key.rsplit("-", 1)[-1])
    colors = [c for i, c in enumerate(kit["colors"]) if i != index]
    _set(s, {**kit, "colors": colors})
    s.form_key += 1


def on_corner(e: me.SelectSelectionChangeEvent):
    s = me.state(BrandState)
    _set(s, {**_kit(s), "corner": e.value})


def on_logo(e: me.UploadEvent):
    s = me.state(BrandState)
    f = e.file
    if f.mime_type not in LOGO_TYPES:
        s.error = "Use a PNG, WebP or JPEG logo (PNG with a transparent background looks best)."
        return
    data = f.getvalue()
    if len(data) > 5 * 1024 * 1024:
        s.error = "The logo is over 5 MB. Use a smaller file."
        return
    ext = {"image/png": "png", "image/webp": "webp", "image/jpeg": "jpg"}[f.mime_type]
    try:
        uri = store_to_gcs("brand_kits", f"logo_{uuid.uuid4().hex[:12]}.{ext}", f.mime_type, data)
    except Exception as exc:
        logger.exception("Brand kit: logo upload failed")
        s.error = f"Could not upload the logo: {str(exc)[:160]}"
        return
    s.error = ""
    _set(s, {**_kit(s), "logo_uri": uri})


def on_remove_logo(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    _set(s, {**_kit(s), "logo_uri": ""})


def on_save(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    try:
        kit = brand_kit.save(me.state(AppState).user_email, _kit(s))
    except Exception as exc:
        logger.exception("Brand kit: save failed")
        s.error = f"Could not save: {str(exc)[:160]}"
        return
    s.kit_json = json.dumps(kit)
    s.error = ""
    s.saved = True


@me.page(path="/brand", title="My brand | GenMedia Studio", on_load=on_load)
def page():
    with page_scaffold(page_name="brand"):  # pylint: disable=not-context-manager
        brand_content()


def brand_content():
    s = me.state(BrandState)
    kit = _kit(s)
    with page_frame():  # pylint: disable=not-context-manager
        header(
            "My brand",
            "palette",
            description="Your logo, colours and tone, applied to films and images.",
        )
        if not s.loaded:
            me.progress_spinner()
            return
        with me.box(classes="gm-brand"):
            with me.box(classes="gm-usage-card"):
                _label("Name and tone", "gm-usage-title")
                me.input(
                    label="Brand name",
                    value=kit["name"],
                    on_blur=on_name,
                    appearance="outline",
                    key=f"brand-name-{s.form_key}",
                    style=me.Style(width="100%"),
                )
                me.textarea(
                    label="Tone of voice",
                    value=kit["tone"],
                    on_blur=on_tone,
                    appearance="outline",
                    rows=3,
                    placeholder="For example: warm, confident and plain-spoken; no slang.",
                    key=f"brand-tone-{s.form_key}",
                    style=me.Style(width="100%"),
                )
            with me.box(classes="gm-usage-card"):
                _label("Colours", "gm-usage-title")
                _label(f"Up to {brand_kit.MAX_COLORS}. They are added to scenario, frame and image prompts.", "gm-brand-hint")
                with me.box(classes="gm-brand-colors"):
                    for i, color in enumerate(kit["colors"]):
                        with me.box(classes="gm-brand-color"):
                            with me.box(classes="gm-brand-swatch"):
                                me.input(
                                    type="color",
                                    value=color,
                                    on_blur=on_color,
                                    appearance="outline",
                                    key=f"brand-color-{s.form_key}-{i}",
                                )
                            _label(color, "gm-brand-hex")
                            me.button(
                                "Remove",
                                on_click=on_remove_color,
                                key=f"brand-rm-{i}",
                            )
                    if len(kit["colors"]) < brand_kit.MAX_COLORS:
                        me.button("Add colour", type="stroked", on_click=on_add_color)
            with me.box(classes="gm-usage-card"):
                _label("Logo", "gm-usage-title")
                _label("Shown small in a corner of exported Story Studio films.", "gm-brand-hint")
                with me.box(classes="gm-brand-logo-row"):
                    if kit["logo_uri"]:
                        with me.box(classes="gm-brand-logo"):
                            me.image(src=create_display_url(kit["logo_uri"]), alt="Brand logo")
                        me.button("Remove logo", on_click=on_remove_logo)
                    me.uploader(
                        label="Upload logo" if not kit["logo_uri"] else "Replace logo",
                        accepted_file_types=LOGO_TYPES,
                        on_upload=on_logo,
                        type="stroked",
                        key="brand-logo-upload",
                    )
                    me.select(
                        label="Corner",
                        options=[me.SelectOption(label=v, value=k) for k, v in CORNER_LABELS.items()],
                        value=kit["corner"],
                        on_selection_change=on_corner,
                        appearance="outline",
                        key="brand-corner",
                    )
            if s.error:
                me.text(s.error, style=me.Style(color=me.theme_var("error")))
            with me.box(classes="gm-brand-actions"):
                me.button("Save brand kit", type="flat", on_click=on_save)
                if s.saved:
                    _label("Saved.", "gm-brand-hint")
            line = brand_kit.prompt_line(kit)
            if line:
                with me.box(classes="gm-usage-card"):
                    _label("Added to prompts", "gm-usage-title")
                    _label(line, "gm-brand-hint")
