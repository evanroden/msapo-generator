"""Compact contact editing preserves synthetic source rows, including blanks."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable, ResolvedBlock


SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import ReportPeriod, BlockSpec, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_contacts
block = st.session_state['block']
spec = BlockSpec(block.key, 'image_page')
draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
    prepared_by='Synthetic Reviewer', blocks=(block,))
# Match the native editor's canonical rerun destination.
draft = st.session_state.setdefault('compact_draft', draft)
changed = edit_contacts(draft, spec, draft.blocks[0], 'compact', {}, _field, show_preview=False)
st.session_state['compact_draft'] = replace(draft, blocks=(changed,))
st.session_state['block'] = changed
'''


def workspace(tables, *, vendor=True):
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    block = ResolvedBlock('subcontractor_matrix' if vendor else 'contact_matrix',
                          'This month', extra_tables=tuple(tables), references=('synthetic-source',))
    app.session_state['block'] = block
    app.session_state['original'] = block
    app.run()
    assert not app.exception
    return app


def block(app):
    assert not app.exception
    return app.session_state['block']


def buttons(app, action):
    return [b for b in app.button if b.label in (action + ' contact', action + ' vendor contact')]


def click(app, action, index=0):
    buttons(app, action)[index].click().run()
    assert not app.exception
    return app


def close(app):
    next(b for b in app.button if b.label == 'Close editing').click().run()
    assert not app.exception


def field(app, label, index=0):
    return [v for v in app.text_input if v.label == label][index]


@pytest.mark.parametrize('vendor', [False, True])
def test_retained_blank_rows_start_compact_and_view_is_exactly_immutable(vendor):
    rows = tuple((f'Invented Person {i+1}', 'Synthetic role', '202-555-0100')
                 if i not in (51, 55) else ('', '', '') for i in range(56))
    table = ReportTable(('Name', 'Role', 'Phone'), rows, 'synthetic-source:table-1')
    app = workspace((table,), vendor=vendor)
    assert not app.text_input
    assert not buttons(app, 'Remove')
    assert len(buttons(app, 'Edit')) == 56
    assert block(app) == app.session_state['original']
    app.run()
    assert not app.text_input and block(app).extra_tables == (table,)
    def card_path(node, suffix, path=()):
        proto = getattr(node, 'proto', None)
        if proto is not None and getattr(proto, 'id', '').endswith(suffix):
            return path
        for index, child in getattr(node, 'children', {}).items():
            found = card_path(child, suffix, path + (index,))
            if found is not None:
                return found
    original_slot = card_path(app._tree, '_row_0_51')
    assert original_slot is not None
    click(app, 'Edit', 51)
    assert card_path(app._tree, '_active_editor') == original_slot  # No long-list jump.
    assert len(buttons(app, 'Edit')) == 55 and len(app.text_input) == 3
    assert block(app).extra_tables == (table,)
    close(app)
    assert len(buttons(app, 'Edit')) == 56 and block(app).extra_tables == (table,)


def test_switch_between_tables_and_close_capture_pending_native_fields():
    first = ReportTable(('Name', 'Phone'), (('Alex Invented', '202-555-0101'),), 'source:first')
    second = ReportTable(('Name', 'Phone'), (('Blair Invented', '202-555-0102'),), 'source:second')
    app = workspace((first, second))
    click(app, 'Edit')
    assert len(app.text_input) == 2 and len(buttons(app, 'Remove')) == 1
    field(app, 'Phone').set_value('202-555-0199')
    click(app, 'Edit')  # The first table is already active; the other row owns Edit.
    assert len(app.text_input) == 2
    assert field(app, 'Name').value == 'Blair Invented'
    assert block(app).extra_tables[0].rows == (('Alex Invented', '202-555-0199'),)
    field(app, 'Name').set_value('Blair Deliberately Corrected')
    close(app)
    assert not app.text_input and not buttons(app, 'Remove')
    assert block(app).extra_tables[1].rows == (('Blair Deliberately Corrected', '202-555-0102'),)
    assert tuple(t.reference for t in block(app).extra_tables) == ('source:first', 'source:second')
    assert app.session_state['original'].extra_tables == (first, second)


def test_custom_duplicate_and_blank_headings_keep_separate_original_columns():
    table = ReportTable(('Name', '', 'Detail', 'Detail'),
                        (('Casey Invented', 'blank heading value', 'first detail', 'second detail'),),
                        'source:custom')
    app = workspace((table,))
    click(app, 'Edit')
    assert len(app.text_input) == 4
    field(app, 'Detail 2').set_value('changed blank-heading value')
    # Equal headings must remain separate widgets, even if display labels differ.
    detail_widgets = [w for w in app.text_input if w.value in ('first detail', 'second detail')]
    assert len(detail_widgets) == 2
    detail_widgets[1].set_value('changed second detail')
    close(app)
    result = block(app).extra_tables[0]
    assert result.columns == table.columns and result.reference == table.reference
    assert result.rows == (('Casey Invented', 'changed blank-heading value', 'first detail', 'changed second detail'),)


def test_open_and_clear_retained_blank_row_never_deletes_any_source_row():
    table = ReportTable(('Name', 'Phone'), (('', ''), ('Keep Invented', '202-555-0100'), ('', '')), 'source:blanks')
    app = workspace((table,))
    click(app, 'Edit')
    close(app)
    assert block(app).extra_tables == (table,)
    click(app, 'Edit', 1)
    field(app, 'Name').set_value('')
    field(app, 'Phone').set_value('')
    close(app)
    assert block(app).extra_tables[0] == replace(table, rows=(('', ''), ('', ''), ('', '')))
    assert len(buttons(app, 'Edit')) == 3


def test_explicit_add_opens_only_temporary_blank_draft_and_close_leaves_sources_exact():
    table = ReportTable(('Name', 'Phone'), (('', ''), ('Dana Invented', '202-555-0100')), 'source:add')
    app = workspace((table,))
    click(app, 'Add')
    assert len(app.text_input) == 2
    assert all(w.value == '' for w in app.text_input)
    assert block(app).extra_tables == (table,)
    close(app)
    assert not app.text_input and block(app).extra_tables == (table,)
    click(app, 'Add')
    field(app, 'Name').set_value('New Explicit Invented')
    close(app)
    assert block(app).extra_tables[0].rows == (*table.rows, ('New Explicit Invented', ''))
    assert app.session_state['original'].extra_tables == (table,)


def test_duplicate_row_values_keep_occurrence_identity_through_switch_and_remove():
    row = ('Duplicate Invented', '202-555-0100')
    table = ReportTable(('Name', 'Phone'), (row, row, ('', '')), 'source:duplicates')
    app = workspace((table,))
    click(app, 'Edit', 1)
    field(app, 'Phone').set_value('202-555-0198')
    close(app)
    assert block(app).extra_tables[0].rows == (row, ('Duplicate Invented', '202-555-0198'), ('', ''))
    click(app, 'Edit')
    click(app, 'Remove')
    assert block(app).extra_tables[0].rows == (('Duplicate Invented', '202-555-0198'), ('', ''))
    assert app.session_state['original'].extra_tables == (table,)


def test_reopening_shifted_row_after_remove_never_reuses_removed_widget_values():
    table = ReportTable(('Name', 'Phone'),
                        (('First Invented', '202-555-0101'), ('Second Invented', '202-555-0102')),
                        'source:shift')
    app = workspace((table,))
    click(app, 'Edit')
    field(app, 'Phone').set_value('202-555-0199')
    click(app, 'Remove')
    assert block(app).extra_tables[0].rows == (table.rows[1],)
    click(app, 'Edit')
    assert field(app, 'Name').value == 'Second Invented'
    assert field(app, 'Phone').value == '202-555-0102'
    close(app)
    assert block(app).extra_tables[0].rows == (table.rows[1],)


@pytest.mark.parametrize('native', [False, True])
def test_no_edit_open_close_keeps_generated_word_xml_and_original_source_exact(tmp_path, native):
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import _build_docx
    from app.monthly_report_native_layout import build_native_docx
    from tests.test_monthly_report_contact_headers import native_contact_source
    from tests.test_monthly_report_generic_contact_page import _draft

    table = ReportTable(('Name', '', 'Custom detail'),
                        (('Output Invented', 'Retain empty-heading value', 'Retain custom value'), ('', '', '')),
                        'source:output')
    app = workspace((table,), vendor=False)
    original = app.session_state['original']
    seed = _draft(chart=False)
    before = replace(seed, blocks=tuple(original if b.key == original.key else b for b in seed.blocks))
    source = native_contact_source(tmp_path / 'synthetic-native.docx')
    original_source = source.read_bytes()
    def render(value):
        raw = build_native_docx(value, source, master=True) if native else _build_docx(value)
        return Document(BytesIO(raw)).element.xml
    before_xml = render(before)
    click(app, 'Edit')
    close(app)
    assert block(app) == original
    after = replace(before, blocks=tuple(block(app) if b.key == original.key else b for b in before.blocks))
    assert render(after) == before_xml
    assert 'Retain custom value' in before_xml
    assert 'Retain empty-heading value' in before_xml
    assert source.read_bytes() == original_source


@pytest.mark.parametrize('choice', ['Use pending contact edits', 'Keep current contacts'])
def test_conflict_recovery_is_actionable_and_stale_choice_cannot_replace_newer_rows(choice):
    table = ReportTable(('Name', 'Phone'), (('Original Invented', '202-555-0100'),), 'source:conflict')
    app = workspace((table,))
    click(app, 'Edit')
    field(app, 'Name').set_value('Pending Invented')
    draft = app.session_state['compact_draft']
    external = replace(draft.blocks[0], extra_tables=(replace(table, rows=(('External Invented', '202-555-0100'),)),))
    app.session_state['compact_draft'] = replace(draft, blocks=(external,))
    click(app, 'Remove')
    assert block(app) == external
    assert any('Compare both versions' in w.value for w in app.warning)
    recovery = next(b for b in app.button if b.label == choice)
    # Another canonical change occurs after this recovery control was rendered.
    newest = replace(external, extra_tables=(replace(table, rows=(('Newest Invented', '202-555-0100'),)),))
    app.session_state['compact_draft'] = replace(draft, blocks=(newest,))
    recovery.click().run()
    assert block(app) == newest
    assert any('Compare both versions' in w.value for w in app.warning)
    next(b for b in app.button if b.label == choice).click().run()
    if choice == 'Use pending contact edits':
        # Recovery restores fields only, never replays the pending Remove.
        assert block(app).extra_tables[0].rows == (('Pending Invented', '202-555-0100'),)
    else:
        assert block(app) == newest
    assert not app.warning
    assert not app.text_input
    assert len(buttons(app, 'Edit')) == 1
