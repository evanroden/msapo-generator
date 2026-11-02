"""A continuously mounted acknowledgment, separate from shared version history."""

from datetime import datetime, timezone
from html import escape
import re

import streamlit as st


def _saved_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "Time unavailable"
        return parsed.astimezone(timezone.utc).strftime("%H:%M UTC")
    except (AttributeError, TypeError, ValueError, OverflowError):
        return "Time unavailable"


def _markup(message, *, timestamp="", state="pending", scope="Browser draft"):
    return ('<p class="enfra-browser-save-status" role="status" aria-live="polite" '
            f'data-save-state="{escape(state)}" title="{escape(timestamp, quote=True)}" '
            'style="font-size:.875rem;line-height:1.5;margin:0">'
            + escape(scope) + '<br>' + escape(message) + '</p>')


def _reserve_status(key, scope, message):
    """Match this status's raw-HTML placeholder without sizing the live text."""
    if st.__version__ != "1.61.1":
        return
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())
    skeleton = (".st-key-" + name + ' [data-testid="stMarkdownContainer"]'
                ' > [data-testid="stSkeleton"]')

    def content(value):
        # CSS strings use hexadecimal escapes, not JSON's \n or \t escapes.
        escaped = []
        for char in value:
            if char in "<>&" or ord(char) < 32 or ord(char) == 127:
                escaped.append("\\" + format(ord(char), "x") + " ")
            else:
                escaped.append("\\" + char if char in '\\"' else char)
        return '"' + "".join(escaped) + '"'

    # Markdown defers raw HTML on a cold load. Its default 2.5rem skeleton
    # becomes 2.625rem for our two lines, or more if either line wraps. Mirror
    # the current text at the native width, instead of fixing a pixel height.
    # These pseudo-elements stay inside the existing aria-hidden skeleton.
    st.html('<style>' + skeleton + '{height:auto;font-size:.875rem;line-height:1.5;}'
            + skeleton + '::before,' + skeleton + '::after{'
            'display:block;visibility:hidden;white-space:normal;'
            'word-break:break-word;overflow-wrap:break-word;margin:0;}'
            + skeleton + '::before{content:' + content(scope) + ';}'
            + skeleton + '::after{content:' + content(message) + ';}</style>')


class SaveStatus:
    def __init__(self, prefix, *, recovery_available):
        # A real keyed block and real text occupy the same path from the first
        # delta. st.empty() followed by an alert briefly removed the status and
        # then moved all editors by 72px during an ordinary native photo click.
        self.key = prefix + "_browser_save_status"
        self.slot = None
        with st.container(key=self.key):
            self._update("Saving changes…" if recovery_available else "Recovery unavailable",
                         state="pending" if recovery_available else "unavailable")

    def _update(self, message, *, timestamp="", state="pending", scope="Browser draft"):
        _reserve_status(self.key, scope, message)
        target = self.slot if self.slot is not None else st
        self.slot = target.markdown(_markup(message, timestamp=timestamp, state=state, scope=scope),
                                    unsafe_allow_html=True)

    def browser_saved(self, timestamp):
        # The actual journal timestamp stays unchanged on a no-op persistence
        # acknowledgment. "Last saved" does not promise unsubmitted keystrokes.
        timestamp = timestamp if isinstance(timestamp, str) else ""
        self._update("Last saved · " + _saved_time(timestamp), timestamp=timestamp, state="saved")

    def shared_saved(self, revision):
        self._update(f"Version {revision} is saved", state="shared", scope="Shared report")

    def failed(self):
        self._update("Save failed · see error below", state="failed")

