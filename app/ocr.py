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
import time
from io import BytesIO
from pathlib import Path

import anthropic

from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from app.api_retry import (
    OPERATION_BUDGET_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    complete_response_text,
    request_with_retry,
)


_OCR_PROMPT = (
    "Extract ALL text from this vendor quote exactly as written — every line, "
    "number, price, quantity, and detail, preserving the order. Output only the "
    "extracted text, no commentary."
)
_MAX_IMAGE_FRAMES = 20
# Pages sent to VISION, not pages in the document. Native-text pages are read
# locally -- no API call, no payload, no cost -- so counting them against a
# vision budget rejects documents that were never going to touch the API.
#
# A real 26-page steam-trap quote was refused by the old document-level cap with
# "Split it into smaller quotes before uploading", and every one of its 26 pages
# had native text: the extraction would have been entirely local. Splitting a
# quote also corrupts the deliverable -- the package attaches the vendor's
# original file, so an operator who split it would attach half a quote.
_MAX_PDF_PAGES = 20
# The page cap used to bound extracted TEXT as a side effect. Now that page
# count no longer limits native reading, that bound has to be explicit, or a
# pathological document would be accepted here and fail later inside
# analyze_quote where the message names nothing the operator can act on.
# ~400k characters is roughly 100k tokens, half the model context, and about
# 470 pages at the density of a real quote (~850 chars/page).
_MAX_EXTRACTED_CHARS = 400_000
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


def _images_cover_half_page(page, images: list[dict]) -> bool:
    """Measure the union of visible image rectangles, not the largest tile.

    Scanners may store one page in several strips under a native-text header.
    Summing areas alone also fails: repeated, overlapping logos can look like
    a full scan. Sweep disjoint x bands and merge their y intervals instead.
    Image coordinates are unrotated, unlike Page.rect; clip in that same space.
    """
    import fitz

    bounds = page.rect * page.derotation_matrix
    threshold = max(1.0, bounds.get_area()) * 0.5
    rectangles = set()
    for info in images:
        rect = fitz.Rect(info["bbox"]) & bounds
        if rect.is_empty:
            continue
        if rect.get_area() >= threshold:
            return True
        rectangles.add(tuple(rect))
    xs = sorted({x for left, _, right, _ in rectangles for x in (left, right)})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted(
            (top, bottom) for x0, top, x1, bottom in rectangles
            if x0 < right and x1 > left
        )
        if not intervals:
            continue
        start, end = intervals[0]
        height = 0.0
        for top, bottom in intervals[1:]:
            if top > end:
                height += end - start
                start, end = top, bottom
            else:
                end = max(end, bottom)
        area += (right - left) * (height + end - start)
        if area >= threshold:
            return True
    return False


def _page_needs_ocr(page, *, native_text: str | None = None) -> bool:
    """Classify once during preflight, reusing text already decoded locally."""
    native = page.get_text().strip() if native_text is None else native_text
    images = page.get_image_info()
    large_scan = _images_cover_half_page(page, images)
    return large_scan or (len(native) < 20 and bool(images or page.get_drawings()))


def _check_extracted_size(size: int) -> None:
    if size > _MAX_EXTRACTED_CHARS:
        raise ValueError(
            f"This document holds {size:,} characters of text; the maximum "
            f"is {_MAX_EXTRACTED_CHARS:,}. Upload the quote pages only, or paste "
            "the relevant section."
        )


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Read native pages locally; OCR scanned pages in ordered contiguous runs."""
    import fitz

    until = time.monotonic() + OPERATION_BUDGET_SECONDS
    parts: list[str] = []
    output_size = 0

    def append(text: str) -> None:
        nonlocal output_size
        output_size += len(text) + bool(parts)
        _check_extracted_size(output_size)
        parts.append(text)

    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        if pdf.is_encrypted and not pdf.authenticate(""):
            raise ValueError("This PDF needs a password. Upload an unlocked copy.")
        # Counted BEFORE any OCR call, so a document over budget costs nothing
        # and fails with a complete number. Counting inside the read loop would
        # bill several vision requests before discovering the total.
        # Reuse this exact plan during reading: the previous pre-count plus
        # read loop decoded every native page three times, and only checked
        # the known native-text budget after making paid OCR calls.
        plan: list[str | None] = []
        scanned = native_size = 0
        for page in pdf:
            native = page.get_text().strip()
            if _page_needs_ocr(page, native_text=native):
                scanned += 1
                plan.append(None)
            else:
                native_size += len(native)
                _check_extracted_size(native_size)
                plan.append(native)
        if scanned > _MAX_PDF_PAGES:
            raise ValueError(
                f"This PDF has {scanned} scanned pages needing image reading; "
                f"the maximum is {_MAX_PDF_PAGES}. Upload a text-based copy, or "
                "paste the quote text instead."
            )
        pending: list[int] = []

        def flush() -> None:
            if not pending:
                return
            with fitz.open() as subset:
                subset.insert_pdf(pdf, from_page=pending[0], to_page=pending[-1])
                payload = subset.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
            append(_ocr_pdf(payload, until=until))
            pending.clear()

        for index, native in enumerate(plan):
            if native is None:
                pending.append(index)
            else:
                flush()
                append(native)
        flush()
    return "\n".join(parts).strip()


def _ocr_pdf(payload: bytes, *, until: float) -> str:
    try:
        text = _ocr_pdf_via_document(payload, until=until).strip()
        if text:
            return text
    except anthropic.APIStatusError as exc:
        # Changing representation cannot repair auth, rate limiting or outages.
        if exc.status_code not in (400, 413):
            raise
    except ValueError:
        pass  # Local direct-document payload budget: try compact pages.
    text = _ocr_pdf_via_page_images(payload, until=until).strip()
    if not text:
        raise ValueError("Scanned quote pages could not be read. Upload a clearer copy or paste the complete text.")
    return text


def _ocr_request(content: list[dict], *, until: float | None = None) -> str:
    until = until if until is not None else time.monotonic() + OPERATION_BUDGET_SECONDS
    with anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        message = request_with_retry(
            lambda timeout: client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=8192, timeout=timeout,
                messages=[{"role": "user", "content": content}],
            ), until=until,
        )
    return complete_response_text(message)


def _ocr_pdf_via_document(file_bytes: bytes, *, until: float | None = None) -> str:
    """OCR a PDF by sending it to Claude as a native document block."""
    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    if len(b64) > _MAX_TOTAL_ENCODED_BYTES:
        raise ValueError(
            "This PDF is too large for direct document OCR; trying bounded "
            "page images instead."
        )
    return _ocr_request([
        {"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf", "data": b64,
        }},
        {"type": "text", "text": _OCR_PROMPT},
    ], until=until)


def _ocr_pdf_via_page_images(file_bytes: bytes, *, until: float | None = None) -> str:
    """OCR a PDF through bounded, normalized page images."""
    import fitz  # PyMuPDF

    content: list[dict] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
        # Backstop, not the operator-facing budget. extract_text_from_pdf counts
        # scanned pages across the whole document before any OCR runs, and hands
        # this function one contiguous run of them -- so a run over the budget
        # implies the pre-count already refused the document. It stays as a
        # guard for a direct caller that skipped that path.
        #
        # The wording is NOT the old "Split it into smaller quotes before
        # uploading". That advice was actively wrong: the PO package attaches
        # the vendor's ORIGINAL file, so splitting a quote to satisfy the tool
        # attaches half a quote to the purchase order.
        if pdf.page_count > _MAX_PDF_PAGES:
            raise ValueError(
                f"This run holds {pdf.page_count} scanned pages needing image "
                f"reading; the maximum is {_MAX_PDF_PAGES}. Upload a text-based "
                "copy, or paste the quote text instead."
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
    return _ocr_request(content, until=until)


def extract_text_from_image(file_bytes: bytes, suffix: str) -> str:
    """Normalize all frames, then make one bounded OCR request."""
    content = image_blocks_for_vision(file_bytes, suffix)
    content.append({"type": "text", "text": _OCR_PROMPT})
    return _ocr_request(content)


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
