"""Center single wide diagram pages without changing source pixels or native designs."""
from dataclasses import replace
from io import BytesIO
from hashlib import sha256

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image, ImageDraw
import pytest
from tests.conftest import requires_libreoffice

from app.monthly_report_docx import _build_docx
from app.monthly_report_model import ResolvedBlock
from tests.test_monthly_report_generic_contact_page import _draft


def diagram():
    image = Image.new('RGB', (1400, 789), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 1391, 780), outline='darkgreen', width=8)
    draw.rectangle((180, 210, 1220, 560), outline='green', width=4)
    draw.text((340, 340), 'SYNTHETIC CONTACT MATRIX - ALL LABELS RETAINED', fill='black')
    stream = BytesIO(); image.save(stream, 'PNG')
    raw = stream.getvalue(); reference = sha256(raw).hexdigest()+'.png'
    return raw, reference


@pytest.mark.parametrize("slot", ["org_chart", "contact_matrix"])
def test_generic_wide_diagram_is_centered_with_aspect_and_bytes_preserved(slot):
    raw, reference = diagram()
    block = ResolvedBlock(slot, 'This month', asset_hashes=(reference,))
    draft = replace(_draft(chart=False, contacts=False), blocks=(block,))
    document = Document(BytesIO(_build_docx(draft, asset_loader={reference: raw}.__getitem__)))
    paragraph = next(p for p in document.paragraphs if p._p.xpath('.//w:drawing'))
    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert 2 < paragraph.paragraph_format.space_before.inches < 2.5
    shape = document.inline_shapes[0]
    assert abs(shape.width / shape.height - 1400/789) < .001
    image = document.part.related_parts[shape._inline.graphic.graphicData.pic.blipFill.blip.embed]
    assert image.blob == raw


@requires_libreoffice
def test_contact_picture_is_vertically_centered_in_actual_pdf(tmp_path, monkeypatch):
    import pymupdf
    from app import pdf_converter
    raw, reference = diagram()
    block = ResolvedBlock('contact_matrix', 'This month', asset_hashes=(reference,))
    draft = replace(_draft(chart=False, contacts=False), blocks=(block,))
    source = tmp_path / 'invented-centered-contact.docx'
    source.write_bytes(_build_docx(draft, asset_loader={reference: raw}.__getitem__))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    with pymupdf.open(pdf_converter.convert_to_pdf(source)) as document:
        page, bounds = next((page, page.get_image_info()[0]['bbox'])
                            for page in document if page.get_image_info())
        x0, y0, x1, y1 = bounds
        assert abs((x0 + x1)/2 - page.rect.width/2) < 10
        assert abs((y0 + y1)/2 - page.rect.height/2) < 25
        assert x0 > 50 and x1 < page.rect.width-40
        assert abs((x1-x0)/(y1-y0) - 1400/789) < .005
