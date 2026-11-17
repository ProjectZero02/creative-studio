"""The full prompt shows on hover in result cards and under the lightbox image."""

import pathlib

from pages.gemini_image_generation import PageState, _prompt_for_image


def test_prompt_for_image_uses_recent_entry():
    state = PageState(
        history_urls=["u1", "u2"],
        history_prompts=["first prompt", "second prompt"],
        last_prompt="latest",
    )
    assert _prompt_for_image(state, "u2") == "second prompt"


def test_prompt_for_image_falls_back_to_last_prompt():
    state = PageState(history_urls=["u1"], history_prompts=[], last_prompt="latest")
    assert _prompt_for_image(state, "u1") == "latest"
    assert _prompt_for_image(state, "other") == "latest"


def test_result_card_caption_has_full_prompt_title():
    js = pathlib.Path("components/result_grid/result_card.js").read_text(
        encoding="utf-8"
    )
    assert '<span class="prompt">' not in js
    assert js.count('<span class="prompt" title=${this.prompt}>') == 2
