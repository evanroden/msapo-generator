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
    _, transparent = _insert(document, _png(mode="RGBA", alpha=0))
    _, partly_transparent = _insert(document, _png(mode="RGBA", alpha=120))
    pre = [_raw(document, blip) for blip in (opaque, transparent, partly_transparent)]
    monochrome_divider_photos(document, [root, transparent.getparent().getparent().getparent().getparent().getparent().getparent()])
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
