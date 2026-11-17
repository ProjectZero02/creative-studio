"""Popups stay above page content: CSS stacking rules in the built studio.css."""

import pathlib
import re

CSS = pathlib.Path("assets/ui/studio.css").read_text(encoding="utf-8")


def _rule(selector_pattern: str) -> str:
    match = re.search(selector_pattern + r"[^{]*\{([^}]*)\}", CSS)
    assert match, selector_pattern
    return match.group(1)


def test_open_avatar_menu_sits_above_page_body():
    """While open, the avatar menu's wrapper must out-rank the page body (z 1)."""
    body = _rule(r"\.gm-page > :has\(user-menu\[data-open\]\)")
    z = int(re.search(r"z-index:\s*(\d+)", body).group(1))
    assert z > 1


def test_user_menu_marks_itself_open():
    js = pathlib.Path("components/user_menu/user_menu.js").read_text(encoding="utf-8")
    assert "toggleAttribute('data-open', this._open)" in js


def test_composer_sits_above_results():
    """Chip menus live inside the composer, so the composer must out-rank results."""
    body = _rule(r"html body \.gm-composer ")
    assert "position: relative" in body
    assert int(re.search(r"z-index:\s*(\d+)", body).group(1)) > 1

