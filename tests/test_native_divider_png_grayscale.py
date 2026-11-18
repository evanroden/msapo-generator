"""A80: prove monochrome is an occurrence-level output, never a source edit."""
from hashlib import sha256
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches
from PIL import Image, ImageDraw

from app.monthly_report_divider_monochrome import (
    A, R, monochrome_divider_photos,
)


def _png(color=(216, 41, 18), *, mode="RGB", alpha=255, brand=False):
    picture = Image.new(mode, (1200, 900), (*color, alpha) if mode == "RGBA" else color)
    if brand:
        draw = ImageDraw.Draw(picture)
        draw.rectangle((0, 0, 1199, 110), fill=(214, 239, 75))
    stream = BytesIO()
    picture.save(stream, "PNG")
    return stream.getvalue()


def _insert(document, data, *, inches=8):
    paragraph = document.add_paragraph()
    inline = paragraph.add_run().add_picture(BytesIO(data), width=Inches(inches), height=Inches(inches))._inline
    inline.tag = qn("wp:anchor")
    return paragraph._p, next(inline.iter(A + "blip"))


def _raw(document, blip):
    return document.part.rels[blip.get(R + "embed")].target_part.blob


def _check_gray(data):
    with Image.open(BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.mode == "L", "The derivative should be a true grayscale PNG."
        assert image.getpixel((10, 200)) not in (18, 41, 216)
        return image.getpixel((10, 200))


def test_opaque_png_occurrence_is_grayscale_without_mutating_shared_original():
    source = _png()
    digest = sha256(source).hexdigest()
    document = Document()
    root, selected = _insert(document, source)
    _, untouched = _insert(document, source)
    old = selected.get(R + "embed")
    assert old == untouched.get(R + "embed")
    monochrome_divider_photos(document, [root])
    assert selected.get(R + "embed") != old
    _check_gray(_raw(document, selected))
    assert _raw(document, untouched) == source
    assert sha256(_raw(document, untouched)).hexdigest() == digest
    assert sha256(source).hexdigest() == digest
    saved = BytesIO()
    document.save(saved)
    reread = Document(BytesIO(saved.getvalue()))
    selected, untouched = list(reread.element.iter(A + "blip"))
    _check_gray(_raw(reread, selected))
    assert _raw(reread, untouched) == source
    # A second report loading this original starts with exactly the original color.
    second = Document()
    _, other = _insert(second, source)
    assert _raw(second, other) == source


def test_opaque_rgba_png_is_eligible_but_transparent_logo_is_not():
    document = Document()
    root, opaque = _insert(document, _png(mode="RGBA"))
    transparent_root, transparent = _insert(document, _png(mode="RGBA", alpha=0))
    half_root, partly_transparent = _insert(document, _png(mode="RGBA", alpha=120))
    pre = [_raw(document, blip) for blip in (opaque, transparent, partly_transparent)]
    monochrome_divider_photos(document, [root, transparent_root, half_root])
    _check_gray(_raw(document, opaque))
    assert _raw(document, transparent) == pre[1]
    assert _raw(document, partly_transparent) == pre[2]
    assert _raw(document, transparent) != _raw(document, opaque)


def test_opaque_png_flat_brand_color_is_preserved():
    document = Document()
    root, selected = _insert(document, _png(brand=True))
    original = _raw(document, selected)
    monochrome_divider_photos(document, [root])
    assert _raw(document, selected) == original
    with Image.open(BytesIO(_raw(document, selected))) as image:
        assert image.convert("RGB").getpixel((100, 50)) == (214, 239, 75)


@pytest.mark.parametrize("bad_data", [b"", b"not-an-image", b"\\x89PNG\\r\\n\\x1a\\nbroken"])
def test_bad_png_parts_do_not_mutate_other_assets(bad_data):
    document = Document()
    root, selected = _insert(document, _png())
    part = document.part.rels[selected.get(R + "embed")].target_part
    part._blob = bad_data
    old = selected.get(R + "embed")
    monochrome_divider_photos(document, [root])
    assert selected.get(R + "embed") == old
    assert part.blob == bad_data


def test_small_png_not_mistaken_for_full_page_divider():
    document = Document()
    root, selected = _insert(document, _png(), inches=2)
    old = selected.get(R + "embed")
    monochrome_divider_photos(document, [root])
    assert selected.get(R + "embed") == old


def test_converted_pdf_image_pixels_are_gray(tmp_path, monkeypatch):
    from conftest import libreoffice_can_convert
    if not libreoffice_can_convert():
        pytest.skip("LibreOffice Writer/Calc unavailable")
    import pymupdf as fitz
    from app import pdf_converter
    document = Document()
    root, selected = _insert(document, _png())
    monochrome_divider_photos(document, [root])
    source = tmp_path / "synthetic-native-divider.docx"
    document.save(source)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    with fitz.open(pdf_converter.convert_to_pdf(source)) as pdf:
        assert len(pdf) == 1
        pictures = pdf[0].get_images(full=True)
        assert pictures, "Word-to-PDF must retain the selected photograph"
        pixmaps = [fitz.Pixmap(pdf, item[0]) for item in pictures]
        samples = [p.samples for p in pixmaps if p.n in (1, 3) and p.width >= 800]
        assert samples, "The full-page grayscale photograph must be present"
        # A PDF encoder may store neutral RGB or a single-channel indexed raster.
        for pixmap in pixmaps:
            if pixmap.width < 800 or pixmap.n == 1:
                continue
            assert pixmap.n == 3
            pixels = pixmap.samples
            assert all(pixels[i] == pixels[i+1] == pixels[i+2]
                       for i in range(0, len(pixels), 3))



def test_generated_divider_transparent_source_flattens_neutrally_without_touching_logo_colors():
    from app.monthly_report_docx import _divider_background
    image = Image.new("RGBA", (700, 920), (220, 35, 11, 0))
    stream = BytesIO()
    image.save(stream, "PNG")
    original = stream.getvalue()
    original_sha = sha256(original).hexdigest()
    document = Document()
    _divider_background(document, original)
    photos = list(document.part.package.image_parts)
    assert len(photos) == 1
    with Image.open(BytesIO(photos[0].blob)) as rendered:
        # Outside the edited green divider band is an opaque, neutral background.
        assert rendered.mode == "RGB"
        neutral = rendered.getpixel((400, 80))
        assert max(neutral) - min(neutral) <= 2 and min(neutral) >= 247
        brand = rendered.getpixel((400, 500))
        assert max(brand) - min(brand) >= 10
    assert sha256(original).hexdigest() == original_sha
