"""
Component for uploading a floor plan (card 1 on the Interiors page).
"""

from typing import Callable

import mesop as me

from common.i18n import tx
from common.utils import create_display_url
from components.demo_flow.demo_flow import (
    cicon,
    ctext,
    demo_card_head,
    demo_upload_button,
)
from components.library.library_chooser_button import library_chooser_button


@me.component
def floor_plan_uploader(
    storyboard: dict,
    on_upload: Callable,
    on_library_select: Callable,
):
    """Floor plan card: numbered heading, drop area, Upload / From library.

    Rendered inside a ``gm-demo-card``, the same layout as Product 360 and
    Fashion.
    """
    uri = storyboard.get("original_floor_plan_uri") if storyboard else None
    demo_card_head("1", "Floor plan", "A clear top-down plan with room names.")
    with me.box(classes="gm-demo-drop"):
        if uri:
            with me.box(classes="gm-demo-img"):
                me.image(src=create_display_url(uri), alt=tx("Floor plan"))
        else:
            cicon("floorplan", "gm-demo-drop-icon")
            ctext("No floor plan yet", "gm-demo-drop-text")
    with me.box(classes="gm-demo-actions"):
        demo_upload_button(
            "Replace plan" if uri else "Upload plan",
            on_upload,
            key="interior_floor_plan_uploader",
        )
        library_chooser_button(
            key="floor_plan",
            on_library_select=on_library_select,
            button_label="From library",
        )
