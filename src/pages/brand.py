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
"""Brands page (/brand): a list of the person's brands and an editor.

Each brand has a name, colours, tone of voice and a logo. One is the
default. Saved with common/brand_kit.py. Story Studio picks a brand in
Setup; Image Studio and Home chat use the default brand.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import nullcontext

import mesop as me

from common import brand_kit
from common.storage import store_to_gcs
from common.utils import create_display_url
from components.header import header
from components.page_scaffold import page_frame, page_scaffold
from state.state import AppState

logger = logging.getLogger(__name__)

LOGO_TYPES = ["image/png", "image/webp", "image/jpeg"]
CORNER_LABELS = {
    "br": "Bottom right",
    "bl": "Bottom left",
    "tr": "Top right",
    "tl": "Top left",
}
NEW = "new"


def _label(text: str, cls: str) -> None:
    """Text with a CSS class (me.text itself takes no classes)."""
    with me.box(classes=cls):
        me.text(text)


@me.stateclass
class BrandState:
    brands_json: str = "[]"
    editing: str = ""  # brand id being edited, NEW, or "" (list only)
    kit_json: str = ""  # the editor's draft
    loaded: bool = False
    saved: bool = False
    error: str = ""
    confirm_delete: str = ""
    form_key: int = 0  # re-mounts the inputs after a load


def _owner() -> str:
    return me.state(AppState).user_email


def _brands(s: BrandState) -> list[dict]:
    try:
        rows = json.loads(s.brands_json or "[]")
    except ValueError:
        return []
    return [brand_kit.clean_brand(r) for r in rows if isinstance(r, dict)]


def _kit(s: BrandState) -> dict:
    return brand_kit.from_json(s.kit_json)


def _set(s: BrandState, kit: dict) -> None:
    s.kit_json = json.dumps(brand_kit.clean(kit))
    s.saved = False


def _refresh(s: BrandState) -> None:
    s.brands_json = json.dumps(brand_kit.list_brands(_owner()))


def _open(s: BrandState, brand_id: str) -> None:
    brand = next((b for b in _brands(s) if b["id"] == brand_id), None)
    s.editing = brand["id"] if brand else NEW
    s.kit_json = json.dumps(brand_kit.clean(brand))
    s.saved = False
    s.error = ""
    s.confirm_delete = ""
    s.form_key += 1


def on_load(e: me.LoadEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    _refresh(s)
    rows = _brands(s)
    wanted = me.query_params.get("id", "") if hasattr(me, "query_params") else ""
    if wanted == NEW:
        _open(s, "")
    elif wanted and any(b["id"] == wanted for b in rows):
        _open(s, wanted)
    elif rows and not s.editing:
        _open(s, rows[0]["id"])
    elif not rows:
        _open(s, "")
    s.loaded = True


def on_pick(e: me.ClickEvent):
    _open(me.state(BrandState), e.key.split("-", 1)[1])


def on_new(e: me.ClickEvent):  # pylint: disable=unused-argument
    _open(me.state(BrandState), "")


def on_make_default(e: me.ClickEvent):
    s = me.state(BrandState)
    brand_kit.set_default(_owner(), s.editing)
    _refresh(s)


def on_ask_delete(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    s.confirm_delete = s.editing


def on_cancel_delete(e: me.ClickEvent):  # pylint: disable=unused-argument
    me.state(BrandState).confirm_delete = ""


def on_delete(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    brand_kit.delete_brand(_owner(), s.confirm_delete)
    s.confirm_delete = ""
    _refresh(s)
    rows = _brands(s)
    _open(s, rows[0]["id"] if rows else "")


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
        s.error = "Use a PNG, WebP or JPEG logo."
        return
    data = f.getvalue()
    if len(data) > 5 * 1024 * 1024:
        s.error = "The logo is over 5 MB. Use a smaller file."
        return
    ext = {"image/png": "png", "image/webp": "webp", "image/jpeg": "jpg"}[f.mime_type]
    try:
        from services.story_service import get_backend, is_mock_mode

        if is_mock_mode():
            uri = get_backend().save_upload(data, f.mime_type)
        else:
            uri = store_to_gcs(
                "brand_kits", f"logo_{uuid.uuid4().hex[:12]}.{ext}", f.mime_type, data
            )
    except Exception as exc:
        logger.exception("Brands: logo upload failed")
        s.error = f"Could not upload the logo: {str(exc)[:160]}"
        return
    s.error = ""
    _set(s, {**_kit(s), "logo_uri": uri})


def on_remove_logo(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    _set(s, {**_kit(s), "logo_uri": ""})


def on_save(e: me.ClickEvent):  # pylint: disable=unused-argument
    s = me.state(BrandState)
    kit = _kit(s)
    if brand_kit.is_empty(kit):
        s.error = "Add a name, a colour, a tone or a logo first."
        return
    try:
        brand = brand_kit.save_brand(
            _owner(), {**kit, "id": "" if s.editing == NEW else s.editing}
        )
    except Exception as exc:
        logger.exception("Brands: save failed")
        s.error = f"Could not save: {str(exc)[:160]}"
        return
    _refresh(s)
    s.editing = brand["id"]
    s.kit_json = json.dumps(brand_kit.clean(brand))
    s.error = ""
    s.saved = True


def _media_url(uri: str) -> str:
    if uri.startswith("local://"):
        from services.story_service import display_url

        return display_url(uri)
    return create_display_url(uri)


@me.page(path="/brand", title="Brands | GenMedia Studio", on_load=on_load)
def page():
    with page_scaffold(page_name="brand"):  # pylint: disable=not-context-manager
        brand_content()


def _brand_card(brand: dict, on: bool) -> None:
    with me.box(
        classes="gm-brand-card" + (" is-on" if on else ""),
        on_click=on_pick,
        key=f"brandpick-{brand['id']}",
    ):
        with me.box(classes="gm-brand-card-logo"):
            if brand["logo_uri"]:
                me.image(src=_media_url(brand["logo_uri"]), alt="")
            else:
                me.icon("palette")
        with me.box(classes="gm-brand-card-text"):
            _label(brand_kit.label(brand), "gm-brand-card-name")
            with me.box(classes="gm-brand-dots"):
                for c in brand["colors"]:
                    me.box(classes="gm-brand-dot", style=me.Style(background=c))
                if brand["is_default"]:
                    _label("Default", "gm-brand-default")


def brand_content(embedded: bool = False):
    """The Brands body; `embedded` drops the frame and title (Settings)."""
    s = me.state(BrandState)
    kit = _kit(s)
    rows = _brands(s)
    frame = nullcontext() if embedded else page_frame()
    with frame:  # pylint: disable=not-context-manager
        if not embedded:
            header(
                "Brands",
                "palette",
                description="Logos, colours and tone, applied to films and images.",
            )
        if not s.loaded:
            me.progress_spinner()
            return
        with me.box(classes="gm-brand-page"):
            with me.box(classes="gm-brand-list"):
                for b in rows:
                    _brand_card(b, b["id"] == s.editing)
                with me.box(
                    classes="gm-brand-card gm-brand-new"
                    + (" is-on" if s.editing == NEW else ""),
                    on_click=on_new,
                    key="brand-new",
                ):
                    with me.box(classes="gm-brand-card-logo"):
                        me.icon("add")
                    _label("New brand", "gm-brand-card-name")
            _editor(s, kit, rows)


def _editor(s: BrandState, kit: dict, rows: list[dict]) -> None:
    current = next((b for b in rows if b["id"] == s.editing), None)
    with me.box(classes="gm-brand"):
        with me.box(classes="gm-usage-card"):
            with me.box(classes="gm-brand-head"):
                _label(
                    "New brand" if current is None else brand_kit.label(current),
                    "gm-usage-title",
                )
                if current is not None:
                    with me.box(classes="gm-brand-head-actions"):
                        if not current["is_default"]:
                            me.button(
                                "Make default",
                                on_click=on_make_default,
                                key="brand-default",
                            )
                        me.button("Delete", on_click=on_ask_delete, key="brand-delete")
            if s.confirm_delete and current is not None:
                with me.box(classes="gm-brand-confirm"):
                    _label(
                        f"Delete {brand_kit.label(current)}? Films keep their copy.",
                        "gm-brand-hint",
                    )
                    me.button(
                        "Delete",
                        type="flat",
                        color="warn",
                        on_click=on_delete,
                        key="brand-delete-yes",
                    )
                    me.button(
                        "Cancel", on_click=on_cancel_delete, key="brand-delete-no"
                    )
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
                placeholder="Warm, confident and plain-spoken; no slang.",
                key=f"brand-tone-{s.form_key}",
                style=me.Style(width="100%"),
            )
        with me.box(classes="gm-usage-card"):
            _label("Colours", "gm-usage-title")
            _label(f"Up to {brand_kit.MAX_COLORS}.", "gm-brand-hint")
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
                            "Remove", on_click=on_remove_color, key=f"brand-rm-{i}"
                        )
                if len(kit["colors"]) < brand_kit.MAX_COLORS:
                    me.button(
                        "Add colour", on_click=on_add_color, key="brand-add-color"
                    )
        with me.box(classes="gm-usage-card"):
            _label("Logo", "gm-usage-title")
            _label("Drawn small in a corner of exported films.", "gm-brand-hint")
            with me.box(classes="gm-brand-logo-row"):
                if kit["logo_uri"]:
                    with me.box(classes="gm-brand-logo"):
                        me.image(src=_media_url(kit["logo_uri"]), alt="Brand logo")
                    me.button(
                        "Remove logo", on_click=on_remove_logo, key="brand-rm-logo"
                    )
                me.uploader(
                    label="Upload logo" if not kit["logo_uri"] else "Replace logo",
                    accepted_file_types=LOGO_TYPES,
                    on_upload=on_logo,
                    key="brand-logo-upload",
                )
                me.select(
                    label="Corner",
                    options=[
                        me.SelectOption(label=v, value=k)
                        for k, v in CORNER_LABELS.items()
                    ],
                    value=kit["corner"],
                    on_selection_change=on_corner,
                    appearance="outline",
                    key="brand-corner",
                )
        if s.error:
            me.text(s.error, style=me.Style(color=me.theme_var("error")))
        with me.box(classes="gm-brand-actions"):
            me.button(
                "Save brand",
                type="flat",
                color="primary",
                on_click=on_save,
                key="brand-save",
            )
            if s.saved:
                _label("Saved.", "gm-brand-hint")
        line = brand_kit.prompt_line(kit)
        if line:
            with me.box(classes="gm-usage-card"):
                _label("Added to prompts", "gm-usage-title")
                _label(line, "gm-brand-hint")
