"""Proposal/onsite cards expose every source field through one native editor."""
from dataclasses import replace
from datetime import date
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportTable, ResolvedBlock, default_sections


SCRIPT = '''
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportPeriod, ReportTable, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
draft = st.session_state.setdefault('draft', synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)))
block = st.session_state.setdefault('block', INITIAL)
spec = SPEC
changed = _edit_content(spec, block, SimpleNamespace(profile=draft.profile), 'row_test', {}, _field, draft)
st.session_state['result'] = changed
if st.session_state.get('commit', True):
    st.session_state['block'] = changed
'''


PROPOSAL_COLUMNS = ('Proposal #', 'Facility', 'Vendor', 'Work Description', 'Status', 'Decision', 'Technical Notes')
PROPOSAL_ROWS = (('0007', 'North', 'Synthetic vendor', 'Long proposal scope ' * 12, 'On hold', 'Awaiting review', 'Keep 45 gpm'),
                 ('0008', 'South', 'Other vendor', 'Long proposal scope ' * 12, 'Declined', 'Alternative requested', 'Keep second source note'))


def example(key='proposals', rows=None, *, extra=False):
    if key == 'proposals':
        spec = BlockSpec(key, 'table', columns=tuple(ColumnSpec(str(n), title) for n, title in enumerate(PROPOSAL_COLUMNS)))
        rows = PROPOSAL_ROWS if rows is None else rows
    else:
        spec = next(spec for section in default_sections() for spec in section.blocks if spec.key == key)
        rows = (('00042', '2026-09-12', 'North plant', 'Inspect pump\nRetain the second line', 'P-0007'),) if rows is None else rows
    block = ResolvedBlock(key, 'This month', rows=rows, references=('synthetic-owned-source',))
    if extra:
        block = replace(block, rows=(), extra_tables=(ReportTable(tuple(column.title for column in spec.columns), rows, 'native-table-origin'),))
    return spec, block


def workspace(key='proposals', rows=None, *, extra=False):
    spec, block = example(key, rows, extra=extra)
    return AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()


def button(app, label, index=0):
    return [item for item in app.button if item.label == label][index]


def field(app, title, kind='text_input'):
    return next(item for item in getattr(app, kind) if item.label == title)


def test_proposal_summary_exposes_identifiers_status_and_decision_without_a_grid():
    app = workspace()
    assert not app.exception and not app.dataframe
    captions = '\n'.join(item.value for item in app.caption)
    assert all(value in captions for value in ('0007', 'North', 'Synthetic vendor', 'Status: On hold', 'Decision: Awaiting review'))
    button(app, 'Edit proposal').click().run()
    assert not app.exception and not app.dataframe
    labels = {item.label for kind in ('text_input', 'text_area') for item in getattr(app, kind)}
    assert labels == set(PROPOSAL_COLUMNS)
    assert field(app, 'Status').value == 'On hold'
    assert field(app, 'Decision').value == 'Awaiting review'
    assert field(app, 'Work Description', 'text_area').value == PROPOSAL_ROWS[0][3]


def test_same_event_edit_then_close_reopen_keeps_native_identity_and_exact_other_row():
    app = workspace()
    before = app.session_state['block']
    button(app, 'Edit proposal').click().run()
    identity = field(app, 'Decision').proto.id
    field(app, 'Decision').set_value('Approved subject to the named condition.')
    button(app, 'Close editing').click().run()
    assert not app.exception and not app.text_input
    result = app.session_state['block']
    assert result.rows[0][5] == 'Approved subject to the named condition.'
    assert result.rows[1] == before.rows[1] and result.references == before.references
    button(app, 'Edit proposal').click().run()
    assert field(app, 'Decision').value == result.rows[0][5]
    assert field(app, 'Decision').proto.id == identity
    field(app, 'Status').set_value('Owner-specific status remains literal').run()
    assert app.session_state['block'].rows[0][4] == 'Owner-specific status remains literal'


def test_clicking_other_same_title_row_captures_pending_text_without_changing_row_identity():
    app = workspace()
    button(app, 'Edit proposal').click().run()
    field(app, 'Technical Notes', 'text_area').set_value('First row note delivered with other Edit.')
    button(app, 'Edit proposal').click().run()  # Only the second row offers Edit while the first is open.
    assert not app.exception
    assert app.session_state['block'].rows[0][-1] == 'First row note delivered with other Edit.'
    assert field(app, 'Proposal #').value == '0008'
    field(app, 'Decision').set_value('Second row decision').run()
    assert app.session_state['block'].rows[1][5] == 'Second row decision'
    assert app.session_state['block'].rows[0][5] == PROPOSAL_ROWS[0][5]


def test_remove_another_row_captures_open_native_edit_and_keeps_correct_source_row():
    app = workspace()
    button(app, 'Edit proposal').click().run()
    field(app, 'Technical Notes', 'text_area').set_value('Retain this edit when removing another row.')
    button(app, 'Remove proposal', 1).click().run()
    assert not app.exception
    assert len(app.session_state['block'].rows) == 1
    assert app.session_state['block'].rows[0][0] == '0007'
    assert app.session_state['block'].rows[0][-1] == 'Retain this edit when removing another row.'
    assert field(app, 'Proposal #').value == '0007'


def test_onsite_native_date_and_identifiers_remain_reachable_and_preserve_unknown_blanks():
    app = workspace('service_calls')
    assert not app.exception and not app.dataframe
    button(app, 'Edit onsite call').click().run()
    assert field(app, 'WO #').value == '00042'
    assert field(app, 'Tag #').value == 'P-0007'
    assert field(app, 'Finish Date', 'date_input').value == date(2026, 9, 12)
    field(app, 'Task Code-Description', 'text_area').set_value('Inspected pump; follow-up remains open.')
    field(app, 'Finish Date', 'date_input').set_value(None)
    button(app, 'Close editing').click().run()
    assert not app.exception
    assert app.session_state['block'].rows == (('00042', '', 'North plant', 'Inspected pump; follow-up remains open.', 'P-0007'),)


def test_recorded_unknown_onsite_date_stays_literal_and_its_native_input_does_not_change_type():
    rows = (('00042', 'Unknown', 'North plant', 'Inspect pump', 'P-0007'),)
    app = workspace('service_calls', rows)
    button(app, 'Edit onsite call').click().run()
    date_field = field(app, 'Finish Date')
    identity = date_field.proto.id
    assert date_field.value == 'Unknown'
    date_field.set_value('2026-09-12').run()
    assert not app.exception
    assert field(app, 'Finish Date').proto.id == identity
    assert app.session_state['block'].rows[0][1] == '2026-09-12'


def test_clearing_and_reentering_all_fields_retains_row_slot_native_identity_and_other_row():
    app = workspace()
    button(app, 'Edit proposal').click().run()
    identity = field(app, 'Proposal #').proto.id
    for kind in ('text_input', 'text_area'):
        for item in getattr(app, kind):
            item.set_value('')
    app.run()
    assert not app.exception and app.session_state['block'].rows == (PROPOSAL_ROWS[1],)
    assert field(app, 'Proposal #').proto.id == identity
    field(app, 'Proposal #').set_value('0009').run()
    assert field(app, 'Proposal #').proto.id == identity
    assert app.session_state['block'].rows[0][0] == '0009'
    assert app.session_state['block'].rows[1] == PROPOSAL_ROWS[1]


def test_ambiguous_imported_headings_are_corrected_before_row_entry_without_replaying_prices():
    spec, block = example(extra=True)
    table = ReportTable(('Work Description Cost Recommendation', 'Column 2', 'Column 3'),
                        (('Replace pump', '$500', 'Awaiting a decision'),), 'native-table-origin')
    block = replace(block, extra_tables=(table,))
    app = AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()
    assert not app.exception and not any(item.label == 'Edit proposal' for item in app.button)
    for item, title in zip(app.text_input, ('Work Description', 'Cost', 'Decision')):
        item.set_value(title)
    app.run()
    button(app, 'Use these column names').click().run()
    app.run()
    assert not app.exception
    corrected = app.session_state['block'].extra_tables[0]
    assert corrected.columns == ('Work Description', 'Decision')
    assert corrected.rows == (('Replace pump', 'Awaiting a decision'),)
    assert corrected.reference == table.reference
    button(app, 'Edit proposal').click().run()
    field(app, 'Decision').set_value('Approved scope').run()
    assert app.session_state['block'].extra_tables[0].rows == (('Replace pump', 'Approved scope'),)


def test_duplicate_source_headings_remain_distinct_in_native_edit_and_conflict_comparison():
    spec, block = example(extra=True)
    table = ReportTable(('Proposal #', 'Decision', 'Decision'), (('0007', 'Client', 'Internal'),), 'native-table-origin')
    block = replace(block, extra_tables=(table,))
    app = AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()
    button(app, 'Edit proposal').click().run()
    decisions = [item for item in app.text_input if item.label == 'Decision']
    decisions[1].set_value('Pending internal revision')
    incoming = replace(table, rows=(('0009', 'New client', 'New internal'),))
    app.session_state['block'] = replace(block, extra_tables=(incoming,))
    app.run()
    assert not app.exception
    assert tuple(app.dataframe[1].value.columns) == ('Proposal #', '2. Decision', '3. Decision')
    assert tuple(app.dataframe[1].value.iloc[0]) == ('0007', 'Client', 'Pending internal revision')
    button(app, 'Use row edits').click().run()
    result = app.session_state['block'].extra_tables[0]
    assert result.columns == table.columns and result.reference == table.reference
    assert result.rows == (('0007', 'Client', 'Pending internal revision'),)


def test_correcting_another_imported_table_keeps_open_row_identity_and_delivered_text():
    spec, block = example(extra=True)
    ambiguous = ReportTable(('Work Description Cost Recommendation', 'Column 2', 'Column 3'),
                            (('Replace pump', '$500', 'Awaiting a decision'),), 'second-origin')
    block = replace(block, extra_tables=(*block.extra_tables, ambiguous))
    app = AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()
    button(app, 'Edit proposal').click().run()
    identity = field(app, 'Decision').proto.id
    for item, title in zip([item for item in app.text_input if item.label.endswith(' heading')],
                           ('Work Description', 'Cost', 'Decision')):
        item.set_value(title)
    app.run()
    field(app, 'Decision').set_value('Delivered with other table correction')
    button(app, 'Use these column names').click().run()
    app.run()
    assert not app.exception and field(app, 'Decision').proto.id == identity
    assert app.session_state['block'].extra_tables[0].rows[0][5] == 'Delivered with other table correction'
    assert app.session_state['block'].extra_tables[1].columns == ('Work Description', 'Decision')


@pytest.mark.parametrize('key,label', [('proposals', 'proposal'), ('service_calls', 'onsite call')])
def test_add_blank_close_and_remove_do_not_create_phantom_rows(key, label):
    app = workspace(key, ())
    original = app.session_state['block']
    button(app, 'Add ' + label).click().run()
    assert not app.exception and app.session_state['block'] == original
    button(app, 'Close editing').click().run()
    assert app.session_state['block'] == original
    button(app, 'Add ' + label).click().run()
    app.text_input[0].set_value('0009').run()
    assert len(app.session_state['block'].rows) == 1
    button(app, 'Close editing').click().run()
    stale_remove = button(app, 'Remove ' + label)
    stale_remove.click().run()
    assert not app.exception and not app.session_state['block'].rows
    stale_remove.click().run()
    assert not app.exception and not app.session_state['block'].rows


def test_consecutive_row_edits_before_parent_commit_keep_the_whole_delivered_row():
    app = workspace()
    button(app, 'Edit proposal').click().run()
    original = app.session_state['block']
    app.session_state['commit'] = False
    field(app, 'Status').set_value('Approved').run()
    field(app, 'Decision').set_value('Proceed with scope only').run()
    assert app.session_state['block'] == original
    assert app.session_state['result'].rows[0][4:6] == ('Approved', 'Proceed with scope only')
    app.session_state['commit'] = True
    button(app, 'Close editing').click().run()
    assert app.session_state['block'].rows[0][4:6] == ('Approved', 'Proceed with scope only')


def test_changed_canonical_table_keeps_both_versions_until_explicit_version_bound_choice():
    app = workspace()
    button(app, 'Edit proposal').click().run()
    field(app, 'Decision').set_value('Pending human edit.')
    original = app.session_state['block']
    changed = replace(original, rows=(('0099', *original.rows[0][1:]), original.rows[1]))
    app.session_state['block'] = changed
    app.run()
    assert not app.exception and app.session_state['block'] == changed
    assert any('Both versions are kept' in item.value for item in app.warning)
    assert len(app.dataframe) == 2
    assert app.dataframe[1].value.iloc[0]['Decision'] == 'Pending human edit.'
    button(app, 'Keep current table').click().run()
    assert not app.exception and app.session_state['block'] == changed


@pytest.mark.parametrize('boundary', ['report', 'source'])
def test_old_native_action_cannot_edit_replaced_report_or_source(boundary):
    app = workspace()
    button(app, 'Edit proposal').click().run()
    old_close = button(app, 'Close editing')
    field(app, 'Decision').set_value('Earlier source or report only.')
    original = app.session_state['block']
    incoming = replace(original, rows=(('0099', *original.rows[0][1:]),))
    if boundary == 'report':
        app.session_state['row_test_rich_text_epoch'] = 'new-report-incarnation'
    else:
        incoming = replace(incoming, references=('replacement-source',))
    app.session_state['block'] = incoming
    old_close.click().run()
    assert not app.exception and app.session_state['block'] == incoming
    assert not app.text_input and not app.text_area
    button(app, 'Edit proposal').click().run()
    assert field(app, 'Proposal #').value == '0099'
    assert field(app, 'Decision').value == PROPOSAL_ROWS[0][5]


@pytest.mark.parametrize('extra', [False, True])
def test_schema_provenance_durable_rows_and_actual_word_output_remain_editable(monkeypatch, tmp_path, extra):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = workspace(extra=extra)
    original = app.session_state['block']
    button(app, 'Edit proposal').click().run()
    field(app, 'Decision').set_value('Conditional approval: retain source scope').run()
    block = app.session_state['block']
    assert block.references == original.references
    if extra:
        assert block.extra_tables[0].reference == original.extra_tables[0].reference
        assert block.extra_tables[0].columns == PROPOSAL_COLUMNS
    spec, _ = example()
    draft = app.session_state['draft']
    section = next(section for section in default_sections() if section.key == 'proposals')
    draft = replace(draft, sections=(replace(section, blocks=(spec,)),), blocks=(block,))
    # The synthetic source identifier is retained for correction. This test
    # supplies no actual source object and asserts output under the existing
    # nonblocking historical-reference qualification only.
    from app.monthly_report_checks import preflight
    assert not any(check.blocking for check in preflight(draft))
    kept = active.save('f' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('f' * 32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft and kept.revision == loaded.revision
    document = Document(BytesIO(assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)))
    native = next(table for table in document.tables if 'Proposal #' in [cell.text for cell in table.rows[0].cells])
    assert tuple(cell.text for cell in native.rows[0].cells) == PROPOSAL_COLUMNS
    assert tuple(cell.text for cell in native.rows[1].cells)[0] == '0007'
    assert tuple(cell.text for cell in native.rows[1].cells)[5] == 'Conditional approval: retain source scope'
    assert tuple(cell.text for cell in native.rows[2].cells) == PROPOSAL_ROWS[1]
