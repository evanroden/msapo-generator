"""Synthetic PDF physical-column evidence must not become completed Activity.

All artwork and text are constructed in the test. No client sources are used.
"""
from dataclasses import replace
from hashlib import sha256

import pymupdf as fitz
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_structured_uploads import native_update, reader_update, reader_sources
from app.monthly_report_vendor_passages import block_spans, read_vendor_document


def _pdf(*, side_by_side):
    with fitz.open() as pdf:
        page = pdf.new_page(width=760, height=620)
        page.insert_text((35, 30), "Vendor service report", fontsize=10)
        page.insert_text((35, 65), "Report date: 2026-10-16", fontsize=10)
        left = ("Actions: Replaced the demo filter.\n"
                "Findings: The removed filter was worn.\n"
                "Follow-up: Inspect the filter next cycle.")
        right = ("Actions: Inspected the demo fan but it\n"
                 "did not start.\n"
                 "Findings: Demo fan remained offline.\n"
                 "Follow-up: Return when parts arrive.")
        assert page.insert_textbox(fitz.Rect(35, 135, 315, 355), left, fontsize=10) >= 0
        if side_by_side:
            assert page.insert_textbox(fitz.Rect(425, 135, 725, 355), right, fontsize=10) >= 0
        else:
            assert page.insert_textbox(fitz.Rect(35, 250, 315, 465), right, fontsize=10) >= 0
        page.insert_text((35, 589), "Footer: Page 1", fontsize=10)
        return pdf.tobytes()


def test_separate_columns_share_vertical_band_and_require_page_review(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = _pdf(side_by_side=True)
    with fitz.open(stream=raw, filetype="pdf") as document:
        page = document[0]
        native = page.get_text().strip()
        # This is intentionally two independent PyMuPDF text blocks, rather
        # than the previously covered side-by-side lines in one block.
        labeled = [b for b in page.get_text("blocks") if "Actions:" in b[4]]
        assert len(labeled) == 2
        assert block_spans(page, native, 1) == ()
        native_png_hash = sha256(page.get_pixmap(dpi=96, alpha=False).tobytes("png")).hexdigest()

    content, _ = sources.ingest(profile, "synthetic-two-column.pdf", raw)
    source = content.source
    assert source.page_texts == (native,)
    assert not source.pdf_text_blocks
    assert not source.actions and not source.follow_ups
    assert not sources.action_evidence(source)[0]
    assert read_vendor_document(source)[1] == ((), True)
    assert native_update((content,), "activity_summary").text == ""
    assert reader_sources((content,), "activity_summary") == ()
    with pytest.raises(ValueError, match="physical reading-order review"):
        reader_update((content,), "activity_summary", {
            "items": [{"source": source.id, "page": 1,
                       "text": "Actions: Inspected the demo fan",
                       "row": [], "include_page": False}],
        })
    assert any("adjacent PDF columns" in note and "Page 1" in note for note in source.notices)
    assert "did not start." in source.page_texts[0]
    assert "Follow-up: Return when parts arrive." in source.page_texts[0]
    assert source.sha256 == sha256(raw).hexdigest()
    assert sources.source_bytes(profile, source) == raw
    with fitz.open(stream=sources.source_bytes(profile, source), filetype="pdf") as reopened:
        assert sha256(reopened[0].get_pixmap(dpi=96, alpha=False).tobytes("png")).hexdigest() == native_png_hash
    first = sources.page_image(profile, content, 1, preview=True)
    second = sources.page_image(profile, content, 1, preview=True)
    assert first.data == second.data


def test_same_text_in_one_column_retains_exact_negative_and_page_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = _pdf(side_by_side=False)
    content, _ = sources.ingest(profile, "synthetic-one-column.pdf", raw)
    source = content.source
    accepted, pending = read_vendor_document(source)[1]
    assert not pending
    assert len(accepted) == 6
    assert any(p.field == "follow_ups" and "Return when parts arrive." in p.text
               and source.page_texts[0][p.start:p.end].startswith("Follow-up:") for p in accepted)
    assert "did not start." in source.page_texts[0]
    activity = native_update((content,), "activity_summary")
    assert "did not start." in activity.text
    assert activity.references == (sources.source_reference(source, 1),)
    read, _ = reader_update((content,), "activity_summary", {
        "items": [{"source": source.id, "page": 1,
                   "text": "Actions: Inspected the demo fan but it did not start.",
                   "row": [], "include_page": False}],
    }, activity)
    assert read.text == activity.text and read.references == activity.references
    assert read.text.count("did not start.") == 1
    assert not any("Replaced the demo filter" in p for p in sources.action_evidence(source)[1])
    assert sources.source_bytes(profile, source) == raw


def test_unrelated_column_margins_do_not_assign_site_vendor_or_date(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with fitz.open(stream=_pdf(side_by_side=True), filetype="pdf") as pdf:
        page = pdf[0]
        page.insert_text((35, 84), "Site: Unrelated Remote Site", fontsize=10)
        page.insert_text((35, 103), "Vendor: Fictional Outside Company", fontsize=10)
        raw = pdf.tobytes()
    content, _ = sources.ingest(profile, "unrelated-margins.pdf", raw)
    source = content.source
    assert source.classification == "Vendor service"
    assert not source.facility and not source.vendor and not source.service_date
    assert "Site: Unrelated Remote Site" in source.page_texts[0]
    assert "Report date: 2026-10-16" in source.page_texts[0]
    assert not source.actions and not source.follow_ups
    assert sources.source_bytes(profile, source) == raw
    # Disposable cache replay cannot restore the older, unsafe date/site guess.
    replay, _ = sources.ingest(profile, "unrelated-margins.pdf", raw)
    assert (replay.source.facility, replay.source.vendor, replay.source.service_date) == ("", "", "")
    assert replay.source.page_texts == source.page_texts


def test_metadata_on_ordinary_single_column_remains_available(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "ordinary-single-column.pdf", _pdf(side_by_side=False))
    assert content.source.service_date == "2026-10-16"
    assert not any("adjacent PDF columns" in text for text in content.source.notices)


def test_missing_or_unlabelled_pdf_never_gets_column_based_certification():
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((35, 65), "Non-service page without labeled events.")
        assert block_spans(page, page.get_text().strip(), 1) == ()
        assert block_spans(page, "invented text", 1) == ()
