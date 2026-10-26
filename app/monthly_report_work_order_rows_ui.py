"""Explicit insertion in imported work-order grids; never infer missing rows.

The native button callback records intent only. The editor's returned values
include edits delivered with that click and are the sole source of cell data.
UI occurrence IDs distinguish identical/blank rows and never enter the model.
"""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import streamlit as st

from app.monthly_report_editor import _cell_text, _grid

ACTIONS = ('Insert blank above', 'Insert blank below')


def _unused_column(columns, name):
    while name in columns:
        name += '_'
    return name


def _new_editor(table, scope):
    identity = _unused_column(table.columns, '__work_order_row_id')
    action = _unused_column((*table.columns, identity), '__work_order_row_action')
    artificial = not table.rows
    rows = table.rows or (('',) * len(table.columns),)
    ids = tuple(uuid4().hex for _ in rows)
    return {'scope': scope, 'epoch': uuid4().hex, 'action_epoch': uuid4().hex,
            'table': table, 'pending': None, 'intent': None, 'rendered': False,
            'identity': identity, 'action': action, 'artificial': artificial,
            'ids': ids, 'seed': [dict(zip(table.columns, row)) | {
                identity: row_id, action: list(ACTIONS) if not artificial else []}
                for row, row_id in zip(rows, ids)]}


def _structure(delta):
    return (tuple(delta.get('deleted_rows', ())), len(delta.get('added_rows', ())))


def _queue_insert(state_key, grid_key, click_key, epoch, action_epoch, ids, structure):
    """Reject retired callbacks before recording an exact row occurrence."""
    state = st.session_state.get(state_key)
    click = st.session_state.get(click_key)
    if (not state or state['epoch'] != epoch or state['action_epoch'] != action_epoch
            or not click or type(click.get('row')) is not int
            or not 0 <= click['row'] < len(ids) or click.get('label') not in ACTIONS):
        return
    # Streamlit 1.61.1's button row is display-relative after row deletion,
    # unlike its cell-edit indexes. If structure changed since these actions
    # were rendered, the integer cannot safely identify the clicked occurrence.
    if (_structure(st.session_state.get(grid_key, {})) != structure
            or state['pending'] and state['pending']['rebase']):
        state['notice'] = 'The rows changed before insertion. Choose a current row to insert beside.'
        return
    anchor = ids[click['row']]
    if state['artificial'] and anchor == state['ids'][0]:
        return
    state['intent'] = {'epoch': epoch, 'anchor': anchor, 'label': click['label']}
    # A repeated wire message or callback from this rendered action is spent.
    # The grid input itself stays mounted until its result is canonical.
    state['action_epoch'] = uuid4().hex


def edit_imported_work_order_table(table, key, scope, prefix):
    state_key = key + '_row_editor'
    state = st.session_state.get(state_key)
    previous_state = state
    if state and state['scope'] == scope:
        pending = state['pending']
        if pending and table == pending['result']:
            grid_key = key + '_' + state['epoch']
            if pending['rebase']:
                if st.session_state.get(grid_key, {}) == pending['delta']:
                    state = _new_editor(table, scope)
                else:
                    # A newer edit arrived before the acknowledged grid was
                    # rebased. Read it from the OLD native seed first; replay
                    # the one insertion against its occurrence boundary below.
                    state['table'] = table
            else:
                state['table'] = table
                state['pending'] = None
                # An ordinary cell acknowledgement keeps the same native
                # grid and row occurrences. Its already visible menu is still
                # current; only a consumed action or structural rebase retires it.
        elif table != state['table']:
            # A replaced table (including observed A -> B -> A) is a new
            # incarnation, not permission to apply old edits or row indexes.
            state = None
    else:
        state = None
    if state:
        grid_key = key + '_' + state['epoch']
        if state['rendered'] and grid_key not in st.session_state:
            # Native state was unmounted. Reopen from canonical rows, not a
            # surviving old delta or its retired artificial empty slot.
            state = None
    if state is None:
        state = _new_editor(table, scope)
    if previous_state and state is not previous_state:
        retired_key = key + '_' + previous_state['epoch']
        # _grid owns these plain session values; unlike native widget state,
        # Streamlit will not clean them up when an incarnation retires.
        for suffix in ('_data', '_data_seed'):
            st.session_state.pop(retired_key + suffix, None)
    st.session_state[state_key] = state
    grid_key = key + '_' + state['epoch']
    click_key = grid_key + '_insert_' + state['action_epoch']
    structure = _structure(st.session_state.get(grid_key, {}))
    raw_rows = _grid(grid_key, state['seed'], num_rows='dynamic', hide_index=True,
                     disabled=[state['identity']],
                     column_config={state['identity']: None,
                                    state['action']: st.column_config.ButtonColumn(
                                        'Row', width=160, pinned=True, type='tertiary',
                                        help='Insert one blank row above or below this row.',
                                        key=click_key, on_click=_queue_insert,
                                        args=(state_key, grid_key, click_key, state['epoch'],
                                              state['action_epoch'], state['ids'], structure))})
    state['rendered'] = True
    # Strip BOTH helper columns before any blank/artificial-slot check. Values
    # in a button or hidden identity cell are not work-order data.
    rows = [tuple(_cell_text(row.get(column)) for column in table.columns) for row in raw_rows]
    ids = [row.get(state['identity']) for row in raw_rows]
    if state['artificial']:
        artificial_id = state['ids'][0]
        if artificial_id in ids:
            index = ids.index(artificial_id)
            if not any(rows[index]):
                del rows[index]
                del ids[index]
    intent = state.pop('intent', None)
    state['intent'] = None
    pending = state['pending']
    operation = pending.get('operation') if pending else None
    inserted = False
    if intent and intent['epoch'] == state['epoch'] and operation is None:
        matches = [index for index, row_id in enumerate(ids) if row_id == intent['anchor']]
        if len(matches) == 1:
            boundary = state['ids'].index(intent['anchor']) + (intent['label'] == ACTIONS[1])
            operation = state['ids'][:boundary]
        else:
            state['notice'] = 'That row changed before insertion. Choose a current row to insert beside.'
    if operation is not None:
        # The insertion is a boundary in the original occurrence sequence,
        # not a positional edit of the saved result. Reapply it exactly once
        # to newer returned values if a parent commit was interrupted. Even
        # deleting its original anchor cannot drop a later delivered edit.
        index = sum(row_id in operation for row_id in ids if row_id is not None)
        rows.insert(index, ('',) * len(table.columns))
        inserted = True
    if notice := state.pop('notice', None):
        st.info(notice)
    result = replace(table, rows=tuple(rows)) if tuple(rows) != table.rows else table
    # Native additions/deletions also require a fresh occurrence map. Ordinary
    # cell editing keeps the same stable seed, including its cumulative delta.
    seed_ids = list(state['ids'][1:] if state['artificial'] else state['ids'])
    rebase = inserted or ids != seed_ids
    if result != table or rebase:
        state['pending'] = {'result': result, 'rebase': rebase, 'operation': operation,
                            'delta': deepcopy(st.session_state.get(grid_key, {}))}
        if rebase:
            # Consumed only after the guided workspace commits the whole draft
            # and attempts durable recovery; never rerun inside this editor.
            st.session_state[prefix + '_work_order_grid_refresh'] = True
    else:
        state['pending'] = None
    return result
