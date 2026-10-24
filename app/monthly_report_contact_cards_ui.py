"""Compact contact presentation; retained source rows are never draft placeholders.

Callbacks capture the delivered active fields before navigation or removal, as
in the reviewed row-card editor. One block-wide receipt binds actions to the
rendered schema/rows and epoch, not a contact name or a shifting row label.
"""
from dataclasses import replace
from uuid import uuid4

import streamlit as st


def _capture(tables, active, fields):
    result = list(tables)
    if active is None or not fields:
        return tuple(result)
    table_index, row_index = active
    table = result[table_index]
    values = tuple(original if st.session_state.get(key, original) == original
                   else st.session_state[key] for key, original in fields)
    rows = list(table.rows)
    if row_index < len(rows):
        # Clearing a source row retains its occurrence, including blank cells.
        rows[row_index] = (rows[row_index] if all(value == original for value, (_, original) in zip(values, fields))
                           else (*values, *rows[row_index][len(values):]))
    elif any(str(value or '').strip() for value in values):
        rows.append(values)
    result[table_index] = replace(table, rows=tuple(rows))
    return tuple(result)


def _queue(key, epoch, expected, active, fields, action, target=None):
    record = dict(st.session_state.get(key, {}))
    if record.get('epoch') != epoch:
        return  # Old report/render controls cannot mutate a newer incarnation.
    prior = record.get('pending')
    if prior and action == 'edit' and prior['action'] != 'edit':
        return  # A late field echo must not undo its delivered Close/Remove.
    corrected = _capture(expected, active, fields)
    result = list(corrected)
    next_active = active
    if action == 'open':
        next_active = target
    elif action == 'add':
        next_active = (target, len(result[target].rows))
    elif action == 'close':
        next_active = None
    elif action == 'remove':
        table_index, row_index = target
        table = result[table_index]
        if row_index < len(table.rows):
            result[table_index] = replace(table, rows=tuple(
                row for index, row in enumerate(table.rows) if index != row_index))
        next_active = None
    record['pending'] = dict(expected=expected, corrected=corrected,
                             result=tuple(result), active=next_active, action=action)
    st.session_state[key] = record



def _resolve_conflict(key, expected, pending, use_pending):
    record = dict(st.session_state.get(key, {}))
    if record.get('pending') != pending:
        return
    result = pending['corrected'] if use_pending else expected
    record['pending'] = dict(expected=expected, corrected=result, result=result,
                             active=None, action='close')
    st.session_state[key] = record


def parent_visibility(key, *, opening):
    """Carry delivered fields across a parent Done and renew on real re-entry."""
    record = st.session_state.get(key)
    if not isinstance(record, dict):
        return
    record = dict(record)
    if opening:
        if record.pop('parent_hidden', False):
            record['field_scope'] = uuid4().hex
        st.session_state[key] = record
        return
    if record.get('active') is not None and record.get('fields') and record.get('tables'):
        corrected = _capture(record['tables'], record['active'], record['fields'])
        if corrected != record['tables'] or record.get('pending'):
            _queue(key, record.get('epoch'), record['tables'], record['active'], record['fields'], 'edit')
            record = dict(st.session_state.get(key, record))
    record['parent_hidden'] = True
    st.session_state[key] = record


def edit_contact_tables(tables, key, field, label, *, vendor=False, prepare=None, can_edit=None):
    """Return exact tables and a removal's edit-only intermediate receipt."""
    tables = tuple(tables)
    record = dict(st.session_state.get(key, {}))
    pending = record.get('pending')
    intermediate = None
    if pending:
        if tables == pending['expected']:
            if pending['action'] == 'remove' and pending['corrected'] != tables:
                intermediate = pending['corrected']
            tables = pending['result']
            record.update(active=pending['active'], tables=tables)
            if pending['action'] in {'open', 'add'}:
                record['field_scope'] = uuid4().hex
                record['editor_slot'] = pending['active']
            record.pop('pending', None)
        elif tables == pending['result']:
            record.update(active=pending['active'], tables=tables)
            if pending['action'] in {'open', 'add'}:
                record['field_scope'] = uuid4().hex
                record['editor_slot'] = pending['active']
            record.pop('pending', None)
        else:
            record['epoch'] = uuid4().hex
            st.session_state[key] = record
            st.warning('Contacts changed after this editor opened. Compare both versions before continuing.')
            st.caption('Current contacts')
            for table in tables:
                st.write(table.rows)
            st.caption('Pending contact fields')
            for table in pending['corrected']:
                st.write(table.rows)
            st.caption('Use pending contact edits replaces these tables with the pending field version; it does not repeat a pending removal. Keep current contacts discards the pending edits.')
            st.button('Use pending contact edits', key=key + '_use',
                      on_click=_resolve_conflict, args=(key, tables, pending, True))
            st.button('Keep current contacts', key=key + '_keep',
                      on_click=_resolve_conflict, args=(key, tables, pending, False))
            return tables, None
    if record.get('tables') != tables:
        # External canonical changes retire row-index bindings, including duplicates.
        record['active'] = None
    active = record.get('active')
    if prepare is not None:
        prepared = tuple(prepare(tables, intermediate))
        if prepared != tables and active is not None:
            ti, ri = active
            # Directory normalization may group an explicitly appended row by
            # site. Bind the same full row occurrence, never a person's name.
            if ti < len(prepared) and ri < len(tables[ti].rows):
                row = tables[ti].rows[ri]
                ordinal = sum(value == row for value in tables[ti].rows[:ri])
                matches = [index for index, value in enumerate(prepared[ti].rows) if value == row]
                active = (ti, matches[ordinal]) if ordinal < len(matches) else None
            else:
                active = None
        tables = prepared
        record['active'] = active
    record.update(tables=tables, epoch=uuid4().hex)
    epoch = record['epoch']
    if can_edit is not None and not can_edit():
        record['active'] = None
        st.session_state[key] = record
        return tables, intermediate
    fields = ()
    if active is not None:
        ti, ri = active
        table = tables[ti]
        row = table.rows[ri] if ri < len(table.rows) else tuple('' for _ in table.columns)
        fields = tuple((key + '_' + record.setdefault('field_scope', uuid4().hex) + f'_field_{ci}', row[ci] if ci < len(row) else '')
                       for ci in range(len(table.columns)))
    record['fields'] = fields
    st.session_state[key] = record
    args = (key, epoch, tables, active, fields)
    noun = 'vendor contact' if vendor else 'contact'
    for ti, table in enumerate(tables):
        if len(tables) > 1:
            st.write(f'Contact table {ti + 1}')
        entries = [(ri, row) for ri, row in enumerate(table.rows) if active != (ti, ri)]
        if active is not None and active[0] == ti:
            ri = active[1]
            row = table.rows[ri] if ri < len(table.rows) else tuple('' for _ in table.columns)
            # Preserve the opened/Add presentation slot until explicit closure.
            # Directory grouping still updates canonical rows and action bindings;
            # it must not move the native editor between positional parent blocks.
            slot = record.get('editor_slot', active)[1]
            entries.insert(min(slot, len(entries)), (ri, row))
        for ri, row in entries:
            editing = active == (ti, ri)
            card_key = key + '_active_editor' if editing else key + f'_row_{ti}_{ri}'
            with st.container(key=card_key, border=True):
                if editing:
                    st.write('Edit ' + noun)
                    _fields(table, fields, field, args, vendor)
                else:
                    st.write(label(table.columns, row, ri))
                    st.button('Edit ' + noun, key=key + f'_open_{ti}_{ri}',
                              on_click=_queue, args=(*args, 'open', (ti, ri)))
        st.button('Add ' + noun, key=key + f'_add_{ti}',
                  on_click=_queue, args=(*args, 'add', ti))
    return tables, intermediate


def _fields(table, fields, field, args, vendor):
    for ci, (key, original) in enumerate(fields):
        heading = table.columns[ci]
        label = ('Agreement status (MSA)' if vendor and heading.strip().casefold() == 'msa'
                 else heading if heading.strip() else f'Detail {ci + 1}')
        # Original blank/duplicate headings remain untouched in the table schema.
        st.text_input(label, key=field(key, original), max_chars=500,
                      on_change=_queue, args=(*args, 'edit'))
    st.button('Close editing', key=args[0] + '_close', on_click=_queue, args=(*args, 'close'))
    st.button('Remove contact', key=args[0] + '_remove', on_click=_queue,
              args=(*args, 'remove', args[3]))
