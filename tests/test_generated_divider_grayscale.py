from io import BytesIO
from PIL import Image
from docx import Document
from app.monthly_report_docx import _divider_background


def test_generated_divider_photo_is_grayscale_without_removing_brand_band():
    image = Image.new('RGB', (800, 1000), (200, 35, 20))
    raw = BytesIO(); image.save(raw, 'PNG')
    source = raw.getvalue()
    document = Document()
    _divider_background(document, source)
    part = next(iter(document.part.package.image_parts))
    with Image.open(BytesIO(part.blob)) as output:
        r, g, b = output.convert('RGB').getpixel((500, 100))
        assert max(r, g, b) - min(r, g, b) <= 2
        r, g, b = output.convert('RGB').getpixel((500, 500))
        assert max(r, g, b) - min(r, g, b) > 10
    assert Image.open(BytesIO(source)).getpixel((1, 1)) == (200, 35, 20)


def test_generated_divider_pdf_photo_is_grayscale(tmp_path, monkeypatch):
    import pymupdf as fitz
    import pytest
    from conftest import libreoffice_can_convert
    from app import pdf_converter
    if not libreoffice_can_convert():
        pytest.skip('LibreOffice writer/calc unavailable')
    raw = BytesIO(); Image.new('RGB',(800,1000),(200,35,20)).save(raw,'PNG')
    document = Document(); _divider_background(document,raw.getvalue())
    path = tmp_path/'divider.docx'; document.save(path)
    monkeypatch.setattr(pdf_converter,'OUTPUT_DIR',tmp_path)
    with fitz.open(pdf_converter.convert_to_pdf(path)) as pdf:
        page=pdf[0]; pix=page.get_pixmap(matrix=fitz.Matrix(1,1),alpha=False)
        rendered=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        # Page-space position (well within the photograph, away from band edges).
        r,g,b=rendered.getpixel((250,80))
        assert max(r,g,b)-min(r,g,b) <= 3
        r,g,b=rendered.getpixel((250,400))
        assert max(r,g,b)-min(r,g,b) > 10
