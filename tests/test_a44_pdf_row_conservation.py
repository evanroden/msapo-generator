"""A44 synthetic native PDF row conservation and explicit-review regression.

These are invented PDFs only. They exercise the same saved-source adapter and
review receipts as the Monthly UI; nothing is automatically published.
"""
from dataclasses import asdict
import hashlib
import json

import pymupdf as fitz
import pytest

from app import monthly_report_sources as sources
from app import monthly_report_work_order_review_flow as flow
from app import monthly_report_library as library
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_pdf_review import review_pdf_workorders
from test_monthly_report_work_order_pdf_review import PROFILE, PERIOD, _line
from test_monthly_report_work_order_review_flow import draft_source, publish


HEADER = ("Work Order", "Site", "Date", "Status", "Type")


def synthetic_pdf(*, include_two_column=False, aggregate=False):
    with fitz.open() as pdf:
        first = pdf.new_page()
        if aggregate:
            _line(first, 90, ("Category", "Total", "September", "October", ""))
            _line(first, 113, ("PM", "25", "12", "13", ""))
        else:
            for index, row in enumerate((
                HEADER,
                ("0100", "North", "2026-09-01", "Open", "PM"),
                ("", "South", "2026-09-02", "Closed", "Repair"),
                HEADER,
                ("0101", "South", "2026-09-03", "Not Completed", "Repair"),
                ("0102", "South", "2026-09-04", "Closed", "PM"),
            )):
                _line(first, 90 + index * 23, row)
            second = pdf.new_page()
            for index, row in enumerate((
                HEADER,
                ("0102", "South", "2026-09-04", "Closed", "PM"),
                ("0103", "North", "2026-09-05", "Open", "Repair"),
            )):
                _line(second, 90 + index * 23, row)
            if include_two_column:
                third = pdf.new_page()
                for index, (wo, status) in enumerate((
                    ("Work Order", "Status"), ("0200", "Open"),
                    ("0201", "Not Completed"),
                )):
                    _line(third, 90 + index * 23, (wo, status), xs=(40, 330))
        return pdf.tobytes()


@pytest.fixture
def stored(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return lambda raw: sources.ingest(PROFILE, "a44-invented-work-orders.pdf", raw)[0]


def test_pdf_page_and_row_identity_conserves_skipped_rows_and_duplicate_ids(stored):
    raw = synthetic_pdf(include_two_column=True)
    content = stored(raw)
    review = review_pdf_workorders(PROFILE, content, PERIOD)
    assert len(review.pages) == 3
    assert [row.work_order for _, row in review.rows] == [
        "0100", "0101", "0102", "0102", "0103", "0200", "0201"]
    assert review.cross_page_duplicates == (("south", "0102"),)
    first = review.pages[0]
    assert first.status == "records"
    assert len(first.unmatched_rows) == 1
    assert first.unmatched_rows[0][:3] == ("", "South", "2026-09-02")
    assert first.unmatched_origins[0].startswith("native table 1, row ")
    assert [row.work_order for row in first.review.rows] == ["0100", "0101", "0102"]
    # A missing WO and a repeated heading keep their source-row slots.
    assert [row.origin.row_number for row in first.review.rows] == [1, 4, 5]
    for page_number, row in review.rows:
        assert row.origin.table_number == page_number
        assert row.origin.cells in review.pages[page_number - 1].review.original_rows
        assert row.origin.cells == review.pages[page_number - 1].review.original_rows[row.origin.row_number - 1]
    assert all("duplicate work-order identity across PDF pages" in row.issues
               for _, row in review.rows if row.work_order == "0102")
    negative = next(row for _, row in review.rows if row.work_order == "0101")
    assert negative.status == "" and ("status", "Not Completed") in negative.corrections
    assert review.eligible_count == 2
    assert review.needs_review
    third = review.pages[2]
    assert third.status == "records"
    assert len(third.review.rows) == 2
    assert all(row.issues for row in third.review.rows)
    assert third.review.mapping.site is None and third.review.mapping.work_date is None
    assert hashlib.sha256(sources.source_bytes(PROFILE, content.source)).digest() == hashlib.sha256(raw).digest()


def test_pdf_correction_approval_and_persisted_reopen_recompute_metrics(stored):
    # No aggregate, missing identity, negative status, or cross-page duplicate
    # can silently become a completed work order.
    raw = synthetic_pdf()
    content = stored(raw)
    draft, _ = draft_source(raw, "a44-invented-work-orders.pdf", profile=PROFILE)
    bundle = flow.prepare_bundle(draft, content)
    assert len(bundle["groups"]) == 2
    assert bundle["groups"][0]["unmatched"]
    with pytest.raises(ValueError):
        publish(draft, bundle)

    first = flow.restored_group(bundle, bundle["groups"][0])
    negative = next(row for row in first.rows if row.work_order == "0101")
    bundle = flow.change_row(bundle, 0, negative.key, {"status": "Open"})
    second = flow.restored_group(bundle, bundle["groups"][1])
    duplicate = next(row for row in second.rows if row.work_order == "0102")
    bundle = flow.change_row(bundle, 1, duplicate.key, {"work_order": "0104"})
    bundle = flow.group_decisions(bundle, 0, omitted=False, omit_unmatched=True)
    # Reconciliation frees the other 0102 only after its conflicting page is corrected.
    first = flow.restored_group(bundle, bundle["groups"][0])
    assert not any(row.issues for row in first.rows)
    assert not any(row.issues for row in flow.restored_group(bundle, bundle["groups"][1]).rows)

    draft = flow.store_bundle(draft, bundle)
    library.save_profile(PROFILE, expected_revision=0, actor="A44 synthetic", confirmed=True)
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    receipt = flow.saved_bundle(reopened, content.source.id, "workorders")
    assert receipt == bundle
    assert sources.source_bytes(PROFILE, content.source) == raw
    cohorts = [flow.restored_group(receipt, group) for group in receipt["groups"]]
    counted = [count_reviewed_work_orders(review, approved_revision=review.revision,
              period=PERIOD, selected_sites=("north", "south")) for review in cohorts]
    assert sum(result.overall.total for result in counted) == 5
    assert sum(result.overall.open for result in counted) == 3
    assert sum(result.overall.completed for result in counted) == 2
    assert {key: sum(group.total for result in counted for group in result.work_types
                     if group.key == key) for key in ("PM", "Non-PM")} == {
                         "PM": 3, "Non-PM": 2}
    accepted = publish(reopened, receipt)
    block = next(block for block in accepted.blocks if block.key == "work_orders")
    assert sum(len(table.rows) for table in block.extra_tables
               if table.columns[0] == "Work order") == 5
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_pdf_aggregate_grid_is_not_a_record_source(stored):
    raw = synthetic_pdf(aggregate=True)
    content = stored(raw)
    review = review_pdf_workorders(PROFILE, content, PERIOD)
    assert review.rows == ()
    assert review.eligible_count == 0
    assert review.needs_review
    assert sources.source_bytes(PROFILE, content.source) == raw


def test_table_heavy_native_geometry_preserves_unheaded_and_conflicting_cells():
    # Deterministic table-finder shapes complement the real PDFs above:
    # PyMuPDF may join disjoint tables differently across supported releases.
    from types import SimpleNamespace
    from app.monthly_report_work_order_pdf_review import _page_table

    class Table:
        def __init__(self, y, cells):
            self.bbox = (40, y, 550, y + 70)
            self.cells = cells
        def extract(self):
            return self.cells

    class Page:
        number = 0
        rotation = 0
        def __init__(self, tables):
            self.tables = tables
        def find_tables(self, *, strategy):
            assert strategy == "text"
            return SimpleNamespace(tables=self.tables)

    one = Table(90, [list(HEADER), ["0300", "North", "2026-09-01", "Open", "PM"]])
    two = Table(300, [list(HEADER), ["0301", "South", "2026-09-02", "Closed", "Repair"]])
    notes = Table(500, [["Code", "Total"], ["PM", "200"]])
    table, unmatched, problems, skipped, origins = _page_table(Page([notes, two, one]))
    assert [row[0] for row in table.rows] == ["0300", "0301"]
    assert table.columns == HEADER
    assert unmatched == (("Code", "Total"), ("PM", "200"))
    assert origins == ("native table 3, row 1", "native table 3, row 2")
    assert skipped == ()
    assert problems

    conflicting = Table(300, [
        ["Ticket Number", "Location", "Service Date", "Current Status", "Type"],
        ["0400", "North", "2026-09-03", "Open", "PM"]])
    table, unmatched, problems, skipped, origins = _page_table(Page([one, conflicting]))
    assert table is None and not skipped
    assert ("0300", "North", "2026-09-01", "Open", "PM") in unmatched
    assert ("0400", "North", "2026-09-03", "Open", "PM") in unmatched
    assert ("native table 1, row 1", "native table 1, row 2",
            "native table 2, row 1", "native table 2, row 2") == origins
    assert any("Multiple work-order tables" in problem for problem in problems)


def test_two_column_pdf_requires_explicit_field_by_field_correction(stored):
    # The source supplies WO and status only. The adapter must not invent a
    # site/date or infer a report-month count, even from the surrounding draft.
    with fitz.open() as pdf:
        page = pdf.new_page()
        for index, (identity, status) in enumerate((
            ("Work Order", "Status"), ("0200", "Open"),
            ("0201", "Not Completed"))):
            _line(page, 90 + index * 23, (identity, status), xs=(40, 330))
        raw = pdf.tobytes()
    content = stored(raw)
    draft, _ = draft_source(raw, "a44-invented-work-orders.pdf", profile=PROFILE)
    bundle = flow.prepare_bundle(draft, content)
    review = flow.restored_group(bundle, bundle["groups"][0])
    assert review.mapping.site is None and review.mapping.work_date is None
    assert review.needs_review
    with pytest.raises(ValueError):
        publish(draft, bundle)

    first, second = review.rows
    bundle = flow.change_row(bundle, 0, first.key,
                             {"site": "North", "work_date": "2026-10-01"})
    # A reviewed site is not permission to assign a different month's row.
    assert any("outside this report period" in note for note in
               flow.restored_group(bundle, bundle["groups"][0]).rows[0].issues)
    bundle = flow.change_row(bundle, 0, first.key, {"work_date": "2026-09-01"})
    assert flow.restored_group(bundle, bundle["groups"][0]).questions
    bundle = flow.change_row(bundle, 0, second.key, {
        "site": "South", "work_date": "2026-09-02", "status": "Completed"})
    checked = flow.restored_group(bundle, bundle["groups"][0])
    assert not checked.questions and not any(row.issues for row in checked.rows)
    assert [(row.work_order, row.status) for row in checked.rows] == [
        ("0200", "Open"), ("0201", "Completed")]
    assert count_reviewed_work_orders(
        checked, approved_revision=checked.revision, period=PERIOD,
        selected_sites=("north", "south")).overall.total == 2
    draft = flow.store_bundle(draft, bundle)
    reread = flow.saved_bundle(draft, content.source.id, "workorders")
    assert reread == bundle
    assert sum(len(t.rows) for t in next(
        block for block in publish(draft, reread).blocks
        if block.key == "work_orders").extra_tables
        if t.columns[0] == "Work order") == 2
    assert sources.source_bytes(PROFILE, content.source) == raw
