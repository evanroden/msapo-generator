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
    # Keep the single source workspace available while a rejected chooser
    # item still needs its own correction, even when its good siblings already
    # satisfy ordinary source-status checks. An empty chooser clears this flag.
    st.session_state[local_key + "_failed_original"] = bool(requests)
    if not requests:
        return None
    guidance = st.empty()
    guidance.caption("Only the failed file needs attention. Retry its unchanged bytes below, "
                     "or replace it by selecting a corrected copy in the uploader above. "
                     "Accepted files and report edits remain in place.")
    for request in requests:
        # An old button cannot address another chooser, source set or report
        # revision. The pure operation repeats those checks before reading.
        identity = sha256(repr(request).encode("utf-8")).hexdigest()[:24]
        action = st.empty()
        if not action.button("Retry failed file · " + safe_source_name(request),
                             key=local_key + "_retry_file_" + identity):
            continue
        try:
            recovered, notices = retry_failed_source(
                profile, period, revision, picked, contents, request)
        except ValueError:
            st.warning("This file selection or report changed. Review the current files before retrying.")
            return None
        # A retry reports only its own result. Keep other failed originals'
        # warnings so their separate actions remain available on the next run.
        notices = tuple(message for message in messages
                        if not message.startswith("Not read: " + request.filename + ". ")) + tuple(notices)
        remaining = tuple(candidate for candidate in failed_source_retries(
            profile, period, revision, picked, recovered)
            if any(message.startswith("Not read: " + candidate.filename + ". ")
                   for message in notices))
        st.session_state[local_key + "_failed_original"] = bool(remaining)
        if request.sha256 in {item.source.id for item in recovered}:
            # This widget was rendered before the ingest result was known.
            # Retire only its placeholder immediately; leave sibling buttons.
            action.empty()
            if not remaining:
                guidance.empty()
        return recovered, notices, request
    return None
