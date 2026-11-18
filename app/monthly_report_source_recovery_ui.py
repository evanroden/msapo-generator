"""Native per-file recovery for every Monthly upload surface.

The actual file selection lives in Streamlit's current uploader. Buttons carry
only revision-scoped hashes, not byte copies, into an independent retry.
"""
from hashlib import sha256

import streamlit as st

from app.monthly_report_source_recovery import (
    failed_source_retries, retry_failed_source, safe_source_name,
)


def render_failed_file_retries(profile, period, revision, local_key, picked, contents, *, messages=()):
    """Return a single attempted retry result, or None for a neutral rerun.

    The caller commits accepted sources through its existing source/route path.
    Never mutate a report block, source metadata, or a reader job here.
    """
    # Absence from the accepted inventory is not itself a parse error. A
    # deliberate Remove leaves browser-side uploader bytes selected until the
    # chooser is cleared; never offer to resurrect those removed originals.
    requests = tuple(request for request in failed_source_retries(
        profile, period, revision, picked, contents)
        if any(message.startswith("Not read: " + request.filename + ". ")
               for message in messages))
    if not requests:
        return None
    st.caption("Only the failed file needs attention. Retry its unchanged bytes below, "
               "or replace it by selecting a corrected copy in the uploader above. "
               "Accepted files and report edits remain in place.")
    for request in requests:
        # An old button cannot address another chooser, source set or report
        # revision. The pure operation repeats those checks before reading.
        identity = sha256(repr(request).encode("utf-8")).hexdigest()[:24]
        if not st.button("Retry failed file · " + safe_source_name(request),
                         key=local_key + "_retry_file_" + identity):
            continue
        try:
            recovered, notices = retry_failed_source(
                profile, period, revision, picked, contents, request)
        except ValueError:
            st.warning("This file selection or report changed. Review the current files before retrying.")
            return None
        return recovered, notices, request
    return None
