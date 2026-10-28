"""Synthetic native Word work-order import review with real source provenance.

No client documents or copies of the approved master are committed. These
tests exercise the real DOCX inspector and its saved-original source contract,
but do not claim served browser or completed Word/PDF output acceptance.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
from docx.shared import Inches
from PIL import Image
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_docx_review import review_docx_workorders
from app.monthly_report_work_order_normalized import (
    correct_row, reimport_review, restore_review, review_record, unmapped_cells,
)

PERIOD = ReportPeriod(2026, 9)
PROFILE = ReportProfile(
    "Synthetic Maintenance Contract", "two-synthetic-sites",
    "Two synthetic facilities", (
        Facility("north", "Synthetic North", ("North",)),
        Facility("south", "Synthetic South", ("South",)),
    ), scope_type="multi_site",
)
HEADERS = ("Work Order", "Site", "Date", "Status", "Trade")
ALTERNATE = ("Ticket Number", "Location", "Service Date", "Current Status", "Discipline")


def _table(document, headers, records, *, title="", repeated_after=None, draw_at=None):
    rows = 1 + len(records) + bool(title) + bool(repeated_after is not None)
    result = document.add_table(rows=rows, cols=len(headers))
    offset = 0
    if title:
        result.rows[0].cells[0].merge(result.rows[0].cells[-1]).text = title
        offset = 1
    for column, value in zip(result.rows[offset].cells, headers):
        column.text = value
    for n, record in enumerate(records):
        for column, value in zip(result.rows[offset + 1 + n].cells, record):
            column.text = value
    if repeated_after is not None:
        # Repeated native header at the bottom of a Word table. It is a header
        # row, not another work-order identity, even when inside first 5 rows.
        row = result.rows[-1]
        for column, value in zip(row.cells, headers):
            column.text = value
    if draw_at is not None:
        r, c = draw_at
        image = BytesIO()
        Image.new("RGB", (32, 20), "blue").save(image, "PNG")
        result.rows[r].cells[c].paragraphs[0].add_run().add_picture(
            BytesIO(image.getvalue()), width=Inches(0.3))
    return result


def _source(tmp_path, document, *, name="synthetic-workorders.docx"):
    path = tmp_path / name
    document.save(path)
    raw = path.read_bytes()
    content, attachments = sources.ingest(PROFILE, path.name, raw)
    assert not attachments
    assert content.source.sha256
    assert sources.source_bytes(PROFILE, content.source) == raw
    return content, path, raw


def _normal_document(*, alternate=False, title=True, unrelated=True, repeat=True):
    doc = Document()
    doc.add_heading("1 Organizational Chart", 1)
    if unrelated:
        unrelated_table = doc.add_table(rows=2, cols=2)
        for row, cells in enumerate((("Name", "Phone"), ("Synthetic User", "202-555-0100"))):
            for cell, value in zip(unrelated_table.rows[row].cells, cells):
                cell.text = value
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Synthetic North and South operations; no monthly work inferred.")
    headers = ALTERNATE if alternate else HEADERS
    _table(doc, headers, (
        ("000071", "North", "2026-09-05", "Open", "HVAC"),
        ("000072", "South", "2026-09-06", "Closed", "Electrical"),
    ), title="Work Order Status" if title else "",
           repeated_after=True if repeat else None)
    doc.add_paragraph("Maintenance narrative is not another table row.")
    if unrelated:
        doc.add_heading("6 Sub-Contractor Status", 1)
        sub = doc.add_table(rows=2, cols=2)
        for row, values in enumerate((("Vendor", "Trade"), ("Synthetic Vendor", "Mechanical"))):
            for cell, value in zip(sub.rows[row].cells, values):
                cell.text = value
    return doc


def test_real_word_inspection_routes_activity_table_and_preserves_native_title_band(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, path, raw = _source(tmp_path, _normal_document())
    inspected = inspect_docx(path)
    original = next(item for item in inspected.items
                    if item.kind == "table" and item.suggested_slot == "work_orders")
    review = review_docx_workorders(PROFILE, content, PERIOD)
    assert len(review.tables) == 1
    assert len(review.ignored_table_ids) == 2
    target, = review.tables
    assert target.item_id == original.id
    assert target.word_position == original.position
    assert target.word_section == original.word_section
    assert target.source_item >= 1
    assert target.source_reference == sources.source_reference(content.source, target.source_item)
    assert target.review.source_reference == target.source_reference
    assert target.status == "records" and target.ready_for_inclusion
    assert target.header_word_row == 2
    assert len(target.title_bands) == 1
    assert target.title_bands[0].word_row == 1
    assert target.title_bands[0].cells[0] == "Work Order Status"
    assert target.original_row_numbers == (3, 4)
    assert not target.unmatched
    assert [row.work_order for row in target.review.rows] == ["000071", "000072"]
    assert [row.site for row in target.review.rows] == ["north", "south"]
    assert [row.status for row in target.review.rows] == ["Open", "Completed"]
    assert len(target.review.rows) == 2  # A repeated header is not a record.
    assert target.review.rows[0].origin.table_number == target.source_item
    assert target.editable_table().reference == target.source_reference
    assert review.ready_for_inclusion
    assert sources.source_bytes(PROFILE, content.source) == path.read_bytes() == raw


def test_second_word_header_shape_yields_same_editable_fields_without_title_band(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, path, raw = _source(tmp_path, _normal_document(
        alternate=True, title=False, repeat=False))
    result = review_docx_workorders(PROFILE, content, PERIOD)
    target, = result.tables
    assert target.status == "records" and target.ready_for_inclusion
    assert not target.title_bands
    assert target.header_word_row == 1
    assert target.original_row_numbers == (2, 3)
    assert tuple((r.work_order, r.site, r.work_date, r.status) for r in target.review.rows) == (
        ("000071", "north", "2026-09-05", "Open"),
        ("000072", "south", "2026-09-06", "Completed"))
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_merged_data_row_retains_all_source_cells_and_is_not_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    t = _table(doc, HEADERS, (
        ("0001", "North", "2026-09-05", "Open", "HVAC"),
        ("0002", "South", "2026-09-06", "Closed", "Plumbing"),
        ("0003", "South", "2026-09-07", "Open", "Electrical"),
    ))
    t.rows[2].cells[3].merge(t.rows[2].cells[4])
    source, path, raw = _source(tmp_path, doc)
    review = review_docx_workorders(PROFILE, source, PERIOD)
    target, = review.tables
    assert not target.ready_for_inclusion
    assert target.original_row_numbers == (2, 4)
    assert len(target.review.rows) == 2
    assert len(target.unmatched) == 1
    assert target.unmatched[0].word_row == 3
    assert target.unmatched[0].cells[0] == "0002"
    assert "merged" in target.unmatched[0].reason
    assert target.raw_rows[2][0] == "0002"
    assert "0002" not in [r.work_order for r in target.review.rows]
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_floating_picture_inside_word_table_is_not_flattened_to_editable_row(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    _table(doc, HEADERS, (
        ("0011", "North", "2026-09-01", "Closed", "HVAC"),
        ("0012", "South", "2026-09-02", "Open", "Electrical"),
    ), draw_at=(2, 4))
    source, _, raw = _source(tmp_path, doc)
    target, = review_docx_workorders(PROFILE, source, PERIOD).tables
    assert not target.ready_for_inclusion
    assert [r.work_order for r in target.review.rows] == ["0011"]
    assert len(target.unmatched) == 1 and target.unmatched[0].word_row == 3
    assert "unsupported" in target.unmatched[0].reason
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_missing_identity_and_multiline_source_rows_remain_reviewable(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    table = _table(doc, HEADERS, (
        ("0011", "North", "2026-09-01", "Open", "HVAC"),
        ("", "", "", "", "Second line of previous description"),
        ("0012", "South", "2026-09-02", "Closed", "Plumbing"),
    ))
    table.rows[3].cells[4].text = "Plumbing\nSecond text paragraph"
    source, _, raw = _source(tmp_path, doc)
    target, = review_docx_workorders(PROFILE, source, PERIOD).tables
    assert not target.ready_for_inclusion
    assert [r.work_order for r in target.review.rows] == ["0011"]
    assert [r.word_row for r in target.unmatched] == [3, 4]
    assert "continuation" in target.unmatched[0].reason
    assert "Multiline" in target.unmatched[1].reason
    assert target.raw_rows[3][-1].endswith("Second text paragraph")
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_foreign_and_aggregate_tables_are_not_misrouted_into_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_heading("1 Organizational Chart", 1)
    foreign = _table(doc, HEADERS, (
        ("0888", "North", "2026-09-02", "Closed", "HVAC"),
    ))
    doc.add_heading("2 Monthly Activity Summary", 1)
    grid = _table(doc, ("Metric", "January", "February", "March", "Total"), (
        ("PM count", "3", "0", "", "3"),
        ("Repairs", "1", "4", "", "5"),
    ))
    doc.add_heading("12 Training Summary", 1)
    training = doc.add_table(rows=2, cols=2)
    training.cell(0, 0).text, training.cell(0, 1).text = "Topic", "Date"
    source, _, raw = _source(tmp_path, doc)
    review = review_docx_workorders(PROFILE, source, PERIOD)
    assert len(review.ignored_table_ids) == 2
    assert len(review.tables) == 1
    assert review.tables[0].status == "not_work_orders"
    assert not review.ready_for_inclusion
    assert not review.tables[0].review
    assert review.tables[0].raw_rows[1] == ("PM count", "3", "0", "", "3")
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_valid_word_review_correction_round_trip_idempotent_and_cas_bound(tmp_path, monkeypatch):
    from app.monthly_report_work_order_normalized import review_record
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, _, raw = _source(tmp_path, _normal_document())
    table, = review_docx_workorders(PROFILE, content, PERIOD).tables
    before = table.review
    key = before.rows[0].key
    changed = correct_row(before, key, {"status": "Completed"}, expected_revision=before.revision)
    assert changed.rows[0].status == "Completed"
    assert changed.rows[0].origin.cells[3] == "Open"
    assert ("status", "Completed") in changed.rows[0].corrections
    from app.monthly_report_work_order_normalized import restore_review
    saved = review_record(changed)
    assert restore_review(saved) == changed
    assert reimport_review(changed, table.review) == changed
    with pytest.raises(ValueError, match="changed"):
        correct_row(changed, key, {"status": "Open"}, expected_revision=before.revision)
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_price_column_is_not_approved_as_unrestricted_work_order_data(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    _table(doc, ("Work Order", "Site", "Date", "Status", "Amount Due"), (
        ("0031", "North", "2026-09-02", "Open", "400"),
    ))
    source, _, raw = _source(tmp_path, doc)
    target, = review_docx_workorders(PROFILE, source, PERIOD).tables
    assert target.status == "records" and not target.ready_for_inclusion
    assert any("pricing" in message for message in target.notices)
    assert target.review.rows[0].origin.cells[-1] == "400"
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_saved_word_source_hash_or_inventory_failure_never_returns_partial_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    source, path, raw = _source(tmp_path, _normal_document())
    assert review_docx_workorders(PROFILE, source, PERIOD).tables
    altered = replace(source, source=replace(source.source, sha256="a" * 64))
    with pytest.raises((ValueError, OSError)):
        review_docx_workorders(PROFILE, altered, PERIOD)
    stale = replace(source, source=replace(source.source, page_texts=("outdated",)))
    with pytest.raises(ValueError, match="inventory differs"):
        review_docx_workorders(PROFILE, stale, PERIOD)
    assert sources.source_bytes(PROFILE, source.source) == path.read_bytes() == raw
