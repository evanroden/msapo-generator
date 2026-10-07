from dataclasses import replace
from io import BytesIO

from docx import Document
from PIL import Image
import pytest

from app.monthly_report_docx import assemble_docx, normalize_report_image
from app.monthly_report_library import asset_reference
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles


def test_image_rotation_downscale_and_no_exif_retention():
    source = BytesIO()
    image = Image.new("RGB", (2800, 1000), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, "JPEG", exif=exif)
    result = normalize_report_image(source.getvalue(), ".jpg", frame=(7, 9))
    assert result.height == 1800
    assert result.width < result.height
    with Image.open(BytesIO(result.data)) as image:
        assert not image.getexif()
    assert len(result.data) < len(source.getvalue())


def test_line_art_transparency_stays_readable_and_lossless():
    source = BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(source, "PNG")
    result = normalize_report_image(source.getvalue(), ".png", line_art=True)
    assert result.extension == "png"
    with Image.open(BytesIO(result.data)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_heic_is_decoded_before_report_compression():
    from pillow_heif import from_pillow
    stream = BytesIO()
    from_pillow(Image.new("RGB", (60, 40), "red")).save(stream)
    result = normalize_report_image(stream.getvalue(), ".heic")
    assert (result.width, result.height, result.extension) == (60, 40, "jpg")


def test_image_limits_apply_before_raster_materialization(monkeypatch):
    stream = BytesIO()
    Image.new("RGB", (10, 10)).save(stream, "PNG")
    import app.monthly_report_docx as renderer
    monkeypatch.setattr(renderer, "_MAX_PIXELS_PER_FRAME", 50)
    with pytest.raises(ValueError, match="decode safely"):
        normalize_report_image(stream.getvalue(), ".png")


def test_images_embed_with_asset_identity_and_remain_deterministic():
    stream = BytesIO()
    Image.new("RGB", (50, 50), "white").save(stream, "PNG")
    image = normalize_report_image(stream.getvalue(), ".png", line_art=True)
    reference = asset_reference(image.data, image.extension)
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    draft = replace(draft, sections=(replace(draft.sections[0], blocks=(BlockSpec("chart", "image_page", True),)),),
                    blocks=(ResolvedBlock("chart", "Library", asset_hashes=(reference,)),))
    draft = replace(draft, blocks=tuple(replace(b, client_reviewed_fingerprint=b.fingerprint) for b in draft.blocks))
    loader = lambda key: {reference: image.data}[key]
    data = assemble_docx(draft, asset_loader=loader)
    assert assemble_docx(draft, asset_loader=loader) == data
    assert len(Document(BytesIO(data)).inline_shapes) == 1
    with pytest.raises(ValueError, match="resolver"):
        assemble_docx(draft)
