"""Every page uses the centred studio header."""

import inspect

import pytest


@pytest.mark.parametrize(
    "module_name",
    ["pages.story_studio", "pages.library_v2", "pages.account", "pages.admin_users"],
)
def test_page_uses_centred_header(module_name):
    import importlib

    source = inspect.getsource(importlib.import_module(module_name))
    # The header() call's arguments fit in a few lines on every page.
    start = source.index("        header(")
    assert "centered=True" in source[start : start + 300]
