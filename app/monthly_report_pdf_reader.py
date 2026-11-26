"""Local, bounded PDF page reading for monthly evidence (no network/model calls).

Native PDF text remains the initial evidence; OCR is supplementary and *never*
constitutes approval for activity extraction. OCR spans use 1-based source page,
character offsets in the returned page text, 0..100 confidence and unrotated
page-coordinate rectangles (the same space as native text blocks and image regions). The original PDF is never modified.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
from io import BytesIO, StringIO
import math
import shutil
import subprocess
import time

import pymupdf as fitz
from app.extracted_text import normalize_extracted_text
from app.image_open import open_image

# Keep long originals admitted; expensive local OCR is separately bounded.
MAX_LOCAL_OCR_PAGES = 20
MAX_LOCAL_OCR_SECONDS = 90
MAX_OCR_PIXELS = 8_000_000
MAX_OCR_PIXELS_LOW_MEMORY = 4_000_000
MIN_IMAGE_PAGE_FRACTION = 0.01


@dataclass(frozen=True)
class PageRead:
    text: str
    needs_vision: bool = False
    notice: str = ""
    # page, start, end, confidence, bbox on the *unrotated* page.
    ocr_spans: tuple[tuple[int, int, int, float, tuple[float, float, float, float]], ...] = ()
    attempted_ocr: bool = False


def _memory_limit() -> int | None:
    """Cgroup v2/v1 memory limit; never infer capacity from host RAM alone."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path, encoding="ascii") as memory_file:
                value = memory_file.read().strip()
            if value.isdecimal() and 0 < int(value) < (1 << 60):
                return int(value)
        except OSError:
            continue
    return None


def _image_regions(page) -> tuple[fitz.Rect, ...]:
    """Only embedded image areas missing native text; ignore logos/icons."""
    unrotated = page.rect * page.derotation_matrix
    if unrotated.is_empty:
        return ()
    images = page.get_image_info()
    if not images:
        return ()
    area = unrotated.get_area()
    text_boxes = [fitz.Rect(block[:4]) for block in page.get_text("blocks")
                  if len(block) > 6 and block[6] == 0 and str(block[4]).strip()]
    regions = []
    for item in images:
        box = fitz.Rect(item["bbox"]) & unrotated
        if box.is_empty or box.get_area() < area * MIN_IMAGE_PAGE_FRACTION:
            continue
        # Small logos confined to the top page margin are not unread charts.
        if (box.get_area() < area * 0.09
                and box.y1 < unrotated.y0 + unrotated.height * 0.18):
            continue
        # A scanned underlay with a searchable text layer is *not* a missing
        # region. Native headers elsewhere on the page do not hide image text.
        overlap = sum((box & text_box).get_area() for text_box in text_boxes)
        if overlap > box.get_area() * 0.035:
            continue
        regions.append(box)
    if not regions:
        return ()
    # Multi-strip scans are one image area; OCR once, not strip-by-strip.
    union = fitz.Rect(regions[0])
    for box in regions[1:]:
        union |= box
    return (union,)


def _column_text(page, native: str) -> tuple[str, bool]:
    """Reorder only unambiguous two-column lines, not adjacent table cells.

    PyMuPDF sometimes puts side-by-side lines into *one text block*, so block
    bboxes are insufficient. Native reading order is retained for uncertainty.
    """
    if native.count("\n") < 2:
        return native, False
    lines = []
    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            if line.get("wmode") != 0 or tuple(line.get("dir", ())) != (1.0, 0.0):
                continue
            content = normalize_extracted_text(
                "".join(span.get("text", "") for span in line.get("spans", ()))).strip()
            if content:
                lines.append((fitz.Rect(line["bbox"]), content))
    if len(lines) < 4:
        return native, False
    middle = (page.rect * page.derotation_matrix).width / 2
    left = [(box, value) for box, value in lines if box.x1 < middle - 8]
    right = [(box, value) for box, value in lines if box.x0 > middle + 8]
    if len(left) < 2 or len(right) < 2 or len(left) + len(right) != len(lines):
        return native, False
    if max(box.y0 for box, _ in left) < min(box.y0 for box, _ in right) or max(box.y0 for box, _ in right) < min(box.y0 for box, _ in left):
        return native, False
    # Lines wholly above the band both columns share (a header) come first and
    # lines wholly below it (a footer) come last, whichever side they sit on.
    band_top = max(min(box.y0 for box, _ in left), min(box.y0 for box, _ in right))
    band_bottom = min(max(box.y1 for box, _ in left), max(box.y1 for box, _ in right))
    before = [item for item in lines if item[0].y1 <= band_top]
    after = [item for item in lines if item[0].y0 >= band_bottom and item not in before]
    edges = before + after
    by_position = lambda item: (item[0].y0, item[0].x0)
    reading = "\n".join(value for group in (
        sorted(before, key=by_position),
        sorted((item for item in left if item not in edges), key=by_position),
        sorted((item for item in right if item not in edges), key=by_position),
        sorted(after, key=by_position)) for box, value in group)
    # Refuse to fabricate source words when native and geometric reading differ.
    if sorted(reading.split()) != sorted(native.split()):
        return native, True
    return reading, True

def _ocr_image(png: bytes, *, timeout: float) -> str:
    """Tesseract TSV permits per-line source offsets, boxes and confidence."""
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6", "tsv"],
        input=png, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=max(1.0, timeout), check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Local OCR could not decode the page image.")
    return result.stdout.decode("utf-8", errors="replace")


def _ocr_lines(tsv: str, *, clip: fitz.Rect, image_width: int, image_height: int):
    """Return (text, confidence, page bbox) for each recognized line.

    The caller passes the raster in its upright orientation and the clip in
    unrotated page coordinates, so OCR pixels scale straight onto the page:
    no display-rotation transform is applied here.
    """
    groups: dict[tuple[str, str, str], list[tuple[str, float, tuple[int, int, int, int]]]] = {}
    for row in csv.DictReader(StringIO(tsv), delimiter="\t"):
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        try:
            confidence = float(row["conf"])
            box = tuple(int(row[k]) for k in ("left", "top", "width", "height"))
        except (KeyError, TypeError, ValueError):
            continue
        if not word or confidence < 20 or len(box) != 4:
            continue
        key = (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))
        groups.setdefault(key, []).append((word, confidence, box))
    lines = []
    for values in groups.values():
        text = " ".join(word for word, _, _ in values)
        score = round(sum(conf for _, conf, _ in values) / len(values), 1)
        x0 = min(b[0] for _, _, b in values)
        y0 = min(b[1] for _, _, b in values)
        x1 = max(b[0] + b[2] for _, _, b in values)
        y1 = max(b[1] + b[3] for _, _, b in values)
        # The upright raster is the unrotated page, so OCR pixels map
        # directly onto the unrotated clip; a rotated page's bbox stays
        # inside the unrotated page bounds instead of the wider display.
        rect = (round(clip.x0 + x0 * clip.width / image_width, 2),
                round(clip.y0 + y0 * clip.height / image_height, 2),
                round(clip.x0 + x1 * clip.width / image_width, 2),
                round(clip.y0 + y1 * clip.height / image_height, 2))
        lines.append((text, score, rect))
    return lines


def read_page(page, number: int, *, native_text: str, needs_ocr: bool,
              may_ocr: bool, deadline: float | None = None) -> PageRead:
    """Return a page even when OCR is absent, times out or produces no text.

    Unread and unverified OCR are always flagged in the normal source notices.
    OCR requires a locally installed executable; it never calls paid AI.
    """
    native = native_text.strip()
    ordered, columns = _column_text(page, native)
    regions = _image_regions(page)
    has_annotations = bool(page.first_annot)
    needs_visual = bool(needs_ocr or regions or columns or has_annotations)
    if not needs_visual:
        return PageRead(ordered)
    if not (needs_ocr or regions or has_annotations):
        return PageRead(ordered, True, f"Page {number}: side-by-side text columns need visual reading-order review.")
    label = f"Page {number}: unread/needs visual review"
    # Searchable text layers over scanned/image-heavy pages should not be
    # duplicated by OCR of the entire raster. Mixed pages with *missing*
    # image regions are still read selectively above.
    if native and len(native) >= 20 and not regions:
        return PageRead(ordered, True,
                        f"Page {number}: native text with image/graphic/annotation content; verify completeness visually.")
    if (regions and not needs_ocr and not has_annotations and not columns
            and len(native.split()) >= 35):
        # Substantive native text is the page evidence; a chart/image region
        # still needs a visual check, but the page is readable, not unread.
        # Keep the review notice without marking the page unreadable, so a
        # technical annex is not dropped from the suggested pages.
        return PageRead(ordered, False,
                        f"Page {number}: native text with image/graphic/annotation content; verify completeness visually.")
    if not may_ocr:
        return PageRead(ordered, True, label + " (local OCR page/time budget reached).")
    if not shutil.which("tesseract"):
        return PageRead(ordered, True, label + " (local OCR is unavailable on this server).")
    if deadline is not None and time.monotonic() >= deadline:
        return PageRead(ordered, True, label + " (local OCR time budget reached).")
    try:
        clip = fitz.Rect(regions[0]) if regions and page.rotation == 0 else fitz.Rect(page.rect)
        # A page with image strips is read once. Raster bytes stay in memory
        # only for this call; each page is released before reading the next.
        cap = MAX_OCR_PIXELS_LOW_MEMORY if (_memory_limit() or 1 << 60) <= 768 * 1024 * 1024 else MAX_OCR_PIXELS
        dpi = min(170, max(70, math.floor(72 * math.sqrt(cap / max(1, clip.get_area())))))
        width, height = math.ceil(clip.width * dpi / 72), math.ceil(clip.height * dpi / 72)
        if width * height > cap or width <= 0 or height <= 0:
            return PageRead(ordered, True, label + " (page exceeds local OCR raster budget).")
        pix = page.get_pixmap(dpi=dpi, clip=clip, colorspace=fitz.csGRAY, alpha=False)
        png = pix.tobytes("png")
        if page.rotation:
            with open_image(BytesIO(png), formats=("PNG",)) as original:
                upright = original.rotate(page.rotation, expand=True)
                data = BytesIO()
                upright.save(data, "PNG")
                png = data.getvalue()
                rotated_width, rotated_height = upright.size
        else:
            rotated_width, rotated_height = pix.width, pix.height
        tsv = _ocr_image(png, timeout=min(18, max(1, (deadline - time.monotonic()) if deadline else 18)))
        # The upright raster is the unrotated page, so hand _ocr_lines the
        # derotated clip; its bboxes land in unrotated page coordinates.
        lines = _ocr_lines(tsv, clip=clip * page.derotation_matrix,
                           image_width=rotated_width,
                           image_height=rotated_height)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return PageRead(ordered, True, label + " (local OCR failed; original page remains available).", attempted_ocr=True)
    if not lines:
        return PageRead(ordered, True, label + " (local OCR returned no readable text).", attempted_ocr=True)
    text, spans = ordered, []
    for line, confidence, bbox in lines:
        start = len(text) + (1 if text else 0)
        text += ("\n" if text else "") + line
        spans.append((number, start, len(text), confidence, bbox))
    mean_confidence = round(sum(span[3] for span in spans) / len(spans))
    return PageRead(text, True, f"Page {number}: local OCR extracted unverified text "
                    f"(mean confidence {mean_confidence}%). Review against the original page.",
                    tuple(spans), True)
