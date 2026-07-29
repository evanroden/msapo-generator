"""Provider- and reader-neutral OCR and text extraction for vendor quotes."""

from __future__ import annotations

import base64
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

from app.ai_provider import (
    AIProvider,
    AIProviderError,
    AIRequest,
    BinaryPart,
    CAP_DOCUMENT,
    CAP_IMAGE,
    UnsupportedCapabilityError,
    get_ai_provider,
    require_capability,
)
from app.pdf_reader import PDFReader, RenderedPage, get_pdf_reader


_OCR_PROMPT = (
    "Extract ALL text from this vendor quote exactly as written — every line, "
    "number, price, quantity, and detail, preserving order. Output only the "
    "extracted text, no commentary."
)
_MAX_IMAGE_FRAMES = 20
_MAX_PIXELS_PER_FRAME = 40_000_000
_MAX_IMAGE_INPUT_BYTES = 50 * 1024 * 1024

DIRECT_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
NORMALIZED_IMAGE_SUFFIXES = {".bmp", ".tif", ".tiff", ".heic", ".heif", ".hif"}
SUPPORTED_IMAGE_SUFFIXES = set(DIRECT_IMAGE_MEDIA_TYPES) | NORMALIZED_IMAGE_SUFFIXES


def _positive_int(env: Mapping[str, str], name: str, default: int, *, maximum: int) -> int:
    raw = str(env.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < 1 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}.")
    return value


def _image_block(data: bytes, media_type: str) -> dict:
    """Legacy Claude-shaped block retained for existing tests and callers."""
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def image_parts_for_vision(file_bytes: bytes, suffix: str) -> list[BinaryPart]:
    if len(file_bytes) > _MAX_IMAGE_INPUT_BYTES:
        raise ValueError("Image input exceeds the 50 MB safety limit.")
    suffix = suffix.lower()
    media_type = DIRECT_IMAGE_MEDIA_TYPES.get(suffix)
    if media_type:
        return [BinaryPart(CAP_IMAGE, file_bytes, media_type)]
    if suffix not in NORMALIZED_IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported image type: {suffix or '(no extension)'}")

    if suffix in {".heic", ".heif", ".hif"}:
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise ValueError(
                "HEIC/HEIF support is not installed. Install the default image adapter dependencies."
            ) from exc
        register_heif_opener(thumbnails=False)

    from PIL import Image, ImageOps, ImageSequence

    parts: list[BinaryPart] = []
    with Image.open(BytesIO(file_bytes)) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        if frame_count > _MAX_IMAGE_FRAMES:
            raise ValueError(
                f"This image contains {frame_count} pages/frames; the maximum is {_MAX_IMAGE_FRAMES}."
            )
        for frame in ImageSequence.Iterator(image):
            oriented = ImageOps.exif_transpose(frame.copy())
            width, height = oriented.size
            if width * height > _MAX_PIXELS_PER_FRAME:
                raise ValueError(
                    f"Image frame is too large ({width}×{height}); reduce it below "
                    f"{_MAX_PIXELS_PER_FRAME:,} pixels."
                )
            buffer = BytesIO()
            oriented.convert("RGB").save(buffer, format="PNG", optimize=True)
            parts.append(BinaryPart(CAP_IMAGE, buffer.getvalue(), "image/png"))
    if not parts:
        raise ValueError("The image did not contain a readable frame.")
    if sum(len(part.data) for part in parts) > _MAX_IMAGE_INPUT_BYTES:
        raise ValueError("Normalized image frames exceed the 50 MB safety limit.")
    return parts


def image_blocks_for_vision(file_bytes: bytes, suffix: str) -> list[dict]:
    return [
        _image_block(part.data, part.media_type)
        for part in image_parts_for_vision(file_bytes, suffix)
    ]


def _complete_ocr(provider: AIProvider, parts: Sequence[BinaryPart], prompt: str) -> str:
    capability = CAP_IMAGE if any(part.kind == CAP_IMAGE for part in parts) else CAP_DOCUMENT
    require_capability(provider, capability)
    text = provider.complete(
        AIRequest(
            operation="quote_ocr",
            prompt=prompt,
            parts=tuple(parts),
            max_tokens=8192,
        )
    ).strip()
    if not text:
        raise AIProviderError("The OCR provider returned no text.", code="empty_response")
    return text


def _usable_embedded_text(text: str, min_chars: int) -> bool:
    cleaned = text.strip()
    if len(cleaned) < min_chars:
        return False
    printable = sum(
        1 for character in cleaned if character.isprintable() or character in "\n\t"
    )
    if printable / max(1, len(cleaned)) < 0.85:
        return False
    return len(re.findall(r"[A-Za-z0-9]{2,}", cleaned)) >= 3


def _ocr_rendered_pages(
    pages: Sequence[RenderedPage],
    provider: AIProvider,
    *,
    batch_size: int,
) -> str:
    require_capability(provider, CAP_IMAGE)
    outputs: list[str] = []
    for start in range(0, len(pages), batch_size):
        batch = pages[start : start + batch_size]
        labels = f"pages {batch[0].page_number}-{batch[-1].page_number}"
        parts = [
            BinaryPart(CAP_IMAGE, page.data, page.media_type) for page in batch
        ]
        outputs.append(
            _complete_ocr(
                provider,
                parts,
                f"{_OCR_PROMPT}\nThese are {labels}; preserve their page order.",
            )
        )
    return "\n".join(output for output in outputs if output).strip()


def extract_text_from_pdf(
    file_bytes: bytes,
    *,
    provider: AIProvider | None = None,
    reader: PDFReader | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    active_reader = reader or get_pdf_reader(source)
    result = active_reader.extract_text(file_bytes)
    min_chars = _positive_int(source, "EPC_PDF_TEXT_MIN_CHARS", 20, maximum=10000)
    if _usable_embedded_text(result.text, min_chars):
        return result.text.strip()

    active_provider = provider or get_ai_provider(source)
    if CAP_DOCUMENT in active_provider.capabilities:
        try:
            return _complete_ocr(
                active_provider,
                [
                    BinaryPart(
                        CAP_DOCUMENT,
                        result.analysis_bytes,
                        "application/pdf",
                        "quote.pdf",
                    )
                ],
                _OCR_PROMPT,
            )
        except UnsupportedCapabilityError:
            pass
        except AIProviderError:
            # Authentication, network, and quota failures must not be hidden by a
            # second expensive request through another representation.
            raise

    max_pages = _positive_int(source, "EPC_OCR_MAX_PAGES", 30, maximum=200)
    dpi = _positive_int(source, "EPC_OCR_DPI", 150, maximum=400)
    batch_size = _positive_int(source, "EPC_OCR_PAGES_PER_BATCH", 5, maximum=20)
    max_pixels = _positive_int(
        source,
        "EPC_OCR_MAX_PIXELS_PER_PAGE",
        40_000_000,
        maximum=100_000_000,
    )
    pages = active_reader.render_pages(
        result.analysis_bytes,
        dpi=dpi,
        max_pages=max_pages,
        max_pixels_per_page=max_pixels,
    )
    if not pages:
        raise ValueError("The configured PDF reader returned no rendered pages for OCR.")
    max_total_bytes = _positive_int(
        source,
        "EPC_OCR_MAX_TOTAL_IMAGE_BYTES",
        50 * 1024 * 1024,
        maximum=250 * 1024 * 1024,
    )
    total_bytes = sum(len(page.data) for page in pages)
    if total_bytes > max_total_bytes:
        raise ValueError(
            f"Rendered PDF pages total {total_bytes:,} bytes, above the configured "
            f"OCR limit of {max_total_bytes:,}."
        )
    return _ocr_rendered_pages(pages, active_provider, batch_size=batch_size)


def extract_text_from_image(
    file_bytes: bytes,
    suffix: str,
    *,
    provider: AIProvider | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    active_provider = provider or get_ai_provider(source)
    parts = image_parts_for_vision(file_bytes, suffix)
    return _complete_ocr(active_provider, parts, _OCR_PROMPT)


def extract_text(
    file_bytes: bytes,
    filename: str,
    *,
    provider: AIProvider | None = None,
    reader: PDFReader | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        return file_bytes.decode("utf-8", errors="replace")
    if suffix == ".pdf":
        return extract_text_from_pdf(
            file_bytes,
            provider=provider,
            reader=reader,
            env=env,
        )
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        return extract_text_from_image(
            file_bytes,
            suffix,
            provider=provider,
            env=env,
        )
    return file_bytes.decode("utf-8", errors="replace")


# Backward-compatible helpers retained for older imports and targeted tests.
def _ocr_pdf_via_document(
    file_bytes: bytes,
    *,
    provider: AIProvider | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    active_provider = provider or get_ai_provider(source)
    return _complete_ocr(
        active_provider,
        [BinaryPart(CAP_DOCUMENT, file_bytes, "application/pdf", "quote.pdf")],
        _OCR_PROMPT,
    )


def _ocr_pdf_via_page_images(
    file_bytes: bytes,
    *,
    provider: AIProvider | None = None,
    reader: PDFReader | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    active_provider = provider or get_ai_provider(source)
    active_reader = reader or get_pdf_reader(source)
    max_pages = _positive_int(source, "EPC_OCR_MAX_PAGES", 30, maximum=200)
    dpi = _positive_int(source, "EPC_OCR_DPI", 150, maximum=400)
    batch_size = _positive_int(source, "EPC_OCR_PAGES_PER_BATCH", 5, maximum=20)
    max_pixels = _positive_int(
        source,
        "EPC_OCR_MAX_PIXELS_PER_PAGE",
        40_000_000,
        maximum=100_000_000,
    )
    pages = active_reader.render_pages(
        file_bytes,
        dpi=dpi,
        max_pages=max_pages,
        max_pixels_per_page=max_pixels,
    )
    if not pages:
        raise ValueError("The configured PDF reader returned no rendered pages for OCR.")
    return _ocr_rendered_pages(pages, active_provider, batch_size=batch_size)
