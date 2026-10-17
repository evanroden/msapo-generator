"""One source manager, with direct re-entry for specific file problems."""
from dataclasses import replace

import streamlit as st

from app.monthly_report_source_status import source_manager_status
from app.monthly_report_upload_ui import render_uploads
from app.monthly_report_model import used_source_ids


def _open_manager(manager_key, selection_key, source_id):
    st.session_state[manager_key] = True
    if source_id:
        st.session_state[selection_key] = source_id


def _statuses(draft, blocks, prefix):
    evidence = prefix + "_evidence"
    pending = bool(st.session_state.get(evidence + "_pending_acceptance")
                   or st.session_state.get(evidence + "_accepted_failure")
                   or any(value for key, value in st.session_state.items()
                          if key.startswith(evidence + "_structured_")
                          and key.endswith(("_job", "_pending"))))
    return source_manager_status(replace(draft, blocks=tuple(blocks.values())),
        st.session_state.get(evidence, ()),
        unavailable=st.session_state.get(prefix + "_unavailable_sources", ()), pending=pending)


def render_guided_source_manager(draft, blocks, prefix, field, apply_prepared, keep_missing):
    """Re-entry changes visibility only; Add retains its atomic commit path."""
    manager_key = field(prefix + "_batch_files_open", False)
    selection_key = prefix + "_evidence_selected"
    states = _statuses(draft, blocks, prefix)
    attention = tuple(item for item in states if item.needs_correction)
    # Another explicit reader may finish earlier in this same ordered render.
    # Never retire an already-open native control merely because its source
    # just resolved: delivered input still belongs to the normal capture below.
    opened = bool(st.session_state[manager_key])

    if states:
        st.caption(f"{len(states)} source {'file' if len(states) == 1 else 'files'}" +
                   (f" · {len(attention)} need details" if attention else ""))
    if attention:
        with st.container(border=True):
            for item in attention:
                if opened:
                    st.caption(item.filename + " · " + item.reason)
                else:
                    st.caption(item.reason)
                    st.button("Review " + item.filename,
                              key=prefix + "_review_source_" + item.source_id,
                              on_click=_open_manager,
                              args=(manager_key, selection_key, item.source_id))
    # Ready pages, optional references and new uploads all reopen this same
    # native editor. Quiet does not mean reviewed, included or saved.
    st.button("Done with source files" if opened else "Manage source files",
              key=prefix + "_source_manager_" + str(opened),
              on_click=_open_manager if not opened else _close_manager,
              args=(manager_key, selection_key, "") if not opened else (manager_key,))
    if not opened:
        return draft, blocks

    selected_id = st.session_state.get(selection_key)
    selected_status = next((item for item in states if item.source_id == selected_id), states[0] if states else None)
    if selected_status and selected_status.summary and not selected_status.needs_correction:
        st.caption(selected_status.filename + " · " + selected_status.summary)

    sources, additions, incoming_specs = render_uploads(
        draft.profile, draft.period, prefix, field, attached_blocks=blocks,
        included_source_ids=used_source_ids(replace(draft, blocks=tuple(blocks.values()))))
    draft = replace(draft, sources=keep_missing(prefix, sources))
    if additions:
        previous_blocks = blocks
        draft, blocks = apply_prepared(draft, blocks, additions, incoming_specs, prefix)
        # A failed/partial preparation cannot close its recovery controls.
        # The atomic merger returns the original mapping on failure and a
        # separate proposed mapping on success, including an idempotent Add.
        # Only a fully resolved canonical result may retire the repeated Add
        # controls, and the full editor reruns after draft/recovery commit.
        updated = _statuses(draft, blocks, prefix)
        if blocks is not previous_blocks and updated and all(item.resolved for item in updated):
            st.session_state[manager_key] = False
            st.session_state[prefix + "_period_editor_refresh"] = True
    if st.session_state.pop(manager_key + "_close_request", False):
        # Read native values delivered with Done before retiring the controls.
        # The next frame closes only after the ordinary draft/recovery commit.
        st.session_state[manager_key] = False
        st.session_state[prefix + "_period_editor_refresh"] = True
    return draft, blocks


def _close_manager(manager_key):
    st.session_state[manager_key + "_close_request"] = True
