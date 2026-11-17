"""Interiors uses the same card layout as the other workflow pages."""

import inspect


def test_cards_use_the_shared_card_heading():
    from components.interior_design import floor_plan_uploader, generated_3d_view

    for module in (floor_plan_uploader, generated_3d_view):
        source = inspect.getsource(module)
        assert "demo_card_head(" in source
        assert "gm-demo-drop" in source


def test_generate_button_sits_in_the_bottom_bar():
    from components.interior_design.generated_3d_view import generated_3d_view
    from pages import interior_design_v2

    assert "on_generate" not in inspect.signature(generated_3d_view).parameters
    page = inspect.getsource(interior_design_v2)
    bar = page.index('classes="gm-demo-bar"')
    assert page.index("on_click=on_generate_3d_view_click", bar) > bar


def test_demo_card_head_renders_number_title_and_hint():
    from components.demo_flow import demo_flow

    source = inspect.getsource(demo_flow.demo_card_head)
    for cls in ("gm-demo-card-num", "gm-demo-card-title", "gm-demo-card-hint"):
        assert cls in source
