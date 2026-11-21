"""A07 synthetic PDF intake: OCR is supplementary, original/review authoritative."""
from hashlib import sha256
from io import BytesIO
import csv
import io
import shutil
import subprocess
import time

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from app import monthly_report_pdf_reader as reader
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


def synthetic_image(text="PUMP PX-72 NOT STARTED"):
    image = Image.new("RGB", (900, 450), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    draw.text((40, 130), text, fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def synthetic_pdf():
    scan = synthetic_image()
    with fitz.open() as document:
        native = document.new_page()
        native.insert_text((40, 50), "Vendor service report: native text control.")
        native.insert_text((40, 72), "Asset ID: 555-013-4431 is a technical tag.")
        mixed = document.new_page()
        mixed.insert_text((40, 50), "Site: Synthetic Unit A")
        mixed.insert_image(fitz.Rect(30, 110, 580, 450), stream=scan)
        rotated = document.new_page()
        rotated.insert_image(fitz.Rect(20, 20, 590, 780), stream=scan)
        rotated.set_rotation(90)
        vector = document.new_page()
        # Main treats one or two shapes as a separator, not a drawing: give
        # this text-free vector page enough artwork to need a visual read.
        vector.draw_rect(fitz.Rect(50, 50, 550, 500), color=(0, 0, 0))
        vector.draw_line(fitz.Point(50, 520), fitz.Point(550, 520), color=(0, 0, 0))
        vector.draw_circle(fitz.Point(300, 600), 40, color=(0, 0, 0))
        columns = document.new_page(width=620, height=700)
        columns.insert_text((36, 100), "Actions: Inspected tag 555-013-4431 but it")
        columns.insert_text((336, 100), "Recommendations: Schedule maintenance.")
        columns.insert_text((36, 125), "did not start; repair remains pending.")
        columns.insert_text((336, 125), "Contact: Synthetic Person, 555-867-5309")
        return document.tobytes()


def fixture_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


def mock_tsv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["level", "page_num", "block_num", "par_num", "line_num", "word_num",
                     "left", "top", "width", "height", "conf", "text"])
    for number, word in enumerate(("PUMP", "PX-72", "NOT", "STARTED"), 1):
        writer.writerow([5, 1, 1, 1, 1, number, 10+number*20, 50, 35, 20, 90, word])
    return output.getvalue()


def test_pdf_mixed_native_scanned_rotated_regions_and_positioned_confidence(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    raw = synthetic_pdf()
    monkeypatch.setattr(reader.shutil, "which", lambda _: "/usr/bin/tesseract")
    calls = iter((mock_tsv(), mock_tsv(), ""))
    monkeypatch.setattr(reader, "_ocr_image", lambda data, *, timeout: next(calls))
    content, _ = sources.ingest(profile, "synthetic-mixed.pdf", raw)
    src = content.source
    assert len(src.page_texts) == 5
    assert "native text control" in src.page_texts[0]
    assert "555-013-4431" in src.page_texts[0]
    assert "PUMP PX-72 NOT STARTED" in src.page_texts[1]
    assert "Site: Synthetic Unit A" in src.page_texts[1]
    assert "PUMP PX-72 NOT STARTED" in src.page_texts[2]
    assert set((2, 3, 4, 5)).issubset(src.needs_vision)
    assert not src.actions, "Unverified OCR / wrapped negation is never completed work"
    assert any("Page 4: unread/needs visual review" in s for s in src.notices)
    assert any("Page 5:" in s and "columns" in s for s in src.notices)
    assert len(content.ocr_spans) >= 2
    for page, start, end, confidence, bbox in content.ocr_spans:
        assert src.page_texts[page - 1][start:end] == "PUMP PX-72 NOT STARTED"
        assert confidence == 90
        assert 0 <= bbox[0] < bbox[2] <= 792
        assert 0 <= bbox[1] < bbox[3] <= 792
    assert sha256(sources.source_bytes(profile, src)).digest() == sha256(raw).digest()
    cached, _ = sources.ingest(profile, "synthetic-mixed.pdf", raw)
    assert cached == content, "OCR offsets, confidence and review notices must survive cache reload"


def test_source_ocr_absent_and_blank_result_have_explicit_review_not_empty(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    raw = synthetic_pdf()
    monkeypatch.setattr(reader.shutil, "which", lambda _: None)
    content, _ = sources.ingest(profile, "unavailable.pdf", raw)
    assert "Page 3: unread/needs visual review" in "\n".join(content.source.notices)
    assert "local OCR is unavailable" in "\n".join(content.source.notices)
    assert 3 in content.source.needs_vision
    assert not content.source.page_texts[2]
    monkeypatch.setattr(reader.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(reader, "_ocr_image", lambda data, *, timeout: "")
    revised, _ = sources.ingest(profile, "unavailable.pdf", raw)
    # Original-content cache is stable; no re-OCR on identical uploads.
    assert revised == content
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_image(page.rect, stream=synthetic_image())
        scan = pdf.tobytes()
    other, _ = sources.ingest(profile, "blank-result.pdf", scan)
    assert "OCR returned no readable text" in "\n".join(other.source.notices)
    assert other.source.needs_vision == (1,)


def test_tesseract_timeout_retains_valid_batch_sibling_and_original(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(reader.shutil, "which", lambda _: "/usr/bin/tesseract")

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 1)

    monkeypatch.setattr(reader, "_ocr_image", timed_out)
    raw = synthetic_pdf()
    accepted, messages = sources.ingest_batch(profile, (
        ("corrupt.pdf", b"%PDF-1.4\nnot valid"),
        ("scan.pdf", raw),
        ("good.txt", b"Approved human source preserved."),
    ))
    assert [item.source.filename for item in accepted] == ["scan.pdf", "good.txt"]
    assert any("corrupt.pdf" in msg for msg in messages)
    scan = accepted[0]
    assert any("local OCR failed" in n for n in scan.source.notices)
    assert sources.source_bytes(profile, scan.source) == raw


def test_side_by_side_columns_stay_separate_and_pending(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(reader.shutil, "which", lambda _: None)
    content, _ = sources.ingest(profile, "synthetic-columns.pdf", synthetic_pdf())
    text = content.source.page_texts[4]
    assert text.index("Actions:") < text.index("did not start") < text.index("Recommendations:")
    assert "555-867-5309" in text, "Source original text must remain reviewable"
    assert not content.source.actions
    assert 5 in content.source.needs_vision


def test_long_500_native_pages_retained_without_ocr_or_page_splitting(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    with fitz.open() as pdf:
        for number in range(500):
            p = pdf.new_page()
            p.insert_text((40, 60), f"Synthetic page {number+1}: inspected fan EF-31 at Site A.")
        raw = pdf.tobytes()
    monkeypatch.setattr(reader, "_ocr_image", lambda *a, **k: pytest.fail("native page must not OCR"))
    content, _ = sources.ingest(profile, "500-pages.pdf", raw)
    assert len(content.source.page_texts) == 500
    assert "page 500" in content.source.page_texts[-1]
    assert not content.source.needs_vision
    assert sources.source_bytes(profile, content.source) == raw
    assert sources.ingest(profile, "500-pages.pdf", raw)[0] == content


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Optional local tesseract not installed")
def test_actual_local_tesseract_captures_scanned_and_rotated_synthetic_text():
    with fitz.open(stream=synthetic_pdf(), filetype="pdf") as pdf:
        for number in (2, 3):
            page = pdf[number-1]
            result = reader.read_page(page, number, native_text=page.get_text().strip(),
                                      needs_ocr=True, may_ocr=True, deadline=time.monotonic()+15)
            assert "PUMP PX-72 NOT STARTED" in result.text
            assert result.ocr_spans and result.attempted_ocr
            assert "local OCR extracted" in result.notice


def test_small_chart_image_and_pdf_annotation_are_in_review_inventory(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(reader.shutil, "which", lambda _: None)
    with fitz.open() as pdf:
        chart = pdf.new_page(width=612, height=792)
        chart.insert_text((40, 55), "A complete native-text report header for chart evidence.")
        # The PDF embeds the image at native aspect ratio; visible area is about 1.7%.
        chart.insert_image(fitz.Rect(190, 285, 320, 445), stream=synthetic_image())
        annotated = pdf.new_page()
        annotated.insert_text((40, 55), "A native-text page has separate annotation content.")
        note = annotated.add_freetext_annot(
            fitz.Rect(70, 180, 370, 240), "Synthetic annotation requires visual review.")
        note.update()
        original = pdf.tobytes()
    content, _ = sources.ingest(profile, "chart-and-note.pdf", original)
    assert content.source.needs_vision == (1, 2)
    assert any("Page 1: unread/needs visual review" in n for n in content.source.notices)
    assert any("Page 2:" in n and "annotation" in n for n in content.source.notices)
    assert "native-text report header" in content.source.page_texts[0]
    assert sources.source_bytes(profile, content.source) == original


def test_local_ocr_page_cap_keeps_extra_original_pages_visible(tmp_path, monkeypatch):
    profile = fixture_profile(tmp_path, monkeypatch)
    with fitz.open() as pdf:
        image = synthetic_image()
        for _ in range(23):
            page = pdf.new_page()
            page.insert_image(page.rect, stream=image)
        raw = pdf.tobytes()
    monkeypatch.setattr(reader.shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(reader, "_ocr_image", lambda data, *, timeout: mock_tsv())
    content, _ = sources.ingest(profile, "23-scans.pdf", raw)
    assert len(content.source.page_texts) == 23
    assert len(content.ocr_spans) == reader.MAX_LOCAL_OCR_PAGES
    assert content.source.needs_vision == tuple(range(1, 24))
    assert sum("page/time budget reached" in s for s in content.source.notices) == 3
    assert sources.source_bytes(profile, content.source) == raw
