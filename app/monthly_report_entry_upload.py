"""One first-use starting-report upload before contract and site choices.

The original stays in an isolated temporary import until the existing native
starting-report review explicitly commits it. Cover names are *suggestions*,
not authority to waive site or period review.
"""
import hashlib

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_import_ui import _stage
from app.monthly_report_upload_guidance import starting_upload_options
from app.monthly_report_start_import import source_sites, mentioned_periods
from app.monthly_report_start_ui import site_choices
from app.monthly_report_starting_errors import starting_docx_failure_notice


ENTRY_STAGE = "report_entry_stage"
ENTRY_COMMITTED = "report_entry_committed_digest"
ENTRY_EPOCH = "report_entry_upload_epoch"
ENTRY_UPLOAD_KEY = "report_entry_upload"


def entry_upload_key():
    """The first-use picker's key; removal rotates it, since Streamlit cannot
    assign an empty value to a file uploader."""
    epoch = st.session_state.get(ENTRY_EPOCH, 0)
    return ENTRY_UPLOAD_KEY + (f"_v{epoch}" if epoch else "")


def inferred_contracts(inspection, contracts):
    """Only unique known cover-site membership may suggest an account."""
    matches = []
    for contract in contracts:
        options = site_choices(contract, library.list_profiles(contract))
        if source_sites(inspection, options):
            matches.append(contract)
    return tuple(matches)


def _retire_stage(stage):
    if stage is None:
        return
    # Other per-site review keys can still reference the same temporary path.
    # Retire those pointers before deleting its immutable staged bytes.
    for key in tuple(st.session_state):
        if key.startswith("report_setup_") and key.endswith("_stage") and st.session_state[key] is stage:
            st.session_state.pop(key, None)
    if stage[0] is not None:
        stage[0].cleanup()


def remove_entry_upload():
    """Retire the first-use upload: its stage, every review pointing at that
    stage, its temporary bytes and the picker itself. Saved reports are never
    touched."""
    prior = st.session_state.pop(ENTRY_STAGE, None)
    st.session_state[ENTRY_EPOCH] = st.session_state.get(ENTRY_EPOCH, 0) + 1
    for key in (ENTRY_COMMITTED, "report_entry_failed_digest", "report_entry_failed_notice"):
        st.session_state.pop(key, None)
    _retire_stage(prior)


def render_first_upload(field, contracts):
    """Return (widget file, staged original, uniquely inferred contract).

    A fresh user can upload first. A valid upload is parsed on selection, not
    after an additional Analyze button. A rejected replacement never imports
    the prior staged source, and an unchanged upload is not parsed twice.
    """
    st.subheader("Start with a report")
    st.caption("Upload last month's Word report or a partly finished report for this month. The source stays unchanged.")
    upload = st.file_uploader("Starting report", type=["docx"],
        key=entry_upload_key(), **starting_upload_options())
    prior = st.session_state.get(ENTRY_STAGE)
    if upload is None:
        _retire_stage(prior)
        # Removing the picker is a new deliberate selection boundary. Do not
        # permanently reject an identical file when it is chosen again.
        st.session_state.pop(ENTRY_COMMITTED, None)
        st.session_state.pop(ENTRY_STAGE, None)
        st.session_state.pop("report_entry_failed_digest", None)
        st.session_state.pop("report_entry_failed_notice", None)
        return None, None, ()
    digest = hashlib.sha256(upload.getvalue()).hexdigest()
    if digest == st.session_state.get(ENTRY_COMMITTED):
        return upload, None, ()
    if prior is None or prior[2].sha256 != digest:
        failed = st.session_state.get("report_entry_failed_digest")
        retry = failed == digest and st.button("Retry report analysis",
            key="report_entry_retry")
        if failed != digest or retry:
            try:
                with st.spinner("Reading the report and identifying its sites…"):
                    staged = _stage(upload)
            except (ValueError, OSError) as exc:
                st.session_state["report_entry_failed_digest"] = digest
                st.session_state["report_entry_failed_notice"] = starting_docx_failure_notice(exc)
            else:
                st.session_state[ENTRY_STAGE] = staged
                st.session_state.pop(ENTRY_COMMITTED, None)
                st.session_state.pop("report_entry_failed_digest", None)
                st.session_state.pop("report_entry_failed_notice", None)
                _retire_stage(prior)
                prior = staged
        if st.session_state.get("report_entry_failed_digest") == digest:
            st.warning(st.session_state["report_entry_failed_notice"])
            if failed != digest:
                st.button("Retry report analysis", key="report_entry_retry")
            return upload, None, ()
    else:
        st.session_state.pop("report_entry_failed_digest", None)
        st.session_state.pop("report_entry_failed_notice", None)
    if prior is None or prior[2].sha256 != digest:
        return upload, None, ()
    contracts = inferred_contracts(prior[2], contracts)
    periods = mentioned_periods("\n".join(prior[2].title_candidates))
    source_period = (next(iter(periods)) if len(periods) == 1 else None)
    if source_period:
        st.caption(f"Detected source month: {source_period[0]}-{source_period[1]:02d}. Choose the month you are preparing below.")
    st.caption("File read. Detected sites and sections will be checked against the selected report before import.")
    return upload, prior, contracts
