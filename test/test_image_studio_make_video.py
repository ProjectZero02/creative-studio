"""Image Studio "Keep going": one "Make a video" button into Video Studio."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config.video_studio_models import DEFAULT_STUDIO_MODEL_ID, VIDEO_STUDIO_PATH


def test_make_video_opens_video_studio_with_default_model():
    from pages import gemini_image_generation as page

    app_state = SimpleNamespace(current_page="/nano-banana", session_id="s")
    with (
        patch("mesop.state", return_value=app_state),
        patch("mesop.navigate") as navigate,
        patch.object(page, "log_ui_click"),
    ):
        list(page.on_make_video_click(SimpleNamespace(key="gs://bucket/img.png")))
    navigate.assert_called_once_with(
        url=VIDEO_STUDIO_PATH,
        query_params={
            "veo_model": DEFAULT_STUDIO_MODEL_ID,
            "image_path": "bucket/img.png",
        },
    )


def test_make_video_without_image_does_nothing():
    from pages import gemini_image_generation as page

    app_state = SimpleNamespace(current_page="/nano-banana", session_id="s")
    with (
        patch("mesop.state", return_value=app_state),
        patch("mesop.navigate") as navigate,
        patch.object(page, "log_ui_click"),
    ):
        list(page.on_make_video_click(SimpleNamespace(key="")))
    navigate.assert_not_called()


@patch("pages.veo.create_display_url", side_effect=lambda u: u)
def test_video_studio_honours_veo_model_with_legacy_pages_off(_display):
    """/veo is not behind SHOW_LEGACY_PAGES, and it reads veo_model= on load."""
    from config.default import Default
    from pages.veo import on_veo_load
    from state.veo_state import PageState

    assert Default.SHOW_LEGACY_PAGES is False
    state = PageState(veo_model="3.1-fast")
    params = {"veo_model": DEFAULT_STUDIO_MODEL_ID, "image_path": "bucket/img.png"}
    with (
        patch("mesop.query_params", params),
        patch("mesop.state", return_value=state),
    ):
        list(on_veo_load(MagicMock()))
    assert state.veo_model == DEFAULT_STUDIO_MODEL_ID
    assert state.veo_mode == "i2v"
    assert state.reference_image_gcs == "gs://bucket/img.png"
