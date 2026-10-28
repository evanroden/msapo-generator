"""Synthetic native-text PDF -> reviewed work-order rows.

No OCR, genuine client document, shared original or paid model is used.
Layouts are deliberately synthetic: unruled/ruled tables, rotated pages,
repeated column headers, partial/wrapped cells and a scanned page control.
"""
from dataclasses import replace
from io import BytesIO
import hashlib

import pymupdf as fitz
from PIL import Image
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_pdf_review import review_pdf_workorders


PROFILE = ReportProfile(
    "Synthetic Multi-Site Contract", "synthetic-two-sites", "Synthetic hospitals",
    (Facility("north", "Synthetic North", ("North",)),
     Facility("south", "Synthetic South", ("South",))),
    scope_type="multi_site",
)
PERIOD = ReportPeriod(2026, 9)
XS = (40, 170, 300, 430, 515)


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return lambda raw, filename="synthetic-work-orders.pdf": sources.ingest(
        PROFILE, filename, raw)[0]


def _line(page, y, items, *, xs=XS):
    for x, label in zip(xs, items):
        if label:
            page.insert_text((x, y), label, fontsize=9)


def _table(page, heading, rows, *, top=90, repeat_header=False):
    _line(page, top, heading)
    for i, row in enumerate(rows):
        _line(page, top + 23 * (i + 1), row)
    if repeat_header:
        _line(page, top + 23 * (len(rows) + 1), heading)
        _line(page, top + 23 * (len(rows) + 2), (
            "0099", "South", "2026-09-21", "Open", "HVAC"))


def _mixed_pdf(*, scanned=False):
    with fitz.open() as pdf:
        first = pdf.new_page()
        _table(first, ("Work Order", "Site", "Date", "Status", "Trade"), (
            ("0001", "North", "2026-09-01", "Open", "HVAC"),
            ("0002", "South", "2026-09-02", "Closed", "Electrical"),
            ("0003", "North", "2026-09-03", "Open", "Plumbing"),
        ), repeat_header=True)
        second = pdf.new_page(width=792, height=612)
        _table(second, ("Ticket Number", "Location", "Service Date",
                        "Current Status", "Trade"), (
            ("0004", "South", "2026-09-04", "Closed", "HVAC"),
            ("0005", "North", "2026-09-05", "Open", "HVAC"),
            ("0006", "South", "2026-09-06", "Closed", "Electrical"),
        ))
        second.set_rotation(90)
        if scanned:
            image = BytesIO()
            Image.new("RGB", (240, 150), "navy").save(image, "PNG")
            extra = pdf.new_page()
            extra.insert_image(fitz.Rect(40, 60, 400, 330), stream=image.getvalue())
        return pdf.tobytes()


def test_two_native_text_layouts_rotation_repeated_headers_and_page_references(stored):
    raw = _mixed_pdf()
    data = stored(raw)
    before = hashlib.sha256(raw).hexdigest()
    review = review_pdf_workorders(PROFILE, data, PERIOD)
    assert len(review.pages) == 2
    assert [p.rotation for p in review.pages] == [0, 90]
    assert all(p.status == "records" and not p.unmatched_rows for p in review.pages)
    assert review.ready_for_inclusion and not review.needs_review
    assert review.eligible_count == 7  # three + repeated-header page extra + three
    assert [row.work_order for _, row in review.rows] == [
        "0001", "0002", "0003", "0099", "0004", "0005", "0006"]
    assert [p.review.source_reference for p in review.pages] == [
        sources.source_reference(data.source, 1),
        sources.source_reference(data.source, 2),
    ]
    assert review.page_references() == tuple(
        sources.source_reference(data.source, n) for n in (1, 2))
    assert [page for page, row in review.rows if row.work_order == "0005"] == [2]
    assert review.rows[-2][1].origin.table_number == 2
    assert review.rows[-2][1].origin.cells[0] == "0005"
    assert hashlib.sha256(sources.source_bytes(PROFILE, data.source)).hexdigest() == before
    with fitz.open(stream=raw, filetype="pdf") as untouched:
        assert untouched[1].rotation == 90


def test_supported_table_with_missing_status_keeps_unconfirmed_row_for_review(stored):
    with fitz.open() as pdf:
        page = pdf.new_page()
        _table(page, ("Work Order", "Site", "Date", "Status", "Trade"), (
            ("0010", "North", "2026-09-12", "Closed", "HVAC"),
            ("0011", "South", "2026-09-13", "", "Plumbing"),
            ("0012", "South", "2026-09-14", "Open", "HVAC"),
        ))
        raw = pdf.tobytes()
    content = stored(raw)
    result = review_pdf_workorders(PROFILE, content, PERIOD)
    assert len(result.rows) == 3
    unconfirmed = next(row for _, row in result.rows if row.work_order == "0011")
    assert unconfirmed.origin.cells[3] == ""
    assert "status needs review" in unconfirmed.issues
    assert result.eligible_count == 2
    assert not result.ready_for_inclusion
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_unlinked_wrap_is_visible_without_becoming_an_extra_work_order(stored):
    with fitz.open() as pdf:
        page = pdf.new_page()
        _table(page, ("Work Order", "Site", "Date", "Status", "Description"), (
            ("0021", "North", "2026-09-12", "Open", "Pump inspection"),
            ("", "", "", "", "additional note"),
            ("0022", "South", "2026-09-13", "Closed", "Valve checked"),
            ("0023", "North", "2026-09-14", "Open", "Filter changed"),
        ))
        raw = pdf.tobytes()
    content = stored(raw)
    result = review_pdf_workorders(PROFILE, content, PERIOD)
    assert [row.work_order for _, row in result.rows] == [
        "0021", "0022", "0023"]
    assert not result.ready_for_inclusion
    assert result.pages[0].unmatched_rows
    assert any("unlinked/partial rows" in note for note in result.pages[0].notices)
    # Full page's native text remains in the immutable source inventory even
    # if PyMuPDF's inferred cell rectangle clips the last text column.
    assert "additional note" in content.source.page_texts[0]
    assert "Pump inspection" in content.source.page_texts[0]
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_image_only_page_fails_closed_without_ocr_or_partial_approval(stored, monkeypatch):
    raw = _mixed_pdf(scanned=True)
    content = stored(raw)
    from app import ocr
    def forbidden(*args, **kwargs):
        pytest.fail("PDF work-order review must not launch OCR")
    monkeypatch.setattr(ocr, "run_ocr", forbidden, raising=False)
    result = review_pdf_workorders(PROFILE, content, PERIOD)
    assert len(result.pages) == 3
    assert result.pages[2].status == "scanned"
    assert "OCR was not performed" in result.pages[2].notices[0]
    assert result.eligible_count == 7
    assert not result.ready_for_inclusion
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_source_modified_or_out_of_budget_blocks_before_partial_return(stored):
    raw = _mixed_pdf()
    content = stored(raw)
    with pytest.raises(ValueError, match="fingerprint|integrity|changed"):
        review_pdf_workorders(PROFILE,
            replace(content, source=replace(content.source, sha256="a" * 64)), PERIOD)
    with fitz.open() as pdf:
        for n in range(151):
            page = pdf.new_page()
            page.insert_text((50, 50), "Synthetic work order table page " + str(n))
        large = pdf.tobytes()
    many = stored(large, "too-many-pages.pdf")
    with pytest.raises(ValueError, match="150-page"):
        review_pdf_workorders(PROFILE, many, PERIOD)
    assert sources.source_bytes(PROFILE, many.source) == large


def test_duplicate_work_order_ids_across_pages_never_double_count(stored):
    with fitz.open() as pdf:
        for n in (1, 2):
            page = pdf.new_page()
            _table(page, ("Work Order", "Site", "Date", "Status", "Trade"), (
                ("0040", "North", "2026-09-11", "Open", "HVAC"),
                (f"004{n}", "South", "2026-09-12", "Closed", "HVAC"),
                (f"005{n}", "North", "2026-09-13", "Open", "HVAC"),
            ))
        raw = pdf.tobytes()
    data = stored(raw)
    result = review_pdf_workorders(PROFILE, data, PERIOD)
    assert result.cross_page_duplicates == (("north", "0040"),)
    assert result.eligible_count == 4
    assert result.needs_review and not result.ready_for_inclusion
    assert len(result.rows) == 6
    assert sources.source_bytes(PROFILE, data.source) == raw
