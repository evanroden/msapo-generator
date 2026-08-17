"""OCR and text-extraction helpers for incoming vendor quotes.

Supported inputs:
- Plain text
- PDF: embedded text first, then Claude PDF vision, then rendered page images
- Images: JPEG, PNG, GIF, WebP, HEIC/HEIF, TIFF and BMP

The original uploaded bytes are never modified; normalization is used only for
analysis. Every image format is decoded, orientation-corrected, bounded, and
sent as ordered JPEG image blocks.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL


_OCR_PROMPT = (
    "Extract ALL text from this vendor quote exactly as written — every line, "
    "number, price, quantity, and detail, preserving the order. Output only the "
    "extracted text, no commentary."
)
_MAX_IMAGE_FRAMES = 20
_MAX_PDF_PAGES = 20
_MAX_PIXELS_PER_FRAME = 40_000_000
# The vision API downsamples anything larger than this on the long edge, so
# sending full-resolution frames only inflates the payload past the per-image
# size limit. Downscale before encoding.
_VISION_MAX_EDGE = (1568, 1568)
# Aggregate base64 budget for one vision request across all frames, kept well
# under the API's overall request ceiling. Per-frame size is bounded by the
# downscale above; this bounds their sum, which _MAX_IMAGE_FRAMES alone does not.
_MAX_TOTAL_ENCODED_BYTES = 24 * 1024 * 1024
_MAX_ENCODED_BYTES_PER_IMAGE = 5 * 1024 * 1024

DIRECT_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
NORMALIZED_IMAGE_SUFFIXES = {
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".hif",
}
SUPPORTED_IMAGE_SUFFIXES = set(DIRECT_IMAGE_MEDIA_TYPES) | NORMALIZED_IMAGE_SUFFIXES


def _image_block(data: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def _enforce_vision_payload_budget(blocks: list[dict], *, label: str) -> None:
    """Reject oversized image payloads before making a paid API request."""
    encoded_sizes = [
        len(block.get("source", {}).get("data", ""))
        for block in blocks
        if block.get("type") == "image"
    ]
    oversized = next(
        (size for size in encoded_sizes if size > _MAX_ENCODED_BYTES_PER_IMAGE),
        None,
    )
    if oversized is not None:
        raise ValueError(
            f"One {label} page is too large to analyze "
            f"({oversized / 1_000_000:.0f} MB encoded). Resize or split it."
        )
    encoded_total = sum(encoded_sizes)
    if encoded_total > _MAX_TOTAL_ENCODED_BYTES:
        raise ValueError(
            f"These {len(encoded_sizes)} {label} pages are too large to analyze "
            f"together ({encoded_total / 1_000_000:.0f} MB encoded). Split the "
            "file into smaller uploads."
        )


def image_blocks_for_vision(file_bytes: bytes, suffix: str) -> list[dict]:
    """Return Claude-compatible image blocks for one uploaded image file.

    Every supported format is decoded with Pillow and re-encoded as bounded,
    ordered JPEG frames. Native formats are normalized too: passing their raw
    bytes through left PNG/GIF/WebP uploads outside both the pixel and request
    size guards.
    """
    suffix = suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported image type: {suffix or '(no extension)'}")

    if suffix in {".heic", ".heif", ".hif"}:
        from pillow_heif import register_heif_opener

        register_heif_opener(thumbnails=False)

    from PIL import Image, ImageOps, ImageSequence

    blocks: list[dict] = []
    with Image.open(BytesIO(file_bytes)) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        if frame_count > _MAX_IMAGE_FRAMES:
            raise ValueError(
                f"This image contains {frame_count} pages/frames; the maximum is "
                f"{_MAX_IMAGE_FRAMES}. Split it into smaller files before uploading."
            )

        for frame in ImageSequence.Iterator(image):
            # Check the declared frame size BEFORE copy()/exif_transpose(), both
            # of which materialize the full raster. Pillow's own decompression
            # guard only trips near 178 MP, so validating afterwards let every
            # frame in the 40-178 MP band allocate hundreds of MB on a shared
            # Render container before being rejected — once per frame, up to
            # _MAX_IMAGE_FRAMES times. expense_report._validate_receipt_dimensions
            # already orders this correctly; this path now matches it.
            width, height = frame.size
            if width * height > _MAX_PIXELS_PER_FRAME:
                raise ValueError(
                    f"Image frame is too large ({width}×{height}). Resize it below "
                    f"{_MAX_PIXELS_PER_FRAME:,} pixels before uploading."
                )
            oriented = ImageOps.exif_transpose(frame.copy())
            # Flatten transparency onto WHITE before dropping the alpha channel.
            # A bare .convert("RGB") discards alpha and leaves whatever RGB the
            # transparent pixels happened to carry, which for a scanned or
            # screenshotted receipt is usually black — turning the page
            # background into a black field that hides the text we are about to
            # ask the model to read. JPEG has no alpha at all, so this must be
            # explicit rather than left to the encoder.
            if oriented.mode in {"RGBA", "LA", "PA"} or (
                oriented.mode == "P" and "transparency" in oriented.info
            ):
                flattened = Image.new("RGB", oriented.size, (255, 255, 255))
                rgba = oriented.convert("RGBA")
                flattened.paste(rgba, mask=rgba.split()[-1])
                normalized = flattened
            else:
                normalized = oriented.convert("RGB")
            if (
                normalized.width > _VISION_MAX_EDGE[0]
                or normalized.height > _VISION_MAX_EDGE[1]
            ):
                normalized = ImageOps.contain(normalized, _VISION_MAX_EDGE)
            buffer = BytesIO()
            # JPEG, not PNG. Downscaling to 1568px alone is NOT sufficient:
            # measured at that size, photographic content encodes to ~5.4 MB of
            # lossless PNG (~7.2 MB once base64-encoded), which still exceeds the
            # vision API's ~5 MB per-image limit that the downscale was meant to
            # solve. The same frame is ~0.9 MB as JPEG q85 (~1.2 MB base64), and
            # a photographed text page drops from 2.8 MB to 0.2 MB. These are
            # camera photos of paper, so JPEG's lossy artifacts are far below the
            # noise already present, and the API re-encodes server-side anyway.
            # receipt_preview_bytes already made this choice.
            # q90 rather than a smaller default: the model has to READ this, so
            # compression ringing around small glyphs costs extraction accuracy,
            # and the payload is already an order of magnitude inside the limit.
            normalized.save(buffer, format="JPEG", quality=90, optimize=True)
            blocks.append(_image_block(buffer.getvalue(), "image/jpeg"))

    if not blocks:
        raise ValueError("The image did not contain a readable frame.")

    _enforce_vision_payload_budget(blocks, label="image")
    return blocks


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF.

    First tries the embedded text layer (fast, free). Scanned/image-only PDFs
    have no useful text layer, so those fall back to Claude vision.
    """
    import fitz  # PyMuPDF

    text_parts: list[str] = []
    ocr_bytes = file_bytes
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        if pdf.page_count > _MAX_PDF_PAGES:
            raise ValueError(
                f"This PDF contains {pdf.page_count} pages; the maximum is "
                f"{_MAX_PDF_PAGES}. Split it into smaller quotes before uploading."
            )
        # Vendors often owner-lock a quote while leaving it openable. Re-serialize
        # a decrypted copy for OCR only; the original upload remains unchanged.
        if pdf.is_encrypted:
            try:
                pdf.authenticate("")
                ocr_bytes = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
            except Exception:
                ocr_bytes = file_bytes
        for page in pdf:
            text_parts.append(page.get_text())
    text = "\n".join(text_parts).strip()

    if len(text) >= 20:
        return text

    try:
        return _ocr_pdf_via_document(ocr_bytes)
    except Exception:
        return _ocr_pdf_via_page_images(ocr_bytes)


def _ocr_pdf_via_document(file_bytes: bytes) -> str:
    """OCR a PDF by sending it to Claude as a native document block."""
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    if len(b64) > _MAX_TOTAL_ENCODED_BYTES:
        raise ValueError(
            "This PDF is too large for direct document OCR; trying bounded "
            "page images instead."
        )
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": _OCR_PROMPT},
                ],
            }
        ],
    )
    return message.content[0].text.strip()


def _ocr_pdf_via_page_images(file_bytes: bytes) -> str:
    """OCR a PDF through bounded, normalized page images."""
    import fitz  # PyMuPDF

    content: list[dict] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        if pdf.page_count > _MAX_PDF_PAGES:
            raise ValueError(
                f"This PDF contains {pdf.page_count} pages; the maximum is "
                f"{_MAX_PDF_PAGES}. Split it into smaller quotes before uploading."
            )
        for page_number, page in enumerate(pdf, 1):
            width = round(page.rect.width * 150 / 72)
            height = round(page.rect.height * 150 / 72)
            if width <= 0 or height <= 0 or width * height > _MAX_PIXELS_PER_FRAME:
                raise ValueError(
                    f"PDF page {page_number} is too large to read safely "
                    f"({width}×{height} pixels at OCR resolution)."
                )
            png = page.get_pixmap(dpi=150).tobytes("png")
            content.extend(image_blocks_for_vision(png, ".png"))
    _enforce_vision_payload_budget(content, label="PDF")
    content.append({"type": "text", "text": _OCR_PROMPT})
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text.strip()


def extract_text_from_image(file_bytes: bytes, suffix: str) -> str:
    """Normalize an image when necessary and read all ordered frames with Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    content = image_blocks_for_vision(file_bytes, suffix)
    content.append({"type": "text", "text": _OCR_PROMPT})
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text.strip()


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Detect the uploaded file type and extract its text."""
    suffix = Path(filename).suffix.lower()

    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="replace")

    if suffix == ".pdf":
        return extract_text_from_pdf(file_bytes)

    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return extract_text_from_image(file_bytes, suffix)

    # Fallback for other text-like files.
    return file_bytes.decode("utf-8", errors="replace")
