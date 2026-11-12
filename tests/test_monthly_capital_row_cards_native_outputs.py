"""Native edited capital and end-of-life imported rows reach durable DOCX/PDF."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app.monthly_report_docx import generate_report
from app.monthly_report_model import ReportTable, default_sections
from conftest import requires_libreoffice
from test_monthly_report_row_cards_ui import SCRIPT, button, example


@requires_libreoffice
@pytest.mark.parametrize('key,noun,sentinel', [
    ('capital_renewal', 'capital item', 'ROW-CAPITAL-EDIT-301'),
    ('end_of_life', 'replacement item', 'ROW-REPLACEMENT-EDIT-301'),
])
def test_imported_native_edit_survives_save_reload_and_actual_word_pdf(
        key, noun, sentinel, tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'isolated-store'))
    spec, block = example(key, ())
    source = ReportTable(
        ('Asset', 'Decision', 'Decision', ''),
        (('CAP-001', 'Keep original decision', 'Review pending', 'Keep unlabeled value'),),
        'synthetic-capital-import-reference')
    block = replace(block, extra_tables=(source,))
    app = AppTest.from_string(SCRIPT.replace('INITIAL', repr(block)).replace('SPEC', repr(spec))).run()
    assert not app.exception and not app.dataframe
    button(app, 'Edit ' + noun).click().run()
    physical_decisions = [w for w in app.text_input if w.label == 'Decision']
    assert len(physical_decisions) == 2
    physical_decisions[1].set_value(sentinel)
    button(app, 'Close editing').click().run()  # No separate field blur.
    edited = app.session_state['block']
    assert edited.rows == ()
    assert edited.extra_tables[0].columns == source.columns
    assert edited.extra_tables[0].reference == source.reference
    assert edited.extra_tables[0].rows == (
        ('CAP-001', 'Keep original decision', sentinel, 'Keep unlabeled value'),)
    assert edited.references == block.references

    section = next(section for section in default_sections() if section.key == 'capital')
    draft = replace(app.session_state['draft'],
                    sections=(replace(section, blocks=(spec,)),), blocks=(edited,))
    active.save('c' * 32, draft, expected_revision=0, base_snapshot_revision=0)
    loaded = active.load('c' * 32, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == draft
    assert loaded.draft.blocks[0].extra_tables[0].columns == source.columns
    assert loaded.draft.blocks[0].extra_tables[0].reference == source.reference
    package = generate_report(loaded.draft,
                              acknowledged_fingerprint=loaded.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error

    (tmp_path / (key + '.docx')).write_bytes(package.docx)
    (tmp_path / (key + '.pdf')).write_bytes(package.pdf)
    doc = Document(BytesIO(package.docx))
    cells = [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
    assert cells.count(sentinel) == 1
    assert cells.count('Keep original decision') == 1
    assert cells.count('Keep unlabeled value') == 1
    with pymupdf.open(stream=package.pdf, filetype='pdf') as pdf:
        output_text = ''.join(page.get_text().replace('\n', '') for page in pdf)
        assert output_text.count(sentinel) == 1
        assert 'Keep original decision' in output_text
        assert 'Keep unlabeled value' in output_text
