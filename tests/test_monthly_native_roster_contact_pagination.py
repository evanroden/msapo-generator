"""Synthetic native roster keeps vendor/contact groups without rebuilding source cells."""
from dataclasses import replace
from io import BytesIO

import pytest
from docx import Document

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from test_monthly_roster_contact_pagination import keeps

COLUMNS = ('Discipline', 'Synthetic Location', 'MSA')
ROWS = (('Electrical', 'Synthetic Vendor', 'X'), ('Contact Name', 'Synthetic Person', ''),
        ('Contact Number', '555-0100', ''), ('', '', ''),
        ('Contact Name', 'Synthetic Dispatch', ''), ('Contact Number', '555-0101', ''))


def fixture(tmp_path):
    doc = Document()
    doc.add_heading('SUBCONTRACTOR STATUS', 1)
    table = doc.add_table(rows=1, cols=3)
    table.style = 'Table Grid'
    for cell, text in zip(table.rows[0].cells, COLUMNS):
        cell.text = text
    for values in ROWS:
        for cell, text in zip(table.add_row().cells, values):
            cell.text = text
            cell.paragraphs[0].runs[0].bold = True
    path = tmp_path / 'source.docx'
    doc.save(path)
    inspection = inspect_docx(path)
    item = next(item for item in inspection.items if item.kind == 'table')
    from app.monthly_report_sections import table_without_prices
    from app.monthly_report_model import ResolvedBlock
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f'docx:{inspection.sha256}:{item.id}')
    blocks = (ResolvedBlock('subcontractor_matrix', 'This month', extra_tables=(supplied,)),)
    section = next(s for s in default_sections() if s.key == 'subcontractors')
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 11), 'Synthetic Reviewer',
                        (section,), blocks, synthetic=True)
    return path, draft


@pytest.mark.parametrize('edited', [False, True])
def test_source_proved_or_rebuilt_native_roster_keeps_contact_pairs(tmp_path, edited):
    path, draft = fixture(tmp_path)
    before = path.read_bytes()
    if edited:
        block = draft.blocks[0]
        table = block.extra_tables[0]
        rows = tuple(('Mechanical', *row[1:]) if n == 0 else row for n, row in enumerate(table.rows))
        draft = replace(draft, blocks=(replace(block, extra_tables=(replace(table, rows=rows),)),))
    raw = build_native_docx(draft, path, section_key='subcontractors')
    doc = Document(BytesIO(raw))
    table = doc.tables[0]
    assert keeps(table)[1:] == [True, True, False, False, True, False]
    expected = draft.blocks[0].extra_tables[0]
    assert tuple(tuple(c.text for c in r.cells) for r in table.rows) == (expected.columns, *expected.rows)
    assert table._tbl.tblPr.xml == Document(path).tables[0]._tbl.tblPr.xml
    assert table._tbl.tblGrid.xml == Document(path).tables[0]._tbl.tblGrid.xml
    if not edited:
        assert all(r.bold for row in table.rows[1:] for c in row.cells for p in c.paragraphs for r in p.runs)
    assert path.read_bytes() == before


def test_omitted_roster_cannot_retain_old_contacts(tmp_path):
    path, draft = fixture(tmp_path)
    draft = replace(draft, blocks=(replace(draft.blocks[0], source='Omit'),))
    doc = Document(BytesIO(build_native_docx(draft, path, section_key='subcontractors')))
    assert all('Synthetic Person' not in t._tbl.xml for t in doc.tables)
