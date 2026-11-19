"""A45: physical Word row identity and conservative native table review.

Only synthetic DOCX documents. No client records or report templates.
"""
from io import BytesIO
from dataclasses import replace
from hashlib import sha256

from docx import Document
import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_docx_review import review_docx_workorders
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_normalized import restore_review, review_record, unmapped_cells

PROFILE = ReportProfile(
    "Synthetic A45 Contract", "synthetic-a45", "Two test locations",
    (Facility("north", "Synthetic North", ("North",)),
     Facility("south", "Synthetic South", ("South",))),
    scope_type="multi_site")
PERIOD = ReportPeriod(2026, 9)


def source(tmp_path, monkeypatch, document):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "originals"))
    path = tmp_path / "a45-original.docx"
    document.save(path)
    raw = path.read_bytes()
    content, files = sources.ingest(PROFILE, path.name, raw)
    assert not files
    return content, raw


def test_merged_group_headers_facility_bands_duplicate_dates_and_category_are_never_counted(tmp_path, monkeypatch):
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Work Order Status")
    table = doc.add_table(rows=11, cols=7)
    table.rows[0].cells[0].merge(table.rows[0].cells[1]).text = "Identity columns"
    table.rows[0].cells[2].merge(table.rows[0].cells[3]).text = "Dates (review required)"
    headings = ("Work Order", "Site", "Date", "Date", "Status", "Type", "Unmapped detail")
    for cell, value in zip(table.rows[1].cells, headings):
        cell.text = value
    table.rows[2].cells[0].merge(table.rows[2].cells[-1]).text = "Synthetic North"
    records = {
        3: ("0091", "North", "2026-09-03", "2026-09-04", "Completed", "PM", "preserve-a"),
        7: ("0092", "South", "2026-09-05", "2026-09-06", "Open", "Non-PM", "preserve-b"),
        8: ("0092", "South", "2026-09-05", "2026-09-06", "Open", "Non-PM", "duplicate"),
        9: ("0093", "Unknown site", "2026-09-07", "2026-09-08", "Open", "PM", "retain"),
        10: ("0094", "North", "2026-08-31", "2026-09-10", "Open", "PM", "earlier month"),
    }
    for index, row in records.items():
        for cell, value in zip(table.rows[index].cells, row):
            cell.text = value
    for cell, value in zip(table.rows[4].cells, headings):
        cell.text = value
    table.rows[5].cells[0].merge(table.rows[5].cells[-1]).text = "Synthetic South"
    table.rows[6].cells[0].text = "Electrical work-order category"
    content, raw = source(tmp_path, monkeypatch, doc)

    result = review_docx_workorders(PROFILE, content, PERIOD)
    target, = result.tables
    assert target.status == "records"
    assert target.header_word_row == 2
    assert target.raw_rows[0][0] == "Identity columns"
    assert len(target.raw_rows) == 11
    assert target.original_row_numbers == (4, 8, 9, 10, 11)
    assert [item.word_row for item in target.unmatched] == [1, 3, 6, 7]
    assert len(target.review.rows) == 5
    assert [row.work_order for row in target.review.rows] == ["0091", "0092", "0092", "0093", "0094"]
    assert all(row.work_date == "" for row in target.review.rows)
    assert "work_date" in target.review.mapping.ambiguous
    assert not result.ready_for_inclusion
    assert target.review.rows[3].site == ""  # A band does not create or authorize a site.
    assert "duplicate work-order identity" in target.review.rows[1].issues
    assert "duplicate work-order identity" in target.review.rows[2].issues
    assert [row.origin.native_row_number for row in target.review.rows] == [4, 8, 9, 10, 11]
    assert {row.origin.native_item_id for row in target.review.rows} == {target.item_id}
    assert len({row.key for row in target.review.rows}) == 5
    assert unmapped_cells(target.review, target.review.rows[0].key)[-1] == (
        6, "Unmapped detail", "preserve-a")
    assert restore_review(review_record(target.review)) == target.review
    # The original unknown date selection is never guessed. A reviewed
    # physical-column choice must be explicit and preserve every other row.
    from app import monthly_report_work_order_review_flow as flow
    from test_monthly_report_work_order_review_flow import draft_source
    draft, native_content = draft_source(raw, "a45-remap.docx", PROFILE)
    initial = flow.prepare_bundle(draft, native_content)
    assert flow.restored_group(initial, initial["groups"][0]).mapping.work_date is None
    remapped = flow.remap_group(draft, native_content, initial, 0, {"work_date": 2})
    remapped_review = flow.restored_group(remapped, remapped["groups"][0])
    assert remapped_review.mapping.work_date == 2
    assert remapped_review.mapping.completed_date is None
    assert [row.work_date for row in remapped_review.rows] == [
        "2026-09-03", "2026-09-05", "2026-09-05", "2026-09-07", "2026-08-31"]
    assert [row.key for row in remapped_review.rows] == [row.key for row in target.review.rows]
    assert remapped["groups"][0]["unmatched"] == initial["groups"][0]["unmatched"]
    counted = count_reviewed_work_orders(remapped_review,
        approved_revision=remapped_review.revision, period=PERIOD,
        selected_sites=("north", "south"))
    assert counted.overall.total == 1
    assert [d.disposition for d in counted.dispositions] == [
        "counted", "needs_review", "needs_review", "needs_review", "needs_review"]
    with pytest.raises(ValueError, match="numeric dates"):
        flow.remap_group(draft, native_content, initial, 0, {"work_date": 2}, "MDY")
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_supported_word_rows_produce_counts_with_exact_native_row_membership(tmp_path, monkeypatch):
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Work Order Status")
    heads = ("Work Order", "Site", "Service Date", "Status", "Type", "Trade", "Inspector notes")
    rows = (
        ("0001", "North", "2026-09-02", "Closed", "PM", "HVAC", "unknown preserved"),
        ("0002", "South", "2026-09-03", "Open", "Non-PM", "Electrical", "unknown preserved 2"),
        ("0003", "South", "2026-08-31", "Closed", "PM", "Plumbing", "prior month"),
    )
    table = doc.add_table(rows=5, cols=len(heads))
    table.rows[0].cells[0].merge(table.rows[0].cells[-1]).text = "Work Order Status"
    for cell, value in zip(table.rows[1].cells, heads):
        cell.text = value
    for index, record in enumerate(rows, 2):
        for cell, value in zip(table.rows[index].cells, record):
            cell.text = value
    content, raw = source(tmp_path, monkeypatch, doc)
    target, = review_docx_workorders(PROFILE, content, PERIOD).tables
    review = target.review
    assert target.ready_for_inclusion is False  # A prior-month record needs review.
    assert target.original_row_numbers == (3, 4, 5)
    assert [row.origin.native_row_number for row in review.rows] == [3, 4, 5]
    counts = count_reviewed_work_orders(review, approved_revision=review.revision,
        period=PERIOD, selected_sites=("north", "south"), include_trades=True)
    assert counts.overall.total == 2
    assert counts.overall.completed == 1 and counts.overall.open == 1
    assert [(group.label, group.total) for group in counts.work_types] == [
        ("PM", 1), ("Non-PM", 1), ("Unclassified work type", 0)]
    assert [d.disposition for d in counts.dispositions] == [
        "counted", "counted", "needs_review"]
    assert set(counts.overall.row_keys) == {review.rows[0].key, review.rows[1].key}
    assert sum(group.total for group in counts.trades) == 2
    assert counts.summary_table().reference == target.source_reference
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_non_word_or_malformed_input_does_not_produce_records(tmp_path, monkeypatch):
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Work Order Status")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "Unknown"
    content, raw = source(tmp_path, monkeypatch, doc)
    with pytest.raises(ValueError, match="Word"):
        review_docx_workorders(PROFILE,
            replace(content, source=replace(content.source, suffix=".csv")), PERIOD)
    target, = review_docx_workorders(PROFILE, content, PERIOD).tables
    assert target.status == "not_work_orders"
    assert not target.ready_for_inclusion
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_native_review_correction_survives_saved_report_and_real_word_pdf(tmp_path, monkeypatch):
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_model import synthetic_profiles
    profile = synthetic_profiles()[1]
    from test_monthly_report_work_order_review_flow import draft_source, stored, publish
    from test_monthly_report_work_order_lane_integration import saved, generated
    # Export requires the native document renderer; this remains a synthetic test.
    if not __import__("shutil").which("libreoffice"):
        pytest.skip("Native Word/PDF renderer not available")

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Work Order Status")
    headers = ("Work Order", "Site", "Service Date", "Status", "Type", "Trade", "Inspector detail")
    table = doc.add_table(rows=4, cols=len(headers))
    table.rows[0].cells[0].merge(table.rows[0].cells[-1]).text = "Work Order Status"
    for cell, value in zip(table.rows[1].cells, headers):
        cell.text = value
    for index, record in enumerate((
        ("0101", "Demo North", "2026-09-04", "Open", "PM", "HVAC", "left unchanged"),
        ("0102", "Demo South", "2026-09-05", "Closed", "Repair", "Electrical", "unmapped stays"),), 2):
        for cell, value in zip(table.rows[index].cells, record):
            cell.text = value
    stream = BytesIO()
    doc.save(stream)
    original = stream.getvalue()
    original_digest = sha256(original).hexdigest()
    draft, content = draft_source(original, "a45-export.docx", profile)
    from app.monthly_report_source_scope import correct_scope
    content = replace(content, source=correct_scope(content.source, profile, ("north", "south")))
    # This fixture validates Activity export only. Newer native export gates
    # require every other included section's required blocks to be resolved.
    draft = replace(draft, sources=(content.source,),
        sections=tuple(section for section in draft.sections if section.key == "activity"))
    draft, bundle = stored(draft, content)
    row_review = flow.restored_group(bundle, bundle["groups"][0])
    assert [r.origin.native_row_number for r in row_review.rows] == [3, 4]
    assert row_review.review_table().rows[0][0] == "3"
    revised = flow.change_row(bundle, 0, row_review.rows[0].key,
                              {"status": "Completed"})
    draft = flow.store_bundle(draft, revised, expected_revision=flow.revision(bundle))
    reopened = saved(publish(draft, revised, include_trades=True))
    persisted = flow.saved_bundle(reopened, content.source.id, "workorders")
    assert flow.restored_group(persisted, persisted["groups"][0]).rows[0].origin.native_row_number == 3
    assert publish(reopened, persisted, include_trades=True) == reopened
    result, pdf_text = generated(reopened, tmp_path, monkeypatch)
    word = Document(BytesIO(result.docx))
    word_text = "\n".join(c.text for table in word.tables for row in table.rows for c in row.cells)
    assert "0101" in word_text and "0102" in word_text
    assert "0101" in pdf_text and "0102" in pdf_text
    assert "Keep my authored wording." in "\n".join(b.text for b in reopened.blocks)
    assert sha256(sources.source_bytes(profile, content.source)).hexdigest() == original_digest
    assert len(sha256(result.docx).hexdigest()) == 64
    assert len(sha256(result.pdf).hexdigest()) == 64


def test_native_word_date_mapping_is_visible_and_requires_explicit_confirmation(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_work_order_review_ui import SCRIPT, button
    from test_monthly_report_work_order_review_flow import draft_source
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Work Order Status")
    table = doc.add_table(rows=3, cols=5)
    table.rows[0].cells[0].merge(table.rows[0].cells[-1]).text = "Work Order Status"
    for cell, header in zip(table.rows[1].cells, ("Work Order", "Site", "Date", "Date", "Status")):
        cell.text = header
    for cell, value in zip(table.rows[2].cells, ("0201", "North", "2026-09-03", "2026-09-04", "Open")):
        cell.text = value
    stream = BytesIO()
    doc.save(stream)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "ui"))
    draft, content = draft_source(stream.getvalue(), "a45-ui.docx", PROFILE)
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state["draft"], app.session_state["content"] = draft, content
    app.run()
    assert not app.exception
    button(app, "Review and correct imported rows").click().run()
    assert not app.exception
    assert button(app, "Include reviewed rows in Activity").disabled
    next(w for w in app.selectbox if w.label == "Work date column").select(2)
    next(w for w in app.checkbox if w.label.startswith("Rebuild this table")).check()
    button(app, "Apply source mapping").click().run()
    assert not app.exception
    receipt = app.session_state["draft"].source_row_reviews
    assert receipt
    assert next(t for t in app.text_input if t.label == "Work date").value == "2026-09-03"
    assert not button(app, "Include reviewed rows in Activity").disabled
    assert sources.source_bytes(PROFILE, content.source) == stream.getvalue()


def test_pre_a45_saved_review_hash_and_existing_user_edits_remain_valid(tmp_path, monkeypatch):
    from dataclasses import asdict
    import json
    from app.monthly_report_work_order_normalized import normalize_table, correct_row
    from test_monthly_report_work_order_review_flow import draft_source
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "legacy"))
    draft, content = draft_source(
        b"Work Order,Site,Date,Status,Type\n0009,North,2026-09-03,Open,PM\n",
        "pre-a45.csv", PROFILE)
    review = normalize_table(content, 1, PROFILE, PERIOD)
    original = asdict(review)
    for row in original["rows"]:
        del row["origin"]["native_item_id"]
        del row["origin"]["native_row_number"]
    legacy_sha = sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert review.revision == legacy_sha
    restored = restore_review({"schema": 1, "review": original, "sha256": legacy_sha})
    assert restored == review
    revised = correct_row(restored, restored.rows[0].key,
        {"status": "Completed"}, expected_revision=legacy_sha)
    assert revised.rows[0].status == "Completed"
    assert revised.rows[0].origin.cells[3] == "Open"
    assert restore_review(review_record(revised)) == revised
