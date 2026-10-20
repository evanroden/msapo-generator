"""Shared display-only workspaces for the three first-party workflows.

The browser adapter changes presentation on existing keyed containers. It never
reads input values, sends geometry to Python, writes business state or remounts
editors. The selectors below deliberately target the locked Streamlit 1.61 DOM
only inside our owned container keys; browser geometry tests are the acceptance
check when that dependency changes.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from hashlib import sha256
from html import escape
from pathlib import Path
import re
from uuid import uuid4

import streamlit as st
from streamlit.runtime import Runtime

_ASSETS = Path(__file__).parent
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _key(value: str) -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ValueError("Workspace keys must be stable lowercase application identifiers")
    return value


@lru_cache(maxsize=2)
def _adapter(runtime):
    # Register once, not once per section/fragment. No user data enters code.
    source = (_ASSETS / "workspace_geometry.js").read_text() + "\n" + (
        _ASSETS / "monthly_report_source_navigation.js").read_text() + "\n" + (
        _ASSETS / "monthly_report_entry_focus.js").read_text() + "\n" + (
        _ASSETS / "workspace_layout.js").read_text()
    return st.components.v2.component("enfra_workspace_layout", js=source,
                                      css=(_ASSETS / "workspace_layout.css").read_text(),
                                      isolate_styles=False)


@contextmanager
def workspace(workflow: str, identity: str, *, navigation_key: str = ""):
    """Own the single ordered editor scroll root; yield its Streamlit container.

    ``identity`` is used only to isolate ephemeral view positions and is hashed
    before entering component data. Use the report/draft identity, not an input
    fingerprint: editing must not reset reading position.
    """
    workflow = _key(workflow)
    if navigation_key:
        _key(navigation_key)
    with st.container(key="epc_workspace_" + workflow) as root:
        _adapter(Runtime.instance())(key="epc_display_" + workflow, data={
            "workflow": workflow,
            "identity": sha256(str(identity).encode()).hexdigest()[:24],
            "navigationKey": navigation_key,
            # New only for a real top-level workspace render, never a preview
            # fragment. It lets display-only viewers distinguish a queued
            # native edit from the completed full-app rerun that accepted it.
            "fullRender": uuid4().hex,
        }, height=1, width="stretch")
        yield root


@contextmanager
def workspace_section(key: str, title: str = ""):
    """Bound one editor/reference pair, including its heading and errors."""
    key = _key(key)
    with st.container(key="epc_pair_" + key) as section:
        st.markdown('<span class="epc-pair-marker" data-epc-pair="' + key +
                    '" data-epc-title="' + escape(title, quote=True) +
                    '" aria-hidden="true"></span>', unsafe_allow_html=True)
        yield section


def workspace_columns(key: str):
    """Return stable editor-left/reference-right containers in every layout."""
    key = _key(key)
    editor_column, reference_column = st.columns([1.12, 1], gap="large")
    with editor_column:
        editor = st.container(key="epc_edit_" + key)
    with reference_column:
        reference = st.container(key="epc_reference_" + key)
    return editor, reference
