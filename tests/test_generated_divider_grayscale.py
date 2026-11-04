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
