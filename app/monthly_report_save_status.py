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


def _markup(message, *, timestamp="", state="pending"):
    # Owner decision (25 Nov 2026): one short line, no "Browser draft" label.
    return ('<p class="enfra-browser-save-status" role="status" aria-live="polite" '
            f'data-save-state="{escape(state)}" title="{escape(timestamp, quote=True)}" '
            'style="font-size:.875rem;line-height:1.5;margin:0">'
            + escape(message) + '</p>')


def _reserve_status(key, message):
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
    # becomes 1.3125rem for our one line, or more if it wraps. Mirror the
    # current text at the native width, instead of fixing a pixel height.
    # This pseudo-element stays inside the existing aria-hidden skeleton.
    st.html('<style>' + skeleton + '{height:auto;font-size:.875rem;line-height:1.5;}'
            + skeleton + '::before{'
            'display:block;visibility:hidden;white-space:normal;'
            'word-break:break-word;overflow-wrap:break-word;margin:0;'
            'content:' + content(message) + ';}</style>')


class SaveStatus:
    def __init__(self, prefix, *, recovery_available):
        # A real keyed block and real text occupy the same path from the first
        # delta. st.empty() followed by an alert briefly removed the status and
        # then moved all editors by 72px during an ordinary native photo click.
        self.key = prefix + "_browser_save_status"
        self.slot = None
        with st.container(key=self.key):
            self._update("Saving…" if recovery_available else "Recovery unavailable",
                         state="pending" if recovery_available else "unavailable")

    def _update(self, message, *, timestamp="", state="pending"):
        _reserve_status(self.key, message)
        target = self.slot if self.slot is not None else st
        self.slot = target.markdown(_markup(message, timestamp=timestamp, state=state),
                                    unsafe_allow_html=True)

    def browser_saved(self, timestamp):
        # The actual journal timestamp stays unchanged on a no-op persistence
        # acknowledgment. "Saved" does not promise unsubmitted keystrokes.
        timestamp = timestamp if isinstance(timestamp, str) else ""
        shown = _saved_time(timestamp)
        self._update("Saved" if shown == "Time unavailable" else "Saved " + shown,
                     timestamp=timestamp, state="saved")

    def shared_saved(self, revision):
        self._update(f"Version {revision} is saved", state="shared")

    def failed(self):
        self._update("Save failed · see error below", state="failed")

