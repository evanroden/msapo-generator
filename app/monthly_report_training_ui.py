"""Hospital training: local validation preserves independent monthly edits."""
from dataclasses import replace
from datetime import date
import math
from uuid import uuid4

import streamlit as st

from app import monthly_report_library as library
from app.monthly_report_editor import _grid, _signature
from app.monthly_report_model import ReportTable
from app.monthly_report_training import (EVENT_COLUMNS, FORMATS, MATRIX_REF, STATUSES,
    add_event, apply_tables, events_for_period, load_training, save_training, seed_matrix,
    training_block, hospital_matrix, matrix_differs_from_current_standing,
    session_row_tokens, remove_event, replace_event)


def _queue_session_removal(key, revision, index, scope):
    st.session_state[key] = (revision, index, scope)



def _queue_session_action(key, action):
    st.session_state[key] = action


def _queue_session_submit(key, scope, token, revision, index, fields, kind="submit"):
    st.session_state[key] = {"kind": kind, "scope": scope, "token": token,
        "revision": revision, "index": index,
        "values": {name: st.session_state.get(widget) for name, widget in fields.items()}}


def _session_errors(values, period):
    errors = {}
    if not str(values.get("title") or "").strip():
        errors["title"] = "Enter a topic"
    when = values.get("when")
    if not isinstance(when, date) or not period.start <= when <= period.end:
        errors["when"] = f"Choose a date in {period.label}"
    if values.get("mode") not in FORMATS:
        errors["mode"] = "Choose a method"
    if not values.get("participants"):
        errors["participants"] = "Choose at least one participant"
    hours = str(values.get("hours") or "").strip()
    if hours:
        try:
            number = float(hours)
            if not math.isfinite(number) or number <= 0:
                raise ValueError
        except ValueError:
            errors["hours"] = "Enter positive hours, or leave blank if unknown"
    return errors


def _new_session_editor(scope, *, editing=None, seed=None):
    return {"scope": scope, "token": uuid4().hex, "editing": editing, "seed": seed}


def _sessions_revision(events):
    # apply_tables omits a genuinely empty session table. Its acknowledged
    # removal and that canonical absence are the same collection state.
    return (_signature((events.columns, events.rows, session_row_tokens(events)))
            if events and events.rows else _signature(()))


def _edited_session_index(editing, events):
    """Rebase only the unchanged row snapshot, never a coincident position."""
    if (not isinstance(editing, dict) or events is None
            or events.columns != editing.get("columns")):
        return None
    tokens = session_row_tokens(events)
    token = editing.get("row_token")
    if token not in tokens:
        return None
    index = tokens.index(token)
    return index if events.rows[index] == editing.get("row") else None


def _session_description(row):
    title, when, mode, participants, hours = row
    try:
        singular = float(hours) == 1
    except (ValueError, TypeError):
        singular = False
    duration = f"{hours} {'hour' if singular else 'hours'}" if hours else ""
    return " · ".join((when, mode, participants, *([duration] if duration else [])))


def _selected_participants(value, names):
    """Recover roster identities without inventing a split in legacy text.

    Saved rows contain a display string, not an escaped participant array.
    An exact roster name wins, including names containing the separator.
    Otherwise use a unique complete roster match; ambiguous or unlisted
    text stays intact as an editable option instead of becoming new people.
    """
    if not value:
        return []
    if value in names:
        return [value]
    separator = "; "
    starts = [0, *(index + 2 for index in range(len(value)) if value.startswith(separator, index))]
    paths = {len(value): [()]}
    for start in reversed(starts):
        candidates = []
        for name in dict.fromkeys(names):
            if not name or not value.startswith(name, start):
                continue
            end = start + len(name)
            if end != len(value) and not value.startswith(separator, end):
                continue
            tail = end if end == len(value) else end + len(separator)
            candidates.extend((name, *rest) for rest in paths.get(tail, ()))
            if len(candidates) > 1:
                break
        paths[start] = candidates[:2]
    matches = paths.get(0, ())
    return list(matches[0]) if len(matches) == 1 else [value]


def _render_monthly_sessions(events, matrix, period, key, scope):
    """One buffered entry form; consume revision-bound actions before mounting it."""
    state_key, request_key = key + "_session_editor", key + "_session_action"
    state = st.session_state.get(state_key)
    if not isinstance(state, dict) or state.get("scope") != scope:
        state = _new_session_editor(scope)
    rows = events.rows if events else ()
    canonical_revision = _sessions_revision(events)
    pending_key = key + "_pending_sessions"
    pending = st.session_state.get(pending_key)
    blocked = False
    if isinstance(pending, dict) and pending.get("scope") == scope:
        proposed = pending["events"]
        proposed_rows = proposed.rows if proposed else ()
        if _sessions_revision(proposed) == canonical_revision:
            st.session_state.pop(pending_key, None)
        elif pending.get("baseline") == canonical_revision:
            events, rows = proposed, proposed_rows
        else:
            st.warning("An earlier training change was interrupted by newer sessions. Both versions are kept for review.")
            with st.expander("Review pending training changes", expanded=True):
                st.caption("Current sessions in this report")
                st.table([dict(zip(("Topic", "Date", "Method", "Participants", "Hours"), row)) for row in rows])
                st.caption("Pending sessions from your earlier change")
                st.table([dict(zip(("Topic", "Date", "Method", "Participants", "Hours"), row)) for row in proposed_rows])
                choice_key = key + "_pending_choice_" + _signature((scope, canonical_revision, proposed_rows))
                if st.button("Use pending sessions", key=choice_key + "_apply",
                             help="Replace this report's current session list with the pending list shown above. Shared requirements and notes stay unchanged."):
                    events, rows = proposed, proposed_rows
                elif st.button("Keep current sessions", key=choice_key + "_keep"):
                    st.session_state.pop(pending_key, None)
                else:
                    blocked = True
    removal = st.session_state.pop(key + "_remove_session_request", None)
    if removal is not None:
        revision, index, removal_scope = removal if len(removal) == 3 else (*removal, None)
        if (not blocked and events and removal_scope == scope
                and revision == _sessions_revision(events) and 0 <= index < len(events.rows)):
            events = remove_event(events, index)
            rows = events.rows
        else:
            st.warning("Training sessions changed. Review the current sessions before removing one.")
    revision = _sessions_revision(events)
    errors, outcome = {}, None
    request = st.session_state.pop(request_key, None)
    if not blocked and isinstance(request, dict) and request.get("scope") == scope:
        kind = request.get("kind")
        if kind == "cancel" and request.get("token") == state["token"]:
            state = _new_session_editor(scope)
        elif kind == "edit":
            index = request.get("index", -1)
            if request.get("revision") == revision and 0 <= index < len(rows):
                state = _new_session_editor(scope, editing={"revision": revision, "index": index,
                    "row_token": session_row_tokens(events)[index], "row": rows[index],
                    "columns": events.columns}, seed=rows[index])
            else:
                st.warning("Training sessions changed. Choose the current session to edit.")
        elif kind in {"submit", "submit_new"} and request.get("token") == state["token"]:
            values = request["values"]
            errors = _session_errors(values, period)
            editing = state.get("editing")
            index = _edited_session_index(editing, events) if editing else None
            valid = (index is not None and request.get("revision") == editing.get("revision")
                     and request.get("index") == editing.get("index")) if isinstance(editing, dict) else (
                not editing and request.get("revision") == revision and request.get("index") is None)
            if kind == "submit_new":
                # This distinct native form submission is an explicit new row,
                # not an automatic resurrection or rebind of the old editor.
                valid = bool(editing and index is None and request.get("index") is None
                             and request.get("revision") == revision
                             and (events is None or events.columns == EVENT_COLUMNS))
            if not valid:
                st.warning("Training sessions changed. Your entered details are kept. Review the current sessions before saving.")
            elif not errors:
                proposed = add_event(None, period=period, **values)
                row = proposed.rows[0]
                if index is None:
                    events = add_event(events, period=period, **values)
                    outcome = (row, "Training added to this report." if row not in rows else "This session is already in this report.")
                elif not 0 <= index < len(rows):
                    st.warning("Training sessions changed. Your entered details are kept.")
                elif row in rows[:index] + rows[index + 1:]:
                    errors["title"] = "This session is already in this report"
                else:
                    events = replace_event(events, index, row)
                    outcome = (row, "Training session updated.")
                if outcome:
                    state = _new_session_editor(scope)
    st.session_state[state_key] = state
    rows = events.rows if events else ()
    revision = _sessions_revision(events)
    editing = state["editing"]
    seed = state["seed"] or ("", "", FORMATS[0], "", "")
    editor_key = key + "_event_" + state["token"]
    fields = {name: editor_key + "_" + name for name in ("title", "when", "mode", "participants", "hours")}
    st.subheader("Training completed this month")
    label = "Edit training session" if editing else "Add completed training"
    # A successful operation creates a fresh closed disclosure and blank form.
    # Invalid input keeps the same native fields and their delivered values.
    with st.expander(label, expanded=bool(editing or errors), key=editor_key + "_disclosure"):
        with st.form(editor_key + "_form", clear_on_submit=False):
            st.text_input("Training topic", value=seed[0], key=fields["title"])
            if errors.get("title"):
                st.error(errors["title"])
            st.date_input("Training date", value=date.fromisoformat(seed[1]) if seed[1] else None,
                          min_value=period.start, max_value=period.end, key=fields["when"])
            if errors.get("when"):
                st.error(errors["when"])
            st.selectbox("Method", FORMATS, index=FORMATS.index(seed[2]) if seed[2] in FORMATS else None, key=fields["mode"])
            if errors.get("mode"):
                st.error(errors["mode"])
            names = list(dict.fromkeys(r[0] for r in (matrix.rows if matrix is not None else ())))
            selected = _selected_participants(seed[3], names)
            st.multiselect("Participants", list(dict.fromkeys((*names, *selected))), default=selected,
                           accept_new_options=True, key=fields["participants"])
            if errors.get("participants"):
                st.error(errors["participants"])
            st.text_input("Hours (optional)", value=seed[4], key=fields["hours"])
            if errors.get("hours"):
                st.error(errors["hours"])
            st.form_submit_button("Save session" if editing else "Add completed training",
                disabled=blocked, on_click=_queue_session_submit,
                args=(request_key, scope, state["token"],
                      editing.get("revision") if isinstance(editing, dict) else revision,
                      editing.get("index") if isinstance(editing, dict) else None, fields))
            if editing and _edited_session_index(editing, events) is None:
                st.caption("The original session changed or was removed. Your entered details are kept. "
                           "Compare the current sessions below before choosing what to keep.")
                if events is None or events.columns == EVENT_COLUMNS:
                    st.form_submit_button("Add as new session", disabled=blocked,
                        help="Add the entered details as a separate session in this report. Existing sessions stay unchanged.",
                        on_click=_queue_session_submit,
                        args=(request_key, scope, state["token"], revision, None, fields, "submit_new"))
        if editing:
            st.button("Cancel editing", key=editor_key + "_cancel", on_click=_queue_session_action,
                      args=(request_key, {"kind": "cancel", "scope": scope, "token": state["token"]}))
    # Keep row action text short visually while retaining its complete native
    # accessible name. The second Markdown paragraph remains in the DOM.
    st.markdown('<style>div[class*="_training_session_action_"] button p + p{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}</style>', unsafe_allow_html=True)
    if rows:
        same_day = [(row[0], row[1]) for row in rows]
        action_revision = _signature((scope, revision))
        for index, row in enumerate(rows):
            title, when, mode, participants, hours = row
            with st.container(border=True):
                st.text(title)
                st.caption(_session_description(row))
                if outcome and outcome[0] == row:
                    st.success(outcome[1])
                detail = f"{title} · {when}"
                if same_day.count((title, when)) > 1:
                    detail += " · " + _session_description(row).split(" · ", 1)[1]
                edit_column, remove_column = st.columns(2)
                with edit_column:
                    st.button("Edit session\n\n" + detail,
                        key=key + f"_training_session_action_edit_{action_revision}_{index}",
                        disabled=blocked, on_click=_queue_session_action,
                        args=(request_key, {"kind": "edit", "scope": scope, "revision": revision, "index": index}))
                with remove_column:
                    st.button("Remove\n\nsession: " + detail,
                        key=key + f"_remove_session_{action_revision}_{index}_training_session_action_remove",
                        disabled=blocked, on_click=_queue_session_removal, args=(key + "_remove_session_request", revision, index, scope))
    else:
        st.caption("No training sessions added this month.")
    if not blocked:
        if _sessions_revision(events) != canonical_revision:
            # Rendering a successful action is not its final canonical commit.
            # Replay only this exact collection transition if a preview interrupts
            # the enclosing report render; acknowledge only the matching result.
            st.session_state[pending_key] = {"scope": scope, "baseline": canonical_revision, "events": events}
        else:
            st.session_state.pop(pending_key, None)
    return events

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
        st.caption("Requirements are shared for these sites and reused in future reports. Completed training and notes stay in this report.")
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
        rows = _grid(key + "_grid_" + str(st.session_state.get(key + "_generation", 0)) + "_" + _signature(matrix.columns), [dict(zip(matrix.columns, row)) for row in matrix.rows] or [{name: "Not recorded" if index > 1 else "" for index, name in enumerate(matrix.columns)}],
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
    from app.monthly_report_guided import _rich_text_scope
    scope = _rich_text_scope(prefix)
    events = events_for_period(block, draft.period)
    events = _render_monthly_sessions(events, matrix, draft.period, key, scope)
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
