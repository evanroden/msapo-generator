"""Native row editors for proposal decisions and ENFRA onsite work.

Rows retain their original schema and source references. A callback captures
the delivered fields and exactly one table-bound action before rendering;
display changes alone cannot change the report.
"""
from dataclasses import replace
from datetime import date
from html import escape
from functools import partial
import re
from uuid import uuid4

import streamlit as st

from app.monthly_report_editor import _cell_text, _signature


CARD_TABLES = {"proposals": ("proposal", "Add proposal"),
               "service_calls": ("onsite call", "Add onsite call"),
               "rfi_matrix": ("request", "Add request")}


def _values(fields):
    return tuple(original if st.session_state.get(key, default) == default else
                 _cell_text(st.session_state.get(key, default))
                 for key, original, kind, default in fields)


def _queue(key, expected, tokens, active, fields, action="edit", target=None):
    """One delivered native action includes the currently open row's text."""
    record = dict(st.session_state.get(key, {}))
    rows, identities = list(expected), list(tokens)
    draft_token = record.get("draft_token")
    draft_index = record.get("draft_index", len(rows))
    changed_fields = False
    if active and fields:
        values = _values(fields)
        if active in identities:
            index = identities.index(active)
            changed_fields = values != rows[index]
            if any(value is not None and str(value).strip() for value in values):
                rows[index] = values
            else:
                del rows[index]
                del identities[index]
                draft_token, draft_index = active, index
        elif active == draft_token and any(value is not None and str(value).strip() for value in values):
            index = min(draft_index, len(rows))
            rows.insert(index, values)
            identities.insert(index, active)
            draft_token = None
            changed_fields = True
    if action == "edit" or changed_fields or action in {"add", "remove"}:
        record.pop("undo", None)
    removed_version = None
    if action == "undo":
        undo = record.get("undo")
        if undo and undo["result"] == expected:
            rows, identities = list(undo["rows"]), list(undo["tokens"])
            active, draft_token = None, None
        record.pop("undo", None)
    elif action == "open":
        active = target if target in identities else None
    elif action == "add":
        draft_token = draft_token or uuid4().hex
        draft_index = len(rows)
        active = draft_token
        record["entry_focus"] = {"token": uuid4().hex, "row": active}
    elif action == "close":
        if active == draft_token:
            draft_token = None
        active = None
    elif action == "remove" and target in identities:
        if record.get("allow_undo"):
            removed_version = (tuple(rows), tuple(identities))
        index = identities.index(target)
        del rows[index]
        del identities[index]
        if active == target:
            active = None
    elif action == "remove" and target == draft_token:
        active, draft_token = None, None
    if action != "add":
        record.pop("entry_focus", None)
    if changed_fields:
        retained = [(row, token) for row, token in zip(rows, identities)
                    if any(value is not None and str(value).strip() for value in row)]
        rows, identities = [row for row, _ in retained], [token for _, token in retained]
    if removed_version is not None:
        record["undo"] = {"rows": removed_version[0], "tokens": removed_version[1], "result": tuple(rows)}
    # Consecutive callbacks may arrive before the parent commits. Collapse
    # only an exact acknowledged result, never an unrelated current table.
    previous = record.get("pending")
    baseline = (previous["baseline"] if previous and previous["result"] == expected else expected)
    record["pending"] = {"baseline": baseline, "expected": expected, "result": tuple(rows), "tokens": tuple(identities),
                         "active": active, "draft_token": draft_token, "draft_index": draft_index}
    st.session_state[key] = record


def _choose_conflict(key, expected, result, tokens):
    record = dict(st.session_state[key])
    record["pending"] = {"baseline": expected, "expected": expected, "result": result, "tokens": tokens,
                         "active": None, "draft_token": None, "draft_index": len(result)}
    st.session_state[key] = record


def _queue_in_group(group, key, expected, tokens, active, fields, action="edit", target=None):
    """Keep one active row in this block without losing another table's input.

    The previous table keeps its own rendered snapshot and pending result.
    Its ordinary conflict comparison still decides whether that edit applies;
    switching rows never rebinds a stale table to a newer canonical revision.
    """
    record = st.session_state.get(key, {})
    if record.get("group") != group:
        return
    selection = dict(st.session_state.get(group, {}))
    previous_key = selection.get("active_table")
    switching = action == "add" or action == "open" and target in tokens
    if previous_key and previous_key != key and (switching or action in {"remove", "undo"}):
        previous = st.session_state.get(previous_key, {})
        rendered = previous.get("rendered")
        if previous.get("group") == group and rendered and rendered[0] == previous_key:
            prior_rows, prior_tokens, prior_active, prior_fields = rendered[1:]
            original = (prior_rows[prior_tokens.index(prior_active)] if prior_active in prior_tokens
                        else tuple("" for _ in prior_fields))
            if switching or prior_fields and _values(prior_fields) != original:
                _queue(*rendered, "close" if switching else "edit")
    _queue(key, expected, tokens, active, fields, action, target)
    record = dict(st.session_state[key])
    pending = dict(record["pending"])
    if switching:
        selection["active_table"] = key if pending["active"] else None
    elif previous_key == key and not pending["active"]:
        selection["active_table"] = None
    elif previous_key != key and pending["active"]:
        # An old field's on_change can follow the other table's Open callback
        # in the same delivery. Keep its text, but do not reopen its editor.
        pending["active"] = None
        if pending["draft_token"] not in pending["tokens"]:
            pending["draft_token"] = None
        record["pending"] = pending
        st.session_state[key] = record
    st.session_state[group] = selection


def _sync_tokens(previous_rows, previous_tokens, rows):
    """Match unchanged row occurrences; never identify a row by its title alone."""
    unused = list(zip(previous_rows, previous_tokens))
    result = []
    for row in rows:
        match = next((index for index, (old, _) in enumerate(unused) if old == row), None)
        result.append(unused.pop(match)[1] if match is not None else uuid4().hex)
    return tuple(result)


def _field_default(value, kind):
    try:
        if kind == "date":
            return date.fromisoformat(value) if value else None
        if kind in {"number", "currency"}:
            return float(value) if value else None
    except (TypeError, ValueError):
        pass  # Keep a recorded unknown value as editable text.
    return value


def _request_content_columns(columns):
    """Recognize whole content headings without relabeling imported metadata."""
    headings = {"requested item", "requested items", "requested details", "question", "questions"}
    return tuple(index for index, column in enumerate(columns)
                 if " ".join(column.casefold().split()).removesuffix(":").strip() in headings)


def _summary(columns, row, noun, index):
    values = tuple((column, row[n] if n < len(row) else "") for n, column in enumerate(columns))
    if noun == "request":
        main = next((values[n][1] for n in _request_content_columns(columns) if values[n][1]), "")
    else:
        main = next((value for column, value in values if value and any(
            word in column.casefold() for word in ("description", "scope", "title", "task", "recommendation", "requested", "question"))), "")
    st.write(main or f"{noun.capitalize()} {index + 1}")
    identifiers = [(column, value) for column, value in values if value and (any(
        word in column.casefold() for word in ("number", "#", "identifier", "facility", "site", "vendor", "area", "asset"))
        or column.casefold() == "id" or column.casefold().endswith(" id"))]
    if identifiers:
        st.caption(" · ".join(f"{column}: {value}" for column, value in identifiers))
    decisions = [(column, value) for column, value in values if any(
        word in column.casefold() for word in ("status", "decision"))]
    if decisions:
        st.caption(" · ".join(f"{column}: {value or 'Not recorded'}" for column, value in decisions))


def _comparison_rows(columns, rows):
    # Duplicate source headings remain separate fields in the comparison.
    # These display-only labels never replace the exported original schema.
    names = tuple(column if column.strip() else f"Detail {index + 1}"
                  for index, column in enumerate(columns))
    labels = tuple(f"{index + 1}. {name}" if names.count(name) > 1 else name
                   for index, name in enumerate(names))
    return [dict(zip(labels, row)) for row in rows]


def _finish_row(key):
    """Retire this row's replaced elements when its native render is complete.

    Streamlit 1.61.1 otherwise retains the former row's stale fields until the
    entire report finishes rendering. Closing onsite work can then move an
    already-visible proposal button between pointer down and up. Only direct
    stale children of this one keyed row are hidden, and only after the last
    current row element arrives. Active fields keep their original native
    nodes; there is no scroll change, event replay or script-state shortcut.

    Remove this compatibility rule when a pinned Streamlit upgrade retires
    replaced row children before later native actions become available, with
    the rapid Close/Edit WebKit journey and active-field continuity passing.
    """
    if st.__version__ != "1.61.1":
        return
    selector = ".st-key-" + re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())
    child = ' > [data-testid="stElementContainer"]'
    marker = '[data-enfra-row-finished]'
    current = child + '[data-stale="false"] ' + marker
    st.html('<span hidden data-enfra-row-finished="true"></span><style>'
            + selector + ':has(' + current + ')' + child
            + '[data-stale="true"]{display:none;}'
            + selector + child + ':has(' + marker + '){display:none;}'
            + '</style>')


def _edit_table(columns, rows, types, key, noun, add_label, field, *, summary=None,
                labels=None, max_chars=None, scope_labels=None, allow_undo=False, empty_label=None,
                group=None, placeholders=None, focus_column=None, multiline_columns=()):
    record = dict(st.session_state.get(key, {}))
    record["allow_undo"] = allow_undo
    if group is not None:
        record["group"] = group
    pending = record.get("pending")
    incoming = tuple(tuple(row) for row in rows)
    # Labels describe the supplied canonical rows. A delivered add/remove can
    # change their positions before the parent commits; bind by row identity,
    # not the new positional index. Ambiguous copies remain report-scoped.
    row_scopes = {}
    if scope_labels:
        for row, scope in zip(incoming, scope_labels):
            row_scopes[row] = scope if incoming.count(row) == 1 else "This report only"
    rows = incoming
    if pending and incoming in (pending["baseline"], pending["expected"], pending["result"]):
        rows = pending["result"]
        record.update(rows=rows, tokens=pending["tokens"], active=pending["active"],
                      draft_token=pending["draft_token"], draft_index=pending["draft_index"])
        if incoming == pending["result"]:
            record.pop("pending", None)
    elif pending:
        st.warning("This table changed after you edited a row. Both versions are kept below.")
        with st.expander("Compare row edits", expanded=True):
            st.caption("Current report")
            st.dataframe(_comparison_rows(columns, incoming), hide_index=True)
            st.caption("Your pending row edits")
            st.dataframe(_comparison_rows(columns, pending["result"]), hide_index=True)
            st.caption("Use row edits replaces this table with the pending version. Keep current table discards those pending row edits.")
            identity = _signature((incoming, pending["result"]))
            st.button("Use row edits", key=key + "_use_" + identity,
                      on_click=_choose_conflict, args=(key, incoming, pending["result"], pending["tokens"]))
            st.button("Keep current table", key=key + "_keep_" + identity,
                      on_click=_choose_conflict, args=(key, incoming, incoming, tuple(uuid4().hex for _ in incoming)))
        return incoming
    elif record.get("rows") != incoming:
        record["tokens"] = _sync_tokens(record.get("rows", ()), record.get("tokens", ()), incoming)
        record["rows"] = incoming
        if record.get("active") not in record["tokens"]:
            record["active"] = None
    tokens = record.setdefault("tokens", tuple(uuid4().hex for _ in rows))
    active = record.get("active")
    draft_token = record.get("draft_token")
    st.session_state[key] = record

    if empty_label:
        with st.container(key=key + "_empty_state"):
            if not rows and not active:
                st.caption(empty_label)

    active_values = (rows[tokens.index(active)] if active in tokens else
                     tuple("" for _ in columns) if active and active == draft_token else ())
    input_kinds = dict(record.get("input_kinds", {}))
    if active and active not in input_kinds:
        input_kinds[active] = tuple(
            kind if (kind == "date" and (isinstance(default, date) or default is None)
                     or kind in {"number", "currency"} and (isinstance(default, float) or default is None))
            else "text"
            for kind, default in ((types[index] if index < len(types) else "text",
                                   _field_default(active_values[index] if index < len(active_values) else "",
                                                  types[index] if index < len(types) else "text"))
                                  for index in range(len(columns))))
        record["input_kinds"] = input_kinds
        st.session_state[key] = record
    kinds = input_kinds.get(active, ())
    fields = tuple((key + "_" + active + "_field_" + str(index),
                    active_values[index] if index < len(active_values) else "",
                    kinds[index],
                    _field_default(active_values[index] if index < len(active_values) else "",
                                   kinds[index]))
                   for index in range(len(columns))) if active else ()
    args = (key, rows, tokens, active, fields)
    callback = partial(_queue_in_group, group) if group is not None else _queue
    if group is not None:
        record["rendered"] = args
        selection = dict(st.session_state.get(group, {}))
        if active and not selection.get("active_table"):
            # An explicitly created first blank contact row starts active.
            selection["active_table"] = key
        st.session_state[group] = selection
        st.session_state[key] = record
    entries = list(zip(tokens, rows))
    if active and active == draft_token:
        entries.insert(min(record.get("draft_index", len(entries)), len(entries)),
                       (active, tuple("" for _ in columns)))
    for index, (token, row) in enumerate(entries):
        if token != active and not any(value is not None and str(value).strip() for value in row):
            continue
        card_key = key + "_card_" + token
        with st.container(key=card_key, border=True):
            if token == active:
                # Live summaries would grow/move the native fields as the
                # first identifier or a long title is entered. Keep this
                # active heading the same height until explicit closure.
                st.write("Edit " + noun)
                if scope_labels is not None:
                    st.caption(row_scopes.get(row, "This report only"))
                _render_fields(columns, fields, args, field, labels=labels, max_chars=max_chars,
                               callback=callback, placeholders=placeholders, multiline_columns=multiline_columns)
                focus = record.get("entry_focus", {})
                if focus_column is not None and focus.get("row") == token:
                    st.html('<span hidden data-epc-entry-focus="' + escape(focus["token"], quote=True)
                            + '" data-epc-field-key="' + escape(fields[focus_column][0], quote=True)
                            + '" data-epc-origin-key="' + escape(key + "_add", quote=True) + '"></span>')
                st.button("Close editing", key=key + "_close_" + token, on_click=callback, args=(*args, "close"))
            else:
                (summary or _summary)(columns, row, noun, index)
                st.button("Edit " + noun, key=key + "_open_" + token,
                          on_click=callback, args=(*args, "open", token))
            if token != draft_token:
                st.button("Remove " + noun, key=key + "_remove_" + token,
                          help="Removes only this row from this report; source files and saved versions remain.",
                          on_click=callback, args=(*args, "remove", token))
            _finish_row(card_key)
    undo = record.get("undo")
    if allow_undo and undo and undo["result"] == rows:
        st.button("Undo remove " + noun, key=key + "_undo", on_click=callback, args=(*args, "undo"))
    if focus_column is not None:
        # This inert marker identifies only this native Add action. The client
        # consumes a later focus nonce only after observing its trusted click;
        # a restored draft or a layout change cannot request focus on its own.
        with st.container(key=key + "_entry_action"):
            selector = ".st-key-" + re.sub(r"[^a-zA-Z0-9_-]", "-", (key + "_entry_action").strip())
            st.html('<span hidden data-epc-entry-origin="' + escape(key + "_add", quote=True) + '"></span><style>'
                    + selector + ' > [data-testid="stElementContainer"]:has([data-epc-entry-origin]){display:none;}'
                    + '</style>')
            st.button(add_label, key=key + "_add", on_click=callback, args=(*args, "add"),
                      disabled=bool(active and active == draft_token))
    else:
        st.button(add_label, key=key + "_add", on_click=callback, args=(*args, "add"),
                  disabled=bool(active and active == draft_token))
    return rows


def _render_fields(columns, fields, args, field, *, labels=None, max_chars=None,
                   callback=_queue, placeholders=None, multiline_columns=()):
    for index, (title, (key, original, kind, default)) in enumerate(zip(columns, fields)):
        label = (labels or {}).get(title, title) or f"Detail {index + 1}"
        if not label.strip():
            label = f"Detail {index + 1}"
        options = dict(key=field(key, default), value=default, on_change=callback, args=args)
        placeholder = (placeholders or {}).get(index)
        if placeholder and kind == "text":
            options["placeholder"] = placeholder
        if kind == "date" and (isinstance(default, date) or default is None):
            st.date_input(label, format="YYYY-MM-DD", **options)
        elif kind in {"number", "currency"} and (isinstance(default, float) or default is None):
            st.number_input(label, **options)
        elif index in multiline_columns or any(word in title.casefold() for word in ("description", "scope", "notes", "recommendation")):
            st.text_area(label, height=100, max_chars=max_chars, **options)
        else:
            st.text_input(label, max_chars=max_chars, **options)


def edit_row_cards(spec, block, prefix, field):
    from app.monthly_report_content_policy import ambiguous_price_columns
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_table_review_ui import review_table_headings
    noun, add_label = CARD_TABLES[spec.key]
    context = (spec.key, _rich_text_scope(prefix), block.references,
               tuple(table.reference for table in block.extra_tables), spec.columns)
    key = prefix + "_row_cards_" + _signature(context)
    request_notice = st.container(key=key + "_empty_state") if spec.key == "rfi_matrix" else None
    def entry_options(columns):
        if spec.key != "rfi_matrix":
            return {}
        content_columns = _request_content_columns(columns)
        request_column = content_columns[0] if len(content_columns) == 1 else None
        # Source schemas keep their own labels and ordering. Focus a recognized
        # content field only when unambiguous; author, date and identifier
        # headings are metadata, even when they include Requested or Question.
        return {"placeholders": {request_column: "What information is needed?"} if request_column is not None else {},
                "focus_column": request_column,
                "multiline_columns": content_columns,
                "group": key + "_request_group"}
    tables = []
    for index, table in enumerate(block.extra_tables):
        if len(block.extra_tables) > 1:
            st.write(f"Table {index + 1}")
        table_key = key + "_extra_" + str(index) + "_" + _signature(table.columns)
        record = st.session_state.get(table_key, {})
        if ambiguous_price_columns(table.columns, table.rows) and not record.get("active"):
            # Resolve imported headings before mounting a row editor. An
            # already-open row retains its native fields and pending text
            # until Close, so a heading correction cannot reshape that row
            # in the same event. Price validation remains in force.
            tables.append(review_table_headings(table, key + "_headings_" + str(index), field))
            continue
        edited = _edit_table(table.columns, table.rows, (), table_key, noun, add_label, field,
                             **entry_options(table.columns))
        tables.append(replace(table, rows=edited) if edited != table.rows else table)
    rows = block.rows
    if rows or not block.extra_tables:
        columns = tuple(column.title for column in spec.columns) or ("Facility", "Item", "Status")
        rows = _edit_table(columns, rows, tuple(column.type for column in spec.columns), key + "_rows", noun, add_label, field,
                          **entry_options(columns))
    if request_notice is not None:
        from app.monthly_report_table_entry_ui import has_values
        active_entry = any(isinstance(value, dict) and value.get("active")
                           for name, value in st.session_state.items() if name.startswith(key))
        if (not active_entry and not any(has_values(values) for values in (rows, *(table.rows for table in tables)))
                and not (block.text.strip() or block.asset_hashes or block.ai_paragraphs)):
            request_notice.caption("No requests added.")
    if rows == block.rows and tuple(tables) == block.extra_tables:
        return block
    return replace(block, source="This month", rows=rows, extra_tables=tuple(tables),
                   reviewed_fingerprint="", client_reviewed_fingerprint="")
