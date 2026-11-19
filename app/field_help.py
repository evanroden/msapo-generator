"""Consistent visible guidance for PO and expense fields on pointer, keyboard and touch.

Streamlit's native help icon may be inaccessible without hover. Consuming the
help argument here, rather than forwarding it, removes that icon and displays
its full instructions directly after the unchanged input widget.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

import streamlit as st

T = TypeVar("T")


def field_with_help(widget: Callable[..., T], *args: Any, help: str, **kwargs: Any) -> T:
    """Render an ordinary Streamlit control followed by persistent guidance."""
    value = widget(*args, **kwargs)
    st.caption(help)
    return value
