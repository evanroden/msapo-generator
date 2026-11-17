"""Close one Streamlit copy during the Render-to-Azure cutover."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import streamlit as st


_LOG = logging.getLogger(__name__)
_DEFAULT_NOTICE = "This copy of Process Control is closed. Use it here:"


def _valid_https_destination(value: str) -> bool:
    """Allow a usable HTTPS destination, never a relative or unsafe link."""
    if value != value.strip() or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and (parsed.port is None or parsed.port > 0)
        )
    except ValueError:
        return False


def close_if_moved() -> None:
    """Display a plain-text closure and stop before starting any app work."""
    destination = os.environ.get("MSAPO_SERVICE_MOVED_TO", "")
    if not destination:
        return

    st.text(os.environ.get("MSAPO_SERVICE_NOTICE") or _DEFAULT_NOTICE)
    if _valid_https_destination(destination):
        st.link_button("Open Process Control", destination)
    else:
        # Do not log the supplied address: it can itself contain private data.
        _LOG.warning("MSAPO_SERVICE_MOVED_TO is not a valid HTTPS URL; link omitted")
    st.stop()
