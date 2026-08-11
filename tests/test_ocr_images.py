import base64
from io import BytesIO

import fitz
import pytest
from PIL import Image

from app.ocr import (
    SUPPORTED_IMAGE_SUFFIXES,
    _ocr_pdf_via_page_images,
    extract_text_from_pdf,
    image_blocks_for_vision,
)


def _decoded(block: dict) -> bytes:
    return base64.b64decode(block["source"]["data"])


def _tiff_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="TIFF")
    return buffer.getvalue()


def _decoded_png(block: dict) -> tuple[bytes, Image.Image]:
    payload = base64.standard_b64decode(block["source"]["data"])
    image = Image.open(BytesIO(payload))
    image.load()
    return payload, image


def test_claude_native_png_passes_through():
    original = b"\x89PNG\r\n\x1a\nexample"
    blocks = image_blocks_for_vision(original, ".png")

    assert len(blocks) == 1
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert _decoded(blocks[0]) == original


def test_bmp_is_normalized_to_png():
    source = BytesIO()
    Image.new("RGB", (12, 8), "white").save(source, format="BMP")

    blocks = image_blocks_for_vision(source.getvalue(), ".bmp")

    assert len(blocks) == 1
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert _decoded(blocks[0]).startswith(b"\x89PNG\r\n\x1a\n")


def test_multiframe_tiff_preserves_page_order():
    source = BytesIO()
    first = Image.new("RGB", (4, 4), "white")
    second = Image.new("RGB", (4, 4), "black")
    first.save(source, format="TIFF", save_all=True, append_images=[second])

    blocks = image_blocks_for_vision(source.getvalue(), ".tiff")

    assert len(blocks) == 2
    assert all(block["source"]["media_type"] == "image/png" for block in blocks)
    assert all(_decoded(block).startswith(b"\x89PNG\r\n\x1a\n") for block in blocks)
    assert _decoded(blocks[0]) != _decoded(blocks[1])


def test_iphone_heic_extensions_are_supported():
    assert {".heic", ".heif", ".hif"}.issubset(SUPPORTED_IMAGE_SUFFIXES)


def test_large_phone_sized_tiff_is_downscaled_below_vision_limit():
    source = Image.effect_noise((4032, 3024), 80).convert("RGB")

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    payload, normalized = _decoded_png(blocks[0])

    assert len(blocks) == 1
    assert len(payload) < 5 * 1024 * 1024
    assert max(normalized.size) <= 1568
    assert normalized.size == (1568, 1176)


def test_small_normalized_image_is_not_upscaled():
    source = Image.new("RGB", (800, 600), "white")

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    _, normalized = _decoded_png(blocks[0])

    assert normalized.size == (800, 600)


def test_overlong_pdf_is_rejected_before_ocr_api_fallback(monkeypatch):
    document = fitz.open()
    for _ in range(21):
        document.new_page(width=100, height=100)
    payload = document.tobytes()
    document.close()

    monkeypatch.setattr(
        "app.ocr._ocr_pdf_via_document",
        lambda _payload: (_ for _ in ()).throw(
            AssertionError("overlong PDF must not reach document OCR")
        ),
    )

    with pytest.raises(ValueError, match="21 pages; the maximum is 20"):
        extract_text_from_pdf(payload)


def test_huge_pdf_page_is_rejected_before_page_image_rasterization(monkeypatch):
    document = fitz.open()
    document.new_page(width=20_000, height=20_000)
    payload = document.tobytes()
    document.close()

    monkeypatch.setattr(
        "app.ocr.anthropic.Anthropic",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("oversized page must not reach the OCR client")
        ),
    )

    with pytest.raises(ValueError, match="PDF page 1 is too large"):
        _ocr_pdf_via_page_images(payload)
