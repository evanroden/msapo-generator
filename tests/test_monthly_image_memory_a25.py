"""A25: bounded image preparation; all artwork and metadata are synthetic.

Tests deliberately cover the previously costly non-cover transpose, duplicate
media in one *owner-scoped* DOCX, and preview derivative privacy.
Refs #270 #491 #462.
"""
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo
import pytest

from app import monthly_report_docx as print_images
from app import monthly_report_preview_images as preview


def _jpeg(size=(2400, 1600), *, orientation=1, author=None):
    image = Image.new("RGB", size, (120, 85, 33))
    exif = Image.Exif()
    exif[274] = orientation
    if author:
        exif[315] = author
    output = BytesIO()
    image.save(output, "JPEG", exif=exif.tobytes(), quality=86)
    image.close()
    return output.getvalue()


def _docx_media(items):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", "<document>synthetic</document>")
        for name, raw in items:
            package.writestr("word/media/" + name, raw)
    return output.getvalue()


def _media(package):
    with ZipFile(BytesIO(package)) as zipfile:
        return {name: zipfile.read(name) for name in zipfile.namelist()
                if name.startswith("word/media/")}


def test_print_rotation_is_applied_after_bounded_thumbnail(monkeypatch):
    original = _jpeg((4800, 3200), orientation=6)
    original_hash = sha256(original).hexdigest()
    transpose = print_images.ImageOps.exif_transpose
    seen = []

    def guard(image):
        seen.append(image.size)
        assert image.width * image.height <= 2_500_000, (
            "EXIF transpose must not allocate a full-resolution raster")
        return transpose(image)

    monkeypatch.setattr(print_images.ImageOps, "exif_transpose", guard)
    prepared = print_images.normalize_report_image(original, ".jpg", frame=(7, 9))
    assert seen and prepared.width <= 1400 and prepared.height <= 1800
    assert prepared.height > prepared.width
    assert sha256(original).hexdigest() == original_hash
    with Image.open(BytesIO(prepared.data)) as image:
        assert not image.getexif()


def test_preview_duplicate_media_decoded_once_per_package_not_across_owners(tmp_path, monkeypatch):
    image = _jpeg()
    package = _docx_media([("a.jpg", image), ("b.jpg", image)])
    before_hash = sha256(package).hexdigest()
    calls = []
    real = preview._smaller_image

    def measured(raw):
        calls.append(sha256(raw).hexdigest())
        return real(raw)

    monkeypatch.setattr(preview, "_smaller_image", measured)
    first = tmp_path / "first.docx"
    second = tmp_path / "second.docx"
    preview.write_preview_docx(package, first)
    assert len(calls) == 1, "Identical media should share one decoded rendition"
    parts = _media(first.read_bytes())
    assert parts["word/media/a.jpg"] == parts["word/media/b.jpg"]
    assert sha256(package).hexdigest() == before_hash

    preview.write_preview_docx(package, second)
    assert len(calls) == 2, "A different package/owner cannot reuse a prior cache"
    assert first.read_bytes() == second.read_bytes()


def test_preview_removes_hidden_rgb_and_author_metadata_even_without_upstream_pass(tmp_path):
    secret = "A25_SYNTHETIC_AUTHOR_PRIVATE_CANARY"
    png_info = PngInfo()
    png_info.add_text("Author", secret)
    image = Image.new("RGBA", (160, 100), (240, 20, 90, 0))
    image.putpixel((80, 50), (5, 200, 30, 255))
    png = BytesIO()
    image.save(png, "PNG", pnginfo=png_info)
    jpeg = _jpeg((200, 100), author=secret)
    source = _docx_media([("logo.png", png.getvalue()), ("photo.jpg", jpeg)])
    original_hash = sha256(source).hexdigest()
    target = tmp_path / "sanitized.docx"
    preview.write_preview_docx(source, target)
    parts = _media(target.read_bytes())
    assert sha256(source).hexdigest() == original_hash
    for data in parts.values():
        assert secret.encode() not in data
    with Image.open(BytesIO(parts["word/media/logo.png"])) as clean:
        assert clean.getpixel((0, 0)) == (0, 0, 0, 0)
        assert clean.getpixel((80, 50)) == (5, 200, 30, 255)


def test_invalid_media_rejected_without_partial_success(tmp_path):
    source = _docx_media([("bad.jpg", b"not a supported image")])
    with pytest.raises(ValueError, match="cannot be read safely"):
        preview.write_preview_docx(source, tmp_path / "bad.docx")


def test_preview_cache_byte_cap_and_distinct_sources(tmp_path, monkeypatch):
    first = _jpeg((2400, 1600), author="first")
    second = _jpeg((2400, 1600), orientation=6, author="second")
    package = _docx_media([("a.jpg", first), ("b.jpg", first), ("c.jpg", second)])
    calls = []
    original = preview._smaller_image

    def measured(raw):
        calls.append(sha256(raw).hexdigest())
        return original(raw)

    monkeypatch.setattr(preview, "_smaller_image", measured)
    monkeypatch.setattr(preview, "MAX_RENDITION_CACHE_BYTES", 0)
    preview.write_preview_docx(package, tmp_path / "uncached.docx")
    assert calls == [sha256(first).hexdigest(), sha256(first).hexdigest(),
                     sha256(second).hexdigest()]
    result = _media((tmp_path / "uncached.docx").read_bytes())
    assert result["word/media/a.jpg"] == result["word/media/b.jpg"]
    assert result["word/media/c.jpg"] != result["word/media/a.jpg"]
