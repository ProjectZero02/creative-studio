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
"""Studio theme layer: adds one stylesheet and the UI font to every page.

Import this module before any module that declares ``@me.page`` (main.py does
it first). It wraps ``mesop.page`` so each page also loads
``/ui/studio.css`` and Google Sans, without editing every page file. That keeps
upstream merges cheap.
"""

from __future__ import annotations

import inspect
import os

import mesop as me

THEME_CSS_PATH = "/ui/studio.css"
THEME_ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "ui")

# IBM Plex Sans Arabic is for Arabic text. assets/ui/rtl.css puts it in the
# --gm-font stack (Arabic letters only), so Latin stays Google Sans.
FONT_CSS = (
    "https://fonts.googleapis.com/css2?"
    "family=Google+Sans:ital,opsz,wght@0,17..18,400..700;1,17..18,400..700"
    "&family=Google+Sans+Code:wght@400;500"
    "&family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&display=swap"
)

# Stylesheets every page gets, in load order. The theme file goes last so it
# wins over page-level sheets with the same specificity.
GLOBAL_STYLESHEETS = [FONT_CSS, THEME_CSS_PATH]

# Feature sheets every page loads too. Mesop only applies a page's own
# stylesheets on a full page load, not after in-app navigation, so styles that
# a page needs when reached from the side nav must be listed here.
SHARED_STYLESHEETS = [
    "/ui/demos.css",  # industry demos (components/demo_flow)
    "/ui/story.css",  # Story Studio
    "/ui/video_studio.css",  # Video Studio
    "/ui/audio-studio.css",  # Voice and Music
    "/ui/rtl.css",  # Arabic font and right-to-left layout (common/i18n.py)
]

_original_page = me.page


def _with_theme(stylesheets: list[str] | None) -> list[str]:
    shared = set(GLOBAL_STYLESHEETS) | set(SHARED_STYLESHEETS)
    sheets = [s for s in (stylesheets or []) if s not in shared]
    return [GLOBAL_STYLESHEETS[0], *SHARED_STYLESHEETS, *sheets, GLOBAL_STYLESHEETS[1]]


def apply_default_theme() -> None:
    """Follow the system light/dark setting until the user picks one."""
    from state.state import AppState  # pylint: disable=import-outside-toplevel

    if not me.state(AppState).theme_chosen:
        me.set_theme_mode("system")


def _with_default_theme(on_load):
    """Wrap a page's on_load so the theme is set first (pages without one get it too)."""

    def wrapped(e: me.LoadEvent):
        apply_default_theme()
        if on_load is not None:
            result = on_load(e)
            if inspect.isgenerator(result):
                yield from result
                return
        yield

    return wrapped


def themed_page(*args, stylesheets: list[str] | None = None, on_load=None, **kwargs):
    """Drop-in replacement for ``me.page`` that adds the studio theme."""
    return _original_page(
        *args,
        stylesheets=_with_theme(stylesheets),
        on_load=_with_default_theme(on_load),
        **kwargs,
    )


def install() -> None:
    """Route ``me.page`` through the theme. Safe to call more than once."""
    if getattr(me.page, "_gm_themed", False):
        return
    themed_page._gm_themed = True  # type: ignore[attr-defined]
    me.page = themed_page


if os.environ.get("GM_THEME", "on").lower() not in ("off", "0", "false"):
    install()
