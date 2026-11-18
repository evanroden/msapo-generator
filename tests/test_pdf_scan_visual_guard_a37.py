"""A37 synthetic scanned/mixed PDF controls; no client data or paid models."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from unittest import mock

import pymupdf as fitz
from PIL import Image, ImageDraw
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import ocr
from app.monthly_report_model import synthetic_profiles


def _image(text: str = "", *, size=(800, 1024)) -> bytes:
    image = Image.new("RGB", size, "white")
    if text:
        drawing = ImageDraw.Draw(image)
        for row in range(9):
            drawing.text((30, 40 + row * 85), text, fill="black", stroke_width=1)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _synthetic_pages() -> bytes:
    with fitz.open() as pdf:
        native = pdf.new_page(width=612, height=792)
        native.insert_text((50, 70), "Native technical data " + "Reviewed inspection. " * 8)

        scan = pdf.new_page(width=612, height=792)
        scan.insert_image(scan.rect, stream=_image("VALVE 91A DID NOT CLOSE"))

        white = pdf.new_page(width=612, height=792)
        white.insert_image(white.rect, stream=_image())

        hybrid = pdf.new_page(width=612, height=792)
        hybrid.insert_text(
            (40, 50),
            "Native observations from supervisor: ventilation checked with diagram below.",
        )
        hybrid.insert_image(
            fitz.Rect(90, 150, 522, 520),
            stream=_image("PUMP-7 PENDING", size=(400, 300)),
        )

        rotated = pdf.new_page(width=612, height=792)
        rotated.insert_image(rotated.rect, stream=_image("ROTATED SCAN"))
        rotated.set_rotation(90)

        duplicate = pdf.new_page(width=612, height=792)
        duplicate.insert_image(duplicate.rect, stream=_image("PUMP-72 NOT STARTED"))
        for row in range(11):
            duplicate.insert_text(
                (30, 55 + row * 57),
                f"SEARCH_LAYER_ROW_{row:02d} not started; verify scheduled service only, not completed work.",
                render_mode=3,  # Searchable native overlay from a scanned PDF.
            )

        logo = pdf.new_page(width=612, height=792)
        logo.insert_text((50, 70), "System details " + "Installed control unit. " * 10)
        logo.insert_image(
            fitz.Rect(20, 20, 85, 75), stream=_image("LOGO", size=(90, 90)),
        )

        separator = pdf.new_page(width=612, height=792)
        separator.draw_line(fitz.Point(20, 60), fitz.Point(590, 60))

        vector = pdf.new_page(width=612, height=792)
        for i in range(8):
            vector.draw_rect(fitz.Rect(60 + i*45, 70 + i*40, 120 + i*45, 130 + i*40))

        # Image tiles are a single scan: no single image covers half the page.
        tiled = pdf.new_page(width=612, height=792)
        tile = _image("SCAN TILE DOES NOT VERIFY WORK", size=(700, 450))
        tiled.insert_image(fitz.Rect(0, 0, 612, 350), stream=tile)
        tiled.insert_image(fitz.Rect(0, 380, 612, 730), stream=tile)
        return pdf.tobytes()


def _one_page(image: bytes) -> bytes:
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=image)
        return pdf.tobytes()


def test_labeled_scan_recall_and_false_positives_without_any_ai():
    payload = _synthetic_pages()
    # Four genuine image/vector cases + one tiled image case; five controls.
    # Expected 5/5 scan recall, 0/5 false positives on these labeled fixtures.
    expected_ocr = (False, True, False, True, True, False, False, False, True, True)
    expected_review = (False, True, True, True, True, True, False, False, True, True)
    decisions = []
    with fitz.open(stream=payload, filetype="pdf") as pdf:
        for page in pdf:
            text = page.get_text().strip()
            need, notice = ocr._page_visual_decision(page, native_text=text)
            assert ocr._page_needs_ocr(page, native_text=text) == need
            decisions.append((need, bool(notice)))
    assert tuple(need for need, _ in decisions) == expected_ocr
    assert tuple(review for _, review in decisions) == expected_review
    assert sum(need and wanted for (need, _), wanted in zip(decisions, expected_ocr)) == 5
    assert sum(need and not wanted for (need, _), wanted in zip(decisions, expected_ocr)) == 0


def test_white_scan_is_not_an_ocr_claim_but_keeps_an_explicit_page_notice():
    raw = _one_page(_image())
    with mock.patch.object(ocr, "_ocr_pdf", side_effect=AssertionError("paid model called")):
        text = ocr.extract_text_from_pdf(raw)
    assert "Source PDF page 1" in text
    assert "appears blank at preview scale" in text
    assert "verify the original" in text
    assert "completed work" not in text.lower()


def test_searchable_scanned_text_layer_is_not_paid_for_or_duplicated():
    payload = _synthetic_pages()
    calls = []

    def fake_ocr(data, *, until):
        with fitz.open(stream=data, filetype="pdf") as pdf:
            calls.append(pdf.page_count)
        return "SYNTHETIC_VISUAL_STUB_NO_APPROVAL"

    with mock.patch.object(ocr, "_ocr_pdf", side_effect=fake_ocr):
        text = ocr.extract_text_from_pdf(payload)
    assert calls == [1, 2, 2]  # 2, 4-5, 9-10; not 3 (white) or 6 (overlay).
    assert text.count("SEARCH_LAYER_ROW_00") == 1
    assert text.count("SEARCH_LAYER_ROW_10") == 1
    assert text.count("SYNTHETIC_VISUAL_STUB_NO_APPROVAL") == 3
    assert "PUMP-7 PENDING" not in text  # No invented reading of image-only text.


def test_vision_budget_counts_only_pages_that_need_model_reading():
    scanned = _image("FAILED TO CLOSE; SERVICE STILL PENDING")
    blank = _image()
    with fitz.open() as pdf:
        for _ in range(20):
            page = pdf.new_page(width=612, height=792)
            page.insert_image(page.rect, stream=scanned)
        empty = pdf.new_page(width=612, height=792)
        empty.insert_image(empty.rect, stream=blank)
        allowed = pdf.tobytes()
        excess = pdf.new_page(width=612, height=792)
        excess.insert_image(excess.rect, stream=scanned)
        refused = pdf.tobytes()
    calls = []
    with mock.patch.object(ocr, "_ocr_pdf", side_effect=lambda data, **kw: calls.append(True) or "SYNTHETIC OCR"):
        result = ocr.extract_text_from_pdf(allowed)
        assert "Source PDF page 21" in result
        assert len(calls) == 1
        with pytest.raises(ValueError, match="21 scanned pages"):
            ocr.extract_text_from_pdf(refused)
        assert len(calls) == 1, "over-budget source incurred a model call"


def test_monthly_cache_preserves_original_pages_review_and_source_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(
        profile, expected_revision=0, actor="Synthetic Editor", confirmed=True,
    )
    raw = _synthetic_pages()
    digest = sha256(raw).hexdigest()
    first, _ = sources.ingest(profile, "A37-synthetic.pdf", raw)
    assert first.source.sha256 == digest
    assert len(first.source.page_texts) == 10
    assert first.source.needs_vision == (2, 3, 4, 5, 6, 9, 10)
    for number in (2, 3, 4, 5, 6, 9, 10):
        assert any(f"Page {number}:" in note for note in first.source.notices)
    assert any("blank at preview scale" in note for note in first.source.notices)
    assert "SEARCH_LAYER_ROW_00" in first.source.page_texts[5]
    original_path = sources._path(profile, digest, ".pdf")
    assert sha256(original_path.read_bytes()).hexdigest() == digest

    # Cache reuse must not recalculate, lose notices, or mutate the original.
    with mock.patch.object(sources.ocr, "_page_visual_decision", side_effect=AssertionError("reparsed PDF")):
        reopened, _ = sources.ingest(profile, "A37-reopened.pdf", raw)
    assert reopened.source.page_texts == first.source.page_texts
    assert reopened.source.needs_vision == first.source.needs_vision
    assert reopened.source.notices == first.source.notices
    assert sha256(original_path.read_bytes()).hexdigest() == digest


def test_missing_empty_and_malformed_sources_are_rejected_without_fake_page_data(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with pytest.raises(ValueError, match="empty"):
        sources.ingest(profile, "bad.pdf", b"")
    with pytest.raises((ValueError, RuntimeError, fitz.FileDataError)):
        sources.ingest(profile, "bad.pdf", b"%PDF-1.4 not a real PDF")
