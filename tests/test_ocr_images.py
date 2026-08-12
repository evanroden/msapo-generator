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


def _decoded_image(block: dict) -> tuple[bytes, Image.Image]:
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


def test_bmp_is_normalized_to_jpeg():
    source = BytesIO()
    Image.new("RGB", (12, 8), "white").save(source, format="BMP")

    blocks = image_blocks_for_vision(source.getvalue(), ".bmp")

    assert len(blocks) == 1
    # JPEG, not PNG: lossless encoding of a camera photo blew past the vision
    # API's per-image size limit even after downscaling. See test below.
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert _decoded(blocks[0]).startswith(b"\xff\xd8\xff")


def test_multiframe_tiff_preserves_page_order():
    source = BytesIO()
    first = Image.new("RGB", (4, 4), "white")
    second = Image.new("RGB", (4, 4), "black")
    first.save(source, format="TIFF", save_all=True, append_images=[second])

    blocks = image_blocks_for_vision(source.getvalue(), ".tiff")

    assert len(blocks) == 2
    assert all(block["source"]["media_type"] == "image/jpeg" for block in blocks)
    assert all(_decoded(block).startswith(b"\xff\xd8\xff") for block in blocks)
    assert _decoded(blocks[0]) != _decoded(blocks[1])


def test_iphone_heic_extensions_are_supported():
    assert {".heic", ".heif", ".hif"}.issubset(SUPPORTED_IMAGE_SUFFIXES)


def test_large_phone_sized_tiff_is_downscaled_below_vision_limit():
    source = Image.effect_noise((4032, 3024), 80).convert("RGB")

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    payload, normalized = _decoded_image(blocks[0])

    assert len(blocks) == 1
    assert max(normalized.size) <= 1568
    assert normalized.size == (1568, 1176)
    # The real constraint is the BASE64 payload the request carries, which is
    # ~4/3 of the encoded bytes. Downscaling alone did not achieve this: the
    # same frame as lossless PNG measured ~5.4MB raw / ~7.2MB base64.
    assert len(payload) * 4 / 3 < 5 * 1024 * 1024


def test_small_normalized_image_is_not_upscaled():
    source = Image.new("RGB", (800, 600), "white")

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    _, normalized = _decoded_image(blocks[0])

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


def test_oversized_frame_is_rejected_before_the_raster_is_materialized(monkeypatch):
    """The pixel guard must run on the declared size, not on a decoded copy.

    Validating after ``frame.copy()``/``exif_transpose`` meant every frame in the
    40MP-178MP band (below Pillow's own decompression-bomb threshold) allocated
    its full raster before being rejected -- repeatedly, on a shared container.
    """
    source = Image.new("RGB", (16, 16), "white")
    calls: list[str] = []

    original_copy = Image.Image.copy

    def _tracking_copy(self):  # pragma: no cover - only fires on regression
        calls.append("copy")
        return original_copy(self)

    monkeypatch.setattr(Image.Image, "copy", _tracking_copy)
    monkeypatch.setattr("app.ocr._MAX_PIXELS_PER_FRAME", 4)

    with pytest.raises(ValueError, match="too large"):
        image_blocks_for_vision(_tiff_bytes(source), ".tiff")

    assert calls == [], "the frame was decoded before its size was validated"


def test_photographic_frame_stays_within_the_vision_payload_budget():
    """Regression for the encode format, independent of the downscale."""
    source = Image.effect_noise((2400, 1800), 90).convert("RGB")

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    payload, _ = _decoded_image(blocks[0])

    assert len(base64.standard_b64encode(payload)) < 5 * 1024 * 1024


def test_transparent_receipt_is_flattened_onto_white_not_black():
    """Dropping alpha without compositing turns a transparent page background
    black, hiding the text the model is being asked to read. JPEG has no alpha,
    so this has to be explicit."""
    source = Image.new("RGBA", (40, 40), (255, 255, 255, 0))
    source.putpixel((20, 20), (0, 0, 0, 255))

    blocks = image_blocks_for_vision(_tiff_bytes(source), ".tiff")
    _, normalized = _decoded_image(blocks[0])

    assert normalized.mode == "RGB"
    corner = normalized.getpixel((0, 0))
    assert min(corner) > 200, f"transparent background became {corner}, not white"


def test_many_frames_are_rejected_with_a_clear_message(monkeypatch):
    """Per-frame limits do not bound the REQUEST; their sum has to be checked."""
    monkeypatch.setattr("app.ocr._MAX_TOTAL_ENCODED_BYTES", 1024)
    first = Image.effect_noise((600, 600), 90).convert("RGB")
    second = Image.effect_noise((600, 600), 90).convert("RGB")
    source = BytesIO()
    first.save(source, format="TIFF", save_all=True, append_images=[second])

    with pytest.raises(ValueError, match="too large to analyze together"):
        image_blocks_for_vision(source.getvalue(), ".tiff")
