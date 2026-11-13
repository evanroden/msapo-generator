"""Native row editors for proposal decisions, ENFRA onsite work and requests.

Rows retain their original schema and source references. A callback captures
the delivered fields and exactly one table-bound action before rendering;
display changes alone cannot change the report.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import partial
import math
import re
from uuid import uuid4

import streamlit as st

from app.monthly_report_editor import _cell_text, _signature
from app.monthly_report_ui_text import literal


CARD_TABLES = {"proposals": ("proposal", "Add proposal"),
               "service_calls": ("onsite call", "Add onsite call"),
               "rfi_matrix": ("request", "Add request"),
               "capital_renewal": ("capital item", "Add capital item"),
               "end_of_life": ("replacement item", "Add replacement item")}
_REQUEST_WORDS = {"request", "requested", "requests", "question", "questions", "answer",
                  "response", "details", "information"}
_REQUEST_METADATA = {"#", "number", "no", "id", "by", "date", "status", "link", "reference", "ref"}
_SOURCE_MARKUP = re.compile(
    r"https?://|www\.|@|[\[\]*_\x60<>~\\]|(?m:^\s*(?:[#>+\-]\s|\d+[.)]\s|[-*_]{3,}\s*$))",
    re.I,
)


def _source_display(value):
    """Escape source markup only; keep ordinary native labels byte-stable.

    The returned string is strictly for Markdown-capable Streamlit controls.
    Never use it for saved rows, field keys, comparison or a callback target.
    """
    raw = str(value)
    return literal(raw) if _SOURCE_MARKUP.search(raw) else raw


def _request_prose(title):
    """A request's own wording, never metadata such as Requested by or Request #."""
    words = set(re.findall(r"[a-z]+|#", title.casefold()))
    return bool(words & _REQUEST_WORDS) and not words & _REQUEST_METADATA


def _values(fields):
    return tuple(original if st.session_state.get(key, default) == default else
                 _cell_text(st.session_state.get(key, default))
                 for key, original, kind, default in fields)


def _queue(key, expected, tokens, active, fields, action="edit", target=None, *, preserve_empty=False, group=()):
    """One delivered native action includes the currently open row's text."""
    record = dict(st.session_state.get(key, {}))
    if group and action == "edit" and record.get("group_closed"):
        return  # A late field echo cannot reopen the row a sibling action closed.
    if group and action in {"open", "add", "remove", "undo_remove"}:
        for other_key in group:
            if other_key == key:
                continue
            other = st.session_state.get(other_key, {})
            snapshot = other.get("group_args")
            if snapshot and snapshot[2] and not other.get("group_closed"):
                # Capture the delivered fields through the same pending-row
                # protocol before changing which table owns the native editor.
                switching = action in {"open", "add"}
                _queue(other_key, *snapshot, "close" if switching else "edit",
                       preserve_empty=preserve_empty)
                if switching:
                    other = dict(st.session_state[other_key])
                    other["group_closed"] = True
                    st.session_state[other_key] = other
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
        record["entry_focus"] = draft_token
    elif action == "close":
        if active == draft_token:
            draft_token = None
        active = None
    elif action == "remove" and target in identities:
        index = identities.index(target)
        removed_row = rows[index]
        del rows[index]
        del identities[index]
        record["removed"] = {"row": removed_row, "token": target, "index": index,
                             "remaining_tokens": tuple(identities)}
        if active == target:
            active = None
    elif action == "remove" and target == draft_token:
        active, draft_token = None, None
    elif action == "undo_remove":
        removed = record.pop("removed", None)
        if removed and tuple(identities) == removed["remaining_tokens"]:
            rows.insert(removed["index"], removed["row"])
            identities.insert(removed["index"], removed["token"])
        elif removed:
            record["undo_notice"] = "The table changed since removal. Current rows were kept; restore the removed content from saved history if needed."
    if changed_fields and not preserve_empty:
        retained = [(row, token) for row, token in zip(rows, identities)
                    if any(value is not None and str(value).strip() for value in row)]
        rows, identities = [row for row, _ in retained], [token for _, token in retained]
    # Consecutive callbacks may arrive before the parent commits. A field's
    # blur and Close can also share the same rendered snapshot and deliver
    # the same complete row. Keep that row's original uncommitted baseline;
    # otherwise Close falsely conflicts with the still-current parent. Do
    # not extend this chain to a different result or different row tokens.
    previous = record.get("pending")
    acknowledged = record.pop("acknowledged_delivery", None)
    if (not previous and action == "edit" and acknowledged
            and acknowledged.get("input_action") == "edit"
            and acknowledged["expected"] == expected
            and acknowledged.get("input_tokens") == tokens
            and acknowledged.get("input_active") == active):
        previous = acknowledged
    continues_pending = previous and (previous["result"] == expected or (
        previous["expected"] == expected and previous["result"] == tuple(rows)
        and previous["tokens"] == tuple(identities)))
    baseline = previous["baseline"] if continues_pending else expected
    # A browser can deliver several blurs from one native render while the
    # parent has acknowledged only an earlier blur. Admit only exact results
    # produced by that same table/row/token snapshot, never arbitrary changes
    # to the current report. Bound the transient lineage; overflow conflicts
    # rather than treating unknown content as our own acknowledged write.
    intermediates = ()
    if (previous and action == "edit" and previous.get("input_action") == "edit"
            and previous["expected"] == expected
            and previous.get("input_tokens") == tokens
            and previous.get("input_active") == active):
        intermediates = tuple(dict.fromkeys((*previous.get("intermediates", ()), previous["result"])))[:32]
    record["pending"] = {"baseline": baseline, "expected": expected, "result": tuple(rows), "tokens": tuple(identities),
                         "active": active, "draft_token": draft_token, "draft_index": draft_index,
                         "input_action": action, "input_tokens": tokens, "input_active": active,
                         "intermediates": intermediates}
    if group:
        record["group_closed"] = not bool(active)
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
            parsed = date.fromisoformat(value) if value else None
            # Streamlit's default calendar range extends ten years on either
            # side. Preserve out-of-range dates as editable source text.
            if parsed is not None and not date.min.year + 10 <= parsed.year <= date.max.year - 10:
                return value
            return parsed
        if kind in {"number", "currency"}:
            if not value:
                return None
            number = float(value)
            # Keep source precision when a browser number would round, underflow,
            # or exceed its safe integer range. Text stays editable, never zeroed.
            if (math.isfinite(number) and abs(number) <= (1 << 53) - 1
                    and Decimal(str(number)) == Decimal(str(value))):
                return number
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        pass  # Keep a recorded unknown value as editable text.
    return value


def _summary(columns, row, noun, index, prose=None):
    values = tuple((column, row[n] if n < len(row) else "") for n, column in enumerate(columns))
    main = next((value for column, value in values if value and prose and prose(column)), "")
    main = main or next((value for column, value in values if value and any(
        word in column.casefold() for word in ("description", "scope", "title", "task", "recommendation"))), "")
    st.write(_source_display(main) if main else f"{noun.capitalize()} {index + 1}")
    identifiers = [(column, value) for column, value in values if value and (any(
        word in column.casefold() for word in ("number", "#", "identifier", "facility", "site", "vendor", "area", "asset"))
        or column.casefold() == "id" or column.casefold().endswith(" id"))]
    if identifiers:
        st.caption(" · ".join(f"{_source_display(column)}: {_source_display(value)}"
                              for column, value in identifiers))
    # Prior grid editing displayed capital priority and replacement timing for
    # every row. Preserve that visibility in collapsed native cards instead of
    # forcing operators to open each renewal/replacement occurrence.
    decisions = [(column, value) for column, value in values if any(
        word in column.casefold() for word in
        ("status", "decision", "priority", "replacement timing"))]
    if decisions:
        st.caption(" · ".join(f"{_source_display(column)}: {_source_display(value or 'Not recorded')}"
                              for column, value in decisions))


def _comparison_rows(columns, rows):
    # Duplicate source headings remain separate fields in the comparison.
    # These display-only labels never replace the exported original schema.
    labels = tuple(f"{index + 1}. {column}" if columns.count(column) > 1 else column
                   for index, column in enumerate(columns))
    if len(set(labels)) != len(labels):
        # An original heading may already equal a duplicate's display label.
        # Prefix every heading only then: positions make all labels unique.
        labels = tuple(f"{index + 1}. {column}" for index, column in enumerate(columns))
    return [dict(zip(labels, row)) for row in rows]


def _key_class(key):
    return "st-key-" + re.sub(r"[^a-zA-Z0-9_-]", "-", key.strip())


def _request_entry_focus(card_key, origin_key, field_key):
    """Ask the workspace adapter, once, to put focus in this new row's field.

    This marker follows the row's fields, so the field exists when the
    marker does. The browser focuses it only if the reader's latest input
    was this Add control (tests/workspace_navigation_test.cjs).
    """
    origin, target = _key_class(origin_key)[7:], _key_class(field_key)[7:]
    st.html('<span hidden data-enfra-entry-focus="' + uuid4().hex + '" data-enfra-entry-field="' + target
            + '" data-enfra-entry-origin="' + origin + '"></span><style>.' + _key_class(card_key)
            + ' > [data-testid="stElementContainer"]:has([data-enfra-entry-focus]){display:none;}</style>')


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
    selector = "." + _key_class(key)
    child = ' > [data-testid="stElementContainer"]'
    marker = '[data-enfra-row-finished]'
    current = child + '[data-stale="false"] ' + marker
    st.html('<span hidden data-enfra-row-finished="true"></span><style>'
            + selector + ':has(' + current + ')' + child
            + '[data-stale="true"]{display:none;}'
            + selector + child + ':has(' + marker + '){display:none;}'
            + '</style>')


_ONSITE_COLUMNS = ("WO #", "Finish Date", "Area", "Task Code-Description", "Tag #")
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def _onsite_projection(columns, rows):
    """Display semantics only: never normalize or remove stored source cells.

    A monthly title is recognized only above the exact canonical header.
    First-column-only values are NOT generally notes: a partial work order is
    still a work order. Only the explicit pending-CMMS narrative is context.
    Unrecognized layouts retain neutral, fully editable source rows.
    """
    context = {}
    canonical = tuple(columns) in (_ONSITE_COLUMNS, ("Facility", *_ONSITE_COLUMNS),
                                   ("WO #", "Date", "Area", "Task", "Asset"))
    title_frame = (len(columns) == 5
                   and re.fullmatch(_MONTH + r" \d{4} Service Calls", columns[0])
                   and tuple(columns[1:]) == ("Column 2", "Column 3", "Column 4", "Column 5")
                   and rows and tuple(rows[0]) == _ONSITE_COLUMNS)
    if title_frame:
        canonical = True
        context[0] = columns[0]
    if canonical:
        for index, row in enumerate(rows):
            if (len(row) == 5 and not any(row[1:]) and isinstance(row[0], str)
                    and re.fullmatch(r"(?:Detailed )?work-order counts are pending (?:FacilityOne )?CMMS availability[.;](?:[^\n]*)",
                                     row[0], flags=re.IGNORECASE)):
                context[index] = row[0]
    return (_ONSITE_COLUMNS if title_frame else columns), context, canonical


def _edit_table(columns, rows, types, key, noun, add_label, field, *, onsite=False, prose=None, group=()):
    record = dict(st.session_state.get(key, {}))
    # A focus request belongs only to the render that follows its Add.
    entry_focus = record.pop("entry_focus", None)
    if entry_focus:
        st.session_state[key] = dict(record)
    pending = record.get("pending")
    incoming = tuple(tuple(row) for row in rows)
    rows = incoming
    if pending and incoming in (pending["baseline"], pending["expected"], pending["result"],
                                *pending.get("intermediates", ())):
        rows = pending["result"]
        record.update(rows=rows, tokens=pending["tokens"], active=pending["active"],
                      draft_token=pending["draft_token"], draft_index=pending["draft_index"])
        if incoming == pending["result"]:
            # Keep one bounded delivery lineage after parent acknowledgement.
            # Later blurs can still name this same native snapshot.
            record["acknowledged_delivery"] = pending
            record.pop("pending", None)
    elif pending:
        if group:
            # Conflict choices retain the pending version; a sibling must not
            # recapture fields from this table's retired editor over it.
            record.update(group_args=None, group_closed=True)
            st.session_state[key] = record
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

    queue = partial(_queue, preserve_empty=onsite, group=group)
    context = {}
    if onsite:
        columns, context, canonical = _onsite_projection(columns, rows)
        if not canonical:
            noun, add_label = "table row", "Add table row"
            st.caption("Source table — original fields retained.")

    active_values = (rows[tokens.index(active)] if active in tokens else
                     tuple("" for _ in columns) if active and active == draft_token else ())
    input_kinds = dict(record.get("input_kinds", {}))
    if active and active not in input_kinds:
        # Multiline source values keep their editor type through clears and
        # one-line edits, just as recorded unknown date/number values do.
        input_kinds[active] = tuple(
            kind if (kind == "date" and (isinstance(default, date) or default is None)
                     or kind in {"number", "currency"} and (isinstance(default, float) or default is None))
            else "multiline" if "\n" in str(default) or "\r" in str(default) else "text"
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
    if group:
        record.update(group_args=args[1:], group_closed=not bool(active))
        st.session_state[key] = record
    entries = list(zip(tokens, rows))
    if active and active == draft_token:
        entries.insert(min(record.get("draft_index", len(entries)), len(entries)),
                       (active, tuple("" for _ in columns)))
    visible_index = 0
    for index, (token, row) in enumerate(entries):
        source_index = tokens.index(token) if token in tokens else None
        if source_index in context:
            st.caption(context[source_index])
            continue
        if token != active and not any(value is not None and str(value).strip() for value in row):
            continue
        card_key = key + "_card_" + token
        widget_keys = ()
        with st.container(key=card_key, border=True):
            if token == active:
                # Live summaries would grow/move the native fields as the
                # first identifier or a long title is entered. Keep this
                # active heading the same height until explicit closure.
                st.write("Edit " + noun)
                widget_keys = _render_fields(columns, fields, args, field, queue, prose=prose)
                st.button("Close editing", key=key + "_close_" + token, on_click=queue, args=(*args, "close"))
            else:
                _summary(columns, row, noun, visible_index if onsite else index, prose)
                st.button("Edit " + noun, key=key + "_open_" + token,
                          on_click=queue, args=(*args, "open", token))
            if token != draft_token:
                st.button("Remove " + noun, key=key + "_remove_" + token,
                          help="Removes only this row from this report; source files and saved versions remain.",
                          on_click=queue, args=(*args, "remove", token))
            _finish_row(card_key)
            if token == active == draft_token == entry_focus and widget_keys:
                # A request's text, not its facility or number, is what a
                # new request is for; other tables start at their first field.
                first = next((n for n, title in enumerate(columns) if prose and prose(title)), 0)
                _request_entry_focus(card_key, key + "_add", widget_keys[first])
        visible_index += 1
    st.button(add_label, key=key + "_add", on_click=queue, args=(*args, "add"),
              disabled=bool(active and active == draft_token))
    if record.get("removed"):
        st.button("Undo last removal", key=key + "_undo_remove", on_click=queue,
                  args=(*args, "undo_remove"),
                  help="Restores only the last removed row. Later edits to other rows are kept.")
    if record.get("undo_notice"):
        st.warning(record.pop("undo_notice"))
        st.session_state[key] = record
    return rows


def _render_fields(columns, fields, args, field, queue=_queue, *, prose=None):
    """Render one row's native fields; return their widget keys in order."""
    keys = []
    for index, (title, (key, original, kind, default)) in enumerate(zip(columns, fields), 1):
        # These labels do not replace the stored or exported source headings.
        label = _source_display(title) if title.strip() else f"Column {index}"
        options = dict(key=field(key, default), value=default, on_change=queue, args=args)
        keys.append(options["key"])
        if kind == "date" and (isinstance(default, date) or default is None):
            st.date_input(label, format="YYYY-MM-DD", **options)
        elif kind in {"number", "currency"} and (isinstance(default, float) or default is None):
            st.number_input(label, **options)
        elif (kind == "multiline" or prose and prose(title)
              or any(word in title.casefold() for word in ("description", "scope", "notes", "recommendation"))):
            st.text_area(label, height=100, **options)
        else:
            st.text_input(label, **options)
    return keys


def _table_key(spec, block, prefix):
    from app.monthly_report_guided import _rich_text_scope

    context = (spec.key, _rich_text_scope(prefix), block.references,
               tuple(table.reference for table in block.extra_tables), spec.columns)
    return prefix + "_row_cards_" + _signature(context)


def primary_row_recovery_pending(spec, block, prefix):
    key = _table_key(spec, block, prefix)
    if spec.key == "service_calls":
        # Onsite editors retire their pre-projection widget identities.
        # Recovery must inspect the same versioned key used by edit_row_cards.
        key += "_onsite_context_v1"
    record = st.session_state.get(key + "_rows", {})
    draft_token = record.get("draft_token")
    return bool(record.get("pending") or record.get("removed")
                or (draft_token and record.get("active") == draft_token))


def edit_row_cards(spec, block, prefix, field, *, empty=None, notice=None):
    """Return the edited block.

    ``empty`` is the empty-state sentence ``notice`` shows while the block has
    no rows and no request is open; an open blank editor is not content.
    """
    from app.monthly_report_content_policy import ambiguous_price_columns
    from app.monthly_report_table_review_ui import review_table_headings
    noun, add_label = CARD_TABLES[spec.key]
    prose = _request_prose if spec.key == "rfi_matrix" else None
    key = _table_key(spec, block, prefix)
    primary = bool(block.rows or not block.extra_tables or primary_row_recovery_pending(spec, block, prefix))
    if spec.key == "service_calls":
        # Retire pre-projection callbacks that could have opened a header as a call.
        key += "_onsite_context_v1"
    group = tuple(key + "_extra_" + str(index) + "_" + _signature(table.columns)
                  for index, table in enumerate(block.extra_tables))
    if primary:
        group += (key + "_rows",)
    tables, table_keys = [], []
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
                             onsite=spec.key == "service_calls", prose=prose, group=group)
        table_keys.append(table_key)
        tables.append(replace(table, rows=edited) if edited != table.rows else table)
    rows = block.rows
    if primary:
        columns = tuple(column.title for column in spec.columns) or ("Facility", "Item", "Status")
        rows = _edit_table(columns, rows, tuple("text" if spec.key == "end_of_life" and column.type == "date" else column.type
                             for column in spec.columns), key + "_rows", noun, add_label, field,
                           onsite=spec.key == "service_calls", prose=prose, group=group)
        table_keys.append(key + "_rows")
    if empty and notice is not None:
        written = any(value is not None and str(value).strip()
                      for row in (*rows, *(r for table in tables for r in table.rows)) for value in row)
        if not written and not any(st.session_state.get(name, {}).get("active") for name in table_keys):
            notice.caption(empty)
    if rows == block.rows and tuple(tables) == block.extra_tables:
        return block
    return replace(block, source="This month", rows=rows, extra_tables=tuple(tables),
                   reviewed_fingerprint="", client_reviewed_fingerprint="")
