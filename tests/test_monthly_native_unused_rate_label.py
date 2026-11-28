"""Source-only utility labels are not current report content."""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_native_rate_label import unused_rate_labels
from app.monthly_report_sections import table_without_prices


def fixture(tmp_path, special=None):
    doc = Document()
    doc.add_heading('MONTHLY SCORECARDS', 1)
    label = doc.add_paragraph('RATE TREND')._p
    if special:
        label.append(OxmlElement('w:' + special))
    doc.add_paragraph('Old monthly utility facts')
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, (('Campus', 'Capacity'), ('Synthetic site', '42'))):
        for cell, value in zip(row.cells, values):
            cell.text = value
    path = tmp_path / 'synthetic.docx'
    doc.save(path)
    inspection = inspect_docx(path)
    item = next(i for i in inspection.items if i.kind == 'table')
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f'docx:{inspection.sha256}:{item.id}')
    section = next(s for s in default_sections() if s.key == 'scorecards')
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 11), 'Synthetic reviewer',
                        (section,), (ResolvedBlock('thermal_capacity', 'This month', extra_tables=(supplied,)),), synthetic=True)
    return path, draft


def test_public_builder_clears_unused_label_without_touching_source_or_tables(tmp_path):
    path, draft = fixture(tmp_path)
    source = path.read_bytes()
    result = Document(BytesIO(build_native_docx(draft, path)))
    assert 'RATE TREND' not in result.element.xml
    assert result.tables[0].cell(1, 1).text == '42'
    assert path.read_bytes() == source
    from app import monthly_report_native_rate_label as cleanup
    from unittest.mock import patch
    with patch.object(cleanup.UnusedRateLabel, 'apply', lambda *args: None):
        baseline = Document(BytesIO(build_native_docx(draft, path)))
    texts = [n for n in baseline.element.iter(qn('w:t')) if n.text == 'RATE TREND']
    assert len(texts) == 1
    texts[0].text = None
    assert baseline.element.xml == result.element.xml


@pytest.mark.parametrize('key,value', [
    ('text', 'Current utility discussion'), ('rows', (('Current utility',),)),
    ('extra_tables', ('owned table',)), ('asset_hashes', ('current.png',)),
    ('asset_instances', ('current occurrence',)), ('org_nodes', ('current node',)),
])
def test_any_current_utility_payload_refuses_label_cleanup(tmp_path, key, value):
    path, draft = fixture(tmp_path)
    block = replace(ResolvedBlock('utility_analysis', 'This month'), **{key: value})
    draft = replace(draft, blocks=(*draft.blocks, block))
    doc = Document(path)
    assert not unused_rate_labels(path, draft, list(doc.element.body), {n:'scorecards' for n in range(1, 10)}, set())


@pytest.mark.parametrize('special', ['bookmarkStart', 'fldSimple', 'hyperlink', 'sdt', 'ins', 'object', 'sectPr'])
def test_unknown_raw_markup_cannot_become_cleanup_proof(tmp_path, special):
    path, draft = fixture(tmp_path)
    doc = Document(path)
    doc.element.body[1].append(OxmlElement('w:' + special))
    doc.save(path)
    # Simulate a passive rendition flattening markup before rendering.
    node = doc.element.body[1]
    node.remove(node[-1])
    assert not unused_rate_labels(path, draft, list(doc.element.body), {n:'scorecards' for n in range(1, 10)}, set())


@pytest.mark.parametrize('guard', ['live', 'support', 'headings', 'changed', 'moved', 'unchanged', 'other-section'])
def test_current_ownership_or_mutation_keeps_label(tmp_path, guard):
    path, draft = fixture(tmp_path)
    doc = Document(path)
    roots = list(doc.element.body)
    plans = unused_rate_labels(path, draft, roots,
        {n:('activity' if guard=='other-section' else 'scorecards') for n in range(1, 10)},
        {2} if guard=='unchanged' else set())
    node = roots[1]
    pages = SimpleNamespace(live=set(), support=set(), headings=set())
    if guard in ('live', 'support', 'headings'):
        getattr(pages, guard).add(node)
    elif guard=='changed':
        node.get_or_add_pPr().append(OxmlElement('w:keepNext'))
    elif guard=='moved':
        doc.element.body.remove(node)
    for plan in plans:
        plan.apply(doc.element.body, pages)
    assert 'RATE TREND' in node.xml


def test_explicit_omission_allows_unused_plain_label_cleanup(tmp_path):
    path, draft = fixture(tmp_path)
    draft = replace(draft, blocks=(*draft.blocks, ResolvedBlock('utility_analysis', 'Omit', text='Not included')))
    assert 'RATE TREND' not in Document(BytesIO(build_native_docx(draft, path))).element.xml


@pytest.mark.parametrize('special', ['pStyle', 'sectPr', 'pageBreakBefore', 'numPr', 'tabs'])
def test_source_geometry_and_inherited_styles_are_not_plain_label_proof(tmp_path, special):
    path, draft = fixture(tmp_path)
    doc = Document(path)
    doc.element.body[1].get_or_add_pPr().append(OxmlElement('w:' + special))
    doc.save(path)
    assert not unused_rate_labels(path, draft, list(doc.element.body), {n:'scorecards' for n in range(1, 10)}, set())


def test_malformed_text_inside_properties_is_not_plain_label_proof(tmp_path):
    path, draft = fixture(tmp_path)
    doc = Document(path)
    hidden = OxmlElement('w:t'); hidden.text = 'RATE TREND'
    node = doc.element.body[1]
    node.remove(node[-1]); node.get_or_add_pPr().append(hidden)
    doc.save(path)
    assert not unused_rate_labels(path, draft, list(doc.element.body), {n:'scorecards' for n in range(1, 10)}, set())


def test_raw_field_normalized_by_passive_view_never_grants_label_cleanup(tmp_path):
    path, draft = fixture(tmp_path)
    doc = Document(path); node = doc.element.body[1]
    run = node[-1]; run.remove(run[-1])
    field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'QUOTE "RATE TREND"')
    content = OxmlElement('w:r'); text = OxmlElement('w:t'); text.text = 'RATE TREND'
    content.append(text); field.append(content); node.append(field); doc.save(path)
    from app.monthly_report_native_package import passive_docx
    passive = Document(BytesIO(passive_docx(path)))
    assert not unused_rate_labels(path, draft, list(passive.element.body), {n:'scorecards' for n in range(1, 10)}, set())
