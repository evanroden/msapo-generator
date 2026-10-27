"""Synthetic normalized work-order contract, review, provenance and conflict tests."""
from dataclasses import asdict, replace
from hashlib import sha256
import json

import pytest

from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ReportSource
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_work_order_normalized import (
    ColumnMapping, correct_row, exclude_row, normalize_table,
    reimport_review, suggest_mapping, unmapped_cells, REVIEW_COLUMNS,
)

PROFILE = ReportProfile(
    "Synthetic Multi-Site Contract", "two-sites", "Two invented campuses",
    (Facility("north", "Synthetic North Campus", ("North",)),
     Facility("south", "Synthetic South Campus", ("South",))),
    scope_type="multi_site",
)
PERIOD = ReportPeriod(2026, 9)


def content(filename, columns, rows, *, revision="same", table_number=1):
    raw = json.dumps((filename, columns, rows, revision)).encode("utf-8")
    digest = sha256(raw).hexdigest()
    source = ReportSource(digest, filename, digest, ".csv")
    tables = tuple(SourceTable("Synthetic data " + str(n + 1),
                               tuple(columns), tuple(tuple(row) for row in rows))
                   for n in range(table_number))
    return SourceContent(source, tables)


def test_two_unrelated_synthetic_header_shapes_resolve_to_same_canonical_fields():
    rows = (("WO-A1", "North", "2026-09-04", "Closed", "Preventive", "HVAC", "0", ""),)
    first = content("alpha.csv",
        ("WO Number", "Facility", "Date", "Status", "Type", "Trade",
         "Hours", "Optional note"), rows)
    second = content("beta.csv",
        ("Ticket Number", "Location", "Service Date", "Current Status",
         "Task Type", "Discipline", "Labor", "Memo"), rows)
    a, b = normalize_table(first, 1, PROFILE, PERIOD), normalize_table(second, 1, PROFILE, PERIOD)
    assert a.kind == b.kind == "records"
    assert (a.rows[0].work_order, a.rows[0].site, a.rows[0].work_date,
            a.rows[0].status, a.rows[0].work_type, a.rows[0].trade) == (
            b.rows[0].work_order, b.rows[0].site, b.rows[0].work_date,
            b.rows[0].status, b.rows[0].work_type, b.rows[0].trade) == (
            "WO-A1", "north", "2026-09-04", "Completed", "PM", "HVAC")
    assert not a.needs_review and not b.needs_review
    assert a.counts() == dict(source_rows=1, included=1,
                               needs_review=0, excluded=0, unmapped_rows=0)
    assert unmapped_cells(a, a.rows[0].key) == (
        (6, "Hours", "0"), (7, "Optional note", ""))
    assert a.rows[0].original_values[-2:] == (("Hours", "0"), ("Optional note", ""))
    assert a.rows[0].key != b.rows[0].key
    assert a.source_reference.startswith(first.source.id + ":1:")
    assert a.review_table().columns == REVIEW_COLUMNS
    assert a.review_table().rows[0][0] == "1"


def test_ambiguous_status_date_and_site_remain_unresolved_with_unchanged_raw_cells():
    raw_rows = (("WO-X", "North / South", "09/04/2026", "On hold", "0", ""),)
    original = content("ambiguous.csv",
        ("Work Order", "Site", "Date", "Status", "Hours", "Extra"), raw_rows)
    previous = tuple(original.tables[0].rows)
    result = normalize_table(original, 1, PROFILE, PERIOD)
    assert result.kind == "records"
    row, = result.rows
    assert (row.work_order, row.site, row.work_date, row.status) == ("WO-X", "", "", "")
    assert set(row.issues) == {"site needs review", "work_date needs review", "status needs review"}
    assert row.origin.cells == raw_rows[0]
    assert unmapped_cells(result, row.key) == ((4, "Hours", "0"), (5, "Extra", ""))
    assert result.counts()["needs_review"] == 1
    assert tuple(original.tables[0].rows) == previous


def test_one_unresolved_row_can_be_corrected_and_reimport_keeps_manual_edits():
    data = content("ambiguous.csv",
        ("Work Order", "Site", "Date", "Status", "Hours"),
        (("WO-X", "North / South", "09/04/2026", "On hold", "0"),))
    draft = normalize_table(data, 1, PROFILE, PERIOD)
    row_key = draft.rows[0].key
    revised = correct_row(draft, row_key, {
        "site": "Synthetic South Campus",
        "work_date": "2026-09-04",
        "status": "Completed",
        "work_type": "PM",
    }, expected_revision=draft.revision)
    assert not revised.needs_review
    assert (revised.rows[0].site, revised.rows[0].status, revised.rows[0].work_type) == (
        "south", "Completed", "PM")
    assert revised.rows[0].origin.cells == draft.rows[0].origin.cells
    assert revised.rows[0].corrections
    assert reimport_review(revised, normalize_table(data, 1, PROFILE, PERIOD)) == revised
    with pytest.raises(ValueError, match="changed"):
        correct_row(revised, row_key, {"status": "Open"}, expected_revision=draft.revision)
    assert draft.rows[0].issues and draft.revision != revised.revision
    assert json.loads(json.dumps(asdict(revised)))["rows"][0]["origin"]["cells"][4] == "0"


def test_duplicate_workorders_are_counted_zero_until_review_not_silently_deduplicated():
    data = content("duplicates.csv",
        ("Work Order", "Site", "Date", "Status"),
        (("WO-7", "North", "2026-09-08", "Open"),
         ("WO-7", "North", "2026-09-09", "Closed"),
         ("WO-7", "South", "2026-09-11", "Closed")))
    before = normalize_table(data, 1, PROFILE, PERIOD)
    assert len(before.rows) == 3 and len({row.key for row in before.rows}) == 3
    assert before.counts() == dict(source_rows=3, included=1,
                                   needs_review=2, excluded=0, unmapped_rows=0)
    assert all("duplicate work-order identity" in row.issues for row in before.rows[:2])
    assert not before.rows[2].issues
    after = correct_row(before, before.rows[1].key, {"work_order": "WO-8"},
                        expected_revision=before.revision)
    assert after.counts()["included"] == 3
    assert not after.needs_review
    assert tuple(row.origin.cells for row in after.rows) == data.tables[0].rows


def test_aggregate_monthly_grid_is_not_fabricated_into_individual_records():
    raw = (("Preventive work", "0", "3", "3"), ("Reactive work", "", "2", "2"))
    data = content("annual.csv", ("Metric", "August", "September", "Total"), raw)
    result = normalize_table(data, 1, PROFILE, PERIOD)
    assert result.kind == "aggregate" and not result.rows
    assert result.original_rows == raw and result.original_columns[0] == "Metric"
    assert result.needs_review
    assert any("Aggregate counts" in q for q in result.questions)
    assert result.counts() == dict(source_rows=2, included=0,
                                   needs_review=0, excluded=0, unmapped_rows=2)
    assert not result.review_table().rows


def test_ambiguous_headers_and_custom_mapping_retain_all_columns():
    data = content("ambiguous-header.csv",
        ("Work Order", "WO", "Facility", "Date", "Status", "Extra", "Extra"),
        (("WO-1", "WO-ALT", "North", "2026-09-13", "Open", "0", ""),))
    auto = normalize_table(data, 1, PROFILE, PERIOD)
    assert auto.kind == "unresolved"
    assert any("Ambiguous work_order" in reason for reason in auto.questions)
    selected = replace(suggest_mapping(data.tables[0].columns), work_order=0,
                       ambiguous=())
    fixed = normalize_table(data, 1, PROFILE, PERIOD, mapping=selected)
    assert fixed.kind == "records"
    assert fixed.rows[0].work_order == "WO-1"
    assert unmapped_cells(fixed, fixed.rows[0].key) == (
        (1, "WO", "WO-ALT"), (5, "Extra", "0"), (6, "Extra", ""))
    with pytest.raises(ValueError, match="overlap|invalid"):
        normalize_table(data, 1, PROFILE, PERIOD,
                        mapping=ColumnMapping(work_order=0, status=0))


def test_period_scope_and_explicit_exclusion_never_erase_a_source_record():
    data = content("cross-month.csv",
        ("WO Number", "Facility", "Date", "Status"),
        (("WO-10", "North", "2026-10-01", "Closed"),
         ("WO-11", "South", "2026-09-22", "Open")))
    first = normalize_table(data, 1, PROFILE, PERIOD)
    assert first.counts() == dict(source_rows=2, included=1, needs_review=1,
                                  excluded=0, unmapped_rows=0)
    assert "source date is outside this report period" in first.rows[0].issues
    excluded = exclude_row(first, first.rows[0].key, expected_revision=first.revision,
                           excluded=True)
    assert excluded.counts() == dict(source_rows=2, included=1, needs_review=0,
                                     excluded=1, unmapped_rows=0)
    assert excluded.rows[0].origin.cells == first.rows[0].origin.cells
    with pytest.raises(ValueError, match="changed"):
        exclude_row(excluded, first.rows[0].key, expected_revision=first.revision,
                    excluded=False)


def test_new_source_or_scope_cannot_reimport_over_reviewed_corrections():
    data = content("same.csv", ("WO Number", "Site", "Date", "Status"),
                   (("WO-A1", "North", "2026-09-13", "Open"),))
    result = normalize_table(data, 1, PROFILE, PERIOD)
    change = correct_row(result, result.rows[0].key, {"status": "Completed"},
                         expected_revision=result.revision)
    changed_data = content("same.csv", data.tables[0].columns,
                           (("WO-A1", "North", "2026-09-13", "Closed"),),
                           revision="new")
    new = normalize_table(changed_data, 1, PROFILE, PERIOD)
    with pytest.raises(ValueError, match="source changed"):
        reimport_review(change, new)
    changed_scope = replace(data, source=replace(data.source, facility="south"))
    with pytest.raises(ValueError, match="source changed"):
        reimport_review(change, normalize_table(changed_scope, 1, PROFILE, PERIOD))
    assert reimport_review(change, result) == change


def test_table_bounds_and_row_number_are_checked_before_processing():
    data = content("short.csv", ("WO Number", "Site", "Date", "Status"),
                   (("WO-A1", "North", "2026-09-13", "Open"),))
    with pytest.raises(ValueError, match="existing source table"):
        normalize_table(data, 0, PROFILE, PERIOD)
    with pytest.raises(ValueError, match="existing source table"):
        normalize_table(data, 2, PROFILE, PERIOD)
    over = replace(data, tables=(replace(data.tables[0], rows=data.tables[0].rows * 20001),))
    with pytest.raises(ValueError, match="budget"):
        normalize_table(over, 1, PROFILE, PERIOD)


def test_existing_real_csv_ingestion_feeds_adapter_without_extra_parser(tmp_path, monkeypatch):
    from app import monthly_report_sources as sources
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = (
        b"WO Number,Facility,Date,Status,Type,Trade,Hours,Notes\\n"
        b"WO-A1,North,2026-09-04,Closed,Preventive,HVAC,0,\\n"
        b"WO-A2,South,2026-09-05,Open,Corrective,Plumbing,,Review pending\\n"
    )
    parsed, _ = sources.ingest(PROFILE, "synthetic-orders.csv", original)
    assert sources.source_bytes(PROFILE, parsed.source) == original
    review = normalize_table(parsed, 1, PROFILE, PERIOD)
    assert review.kind == "records"
    assert review.counts()["included"] == 2
    assert [(row.site, row.status, row.work_type) for row in review.rows] == [
        ("north", "Completed", "PM"), ("south", "Open", "Non-PM")]
    assert unmapped_cells(review, review.rows[0].key)[0][-1] == "0"
    assert unmapped_cells(review, review.rows[1].key)[0][-1] == ""
    assert review.source_reference == (
        parsed.source.id + ":1:" + parsed.source.fingerprint)
    assert sources.source_bytes(PROFILE, parsed.source) == original
