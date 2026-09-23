"""The page budget bounds VISION work, not document length.

Reported from production: two 26-page steam-trap quotes were refused with

    The file could not be read. Try reading it again, upload a clearer copy,
    or switch to Paste text.
    File-reading detail: This PDF contains 26 pages; the maximum is 20. Split
    it into smaller quotes before uploading.

Every one of those 26 pages carried native text. Only 3 pages -- image-heavy
ones with almost no text -- actually needed OCR. The extraction was almost
entirely local: no API call, no payload, no cost. The cap rejected them anyway,
because it counted PAGES IN THE DOCUMENT rather than pages going to vision.

The advice it gave was also the wrong thing to do. The PO package attaches the
vendor's ORIGINAL file, so an operator who split the quote to satisfy the tool
would have attached half a quote to the purchase order.

The cap was doing a second, unnamed job: bounding how much text reached
analyze_quote. Removing it without replacement would have traded a clear error
for a context blowout inside the analyzer, where the message names nothing the
operator can act on. That bound is now explicit.
"""

from __future__ import annotations

from unittest import mock

import fitz
import pytest

import app.ocr as ocr
from app.ocr import _MAX_EXTRACTED_CHARS, _MAX_PDF_PAGES, extract_text_from_pdf


def _native_pdf(pages: int, text: str = "Steam trap survey line item") -> bytes:
    """A text-based PDF -- the shape that needs no vision at all."""
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"{text} page {index + 1}")
    payload = document.tobytes()
    document.close()
    return payload


def _scanned_pdf(pages: int) -> bytes:
    """Pages carrying a full-page image and no text -- these must go to vision."""
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80))
        pixmap.clear_with(255)
        page.insert_image(page.rect, pixmap=pixmap)
    payload = document.tobytes()
    document.close()
    return payload


def test_a_long_text_based_quote_is_read_without_any_vision_call():
    """The reported case. 26 native pages, well past the old 20-page cap.

    _ocr_pdf is patched to EXPLODE: if the reader reaches for vision on a
    document like this, the test fails rather than silently passing on a
    mocked-out return value.
    """
    payload = _native_pdf(26)

    def _must_not_be_called(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("a native-text PDF must not be sent to vision")

    with mock.patch.object(ocr, "_ocr_pdf", _must_not_be_called):
        text = extract_text_from_pdf(payload)

    assert "page 1" in text
    assert "page 26" in text


@pytest.mark.parametrize("pages", [21, 40, 120])
def test_page_count_alone_never_blocks_a_text_based_quote(pages):
    """There is no document-length limit any more, only a vision budget."""
    with mock.patch.object(ocr, "_ocr_pdf", lambda *_a, **_k: ""):
        assert extract_text_from_pdf(_native_pdf(pages))


def test_a_document_over_the_scanned_page_budget_is_still_refused():
    """The budget the cap exists for. These pages genuinely cost vision calls."""
    with pytest.raises(ValueError, match="scanned pages"):
        extract_text_from_pdf(_scanned_pdf(_MAX_PDF_PAGES + 1))


def test_the_scanned_budget_is_counted_before_any_vision_call_is_made():
    """Counted up front so an over-budget document costs nothing and the number
    in the message is complete. Counting inside the read loop would bill several
    requests before discovering the total."""

    def _must_not_be_called(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("billed a vision call before refusing the document")

    with mock.patch.object(ocr, "_ocr_pdf", _must_not_be_called):
        with pytest.raises(ValueError, match="scanned pages"):
            extract_text_from_pdf(_scanned_pdf(_MAX_PDF_PAGES + 1))


def test_a_scanned_quote_within_budget_still_reads():
    with mock.patch.object(ocr, "_ocr_pdf", lambda *_a, **_k: "scanned text"):
        assert "scanned text" in extract_text_from_pdf(_scanned_pdf(3))


def test_the_message_names_scanned_pages_not_total_pages():
    """"Split it into smaller quotes" was actively harmful advice: the package
    attaches the vendor's ORIGINAL file, so splitting attaches half a quote."""
    with pytest.raises(ValueError) as caught:
        extract_text_from_pdf(_scanned_pdf(_MAX_PDF_PAGES + 1))

    message = str(caught.value)
    assert "scanned pages" in message
    assert "Split it into smaller quotes" not in message
    assert "paste the quote text" in message.lower()


def test_a_runaway_document_is_bounded_by_extracted_text():
    """The cap was silently bounding text length too. That job is now explicit,
    so a pathological document fails HERE with an actionable message instead of
    inside analyze_quote."""
    oversized = "x" * (_MAX_EXTRACTED_CHARS + 1)

    with mock.patch.object(ocr, "_ocr_pdf", lambda *_a, **_k: ""):
        with mock.patch.object(
            fitz.Page, "get_text", lambda self, *a, **k: oversized
        ):
            with pytest.raises(ValueError, match="characters of text"):
                extract_text_from_pdf(_native_pdf(1))


def test_a_real_sized_quote_is_far_inside_the_text_bound():
    """~850 chars/page on a real quote, so the bound is ~470 pages. It exists to
    catch a runaway, not to constrain ordinary work."""
    with mock.patch.object(ocr, "_ocr_pdf", lambda *_a, **_k: ""):
        text = extract_text_from_pdf(_native_pdf(26))
    assert len(text) < _MAX_EXTRACTED_CHARS / 10
