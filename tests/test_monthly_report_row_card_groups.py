"""A delivered row edit survives switching between tables in one block."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from conftest import requires_libreoffice
from test_monthly_report_row_cards_ui import SCRIPT, example, field


CASES = [('proposals', 'proposal', 'Technical Notes'),
         ('service_calls', 'onsite call', 'Task Code-Description')]


def workspace(key, *, primary=False):
    spec, original = example(key, extra=True)
    first = replace(original.extra_tables[0], rows=(original.extra_tables[0].rows[0],),
                    reference='synthetic-table-one')
    second = replace(first, rows=(('SECOND-002', *first.rows[0][1:]),),
                     reference='synthetic-table-two')
    block = replace(original, rows=second.rows if primary else (),
                    extra_tables=(first,) if primary else (first, second))
    app = AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()
    assert not app.exception
    return app, block


def control(app, label, table):
    marker = '_rows_' if table == 'primary' else f'_extra_{table}_'
    return next(item for item in app.button if item.label == label and marker in item.key)


def one_editor(app):
    assert not app.exception
    assert len([item for item in app.button if item.label == 'Close editing']) == 1


def rows(block, table):
    return block.rows if table == 'primary' else block.extra_tables[table].rows


@pytest.mark.parametrize('key,noun,text', CASES)
@pytest.mark.parametrize('primary', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_switch_captures_same_event_text_and_preserves_both_tables(key, noun, text, primary, reverse):
    app, original = workspace(key, primary=primary)
    first, second = (0, 'primary' if primary else 1)
    if reverse:
        first, second = second, first
    control(app, 'Edit ' + noun, first).click().run()
    one_editor(app)
    identity = field(app, text, 'text_area').proto.id
    field(app, text, 'text_area').set_value('Delivered with the other table Edit.')
    control(app, 'Edit ' + noun, second).click().run()
    one_editor(app)
    changed = app.session_state['block']
    assert 'Delivered with the other table Edit.' in rows(changed, first)[0]
    assert rows(changed, second) == rows(original, second)
    assert changed.references == original.references
    assert tuple((t.columns, t.reference) for t in changed.extra_tables) == tuple(
        (t.columns, t.reference) for t in original.extra_tables)
    control(app, 'Edit ' + noun, first).click().run()
    one_editor(app)
    assert field(app, text, 'text_area').proto.id == identity
    assert field(app, text, 'text_area').value == 'Delivered with the other table Edit.'
    assert app.session_state['block'] == changed


@pytest.mark.parametrize('key,noun,text', CASES)
def test_empty_add_switch_closes_only_the_draft_without_creating_a_source_row(key, noun, text):
    app, original = workspace(key)
    control(app, 'Add ' + noun, 0).click().run()
    one_editor(app)
    assert app.session_state['block'] == original
    control(app, 'Edit ' + noun, 1).click().run()
    one_editor(app)
    assert app.session_state['block'] == original
    control(app, 'Add ' + noun, 0).click().run()
    one_editor(app)
    field(app, text, 'text_area').set_value('Explicitly entered new synthetic row.')
    control(app, 'Edit ' + noun, 1).click().run()
    one_editor(app)
    changed = app.session_state['block']
    assert len(changed.extra_tables[0].rows) == len(original.extra_tables[0].rows) + 1
    assert changed.extra_tables[0].rows[:-1] == original.extra_tables[0].rows
    assert 'Explicitly entered new synthetic row.' in changed.extra_tables[0].rows[-1]
    assert changed.extra_tables[1] == original.extra_tables[1]


@pytest.mark.parametrize('key,noun,text', CASES)
def test_remove_in_another_table_captures_delivered_text_and_keeps_current_editor(key, noun, text):
    app, original = workspace(key)
    control(app, 'Edit ' + noun, 0).click().run()
    identity = field(app, text, 'text_area').proto.id
    field(app, text, 'text_area').set_value('Retained while the other source row is removed.')
    control(app, 'Remove ' + noun, 1).click().run()
    one_editor(app)
    changed = app.session_state['block']
    assert 'Retained while the other source row is removed.' in changed.extra_tables[0].rows[0]
    assert not changed.extra_tables[1].rows
    assert changed.extra_tables[1].reference == original.extra_tables[1].reference
    assert field(app, text, 'text_area').proto.id == identity


@pytest.mark.parametrize('key,noun,text', CASES)
def test_opening_a_sibling_preserves_a_genuine_pending_table_conflict(key, noun, text):
    app, original = workspace(key)
    control(app, 'Edit ' + noun, 0).click().run()
    field(app, text, 'text_area').set_value('Pending correction remains recoverable.')
    first = original.extra_tables[0]
    replacement = replace(first, rows=(('REPLACEMENT-003', *first.rows[0][1:]),))
    current = replace(original, extra_tables=(replacement, original.extra_tables[1]))
    app.session_state['block'] = current
    app.run()
    assert not app.exception and app.session_state['block'] == current
    assert any('Both versions are kept' in item.value for item in app.warning)
    control(app, 'Edit ' + noun, 1).click().run()
    one_editor(app)
    assert app.session_state['block'] == current
    assert any('Both versions are kept' in item.value for item in app.warning)
    assert 'Pending correction remains recoverable.' in tuple(app.dataframe[1].value.iloc[0])


@pytest.mark.parametrize('boundary', ['report', 'source'])
def test_old_group_control_cannot_close_or_edit_replaced_report(boundary):
    app, original = workspace('proposals')
    control(app, 'Edit proposal', 0).click().run()
    old_open = control(app, 'Edit proposal', 1)
    field(app, 'Technical Notes', 'text_area').set_value('Earlier report fields.')
    replacement = replace(original, references=('replacement-synthetic-source',))
    if boundary == 'report':
        replacement = original
        app.session_state['row_test_rich_text_epoch'] = 'new-report-incarnation'
    app.session_state['block'] = replacement
    old_open.click().run()
    assert not app.exception and app.session_state['block'] == replacement
    assert not app.text_input and not app.text_area


@requires_libreoffice
def test_switched_rows_survive_save_reopen_and_actual_editable_word_pdf(tmp_path, monkeypatch):
    from app import monthly_report_active_work as active
    from app.monthly_report_docx import generate_report
    from app.monthly_report_model import default_sections
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'isolated-store'))
    app, original = workspace('proposals')
    control(app, 'Edit proposal', 0).click().run()
    field(app, 'Technical Notes', 'text_area').set_value('FIRST-TABLE-DELIVERED-NOTE')
    control(app, 'Edit proposal', 1).click().run()
    one_editor(app)
    field(app, 'Technical Notes', 'text_area').set_value('SECOND-TABLE-DELIVERED-NOTE')
    control(app, 'Close editing', 1).click().run()
    block = app.session_state['block']
    spec, _ = example('proposals')
    section = next(s for s in default_sections() if s.key == 'proposals')
    draft = replace(app.session_state['draft'], sections=(replace(section, blocks=(spec,)),), blocks=(block,))
    active.save('e' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('e' * 32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft
    package = generate_report(loaded.draft, acknowledged_fingerprint=loaded.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    (tmp_path / 'synthetic-grouped-rows.docx').write_bytes(package.docx)
    (tmp_path / 'synthetic-grouped-rows.pdf').write_bytes(package.pdf)
    word = Document(BytesIO(package.docx))
    columns = original.extra_tables[0].columns
    tables = [table for table in word.tables if tuple(c.text for c in table.rows[0].cells) == columns]
    assert len(tables) == 2
    for index, table in enumerate(tables):
        expected = (*original.extra_tables[index].rows[0][:-1],
                    ('FIRST', 'SECOND')[index] + '-TABLE-DELIVERED-NOTE')
        assert tuple(c.text for c in table.rows[1].cells) == expected
        assert block.extra_tables[index].columns == original.extra_tables[index].columns
        assert block.extra_tables[index].reference == original.extra_tables[index].reference
    with pymupdf.open(stream=package.pdf, filetype='pdf') as pdf:
        # The native table may wrap a note across lines. Every literal
        # sentinel character must survive; line wrapping is not lost content.
        text = ''.join(page.get_text().replace('\n', '') for page in pdf)
        assert 'FIRST-TABLE-DELIVERED-NOTE' in text and 'SECOND-TABLE-DELIVERED-NOTE' in text
    assert block.references == original.references
