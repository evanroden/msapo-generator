"""A continuously mounted acknowledgment, separate from shared version history."""

from datetime import datetime, timezone
from html import escape

import streamlit as st


def _saved_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "Time unavailable"
        return parsed.astimezone(timezone.utc).strftime("%H:%M UTC")
    except (AttributeError, TypeError, ValueError):
        return "Time unavailable"


def _markup(message, *, timestamp="", state="pending", scope="Browser draft"):
    return ('<p class="enfra-browser-save-status" role="status" aria-live="polite" '
            f'data-save-state="{escape(state)}" title="{escape(timestamp, quote=True)}" '
            'style="font-size:.875rem;line-height:1.5;margin:0">'
            + escape(scope) + '<br>' + escape(message) + '</p>')


class SaveStatus:
    def __init__(self, prefix, *, recovery_available):
        # A real keyed block and real text occupy the same path from the first
        # delta. st.empty() followed by an alert briefly removed the status and
        # then moved all editors by 72px during an ordinary native photo click.
        with st.container(key=prefix + "_browser_save_status"):
            self.slot = st.markdown(_markup(
                "Saving changes…" if recovery_available else "Recovery unavailable",
                state="pending" if recovery_available else "unavailable"), unsafe_allow_html=True)

    def browser_saved(self, timestamp):
        # The actual journal timestamp stays unchanged on a no-op persistence
        # acknowledgment. "Last saved" does not promise unsubmitted keystrokes.
        timestamp = timestamp if isinstance(timestamp, str) else ""
        self.slot.markdown(_markup("Last saved · " + _saved_time(timestamp),
                                   timestamp=timestamp, state="saved"), unsafe_allow_html=True)

    def shared_saved(self, revision):
        self.slot.markdown(_markup(f"Version {revision} is saved", state="shared", scope="Shared report"),
                           unsafe_allow_html=True)

    def failed(self):
        self.slot.markdown(_markup("Save failed · see error below", state="failed"),
                           unsafe_allow_html=True)

