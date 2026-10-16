"""Current output receipts and targeted retries, separate from draft recovery."""
from hashlib import sha256

import streamlit as st


def package_identity(package):
    return (package.fingerprint, sha256(package.docx).hexdigest())


def record_shared_save(prefix, package, *, saved=None, error=""):
    st.session_state[prefix + "_package_save"] = {
        "identity": package_identity(package), "revision": saved.revision if saved else None,
        "saved_at": saved.generated_at if saved else "", "error": error,
    }


def render_output_status(package, draft, snapshot, prefix):
    """Return whether this exact package still needs a shared-version save."""
    status = st.session_state.get(prefix + "_package_save")
    if not status or status["identity"] != package_identity(package):
        status = None
    # A later manual checkpoint can independently establish that this exact
    # current draft is saved, without generating or saving again on display.
    if snapshot and snapshot.draft.fingerprint == draft.fingerprint:
        revision = snapshot.revision
    else:
        revision = status["revision"] if status else None
    st.success("Word and PDF ready to download" if package.pdf else "Word ready to download")
    if revision is not None:
        st.caption(f"[Shared version {revision}](#shared-report-history) · {draft.period.label}")
        return False
    message = status["error"] if status else "No shared-version save was confirmed for these files."
    st.warning("Downloads are ready, but this version was not saved in shared report history: " + message)
    st.caption("Retry saving this version below. Your files stay available; saving does not generate them again.")
    return True


def queue_retry(prefix, kind, identity, scope, revision):
    st.session_state[prefix + "_pending_output_" + kind] = (identity, scope, revision)


def take_retries(prefix):
    # Consume even when a delivered native edit retires the old package. A
    # stale action cannot sit pending until an older draft is opened again.
    return {kind: st.session_state.pop(prefix + "_pending_output_" + kind, None)
            for kind in ("save", "pdf")}


def matches_retry(request, package, scope, revision):
    return request == (package_identity(package), scope, revision)
