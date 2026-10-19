"""Truthful source-correction warnings while the native client is loading.

The alert is useful without JavaScript. Its correction becomes a link only
when the existing display adapter can reach this source's actual native field.
No report data, acceptance decision or editor input is changed here.

The bridge follows the locked Streamlit 1.61.1 alert/form contract in
workspace_layout. Review its native selectors on a dependency change; remove
it when a framework-provided deferred native correction link replaces it.
"""
from hashlib import sha256
from html import escape

import streamlit as st


def render_source_check(check, draft):
    if check.code not in {"source_facility", "source_period", "source_date_unknown"}:
        return False
    source = next((item for item in draft.sources if item.id == check.block_key), None)
    if source is None:
        return False
    kind = "site" if check.code == "source_facility" else "date"
    label = "Correct site" if kind == "site" else "Correct date"
    key = sha256((source.id + "\0" + check.code).encode()).hexdigest()[:24]
    with st.container(key="source_correction_" + key):
        # Keep source identity out of the visible warning and URL parameters.
        # This inert marker belongs to the alert, not to its native form.
        st.markdown('<span class="enfra-source-correction" data-source-id="' +
                    escape(source.id, quote=True) + '" data-kind="' + kind +
                    '" data-label="' + label + '" aria-hidden="true"></span>',
                    unsafe_allow_html=True)
        # Streamlit's standard alert retains the exact problem and severity.
        # Only this final app-owned status is exchanged for a native link.
        (st.error if check.blocking else st.warning)(
            check.message + " **Loading correction controls…**")
    return True
