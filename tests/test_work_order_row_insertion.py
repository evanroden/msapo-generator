"""Synthetic native ButtonColumn wire events; not browser input-delivery proof."""
from dataclasses import replace
import json

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable
from test_work_order_imported_rows import APP, current, launch, native_rows

ABOVE = 'Insert blank above'
BELOW = 'Insert blank below'
COLUMNS = ('Work orders', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun')
BLANK = ('',) * 7
COMPACT = ReportTable(COLUMNS, (
    ('Received', '1', '2', '3', '4', '5', '6'),
    ('', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'),
    ('', '7', '8', '9', '10', '11', '12'),
    ('Closed', '13', '14', '15', '16', '17', '18'),
    ('', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'),
), 'synthetic:original-annual-frame')


def wire(app, row=None, label=ABOVE, *, edited=None, added=None, deleted=None,
         proto=None, send_edit=False):
    proto = proto or app.dataframe[0].proto
    message = WidgetStates()
    if send_edit or edited is not None or added is not None or deleted is not None:
        message.widgets.add(id=proto.id, string_value=json.dumps({
            'edited_rows': edited or {}, 'added_rows': added or [], 'deleted_rows': deleted or []}))
    else:
        try:
            delta = app.session_state[proto.id]
        except KeyError:
            delta = {'edited_rows': {}, 'added_rows': [], 'deleted_rows': []}
        message.widgets.add(id=proto.id, string_value=json.dumps(delta))
    if row is not None:
        assert len(proto.button_click_widgets) == 1, 'Imported work-order rows need a native contextual insertion action'
        message.widgets.add(id=next(iter(proto.button_click_widgets.values())),
                            string_trigger_value={'data': json.dumps({'row': row, 'label': label})})
    app._run(message)
    assert not app.exception
    return message


def test_six_by_seven_legacy_grid_is_restored_only_by_two_explicit_row_actions():
    app = launch(COMPACT)
    original = app.session_state['block']
    assert len(native_rows(current(app))) == 6
    wire(app)
    assert app.session_state['block'] == original  # Never infer the missing rows.
    wire(app, 0, ABOVE)
    wire(app)  # Canonical acknowledgement rebases the stable native input.
    wire(app, 3, BELOW)
    expected = (BLANK, *COMPACT.rows[:3], BLANK, *COMPACT.rows[3:])
    assert current(app).rows == expected
    assert len(native_rows(current(app))) == 8
    assert current(app).columns == COMPACT.columns
    assert current(app).reference == COMPACT.reference
    assert replace(app.session_state['block'], extra_tables=original.extra_tables) == original


@pytest.mark.parametrize('row,label,position', [(0, ABOVE, 0), (4, BELOW, 5)])
def test_above_first_and_below_last_preserve_same_event_cell_edit(row, label, position):
    app = launch(COMPACT)
    wire(app, row, label, edited={2: {'Mar': '99'}})
    expected = list(COMPACT.rows)
    expected[2] = ('', '7', '8', '99', '10', '11', '12')
    expected.insert(position, BLANK)
    assert current(app).rows == tuple(expected)
    wire(app)
    assert current(app).rows == tuple(expected)


def test_duplicate_blank_anchors_have_occurrence_identity():
    original = replace(COMPACT, rows=(BLANK, BLANK, COMPACT.rows[0]))
    app = launch(original)
    wire(app, 1, ABOVE, edited={1: {'Jan': 'second blank'}})
    assert current(app).rows == (BLANK, BLANK, ('', 'second blank', '', '', '', '', ''), COMPACT.rows[0])


def test_deleted_anchor_is_rejected_without_losing_other_delivered_edits():
    app = launch(COMPACT)
    wire(app, 1, BELOW, deleted=[1], edited={3: {'Jan': '23'}})
    expected = list(COMPACT.rows)
    expected[3] = ('Closed', '23', '14', '15', '16', '17', '18')
    del expected[1]
    assert current(app).rows == tuple(expected)


def test_changed_structure_rejects_ambiguous_button_index_then_fresh_anchor_works():
    app = launch(COMPACT)
    wire(app, 3, ABOVE, deleted=[0])
    assert current(app).rows == COMPACT.rows[1:]
    assert any('rows changed' in notice.value for notice in app.info)
    wire(app)
    wire(app, 2, ABOVE)
    assert current(app).rows == (*COMPACT.rows[1:3], BLANK, *COMPACT.rows[3:])


def test_native_append_then_insert_by_new_blank_anchor_and_explicit_delete():
    app = launch(COMPACT)
    wire(app, added=[dict.fromkeys(COLUMNS, '')])
    wire(app)
    wire(app, 5, ABOVE)
    assert current(app).rows == (*COMPACT.rows, BLANK, BLANK)
    wire(app)
    wire(app, deleted=[5])
    assert current(app).rows == (*COMPACT.rows, BLANK)
    wire(app)
    wire(app, 5, BELOW)
    assert current(app).rows == (*COMPACT.rows, BLANK, BLANK)


def test_replayed_action_and_edit_payload_cannot_duplicate_insertion():
    app = launch(COMPACT)
    proto = app.dataframe[0].proto
    message = wire(app, 1, ABOVE, edited={0: {'Jan': '28'}})
    expected = current(app)
    app._run(message)
    assert not app.exception and current(app) == expected
    wire(app)
    wire(app, 1, ABOVE, proto=proto, edited={0: {'Jan': 'stale'}})
    assert current(app) == expected


@pytest.mark.parametrize('change', ['table', 'report', 'aba', 'unmount'])
def test_stale_action_cannot_mutate_replaced_or_reopened_grid(change):
    app = launch(COMPACT)
    old = app.dataframe[0].proto
    if change == 'report':
        app.session_state['row_probe_rich_text_epoch'] = 'new-report-incarnation'
    elif change in ('table', 'aba'):
        block = app.session_state['block']
        app.session_state['block'] = replace(block, extra_tables=(replace(COMPACT, rows=(BLANK,)),))
        wire(app)
        if change == 'aba':
            app.session_state['block'] = block
    else:
        app.session_state['show'] = False
        app.run()
        app.session_state['show'] = True
    app.run()
    expected = current(app)
    wire(app, 1, BELOW, proto=old)
    assert current(app) == expected


def test_empty_artificial_slot_and_action_cells_never_become_data():
    app = launch(replace(COMPACT, rows=()))
    assert not current(app).rows
    wire(app)
    assert not current(app).rows
    # A stale/forged click on the artificial slot must not promote it.
    wire(app, 0, ABOVE)
    assert not current(app).rows
    wire(app, edited={0: {'Jan': '7'}})
    assert current(app).rows == (('', '7', '', '', '', '', ''),)
    wire(app)
    wire(app, 0, BELOW)
    assert current(app).rows == (('', '7', '', '', '', '', ''), BLANK)
    assert all(len(row) == 7 for row in native_rows(current(app)))
    assert not any('Insert blank' in cell for row in native_rows(current(app)) for cell in row)


def test_ordinary_cell_edits_keep_editor_seed_and_do_not_need_row_actions():
    app = launch(COMPACT)
    editor = app.dataframe[0].proto.id
    wire(app, edited={2: {'Mar': '91'}})
    wire(app)
    assert app.dataframe[0].proto.id == editor
    wire(app, edited={2: {'Mar': '92'}})
    assert current(app).rows[2][3] == '92'


def test_no_action_column_on_other_imported_tables():
    app = launch(COMPACT, key='utility_analysis')
    assert not app.dataframe[0].proto.button_click_widgets
    assert current(app) == COMPACT


def test_saved_and_reloaded_rows_keep_blanks_without_ui_values(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active
    from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = launch(COMPACT)
    wire(app, 0, BELOW)
    wire(app)
    wire(app, 3, BELOW)
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 10)),
                    blocks=(app.session_state['block'],))
    active.save('b' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    saved = active.load('b' * 32, draft.profile.contract, draft.profile.key, draft.period).draft
    assert saved == draft
    reopened = launch(saved.blocks[0].extra_tables[0])
    assert current(reopened) == current(app)
    assert native_rows(current(reopened)) == (current(app).columns, *current(app).rows)


@pytest.mark.parametrize('commit_completed', [False, True])
def test_newer_delivery_before_seed_rebase_is_not_lost(commit_completed):
    app = launch(COMPACT)
    original = app.session_state['block']
    wire(app, 0, ABOVE, edited={2: {'Mar': 'first'}})
    if not commit_completed:
        app.session_state['block'] = original
    wire(app, edited={2: {'Mar': 'newer delivered'}})
    expected = list(COMPACT.rows)
    expected[2] = ('', '7', '8', 'newer delivered', '10', '11', '12')
    assert current(app).rows == (BLANK, *expected)
    wire(app)
    assert current(app).rows == (BLANK, *expected)


def test_interrupted_insert_preserves_newer_delete_of_its_anchor():
    app = launch(COMPACT)
    original = app.session_state['block']
    wire(app, 1, ABOVE)
    app.session_state['block'] = original
    wire(app, deleted=[1], edited={2: {'Mar': 'newer'}})
    expected = list(COMPACT.rows)
    expected[2] = ('', '7', '8', 'newer', '10', '11', '12')
    del expected[1]
    expected.insert(1, BLANK)
    assert current(app).rows == tuple(expected)
    wire(app)
    assert current(app).rows == tuple(expected)


def test_canonical_commit_refreshes_native_grid_without_an_extra_business_click():
    script = APP + "\nfrom app.monthly_report_guided import _refresh_period_editors_after_commit\n_refresh_period_editors_after_commit('row_probe')\n"
    app = AppTest.from_string(script)
    from app.monthly_report_model import ResolvedBlock
    app.session_state['block'] = ResolvedBlock('work_orders', 'Last month', extra_tables=(COMPACT,))
    app.run()
    assert not app.exception
    old_id = app.dataframe[0].proto.id
    wire(app, 0, ABOVE, edited={2: {'Mar': '91'}})
    assert app.dataframe[0].proto.id != old_id
    assert current(app).rows[0] == BLANK and current(app).rows[3][3] == '91'
    assert len(app.dataframe[0].value) == 6  # Already refreshed after canonical commit.
    wire(app, 0, BELOW)
    assert current(app).rows[:2] == (BLANK, BLANK)
    assert len(app.dataframe[0].value) == 7


def test_retired_grid_caches_are_bounded_and_helper_columns_cannot_be_edited():
    app = launch(COMPACT)
    for _ in range(4):
        wire(app, 0, ABOVE)
        wire(app)
    caches = [value for name, value in app.session_state.filtered_state.items()
              if name.startswith('row_probe_edit_work_orders_imported_0_')
              and name.endswith(('_data', '_data_seed'))]
    assert len(caches) == 2
    config = json.loads(app.dataframe[0].proto.columns)
    ids = [column for column in config.values() if column.get('hidden') and column.get('disabled')]
    assert len(ids) == 1


def test_multiple_tables_and_colliding_source_column_names_preserve_all_data():
    app = launch(COMPACT)
    block = app.session_state['block']
    collision = ReportTable(('__work_order_row_id', '__work_order_row_action'),
                            (('source ID', 'source action text'),), 'synthetic:other-frame')
    app.session_state['block'] = replace(block, extra_tables=(COMPACT, collision),
                                        references=('synthetic:source-reference',))
    app.run()
    before = app.session_state['block']
    wire(app, 0, ABOVE, proto=app.dataframe[1].proto)
    changed = app.session_state['block']
    assert changed.extra_tables[0] == COMPACT and changed.references == before.references
    assert changed.extra_tables[1] == replace(collision, rows=(('', ''), *collision.rows))


def test_actual_report_docx_contains_only_original_columns_and_explicit_blank_rows():
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_model import ReportPeriod, default_sections, synthetic_draft, synthetic_profiles
    app = launch(COMPACT)
    wire(app, 0, ABOVE)
    wire(app)
    wire(app, 3, BELOW)
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 10)),
                    sections=tuple(replace(section, included=any(spec.key == 'work_orders' for spec in section.blocks))
                                   for section in default_sections()),
                    blocks=(app.session_state['block'],))
    document = Document(BytesIO(_build_docx(draft)))
    rows = [tuple(tuple(cell.text for cell in row.cells) for row in table.rows) for table in document.tables]
    expected = (COMPACT.columns, *current(app).rows)
    assert expected in rows
    assert not any('Insert blank' in cell or '__work_order_row_' in cell
                   for table in rows for row in table for cell in row)


def test_value_equal_delete_and_readd_gets_fresh_blank_occurrence_actions():
    app = launch(replace(COMPACT, rows=(BLANK,)))
    old = app.dataframe[0].proto
    wire(app, deleted=[0], added=[dict.fromkeys(COLUMNS, '')])
    assert current(app).rows == (BLANK,)
    wire(app)
    assert app.dataframe[0].proto.id != old.id
    wire(app, 0, ABOVE, proto=old)
    assert current(app).rows == (BLANK,)
    wire(app, 0, BELOW)
    assert current(app).rows == (BLANK, BLANK)
