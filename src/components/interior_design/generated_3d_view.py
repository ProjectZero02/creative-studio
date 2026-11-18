"""
Component that shows the generated 3D view (card 2 on the Interiors page).
"""

import mesop as me

from common.utils import create_display_url
from components.demo_flow.demo_flow import cicon, ctext, demo_card_head


@me.component
def generated_3d_view(storyboard: dict, is_generating: bool):
    """3D view card: numbered heading and the result (or a placeholder).

    The "Generate 3D view" button lives in the page's bottom action bar, like
    the other workflow pages.
    """
    uri = storyboard.get("generated_3d_view_uri") if storyboard else None
    demo_card_head("2", "3D view", "A furnished 3D model of the whole plan.")
    with me.box(classes="gm-demo-drop"):
        if is_generating:
            me.progress_spinner(diameter=36)
            ctext("Building the 3D view…", "gm-demo-drop-text")
        elif uri:
            with me.box(classes="gm-demo-img"):
                me.image(src=create_display_url(uri), alt="Generated 3D view")
        else:
            cicon("view_in_ar", "gm-demo-drop-icon")
            ctext("Your 3D view appears here", "gm-demo-drop-text")
