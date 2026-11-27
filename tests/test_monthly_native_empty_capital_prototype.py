"""Unused priority prototypes do not accompany an explicitly supplied schedule."""
from dataclasses import replace
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_sections import table_without_prices


def fixture(tmp_path, special=None):
    doc = Document()
    doc.add_heading('PRIORITY CAPITAL RENEWAL LIST', 1)
    table = doc.add_table(rows=2, cols=4)
    for cell, text in zip(table.rows[0].cells, ('Equipment Description', 'End of Useful Life', 'Cost', 'Summary of deficiency')):
        cell.text = text
    table.rows[1].cells[0].text = 'Old synthetic monthly recommendation'
    if special == 'bookmark':
        table.cell(1, 0).paragraphs[0]._p.append(OxmlElement('w:bookmarkStart'))
    elif special == 'boundary':
        table.cell(1, 0).paragraphs[0]._p.get_or_add_pPr().append(OxmlElement('w:sectPr'))
    elif special == 'field':
        table.cell(1, 0).paragraphs[0]._p.append(OxmlElement('w:fldSimple'))
    elif special == 'header':
        table.cell(0, 0).text = 'Unknown equipment geometry'
    doc.add_heading('Contract Asset End of Useful Life Schedule', 2)
    schedule = doc.add_table(rows=2, cols=3)
    for row, values in zip(schedule.rows, [('Description', 'Designation', 'End of Useful Life'), ('Synthetic pump', 'P-1', '2032')]):
        for cell, text in zip(row.cells, values):
            cell.text = text
    path = tmp_path / 'source.docx'; doc.save(path)
    inspection = inspect_docx(path)
    item = [x for x in inspection.items if x.kind == 'table'][-1]
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f'docx:{inspection.sha256}:{item.id}')
    block = ResolvedBlock('end_of_life', 'This month', extra_tables=(supplied,))
    section = next(s for s in default_sections() if s.key == 'capital')
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 11), 'Synthetic Reviewer', (section,), (block,), synthetic=True)
    return path, draft


def render(path, draft):
    return Document(BytesIO(build_native_docx(draft, path, section_key='capital')))


def test_unused_proved_priority_prototype_removed_but_schedule_and_source_preserved(tmp_path):
    path, draft = fixture(tmp_path); before = path.read_bytes()
    result = render(path, draft)
    assert len(result.tables) == 1
    assert 'Synthetic pump' in result.tables[0]._tbl.xml
    assert len(result.sections) == len(Document(path).sections)
    assert path.read_bytes() == before


@pytest.mark.parametrize('special', ['bookmark', 'boundary', 'field', 'header'])
def test_unproved_or_boundary_bearing_priority_geometry_stays(tmp_path, special):
    path, draft = fixture(tmp_path, special)
    assert len(render(path, draft).tables) >= 2


def test_current_priority_values_cannot_lose_their_table(tmp_path):
    path, draft = fixture(tmp_path)
    current = ResolvedBlock('capital_renewal', 'This month', rows=(('Synthetic site', 'High', 'Current pump renewal'),))
    result = render(path, replace(draft, blocks=(*draft.blocks, current)))
    assert 'Current pump renewal' in result._element.xml


def test_no_explicit_schedule_does_not_authorize_cleanup(tmp_path):
    path, draft = fixture(tmp_path)
    assert len(render(path, replace(draft, blocks=())).tables) == 2


def test_unproved_schedule_reference_does_not_authorize_cleanup(tmp_path, monkeypatch):
    path, draft = fixture(tmp_path)
    b = draft.blocks[0]
    extra = replace(b.extra_tables[0], reference='synthetic:unproved')
    result = render(path, replace(draft, blocks=(replace(b, extra_tables=(extra,)),)))
    from app import monthly_report_native_empty_capital as cleanup
    monkeypatch.setattr(cleanup, 'remove_unused_priority_prototypes', lambda *args: None)
    baseline = render(path, replace(draft, blocks=(replace(b, extra_tables=(extra,)),)))
    assert result._element.xml == baseline._element.xml


def test_edited_schedule_is_not_unchanged_geometry_proof(tmp_path, monkeypatch):
    path, draft = fixture(tmp_path)
    b = draft.blocks[0]
    extra = replace(b.extra_tables[0], rows=(('Edited pump', 'P-2', '2040'),))
    result = render(path, replace(draft, blocks=(replace(b, extra_tables=(extra,)),)))
    from app import monthly_report_native_empty_capital as cleanup
    monkeypatch.setattr(cleanup, 'remove_unused_priority_prototypes', lambda *args: None)
    baseline = render(path, replace(draft, blocks=(replace(b, extra_tables=(extra,)),)))
    assert result._element.xml == baseline._element.xml
    assert 'Edited pump' in result._element.xml


@pytest.mark.parametrize('special', [None, 'field'])
def test_source_view_uses_immutable_original_before_passive_field_normalization(tmp_path, special):
    from app.monthly_report_compatibility_view import derive_compatibility_view
    from app.monthly_report_native_layout import _build_native_docx
    from app.monthly_report_operational_source import rendition_file
    path, draft = fixture(tmp_path, special)
    from copy import deepcopy
    from test_monthly_report_source_frame_logo_role import source
    cover = Document(source(tmp_path, divergent=True, shared_outside=False))
    original = Document(path)
    for node in list(original._element.body)[:-1]:
        cover._element.body.insert(len(cover._element.body) - 1, deepcopy(node))
    cover.save(path)
    inspection = inspect_docx(path)
    item = [x for x in inspection.items if x.kind == 'table'][-1]
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f'docx:{inspection.sha256}:{item.id}')
    draft = replace(draft, blocks=(replace(draft.blocks[0], extra_tables=(supplied,)),))
    view = derive_compatibility_view(path.read_bytes())
    with rendition_file(view) as derivative:
        result = Document(BytesIO(_build_native_docx(
            draft, derivative, source_view=view, original_path=path, section_key='capital')))
    assert len(result.tables) == (2 if special == 'field' else 1)
