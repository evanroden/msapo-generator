"""Quiet guided intake after exact included-page resolution; one original editor."""
from dataclasses import replace

import streamlit as st

from app.monthly_report_source_status import source_manager_status
from app.monthly_report_upload_ui import render_uploads


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
    """A disclosure changes visibility only; Add retains its atomic commit path."""
    from app.monthly_report_sections import readable_label

    manager_key = field(prefix + "_batch_files_open", False)
    selection_key = prefix + "_evidence_selected"
    states = _statuses(draft, blocks, prefix)
    ready = tuple(item for item in states if item.resolved)
    attention = tuple(item for item in states if not item.resolved)
    # Another explicit reader may finish earlier in this same ordered render.
    # Never retire an already-open native control merely because its source
    # just resolved: delivered input still belongs to the normal capture below.
    opened = bool(st.session_state[manager_key])

    if not opened and ready:
        with st.expander("Included files and pictures", expanded=False):
            for item in ready:
                destinations = ", ".join(readable_label(key) for key in item.destinations)
                st.caption(f"{item.filename} · {item.pages} {'page' if item.pages == 1 else 'pages'} · {destinations}")
            st.button("Change", key=prefix + "_change_included_sources",
                      on_click=_open_manager, args=(manager_key, selection_key, ready[0].source_id))
    if attention:
        with st.container(border=True):
            count = len(attention)
            st.markdown(f"**Source files to review ({count})**")
            for item in attention:
                st.caption(item.filename + " · " + item.reason)
            if not opened:
                st.button("Review source files", key=prefix + "_review_sources",
                          on_click=_open_manager,
                          args=(manager_key, selection_key, attention[0].source_id))
    if opened or not states:
        st.button("Done with source files" if opened else "Manage source files",
                  key=prefix + "_source_manager_" + str(opened),
                  on_click=_open_manager if not opened else _close_manager,
                  args=(manager_key, selection_key, "") if not opened else (manager_key,))
    if not opened:
        return draft, blocks

    sources, additions, incoming_specs = render_uploads(
        draft.profile, draft.period, prefix, field, attached_blocks=blocks)
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
