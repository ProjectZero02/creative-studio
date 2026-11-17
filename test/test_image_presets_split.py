"""Image Studio "Keep going": core presets inline, the rest behind "More styles"."""

import json

from config.banana_presets import CORE_CREATIVE_KEYS, IMAGE_ACTION_PRESETS
from pages.gemini_image_generation import split_presets

PERSON_KEYS = {
    "alien",
    "hairstyle-bob",
    "restore-colorize",
    "80s-highschool",
    "labubu",
    "professional_headshot",
    "trollify",
}


def _keys(presets):
    return {p["key"] for p in presets}


def test_person_presets_are_tagged_in_both_configs():
    static = {
        p["key"]
        for ps in IMAGE_ACTION_PRESETS.values()
        for p in ps
        if p.get("subject") == "person"
    }
    with open("config/image_prompt_templates.json", encoding="utf-8") as f:
        templates = json.load(f)
    dynamic = {t["key"] for t in templates if t.get("subject") == "person"}
    assert static == PERSON_KEYS
    # labubu is only in banana_presets.py.
    assert dynamic == PERSON_KEYS - {"labubu"}


def test_core_shows_edit_and_short_creative_set():
    core, more = split_presets(IMAGE_ACTION_PRESETS)
    assert _keys(core["edit"]) == _keys(IMAGE_ACTION_PRESETS["edit"])
    assert _keys(core["creative"]) == set(CORE_CREATIVE_KEYS)
    shown = _keys(core["edit"]) | _keys(core["creative"])
    assert not shown & PERSON_KEYS
    assert PERSON_KEYS <= _keys(more)
    total = sum(len(v) for v in IMAGE_ACTION_PRESETS.values())
    assert len(shown) + len(more) == total


def test_person_tag_wins_over_core_and_custom_goes_to_more():
    presets = {
        "edit": [{"key": "fix_face", "subject": "person"}, {"key": "blur"}],
        "custom": [{"key": "admin_made"}],
    }
    core, more = split_presets(presets)
    assert _keys(core["edit"]) == {"blur"}
    assert "custom" not in core
    assert _keys(more) == {"fix_face", "admin_made"}


def test_prompt_template_accepts_subject():
    from common.prompt_template_service import PromptTemplate

    t = PromptTemplate(
        key="k",
        label="l",
        prompt="p",
        category="creative",
        template_type="image",
        attribution="a",
        subject="person",
    )
    assert t.subject == "person"
    assert (
        PromptTemplate(
            key="k",
            label="l",
            prompt="p",
            category="creative",
            template_type="image",
            attribution="a",
        ).subject
        is None
    )
