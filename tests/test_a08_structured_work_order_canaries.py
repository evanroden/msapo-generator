"""A08 synthetic CSV/XLSX source-conservation and ambiguity canaries."""
from dataclasses import replace
from io import BytesIO
from zipfile import BadZipFile
import json

import pytest
from openpyxl import Workbook

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import is_work_order_source, work_order_evidence
from app.monthly_report_work_order_csv_review import (
    csv_review_record, mapped_columns, reimport_csv_review, restore_csv_review,
    review_csv, review_spreadsheet,
)
from app.monthly_report_work_order_normalized import suggest_mapping, unmapped_cells


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile(
        "A08 Synthetic", "two-sites", "Two synthetic facilities",
        (Facility("north", "North Campus", ("North",)),
         Facility("south", "South Campus", ("South",))),
        scope_type="multi_site",
    )
    return profile, ReportPeriod(2026, 9)


def _ingest(profile, name, raw):
    content, _ = sources.ingest(profile, name, raw)
    assert sources.source_bytes(profile, content.source) == raw
    return content


def _workbook(*, hidden=True, formula=True, sheet_count=2):
    wb = Workbook()
    first = wb.active
    first.title = "Current"
    first.append(("WO Number", "Site", "Date", "Status", "Trade", "Extra"))
    first.append(("0001", "North", "2026-09-05",
                  '=IF(1=1,"Closed","Open")' if formula else "Closed", "HVAC", "0"))
    for n in range(2, sheet_count + 1):
        sheet = wb.create_sheet(f"Archive {n}")
        sheet.append(("WO Number", "Site", "Date", "Status", "Trade", "Extra"))
        sheet.append((f"{n:04d}", "South", "2026-09-06", "Closed", "Vendor", ""))
        if hidden:
            sheet.sheet_state = "hidden"
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def test_identically_repeated_status_header_requires_physical_mapping(context):
    profile, period = context
    raw = (
        b"WO Number,Site,Date,Status,Status,Extra\n"
        b"00021,North,2026-09-04,Open,Closed,0\n"
    )
    source = _ingest(profile, "same-heading.csv", raw)
    assert source.tables[0].columns == (
        "WO Number", "Site", "Date", "Status", "Status (2)", "Extra")
    assert suggest_mapping(source.tables[0].columns).status is None
    assert "status" in suggest_mapping(source.tables[0].columns).ambiguous
    pending = review_csv(source, profile, period)
    assert not pending.ready_for_inclusion
    assert not is_work_order_source(source)
    assert not work_order_evidence(source, period, profile)

    mapping = mapped_columns(source.tables[0].columns, {"status": 4})
    reviewed = review_csv(source, profile, period, mapping=mapping)
    assert reviewed.ready_for_inclusion
    row, = reviewed.workorders.rows
    assert (row.work_order, row.site, row.status) == ("00021", "north", "Completed")
    assert unmapped_cells(reviewed.workorders, row.key) == (
        (3, "Status", "Open"), (5, "Extra", "0"))
    stored = restore_csv_review(json.loads(json.dumps(csv_review_record(reviewed))))
    assert reimport_csv_review(stored, review_csv(source, profile, period, mapping=mapping)) == stored
    assert sources.source_bytes(profile, source.source) == raw


def test_xlsx_missing_formula_cache_and_hidden_sheet_are_explicit(context):
    profile, period = context
    raw = _workbook()
    parsed = _ingest(profile, "formula-and-hidden.xlsx", raw)
    assert len(parsed.tables) == 2
    assert parsed.tables[0].missing_formula_cache_count == 1
    assert parsed.tables[0].missing_formula_cache_cells == ("D2",)
    assert parsed.tables[1].hidden is True
    assert parsed.tables[0].rows[0][3] == ""
    assert any("without cached results" in notice for notice in parsed.source.notices)
    assert any("Hidden worksheets" in notice for notice in parsed.source.notices)
    assert work_order_evidence(parsed, period, profile) == ()
    pending = review_spreadsheet(parsed, profile, period)
    assert pending.workorders.rows[0].status == ""
    assert not pending.ready_for_inclusion
    explicit = review_spreadsheet(parsed, profile, period, table_number=2)
    assert explicit.ready_for_inclusion
    assert explicit.workorders.rows[0].site == "south"
    assert _ingest(profile, "formula-and-hidden.xlsx", raw).tables == parsed.tables


def test_xlsx_30_sheet_control_31_sheet_rejected_and_malformed_input(context):
    profile, period = context
    raw = _workbook(hidden=False, formula=False, sheet_count=30)
    parsed = _ingest(profile, "thirty.xlsx", raw)
    assert len(parsed.tables) == 30
    assert all(not table.hidden for table in parsed.tables)
    assert len(work_order_evidence(parsed, period, profile)) == 30
    with pytest.raises(ValueError, match="30 worksheets"):
        _ingest(profile, "thirty-one.xlsx",
                _workbook(hidden=False, formula=False, sheet_count=31))
    with pytest.raises((ValueError, BadZipFile)):
        _ingest(profile, "broken.xlsx", b"not-a-valid-workbook")
