"""Hospital training: local validation preserves independent monthly edits."""
from dataclasses import replace

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_editor import _grid, _signature
from app.monthly_report_model import ReportTable
from app.monthly_report_training import (FORMATS, MATRIX_REF, STATUSES,
    add_event, apply_tables, events_for_period, load_training, save_training, seed_matrix,
    training_block, hospital_matrix, matrix_differs_from_current_standing)


def render_training(draft, blocks, prefix, field):
    from app.monthly_report_directory import load_directory
    if not draft.prepared_by.strip():
        st.info("Enter your name above to view or edit saved team training.")
        return blocks
    block = training_block(blocks)
    original_block = block
    key = prefix + "_training_" + _signature((draft.profile.contract, tuple(f.key for f in draft.profile.facilities), draft.period.key))
    had_conflict = bool(st.session_state.get(key + "_conflict"))
    if had_conflict:
        blocks = _reload_matrix(draft, blocks, block, key)
        block = training_block(blocks)
    matrix = None
    try:
        store_key = key + "_saved"
        if store_key not in st.session_state:
            st.session_state[store_key] = load_training(draft.profile.contract)
        stored = st.session_state[store_key]
        directory = load_directory(draft.profile.contract)
        matrix = seed_matrix(draft.profile, block, stored, directory)
        matrix_key = key + "_matrix_draft"
        if matrix_key not in st.session_state:
            st.session_state[matrix_key] = matrix
            st.session_state[key + "_stale_standing"] = matrix_differs_from_current_standing(
                draft.profile, block, stored, directory)
        previous = st.session_state[matrix_key]
        matrix = hospital_matrix(draft.profile, previous, directory)
        if matrix != previous:
            st.session_state[matrix_key] = matrix
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
        st.subheader("Staff training requirements")
        st.caption("Client/hospital staff only. Requirement changes are saved for these sites and reused in future reports; sessions and notes stay in this report.")
        if st.session_state.get(key + "_stale_standing"):
            st.warning("This report has an older training matrix. Review the latest shared training before changing the matrix. "
                       "Monthly notes and the saved report version are unchanged.")
        with st.expander("Add requirement", expanded=False):
            new_training = st.text_input("Requirement name", key=key + "_new_requirement")
            if st.button("Add requirement", key=key + "_add_requirement", disabled=not new_training.strip()):
                title = new_training.strip()
                if title.casefold() in {c.casefold() for c in matrix.columns}:
                    st.error("That training already has a column.")
                else:
                    proposed = replace(matrix, columns=(*matrix.columns, title), rows=tuple((*r, "Not recorded") for r in matrix.rows))
                    if st.session_state.get(key + "_stale_standing"):
                        raise library.RevisionConflict("Shared training has newer information. Reload saved training before editing its matrix.")
                    stored = save_training(draft.profile, proposed, expected_revision=stored["revision"], actor=draft.prepared_by)
                    matrix = proposed
                    st.session_state[store_key] = stored
                    st.session_state[matrix_key] = matrix
        sites = [facility.title for facility in draft.profile.facilities]
        config = {"Site": st.column_config.SelectboxColumn("Site", options=sites, required=True)}
        labels = {"": "— Not recorded (blank)", "Completed": "🟢 Completed", "Pending": "🟠 Pending", "Not required": "⚪ Not required", "Not recorded": "— Not recorded"}
        config.update({name: st.column_config.SelectboxColumn(name, options=STATUSES, format_func=labels.get, required=True, default="Not recorded") for name in matrix.columns[2:]})
        rows = _grid(key + "_grid_" + str(st.session_state.get(key + "_generation", 0)) + "_" + _signature(matrix.columns), [dict(zip(matrix.columns, row)) for row in matrix.rows] or [dict.fromkeys(matrix.columns, "")],
                     num_rows="dynamic", hide_index=True, column_config=config)
        # Defaults apply to absent new cells; an existing/explicit blank remains
        # distinct from the recorded "Not recorded" option and is never saved
        # merely because the matrix was displayed.
        edited = ReportTable(matrix.columns, tuple(tuple(str(row.get(c, "Not recorded" if i > 1 else "") or "").strip()
                              for i, c in enumerate(matrix.columns)) for row in rows if row.get("Team member")), MATRIX_REF)
        if hospital_matrix(draft.profile, edited, directory) != edited:
            raise ValueError("This matrix is for hospital staff. Remove the identified ENFRA, asset-management or vendor person before saving.")
        if edited != matrix:
            if st.session_state.get(key + "_stale_standing"):
                raise library.RevisionConflict("Shared training has newer information. Reload saved training before editing its matrix.")
            stored = save_training(draft.profile, edited, expected_revision=stored["revision"], actor=draft.prepared_by)
            st.session_state[store_key] = stored
            st.session_state[matrix_key] = edited
            matrix = edited
    except library.RevisionConflict as exc:
        st.session_state[key + "_conflict"] = str(exc)
        st.error(str(exc))
        if not had_conflict:
            blocks = _reload_matrix(draft, blocks, block, key)
    except (ValueError, OSError) as exc:
        st.error(str(exc))

    # Always render monthly fields. A rejected matrix/event must not let
    # Streamlit discard a sibling widget or its in-flight value.
    events = events_for_period(block, draft.period)
    st.subheader("Training completed this month")
    with st.expander("Add training session", expanded=False):
        with st.form(key + "_event_form", clear_on_submit=False):
            title = st.text_input("Training topic", key=key + "_event_topic")
            when = st.date_input("Training date", value=None, min_value=draft.period.start, max_value=draft.period.end, key=key + "_event_date")
            mode = st.selectbox("Method", FORMATS, key=key + "_event_format")
            participants = st.multiselect("Participants", list(dict.fromkeys(r[0] for r in (matrix.rows if matrix is not None else ()))), accept_new_options=True, key=key + "_event_participants")
            hours = st.text_input("Hours (optional)", key=key + "_event_hours")
            submit = st.form_submit_button("Add training session")
    if submit:
        try:
            events = add_event(events, title=title, when=when, mode=mode, participants=participants, hours=hours, period=draft.period)
        except ValueError as exc:
            st.error(str(exc))
    if events and events.rows:
        removed = set()
        # Binding every row action to this collection prevents a delayed click
        # from removing a different row after another session was added/removed.
        event_revision = _signature(events.rows)
        for index, row in enumerate(events.rows):
            title, when, mode, participants, hours = row
            slot = st.empty()
            with slot.container(border=True):
                st.text(title)
                st.caption(" · ".join((when, mode, participants, *([f"{hours} hours"] if hours else []))))
                if st.button(f"Remove session: {title} · {when}",
                             key=key + f"_remove_session_{event_revision}_{index}"):
                    removed.add(index)
                    slot.empty()
        if removed:
            events = replace(events, rows=tuple(row for index, row in enumerate(events.rows) if index not in removed))
            if not events.rows:
                st.caption("No training sessions added this month.")
    else:
        st.caption("No training sessions added this month.")
    block = apply_tables(block, matrix, events)
    # Match the native protocol default to the canonical notes, as Activity
    # already does. A one-shot session-state set_value is not the first-mount
    # default and can otherwise be echoed back as an unintended empty edit.
    # The pinned keyed textarea retains its ID and accepts deliberate clears.
    notes = st.text_area("Training notes", value=block.text,
                         key=field(key + "_notes_" + _signature(block.references), block.text), height=120)
    if notes != block.text:
        block = replace(block, text=notes, source="This month", reviewed_fingerprint="", client_reviewed_fingerprint="")
    if block != original_block or block.key in blocks:
        blocks = dict(blocks)
        blocks[block.key] = block
    return blocks


def _reload_matrix(draft, blocks, block, key):
    from app.monthly_report_directory import load_directory
    st.caption("Reload replaces only this training matrix with the latest saved version. Your monthly training entries, notes and photos stay in this report.")
    if st.button("Reload saved training matrix", key=key + "_reload"):
        try:
            latest = load_training(draft.profile.contract)
            without_matrix = replace(block, extra_tables=tuple(t for t in block.extra_tables if t.reference != MATRIX_REF))
            refreshed = seed_matrix(draft.profile, without_matrix, latest, load_directory(draft.profile.contract))
            st.session_state[key + "_saved"] = latest
            st.session_state[key + "_matrix_draft"] = refreshed
            st.session_state[key + "_stale_standing"] = False
            st.session_state[key + "_generation"] = st.session_state.get(key + "_generation", 0) + 1
            st.session_state.pop(key + "_conflict", None)
            blocks = dict(blocks)
            blocks[block.key] = apply_tables(block, refreshed, events_for_period(block, draft.period))
            st.success("Latest saved training matrix loaded.")
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    return blocks
