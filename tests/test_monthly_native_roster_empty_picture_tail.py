"""Only the exact cleared source-picture tail loses its obsolete page break."""
from io import BytesIO
from dataclasses import replace

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image

from app.monthly_report_import import inspect_docx
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_sections import table_without_prices
from test_monthly_native_roster_contact_pagination import fixture


def setup(tmp_path, boundary=False, following=False, bookmark=False, picture=True):
    path, draft = fixture(tmp_path)
    doc = Document(path)
    p = doc.add_paragraph('Synthetic old vendor page')
    p.paragraph_format.page_break_before = True
    if picture:
        image = BytesIO(); Image.new('RGB', (40, 40), 'navy').save(image, format='PNG')
        p.add_run().add_picture(BytesIO(image.getvalue()))
    if boundary:
        p._p.get_or_add_pPr().append(OxmlElement('w:sectPr'))
    if following:
        doc.add_table(rows=2, cols=2).cell(0, 0).text = 'Unrelated retained geometry'
    if bookmark:
        node = OxmlElement('w:bookmarkStart'); node.set(qn('w:id'), '42');node.set(qn('w:name'),'synthetic')
        p._p.append(node)
    doc.save(path)
    inspection = inspect_docx(path)
    item = next(i for i in inspection.items if i.kind == 'table')
    supplied, _ = table_without_prices(item)
    supplied = replace(supplied, reference=f'docx:{inspection.sha256}:{item.id}')
    draft = replace(draft, blocks=(replace(draft.blocks[0], extra_tables=(supplied,)),))
    return path, draft


def breaks(doc):
    return doc._element.xpath('//w:pPr/w:pageBreakBefore')


def test_cleared_roster_picture_tail_loses_break_but_preserves_sections(tmp_path):
    path, draft = setup(tmp_path)
    before = path.read_bytes()
    doc = Document(BytesIO(build_native_docx(draft, path, section_key='subcontractors')))
    assert not breaks(doc)
    assert len(doc.sections) == len(Document(path).sections)
    assert path.read_bytes() == before


@pytest.mark.parametrize('kwargs', [dict(boundary=True), dict(following=True), dict(bookmark=True), dict(picture=False)])
def test_unknown_or_boundary_owners_keep_their_break(tmp_path, kwargs):
    path, draft = setup(tmp_path, **kwargs)
    doc = Document(BytesIO(build_native_docx(draft, path, section_key='subcontractors')))
    assert breaks(doc)


def test_retained_current_picture_cannot_lose_its_break(tmp_path):
    from app.monthly_report_import import ImportMapping, map_items
    path, draft = setup(tmp_path)
    inspection = inspect_docx(path)
    image = next(item for item in inspection.items if item.kind == 'image')
    mapped = map_items(path, inspection, (ImportMapping(image.id, 'vendor_reports'),))
    from app.monthly_report_model import BlockSpec
    section = replace(draft.sections[0], blocks=(*draft.sections[0].blocks, BlockSpec("vendor_reports", "pdf_pages")))
    current = replace(draft, sections=(section,), blocks=(*draft.blocks, *mapped.blocks))
    raw = build_native_docx(current, path, section_key='subcontractors',
                            asset_loader=dict(mapped.assets).__getitem__)
    doc = Document(BytesIO(raw))
    assert breaks(doc)
    assert doc._element.xpath('//w:drawing')
