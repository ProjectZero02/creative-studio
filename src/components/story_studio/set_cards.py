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
"""Set step cards: one per character, location or prop.

Presentational only. The page passes its event handlers in `SetHandlers`;
every control's key is ``<action>|<kind>|<asset id>|<view>`` so one handler
serves every card (see ``parse_key``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import mesop as me

from services.story_models import VOICE_GENDER, VOICES
from services.story_service import display_url
from services.story_sets import (
    VIEW_LABELS,
    Character,
    Location,
    ensure_views,
    views_for,
)


def card_key(action: str, kind: str, asset_id: str, view: str = "") -> str:
    return f"{action}|{kind}|{asset_id}|{view}"


def parse_key(key: str) -> tuple[str, str, str, str]:
    parts = (key or "").split("|")
    parts += [""] * (4 - len(parts))
    return parts[0], parts[1], parts[2], parts[3]


@dataclass
class SetHandlers:
    on_field: Callable  # input blur: name / description / outfit / time / style...
    on_voice: Callable  # select change: TTS voice
    on_regen: Callable  # click: regenerate one image (or the voice sample)
    on_lock: Callable  # click: lock / unlock one image
    on_upload: Callable  # upload: replace the main image
    on_library: Callable  # library pick: replace the main image
    on_play: Callable  # click: play the voice sample
    on_remove: Callable  # click: remove the asset
    library_button: Callable | None = None  # components.library chooser


def _icon_button(icon: str, label: str, key: str, on_click, disabled: bool) -> None:
    with me.content_button(type="icon", on_click=on_click, disabled=disabled, key=key):
        me.icon(icon)
        with me.box(classes="gm-sr-only"):
            me.text(label)


def _tile(kind: str, asset, view: str, task: dict | None, h: SetHandlers, busy: bool):
    img = next((i for i in asset.images if i.view == view), None)
    uri = img.uri if img else ""
    locked = bool(img and img.locked)
    status = (task or {}).get("status", "")
    ratio = {"16:9": "ss-ar-169", "1:1": "ss-ar-11"}.get(
        "16:9"
        if isinstance(asset, Location)
        else ("1:1" if view in ("face", "item") else ""),
        "ss-ar-34",
    )
    with me.box(classes=f"ss-set-tile{' is-locked' if locked else ''}"):
        with me.box(classes=f"ss-media {ratio}"):
            if uri and status != "running":
                me.image(
                    src=display_url(uri),
                    alt=f"{asset.name} {VIEW_LABELS.get(view, view)}",
                    style=me.Style(width="100%", height="100%", object_fit="cover"),
                )
            elif status == "running":
                me.box(classes="ss-skel ss-skel-fill")
                with me.box(classes="ss-media-overlay"):
                    me.box(classes="ss-spinner")
            elif status == "failed":
                with me.box(classes="ss-media-overlay ss-failed"):
                    me.icon("error", style=me.Style(font_size=20, width=20, height=20))
                    me.text(task.get("error") or "Failed", style=me.Style(font_size=12))
            elif status == "queued":
                me.box(classes="ss-skel ss-skel-fill is-idle")
            else:
                with me.box(classes="ss-media-overlay"):
                    me.icon("image", style=me.Style(font_size=20, width=20, height=20))
            with me.box(classes="ss-set-tile-label"):
                me.text(VIEW_LABELS.get(view, view))
        with me.box(classes="ss-set-tile-bar"):
            _icon_button(
                "lock" if locked else "lock_open",
                f"{'Unlock' if locked else 'Lock'} {VIEW_LABELS.get(view, view)}",
                card_key("lock", kind, asset.id, view),
                h.on_lock,
                busy or not uri,
            )
            _icon_button(
                "refresh",
                f"Regenerate {VIEW_LABELS.get(view, view)}",
                card_key("regen", kind, asset.id, view),
                h.on_regen,
                busy or locked,
            )


def _field(label: str, value: str, key: str, h: SetHandlers, busy: bool, rows: int = 0):
    if rows:
        me.textarea(
            label=label,
            value=value,
            rows=rows,
            appearance="outline",
            disabled=busy,
            on_blur=h.on_field,
            style=me.Style(width="100%"),
            key=key,
        )
    else:
        me.input(
            label=label,
            value=value,
            appearance="outline",
            disabled=busy,
            on_blur=h.on_field,
            style=me.Style(width="100%"),
            key=key,
        )


def _voice(kind: str, c: Character, h: SetHandlers, busy: bool, task, playing: bool):
    with me.box(classes="ss-set-voice"):
        me.select(
            label="Voice",
            options=[
                me.SelectOption(label=f"{v} · {VOICE_GENDER.get(v, '')}", value=v)
                for v in VOICES
            ],
            value=c.voice.tts_voice,
            appearance="outline",
            disabled=busy,
            on_selection_change=h.on_voice,
            key=card_key("voice", kind, c.id),
        )
        _field("Delivery", c.voice.style, card_key("style", kind, c.id), h, busy)
        making = (task or {}).get("status") in ("queued", "running")
        me.button(
            "Making…"
            if making
            else ("Play sample" if c.voice.sample_uri else "Make sample"),
            type="stroked",
            disabled=busy,
            on_click=h.on_play if c.voice.sample_uri else h.on_regen,
            key=card_key(
                "play" if c.voice.sample_uri else "regen", kind, c.id, "voice"
            ),
        )
    if not c.narrator:
        _field(
            "On-camera voice",
            c.voice.description,
            card_key("voice_description", kind, c.id),
            h,
            busy,
        )
    if playing and c.voice.sample_uri:
        me.audio(src=display_url(c.voice.sample_uri), autoplay=True)


def asset_card(
    kind: str,
    asset,
    *,
    tasks: dict,
    h: SetHandlers,
    busy: bool,
    playing: str = "",
    demo: bool = False,
) -> None:
    """One card: images in a row, the text fields and (characters) the voice."""
    ensure_views(asset)
    narrator = isinstance(asset, Character) and asset.narrator
    with me.box(classes="ss-card ss-set-card"):
        with me.box(classes="ss-set-card-head" + (" is-narrator" if narrator else "")):
            with me.box(classes="ss-grow"):
                _field("Name", asset.name, card_key("name", kind, asset.id), h, busy)
            if not narrator:
                me.uploader(
                    label="Upload",
                    accepted_file_types=["image/png", "image/jpeg", "image/webp"],
                    type="stroked",
                    disabled=busy,
                    on_upload=h.on_upload,
                    key=card_key("upload", kind, asset.id),
                )
                if h.library_button is not None and not demo:
                    h.library_button(
                        on_library_select=h.on_library,
                        button_label="Library",
                        key=card_key("library", kind, asset.id),
                        disabled=busy,
                    )
                else:  # demo mode has no media library
                    me.button(
                        "Library",
                        type="stroked",
                        disabled=True,
                        key=card_key("library", kind, asset.id),
                    )
            _icon_button(
                "delete_outline",
                f"Remove {asset.name or kind}",
                card_key("remove", kind, asset.id),
                h.on_remove,
                busy,
            )
        views = views_for(asset)
        if views:
            with me.box(classes=f"ss-set-tiles is-{kind}"):
                for view in views:
                    _tile(kind, asset, view, tasks.get((kind, asset.id, view)), h, busy)
        if narrator:
            me.text(
                "Off-screen narrator",
                style=me.Style(font_size=13, color=me.theme_var("on-surface-variant")),
            )
        else:
            _field(
                "Look",
                asset.description,
                card_key("description", kind, asset.id),
                h,
                busy,
                rows=2,
            )
        if isinstance(asset, Character) and not narrator:
            _field("Outfit", asset.outfit, card_key("outfit", kind, asset.id), h, busy)
        if isinstance(asset, Location):
            _field(
                "Time of day",
                asset.time_of_day,
                card_key("time_of_day", kind, asset.id),
                h,
                busy,
            )
        if isinstance(asset, Character):
            _voice(
                kind,
                asset,
                h,
                busy,
                tasks.get((kind, asset.id, "voice")),
                playing == asset.id,
            )
