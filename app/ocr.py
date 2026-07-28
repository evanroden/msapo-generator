"""OCR and text-extraction helpers for incoming vendor quotes.

Supported inputs:
- Plain text
- PDF: embedded text first, then Claude PDF vision, then rendered page images
- Claude-native images: JPEG, PNG, GIF, WebP
- Normalized images: HEIC/HEIF, TIFF and BMP converted to PNG in memory

The original uploaded bytes are never modified; normalization is used only for
analysis. Multi-frame TIFF/HEIF files are sent as ordered PNG image blocks.
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
_MAX_PIXELS_PER_FRAME = 40_000_000

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


def image_blocks_for_vision(file_bytes: bytes, suffix: str) -> list[dict]:
    """Return Claude-compatible image blocks for one uploaded image file.

    Claude-native formats pass through unchanged. HEIC/HEIF, TIFF and BMP are
    decoded with Pillow and re-encoded as ordered PNG frames. This also prevents
    the app from claiming support for media types the vision API does not accept.
    """
    suffix = suffix.lower()
    media_type = DIRECT_IMAGE_MEDIA_TYPES.get(suffix)
    if media_type:
        return [_image_block(file_bytes, media_type)]

    if suffix not in NORMALIZED_IMAGE_SUFFIXES:
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
            oriented = ImageOps.exif_transpose(frame.copy())
            width, height = oriented.size
            if width * height > _MAX_PIXELS_PER_FRAME:
                raise ValueError(
                    f"Image frame is too large ({width}×{height}). Resize it below "
                    f"{_MAX_PIXELS_PER_FRAME:,} pixels before uploading."
                )
            normalized = oriented.convert("RGB")
            buffer = BytesIO()
            normalized.save(buffer, format="PNG", optimize=True)
            blocks.append(_image_block(buffer.getvalue(), "image/png"))

    if not blocks:
        raise ValueError("The image did not contain a readable frame.")
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
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
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
    """OCR a PDF by rasterizing each page to PNG and reading the images."""
    import fitz  # PyMuPDF

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    content: list[dict] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for page in pdf:
            png = page.get_pixmap(dpi=150).tobytes("png")
            content.append(_image_block(png, "image/png"))
    content.append({"type": "text", "text": _OCR_PROMPT})
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
