"""Image Studio shows the result before the slow reads, with no 3 s snackbar."""

from unittest.mock import MagicMock

import pytest


def test_result_shows_before_resolution_and_c2pa(monkeypatch: pytest.MonkeyPatch):
    import pages.gemini_image_generation as page_mod

    state = page_mod.PageState(selected_model="gemini-nano-banana-2.1")
    app_state = MagicMock(user_email="tester@example.com")
    monkeypatch.setattr(
        page_mod.me,
        "state",
        lambda cls: state if cls is page_mod.PageState else app_state,
    )
    monkeypatch.setattr(page_mod, "mock_enabled", lambda: False)
    monkeypatch.setattr(page_mod, "create_display_url", lambda u: f"https://x/{u[5:]}")
    monkeypatch.setattr(
        page_mod,
        "generate_image_from_prompt_and_images",
        lambda **_kw: (["gs://b/1.png"], 1.2, ["cap"], None, []),
    )
    monkeypatch.setattr(page_mod, "add_media_item_to_firestore", lambda item: None)

    seen = {}

    def fake_resolution(uri):
        seen["shown_before_resolution"] = (
            state.generated_image_urls == ["https://x/b/1.png"]
            and state.selected_image_url == "https://x/b/1.png"
            and not state.is_generating
        )
        return "1024x1024"

    def fake_manifest(uri):
        seen["c2pa_after_show"] = not state.is_generating
        return {"claim": "x"}

    monkeypatch.setattr(page_mod, "get_image_resolution", fake_resolution)
    monkeypatch.setattr(page_mod.c2pa_service, "read_manifest", fake_manifest)
    snackbar = MagicMock()
    monkeypatch.setattr(page_mod, "show_snackbar", snackbar)
    monkeypatch.setattr(
        page_mod.time, "sleep", MagicMock(side_effect=AssertionError("slept"))
    )

    list(page_mod._generate_and_save(base_prompt="a cup", input_gcs_uris=[]))

    assert seen == {"shown_before_resolution": True, "c2pa_after_show": True}
    snackbar.assert_not_called()
    assert state.generated_resolution == "1024x1024"
    assert "https://x/b/1.png" in state.c2pa_manifests
    assert state.is_generating is False
    assert state.generation_complete is True
    assert state.progress_status == "done"
