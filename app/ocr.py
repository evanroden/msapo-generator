"""
OCR / text extraction helpers for incoming quote files.

Supports:
  - Plain text (.txt)
  - PDF  — extracted via PyMuPDF (fitz)
  - Images (.png, .jpg, .jpeg, .tiff, .bmp) — sent to Claude's vision
"""

from __future__ import annotations

import base64
from pathlib import Path

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL


_OCR_PROMPT = (
    "Extract ALL text from this vendor quote exactly as written — every line, "
    "number, price, quantity, and detail, preserving the order. Output only the "
    "extracted text, no commentary."
)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF.

    First tries the embedded text layer (fast, free).  Scanned / image-only
    PDFs — common for vendor quotes — have no text layer, so PyMuPDF returns
    nothing; in that case fall back to reading the PDF with Claude's vision.
    """
    import fitz  # PyMuPDF

    text_parts: list[str] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for page in pdf:
            text_parts.append(page.get_text())
    text = "\n".join(text_parts).strip()

    if len(text) >= 20:  # has a real, usable text layer
        return text

    # No usable text layer (scanned/image PDF) → OCR via Claude.
    try:
        return _ocr_pdf_via_document(file_bytes)
    except Exception:
        # Fallback: rasterize each page and OCR the images.
        return _ocr_pdf_via_page_images(file_bytes)


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
    """OCR a PDF by rasterizing each page to a PNG and reading the images."""
    import fitz  # PyMuPDF

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    content: list[dict] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        for page in pdf:
            png = page.get_pixmap(dpi=150).tobytes("png")
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.standard_b64encode(png).decode("ascii"),
                    },
                }
            )
    content.append({"type": "text", "text": _OCR_PROMPT})
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text.strip()


def extract_text_from_image(file_bytes: bytes, media_type: str) -> str:
    """Use Claude's vision capability to read text from an image."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract ALL text from this vendor quote image. "
                            "Reproduce every line, number, and detail exactly "
                            "as written. Output only the extracted text."
                        ),
                    },
                ],
            }
        ],
    )
    return message.content[0].text.strip()


IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}


def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Detect file type and extract text accordingly.
    """
    suffix = Path(filename).suffix.lower()

    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="replace")

    if suffix == ".pdf":
        return extract_text_from_pdf(file_bytes)

    media_type = IMAGE_MEDIA_TYPES.get(suffix)
    if media_type:
        return extract_text_from_image(file_bytes, media_type)

    # Fallback: try to decode as text
    return file_bytes.decode("utf-8", errors="replace")
