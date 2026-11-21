"""A08 synthetic CSV/XLSX source-conservation and ambiguity canaries."""
from dataclasses import replace
from io import BytesIO
from zipfile import BadZipFile, ZipFile
import json

import pytest
from openpyxl import Workbook

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import (
    is_work_order_source, requires_work_order_column_mapping, work_order_evidence,
)
from app.monthly_report_work_order_csv_review import (
    csv_review_record, mapped_columns, reimport_csv_review, restore_csv_review,
    review_csv, review_spreadsheet,
)
from app.monthly_report_work_order_normalized import suggest_mapping, unmapped_cells
from app.monthly_report_pre_model_routing import choose_reader_pages
from app.monthly_report_structured_uploads import (
    _native_reader_page_pairs, mapped_rows, native_update, reader_notices, reader_request,
    reader_sources, reader_update,
)


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


def _saved(wb):
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def _amend_sheet(raw, *replacements, part_name="xl/worksheets/sheet1.xml"):
    """Rewrite stored cell XML exactly as Excel or LibreOffice would save it."""
    amended = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(amended, "w") as target:
        for part in original.infolist():
            data = original.read(part.filename)
            if part.filename == part_name:
                for old, new in replacements:
                    assert data.count(old) == 1, old
                    data = data.replace(old, new)
            target.writestr(part, data)
    return amended.getvalue()


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
    assert any("without trusted cached results" in notice for notice in parsed.source.notices)
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


def test_cached_formula_result_is_read_not_executed(context):
    profile, period = context
    wb = Workbook()
    sheet = wb.active
    sheet.append(("WO Number", "Site", "Date", "Status", "Hours"))
    sheet.append(("0007", "North", "2026-09-08", "Closed", "=1+1"))
    stream = BytesIO()
    wb.save(stream)
    amended = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as original, ZipFile(amended, "w") as target:
        for part in original.infolist():
            data = original.read(part.filename)
            if part.filename == "xl/worksheets/sheet1.xml":
                old = b"<f>1+1</f><v></v>"
                assert old in data
                data = data.replace(old, b"<f>1+1</f><v>2</v>", 1)
            target.writestr(part, data)
    raw = amended.getvalue()
    content = _ingest(profile, "cached-formula.xlsx", raw)
    assert content.tables[0].rows[0][-1] == "2"
    assert content.tables[0].missing_formula_cache_count == 0
    assert review_spreadsheet(content, profile, period).ready_for_inclusion
    assert not any("without trusted cached results" in notice for notice in content.source.notices)
    assert sources.source_bytes(profile, content.source) == raw


def test_hidden_worksheet_cannot_auto_fill_capital_table(context):
    profile, period = context
    wb = Workbook()
    wb.active.append(("Note",))
    wb.active.append(("Visible workbook tab",))
    hidden = wb.create_sheet("Private archive")
    hidden.sheet_state = "hidden"
    hidden.append(("Facility", "Priority", "Recommendation"))
    hidden.append(("South", "High", "Synthetic hidden proposal"))
    memory = BytesIO()
    wb.save(memory)
    content = _ingest(profile, "hidden-capital.xlsx", memory.getvalue())
    assert content.tables[1].hidden
    assert content.tables[1].rows[0][2] == "Synthetic hidden proposal"
    assert mapped_rows(content, "capital_renewal") == ()
    assert reader_sources((content,), "activity_summary") == ()
    assert native_update((content,), "activity_summary").text == ""


def test_repeated_status_workbook_without_site_stays_out_of_both_activity_paths(context):
    """A visible, fully cached work-order workbook whose Status column repeats is
    neither counted automatically nor read into Activity by either route."""
    profile, period = context
    wb = Workbook()
    wb.active.append(("WO Number", "Date", "Status", "Status", "Work Description"))
    wb.active.append(("00031", "2026-09-08", "Open", "Closed", "Synthetic chiller inspection"))
    memory = BytesIO()
    wb.save(memory)
    content = _ingest(profile, "repeated-status.xlsx", memory.getvalue())
    assert not any(table.hidden or table.missing_formula_cache_count for table in content.tables)
    assert not is_work_order_source(content)
    assert requires_work_order_column_mapping(content)
    assert not work_order_evidence(content, period, profile)
    assert reader_sources((content,), "activity_summary") == ()
    notice, = reader_notices((content,), "activity_summary")
    assert "explicit column-position mapping" in notice
    assert native_update((content,), "activity_summary").text == ""


def test_cached_empty_string_formula_result_is_trusted_but_absent_results_are_not(context):
    """Excel and LibreOffice save an empty-string result as t="str" with an empty <v>.

    openpyxl's data-only view returns None for that cell and for a formula with
    no saved result. Only the stored XML separates the two; nothing is evaluated.
    """
    profile, _period = context
    wb = Workbook()
    wb.active.append(("Date", "Work Performed", "Note", "Check", "Label", "Owner"))
    wb.active.append(("2026-09-09", "Synthetic boiler inspection",
                      '=TRIM("")', "=1+1", '=TRIM(" ")', '=TRIM("b")'))
    raw = _amend_sheet(
        _saved(wb),
        (b'<c r="C2"><f>TRIM("")</f><v></v></c>', b'<c r="C2" t="str"><f>TRIM("")</f><v></v></c>'),
        (b'<c r="E2"><f>TRIM(" ")</f><v></v></c>', b'<c r="E2" t="str"><f>TRIM(" ")</f><v/></c>'),
        # A declared string type with no stored <v> is still an absent result.
        (b'<c r="F2"><f>TRIM("b")</f><v></v></c>', b'<c r="F2" t="str"><f>TRIM("b")</f></c>'),
    )
    content = _ingest(profile, "cached-empty-string.xlsx", raw)
    table, = content.tables
    assert table.rows[0][2] == table.rows[0][4] == ""
    assert table.missing_formula_cache_count == 2
    assert table.missing_formula_cache_cells == ("D2", "F2")
    assert sources.source_bytes(profile, content.source) == raw


def test_optional_blank_formula_column_does_not_exclude_workbook_from_activity(context):
    profile, _period = context
    wb = Workbook()
    wb.active.append(("Date", "Work Performed", "Follow-up"))
    wb.active.append(("2026-09-09", "Synthetic boiler inspection completed", '=IF(1=1,"","x")'))
    raw = _amend_sheet(
        _saved(wb),
        (b'<c r="C2"><f>IF(1=1,"","x")</f><v></v></c>',
         b'<c r="C2" t="str"><f>IF(1=1,"","x")</f><v></v></c>'),
    )
    # A cache written under provenance policy 1 recorded the blank as missing.
    stale = _ingest(profile, "optional-blank-formula.xlsx", raw)
    cache = sources._path(profile, stale.source.sha256, ".json")
    record = json.loads(cache.read_text())
    assert record["xlsx_provenance_policy"] == 2
    record["xlsx_provenance_policy"] = 1
    record["tables"][0].update(missing_formula_cache_count=1, missing_formula_cache_cells=["C2"])
    cache.write_text(json.dumps(record))
    content = _ingest(profile, "optional-blank-formula.xlsx", raw)
    assert content.tables[0].missing_formula_cache_count == 0
    assert json.loads(cache.read_text())["xlsx_provenance_policy"] == 2
    assert not any("without trusted cached results" in notice for notice in content.source.notices)
    assert not any("missing formula cached results" in notice
                   for notice in reader_notices((content,), "activity_summary"))
    assert reader_sources((content,), "activity_summary") == (content,)


@pytest.mark.parametrize("destination, header, row", (
    ("capital_renewal", ("Facility", "Priority", "Recommendation"),
     ("South", "High", "Synthetic hidden renewal")),
    ("proposals", ("Facility", "Vendor", "Scope", "Status"),
     ("South", "Synthetic Vendor", "Synthetic hidden scope", "Pending")),
))
def test_hidden_worksheet_never_reaches_the_external_reader(context, destination, header, row):
    """Skipping a hidden sheet natively must not make it eligible for paid reading."""
    profile, period = context
    wb = Workbook()
    wb.active.title = "Visible"
    wb.active.append(header)
    wb.active.append(("North",) + row[1:-1] + ("Synthetic visible " + row[-1].split()[-1],))
    hidden = wb.create_sheet("Private archive")
    hidden.sheet_state = "hidden"
    hidden.append(header)
    hidden.append(row)
    content = _ingest(profile, f"hidden-{destination}.xlsx", _saved(wb))
    contents = (content,)
    assert content.tables[1].hidden
    hidden_page = (content.source.id, 2)

    native = _native_reader_page_pairs(contents, destination)
    assert hidden_page not in choose_reader_pages(
        profile, contents, destination, period=period, native_mapped=native)
    assert hidden_page not in choose_reader_pages(None, contents, destination)
    assert reader_request(profile, contents, destination, (hidden_page,)) == []

    # An old cached or in-flight response citing the hidden page adds nothing,
    # whether or not the caller supplies the admission profile.
    value = {"items": [{"source": content.source.id, "page": 2, "text": "", "row": list(row)}]}
    for kwargs in ({}, {"profile": profile, "period": period}):
        block, pages = reader_update(contents, destination, value, **kwargs)
        assert block.rows == () and block.references == () and pages == {}
