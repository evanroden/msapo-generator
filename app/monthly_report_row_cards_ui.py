"""Native row editors for proposal decisions and ENFRA onsite work.

Rows retain their original schema and source references. A callback captures
the delivered fields and exactly one table-bound action before rendering;
display changes alone cannot change the report.
"""
from dataclasses import replace
from datetime import date
from uuid import uuid4

import streamlit as st

from app.monthly_report_editor import _cell_text, _signature


CARD_TABLES = {"proposals": ("proposal", "Add proposal"),
               "service_calls": ("onsite call", "Add onsite call")}


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
    if action == "open":
        active = target if target in identities else None
    elif action == "add":
        draft_token = draft_token or uuid4().hex
        draft_index = len(rows)
        active = draft_token
    elif action == "close":
        if active == draft_token:
            draft_token = None
        active = None
    elif action == "remove" and target in identities:
        index = identities.index(target)
        del rows[index]
        del identities[index]
        if active == target:
            active = None
    elif action == "remove" and target == draft_token:
        active, draft_token = None, None
    if changed_fields:
        retained = [(row, token) for row, token in zip(rows, identities)
                    if any(value is not None and str(value).strip() for value in row)]
        rows, identities = [row for row, _ in retained], [token for _, token in retained]
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


def _summary(columns, row, noun, index):
    values = tuple((column, row[n] if n < len(row) else "") for n, column in enumerate(columns))
    main = next((value for column, value in values if value and any(
        word in column.casefold() for word in ("description", "scope", "title", "task", "recommendation"))), "")
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
    labels = tuple(f"{index + 1}. {column}" if columns.count(column) > 1 else column
                   for index, column in enumerate(columns))
    return [dict(zip(labels, row)) for row in rows]


def _edit_table(columns, rows, types, key, noun, add_label, field):
    record = dict(st.session_state.get(key, {}))
    pending = record.get("pending")
    incoming = tuple(tuple(row) for row in rows)
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
    entries = list(zip(tokens, rows))
    if active and active == draft_token:
        entries.insert(min(record.get("draft_index", len(entries)), len(entries)),
                       (active, tuple("" for _ in columns)))
    for index, (token, row) in enumerate(entries):
        if token != active and not any(value is not None and str(value).strip() for value in row):
            continue
        with st.container(key=key + "_card_" + token, border=True):
            if token == active:
                # Live summaries would grow/move the native fields as the
                # first identifier or a long title is entered. Keep this
                # active heading the same height until explicit closure.
                st.write("Edit " + noun)
                _render_fields(columns, fields, args, field)
                st.button("Close editing", key=key + "_close_" + token, on_click=_queue, args=(*args, "close"))
            else:
                _summary(columns, row, noun, index)
                st.button("Edit " + noun, key=key + "_open_" + token,
                          on_click=_queue, args=(*args, "open", token))
            if token != draft_token:
                st.button("Remove " + noun, key=key + "_remove_" + token,
                          help="Removes only this row from this report; source files and saved versions remain.",
                          on_click=_queue, args=(*args, "remove", token))
    st.button(add_label, key=key + "_add", on_click=_queue, args=(*args, "add"),
              disabled=bool(active and active == draft_token))
    return rows


def _render_fields(columns, fields, args, field):
    for title, (key, original, kind, default) in zip(columns, fields):
        options = dict(key=field(key, default), value=default, on_change=_queue, args=args)
        if kind == "date" and (isinstance(default, date) or default is None):
            st.date_input(title, format="YYYY-MM-DD", **options)
        elif kind in {"number", "currency"} and (isinstance(default, float) or default is None):
            st.number_input(title, **options)
        elif any(word in title.casefold() for word in ("description", "scope", "notes", "recommendation")):
            st.text_area(title, height=100, **options)
        else:
            st.text_input(title, **options)


def edit_row_cards(spec, block, prefix, field):
    from app.monthly_report_content_policy import ambiguous_price_columns
    from app.monthly_report_guided import _rich_text_scope
    from app.monthly_report_table_review_ui import review_table_headings
    noun, add_label = CARD_TABLES[spec.key]
    context = (spec.key, _rich_text_scope(prefix), block.references,
               tuple(table.reference for table in block.extra_tables), spec.columns)
    key = prefix + "_row_cards_" + _signature(context)
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
        edited = _edit_table(table.columns, table.rows, (), table_key, noun, add_label, field)
        tables.append(replace(table, rows=edited) if edited != table.rows else table)
    rows = block.rows
    if rows or not block.extra_tables:
        columns = tuple(column.title for column in spec.columns) or ("Facility", "Item", "Status")
        rows = _edit_table(columns, rows, tuple(column.type for column in spec.columns), key + "_rows", noun, add_label, field)
    if rows == block.rows and tuple(tables) == block.extra_tables:
        return block
    return replace(block, source="This month", rows=rows, extra_tables=tuple(tables),
                   reviewed_fingerprint="", client_reviewed_fingerprint="")
