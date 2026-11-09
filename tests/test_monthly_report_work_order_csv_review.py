"""Synthetic CSV work-order mapping and deliberate date interpretation tests.

Exercises real saved-source ingest, not an invented parser. No client records,
documents or live report data enter the repository or test runner.
"""
from dataclasses import asdict, replace
import json

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import work_order_evidence
from app.monthly_report_work_order_normalized import unmapped_cells, suggest_mapping
from app.monthly_report_work_order_csv_review import (
    correct_csv_row, csv_review_record, exclude_csv_row, mapped_columns,
    physical_columns, reimport_csv_review, restore_csv_review, review_csv,
)


@pytest.fixture
def scope(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile(
        "Synthetic Example Contract", "two-campuses", "Synthetic Hospital Group",
        (Facility("north", "Synthetic North Campus", ("North",)),
         Facility("south", "Synthetic South Campus", ("South",))),
        scope_type="multi_site",
    )
    return profile, ReportPeriod(2026, 9)


def imported(profile, filename, raw):
    result, _ = sources.ingest(profile, filename, raw)
    assert sources.source_bytes(profile, result.source) == raw
    return result


def comparable_rows(review):
    return tuple((row.work_order, row.site, row.work_date, row.status,
                  row.work_type, row.trade)
                 for row in review.workorders.rows)


def test_bom_semicolon_and_pipe_csvs_normalize_identically_with_explicit_date_orders(scope):
    profile, period = scope
    one = (b"\xef\xbb\xbfWO Number;Site;Service Date;Current Status;Type;Trade;Hours;Notes\n"
           b"000123;North;09/12/2026;Finished;Preventive;HVAC;0;\n"
           b"000124;South;09/13/2026;Open;Corrective;Electrical;;Unresolved repair\n")
    two = (b"Ticket Number|Location|Date|Status|Task Type|Discipline|Hours|Memo\n"
           b"000123|North|12/09/2026|Finished|Preventive|HVAC|0|\n"
           b"000124|South|13/09/2026|Open|Corrective|Electrical||Unresolved repair\n")
    alpha = imported(profile, "alpha.csv", one)
    beta = imported(profile, "beta.csv", two)
    assert physical_columns(alpha)[0] == (0, "1 · WO Number")
    assert physical_columns(beta)[0] == (0, "1 · Ticket Number")
    pending = review_csv(alpha, profile, period)
    assert not pending.ready_for_inclusion
    assert len(pending.unresolved_dates) == 2
    assert any("MDY/DMY" in question for question in pending.questions)
    assert pending.workorders.counts()["needs_review"] == 2

    a = review_csv(alpha, profile, period, numeric_date_order="MDY")
    b = review_csv(beta, profile, period, numeric_date_order="DMY")
    assert a.ready_for_inclusion and b.ready_for_inclusion
    assert comparable_rows(a) == comparable_rows(b) == (
        ("000123", "north", "2026-09-12", "Completed", "PM", "HVAC"),
        ("000124", "south", "2026-09-13", "Open", "Non-PM", "Electrical"),
    )
    assert a.workorders.source_reference.startswith(alpha.source.id + ":1:")
    assert b.workorders.source_reference.startswith(beta.source.id + ":1:")
    assert a.workorders.counts() == dict(
        source_rows=2, included=2, needs_review=0, excluded=0, unmapped_rows=0)
    assert unmapped_cells(a.workorders, a.workorders.rows[0].key) == (
        (6, "Hours", "0"), (7, "Notes", ""))
    assert unmapped_cells(a.workorders, a.workorders.rows[1].key) == (
        (6, "Hours", ""), (7, "Notes", "Unresolved repair"))
    assert [row.origin.cells[2] for row in a.workorders.rows] == [
        "09/12/2026", "09/13/2026"]
    assert sources.source_bytes(profile, alpha.source) == one
    assert sources.source_bytes(profile, beta.source) == two


def test_numeric_date_locale_is_never_inferred_and_wrong_order_remains_outside_period(scope):
    profile, period = scope
    original = imported(profile, "locale.csv",
        b"Work Order,Site,Date,Status\n0003,North,09/10/2026,Open\n")
    none = review_csv(original, profile, period)
    assert not none.ready_for_inclusion
    assert not none.workorders.rows[0].work_date
    mdy = review_csv(original, profile, period, numeric_date_order="MDY")
    dmy = review_csv(original, profile, period, numeric_date_order="DMY")
    assert mdy.ready_for_inclusion
    assert mdy.workorders.rows[0].work_date == "2026-09-10"
    assert not dmy.ready_for_inclusion
    assert dmy.workorders.rows[0].work_date == "2026-10-09"
    assert "source date is outside this report period" in dmy.workorders.rows[0].issues
    with pytest.raises(ValueError, match="MDY"):
        review_csv(original, profile, period, numeric_date_order="auto")
    assert original.tables[0].rows[0][2] == "09/10/2026"


def test_unknown_fields_and_duplicate_headers_require_reviewable_physical_mapping(scope):
    profile, period = scope
    source = imported(profile, "aliases.csv",
        b"WO Number,WO,Site label,Service When,Current State,Repair Type,Hours,Hours\n"
        b"0005,ALT-005,North,2026-09-07,Deferred,Repair,0,\n")
    original_headers = source.tables[0].columns
    assert original_headers[-2:] == ("Hours", "Hours (2)")
    suggestion = suggest_mapping(original_headers)
    assert "work_order" in suggestion.ambiguous
    assert review_csv(source, profile, period).workorders.kind == "unresolved"
    mapped = mapped_columns(original_headers, {
        "work_order": 0, "site": 2, "work_date": 3, "status": 4,
        "work_type": 5,
    }, suggested=suggestion)
    review = review_csv(source, profile, period, mapping=mapped)
    assert review.workorders.kind == "records"
    assert review.workorders.rows[0].work_order == "0005"
    assert review.workorders.rows[0].work_type == "Non-PM"
    assert review.workorders.rows[0].issues == ("status needs review",)
    assert unmapped_cells(review.workorders, review.workorders.rows[0].key) == (
        (1, "WO", "ALT-005"), (6, "Hours", "0"), (7, "Hours (2)", ""))
    with pytest.raises(ValueError, match="multiple"):
        mapped_columns(original_headers, {"work_order": 0, "status": 0})
    with pytest.raises(ValueError, match="within"):
        mapped_columns(original_headers, {"status": 200})
    with pytest.raises(ValueError, match="supported"):
        mapped_columns(original_headers, {"unsupported": 1})


def test_status_correction_and_reimport_preserve_manual_edits_and_original_bytes(scope):
    profile, period = scope
    data = b"Ticket Number,Site,Date,Status,Category\n00071,North,2026-09-20,Deferred,Repair\n"
    source = imported(profile, "review.csv", data)
    draft = review_csv(source, profile, period)
    row = draft.workorders.rows[0]
    assert "status needs review" in row.issues
    changed = correct_csv_row(draft, row.key, {"status": "Open"},
                              expected_revision=draft.revision)
    assert changed.ready_for_inclusion
    assert changed.workorders.rows[0].origin.cells[3] == "Deferred"
    assert ("status", "Open") in changed.workorders.rows[0].corrections
    saved = json.loads(json.dumps(csv_review_record(changed)))
    loaded = restore_csv_review(saved)
    assert loaded == changed
    assert reimport_csv_review(changed, review_csv(source, profile, period)) == changed
    with pytest.raises(ValueError, match="changed"):
        correct_csv_row(changed, row.key, {"status": "Completed"},
                        expected_revision=draft.revision)
    assert sources.source_bytes(profile, source.source) == data
    saved["numeric_date_order"] = "MDY"
    with pytest.raises(ValueError, match="integrity"):
        restore_csv_review(saved)


def test_duplicate_wo_and_wrong_period_are_explicit_and_exclusions_are_scoped(scope):
    profile, period = scope
    source = imported(profile, "duplicates.csv",
        b"WO Number,Site,Date,Status,Type\n"
        b"0001,North,2026-09-02,Open,PM\n"
        b"0001,North,2026-09-03,Closed,PM\n"
        b"0002,South,2026-10-02,Closed,Corrective\n"
        b"0003,South,2026-09-05,Deferred,Corrective\n")
    draft = review_csv(source, profile, period)
    assert len(draft.workorders.rows) == 4
    assert draft.workorders.counts() == dict(
        source_rows=4, included=0, needs_review=4, excluded=0, unmapped_rows=0)
    assert all("duplicate work-order identity" in row.issues
               for row in draft.workorders.rows[:2])
    resolved = correct_csv_row(
        draft, draft.workorders.rows[1].key, {"work_order": "0004"},
        expected_revision=draft.revision)
    assert resolved.workorders.counts()["included"] == 2
    remaining = exclude_csv_row(
        resolved, resolved.workorders.rows[2].key,
        expected_revision=resolved.revision, excluded=True)
    assert remaining.workorders.counts() == dict(
        source_rows=4, included=2, needs_review=1, excluded=1, unmapped_rows=0)
    assert remaining.workorders.rows[2].origin.cells[2] == "2026-10-02"
    corrected = correct_csv_row(
        remaining, remaining.workorders.rows[3].key,
        {"status": "Pending"}, expected_revision=remaining.revision)
    assert corrected.ready_for_inclusion
    assert corrected.workorders.counts()["included"] == 3
    assert all(row.origin.cells[0] in ("0001", "0002", "0003")
               for row in corrected.workorders.rows)


def test_date_mapping_and_locale_change_require_explicit_review(scope):
    profile, period = scope
    source = imported(profile, "dates.csv",
        b"WO Number,Site,Date,Status\n0004,North,09/13/2026,Open\n")
    mdy = review_csv(source, profile, period, numeric_date_order="MDY")
    same = review_csv(source, profile, period, numeric_date_order="MDY")
    assert reimport_csv_review(mdy, same) == mdy
    with pytest.raises(ValueError, match="date interpretation"):
        reimport_csv_review(mdy, review_csv(
            source, profile, period, numeric_date_order="DMY"))
    mapped = mapped_columns(source.tables[0].columns,
                            {"work_date": None})
    with pytest.raises(ValueError, match="mapping"):
        reimport_csv_review(mdy, review_csv(
            source, profile, period, mapping=mapped, numeric_date_order="MDY"))
    newperiod = ReportPeriod(2026, 10)
    with pytest.raises(ValueError, match="month"):
        reimport_csv_review(mdy, review_csv(
            source, profile, newperiod, numeric_date_order="MDY"))
    other = imported(profile, "changed.csv",
        b"WO Number,Site,Date,Status\n0004,North,09/13/2026,Closed\n")
    with pytest.raises(ValueError, match="source changed"):
        reimport_csv_review(mdy, review_csv(
            other, profile, period, numeric_date_order="MDY"))
    assert restore_csv_review(json.loads(json.dumps(csv_review_record(mdy)))) == mdy


def test_existing_csv_metric_path_remains_independent_of_mapping_reviews(scope):
    profile, period = scope
    raw = (b"Work Order,Date,Status,Facility,Category\n"
           b"0001,2026-09-03,Completed,Synthetic North Campus,PM\n"
           b"0002,2026-09-05,Open,Synthetic South Campus,Corrective\n")
    source = imported(profile, "existing-metrics.csv", raw)
    before = work_order_evidence(source, period, profile)
    assert len(before) == 1
    assert (before[0].total, before[0].completed, before[0].open) == (2, 1, 1)
    alternative = review_csv(source, profile, period)
    assert alternative.ready_for_inclusion
    assert work_order_evidence(source, period, profile) == before
    assert sources.source_bytes(profile, source.source) == raw


def test_out_of_scope_import_and_damaged_csv_review_fail_closed(scope):
    profile, period = scope
    source = imported(profile, "small.csv",
        b"Work Order,Site,Date,Status\n0001,North,2026-09-03,Open\n")
    foreign = replace(source, source=replace(source.source, suffix=".xlsx"))
    with pytest.raises(ValueError, match="CSV source"):
        review_csv(foreign, profile, period)
    with pytest.raises(ValueError, match="CSV source"):
        physical_columns(foreign)
    good = review_csv(source, profile, period)
    blob = json.loads(json.dumps(csv_review_record(good)))
    blob["workorders"]["review"]["rows"][0]["origin"]["cells"][0] = "OTHER-WO"
    with pytest.raises(ValueError, match="invalid|integrity"):
        restore_csv_review(blob)


def test_cp1252_tab_delimited_rows_keep_unmapped_narrative_and_leading_zero(scope):
    profile, period = scope
    raw = (b"WO Number\tSite\tDate\tStatus\tNotes\n"
           b"000077\tSouth\t2026-09-12\tClosed\tTechnician\x92s check\n")
    source = imported(profile, "regional.tsv.csv", raw)
    review = review_csv(source, profile, period)
    assert review.ready_for_inclusion
    row, = review.workorders.rows
    assert (row.work_order, row.site, row.status) == (
        "000077", "south", "Completed")
    assert unmapped_cells(review.workorders, row.key) == (
        (4, "Notes", "Technician’s check"),)
    assert sources.source_bytes(profile, source.source) == raw


def test_unsupported_short_numeric_year_requires_row_review_not_date_guess(scope):
    profile, period = scope
    source = imported(profile, "short-year.csv",
        b"Work Order,Site,Date,Status\n0008,North,09/12/26,Completed\n")
    result = review_csv(source, profile, period, numeric_date_order="MDY")
    assert result.workorders.rows[0].work_date == ""
    assert not result.ready_for_inclusion
    assert "work_date needs review" in result.workorders.rows[0].issues
    assert result.workorders.rows[0].origin.cells[2] == "09/12/26"


def test_site_alias_change_requires_reconciliation_even_with_identical_csv_bytes(scope):
    profile, period = scope
    source = imported(profile, "scope.csv",
        b"WO Number,Site,Date,Status\n0008,North,2026-09-12,Open\n")
    first = review_csv(source, profile, period)
    changed_profile = replace(profile, facilities=(
        Facility("north-other", "Synthetic North Campus", ("North",)),
        profile.facilities[1],
    ))
    with pytest.raises(ValueError, match="site/month"):
        reimport_csv_review(first, review_csv(source, changed_profile, period))
