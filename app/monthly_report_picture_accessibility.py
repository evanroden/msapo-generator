"""Give imported native images their own visible review caption as alt text."""
from functools import lru_cache
from pathlib import Path

import streamlit as st
from streamlit.runtime import Runtime


@lru_cache(maxsize=2)
def _adapter(runtime):
    return st.components.v2.component("monthly_import_picture_description",
        js=Path(__file__).with_suffix(".js").read_text(), isolate_styles=False)


def review_image(data, *, width, caption, key):
    """Keep Streamlit's native fullscreen image and its grounded visible label."""
    owner = "monthly_import_picture_" + key
    with st.container(key=owner):
        st.image(data, width=width, caption=caption)
        # Streamlit 1.61 uses a numeric image index as img.alt. The display-only
        # companion reads this image's rendered caption, never report state.
        _adapter(Runtime.instance())(key=owner + "_description", data={"owner": owner},
                                     height=1, width="stretch")
