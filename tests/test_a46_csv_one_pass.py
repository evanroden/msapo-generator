"""A46 synthetic CSV controls: one-pass columns, immutable cells and safe totals."""
import json
from dataclasses import replace

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import work_order_evidence
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_csv_review import (
    correct_csv_row, csv_review_record, mapped_columns, reimport_csv_review,
    restore_csv_review, review_csv,
)
from app.monthly_report_work_order_normalized import unmapped_cells

PROFILE = ReportProfile(
    "Synthetic A46 contract", "a46-two-sites", "Synthetic sites",
    (Facility("north", "Synthetic North Campus", ("North",)),
     Facility("south", "Synthetic South Campus", ("South",))),
    scope_type="multi_site",
)
PERIOD = ReportPeriod(2026, 9)


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def imported(name, raw):
    content, _ = sources.ingest(PROFILE, name, raw)
    assert sources.source_bytes(PROFILE, content.source) == raw
    return content


@pytest.mark.parametrize("name,raw", [
    ("a46-comma.csv",
     b"WO ID,Site Label,Service When,Current State,Repair Type,Trade Name,Notes\n"
     b"000123,North,2026-09-12,Completed,Preventive,HVAC,0\n"
     b"000124,South,2026-09-13,Open,Corrective,Electrical,\n"),
    ("a46-semicolon.csv",
     b"Ticket ID;Location Name;Reported On;WO Status;Maintenance Type;Discipline;Notes\n"
     b"000123;North;2026-09-12;Completed;Preventive;HVAC;0\n"
     b"000124;South;2026-09-13;Open;Corrective;Electrical;\n"),
])
def test_standard_cmms_aliases_are_one_pass_with_original_cells(name, raw):
    source = imported(name, raw)
    result = review_csv(source, PROFILE, PERIOD)
    assert result.ready_for_inclusion
    assert not result.questions
    assert result.workorders.counts() == dict(
        source_rows=2, included=2, needs_review=0, excluded=0, unmapped_rows=0)
    assert [(r.work_order, r.site, r.work_date, r.status, r.work_type, r.trade)
            for r in result.workorders.rows] == [
        ("000123", "north", "2026-09-12", "Completed", "PM", "HVAC"),
        ("000124", "south", "2026-09-13", "Open", "Non-PM", "Electrical"),
    ]
    assert unmapped_cells(result.workorders, result.workorders.rows[0].key) == (
        (6, "Notes", "0"),)
    assert [r.origin.row_number for r in result.workorders.rows] == [1, 2]
    counts = count_reviewed_work_orders(
        result.workorders, approved_revision=result.workorders.revision,
        period=PERIOD, selected_sites=("north", "south"), include_trades=True)
    assert (counts.overall.total, counts.overall.completed, counts.overall.open) == (2, 1, 1)
    assert [(group.label, group.total) for group in counts.work_types] == [
        ("PM", 1), ("Non-PM", 1), ("Unclassified work type", 0)]
    assert {group.label: group.total for group in counts.trades} == {
        "HVAC": 1, "Electrical": 1}
    assert set(counts.overall.row_keys) == {row.key for row in result.workorders.rows}
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_case_variant_and_repeated_physical_header_need_explicit_id_selection():
    raw = (b"WO ID,WO ID,Site Label,Service When,Current State,Repair Type,Notes\n"
           b"WO-A,ALT-1,North,2026-09-08,Closed,PM,0\n"
           b"wo-a,ALT-2,North,2026-09-08,Open,Corrective,\n")
    source = imported("a46-duplicate.csv", raw)
    assert source.tables[0].columns[:2] == ("WO ID", "WO ID (2)")
    initial = review_csv(source, PROFILE, PERIOD)
    assert initial.workorders.kind == "unresolved"
    assert "work_order" in initial.workorders.mapping.ambiguous
    assert initial.workorders.counts()["unmapped_rows"] == 2
    mapping = mapped_columns(source.tables[0].columns, {"work_order": 0})
    candidate = review_csv(source, PROFILE, PERIOD, mapping=mapping)
    assert candidate.workorders.counts() == dict(
        source_rows=2, included=0, needs_review=2, excluded=0, unmapped_rows=0)
    assert all("duplicate work-order identity" in r.issues
               for r in candidate.workorders.rows)
    corrected = correct_csv_row(candidate, candidate.workorders.rows[1].key,
                                {"work_order": "WO-B"},
                                expected_revision=candidate.revision)
    assert corrected.workorders.counts()["included"] == 2
    assert unmapped_cells(corrected.workorders, corrected.workorders.rows[0].key) == (
        (1, "WO ID (2)", "ALT-1"), (6, "Notes", "0"))
    assert corrected.workorders.rows[1].origin.cells[0] == "wo-a"
    restored = restore_csv_review(json.loads(json.dumps(csv_review_record(corrected))))
    assert restored == corrected
    assert reimport_csv_review(restored, review_csv(
        source, PROFILE, PERIOD, mapping=mapping)) == corrected
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_case_variant_distinct_headers_also_remain_visibly_ambiguous():
    source = imported("a46-case-headers.csv",
        b"WO ID,wo id,Site Label,Service When,Current State\n"
        b"WO-C,OTHER,North,2026-09-01,Open\n")
    result = review_csv(source, PROFILE, PERIOD)
    assert "work_order" in result.workorders.mapping.ambiguous
    assert result.workorders.kind == "unresolved"
    assert result.workorders.original_rows[0][1] == "OTHER"


def test_monthly_summary_with_work_order_heading_never_fabricates_rows():
    raw = (b"Work Order,August,September,Total\n"
           b"PM,2,3,5\nNon-PM,1,4,5\n")
    source = imported("a46-grid.csv", raw)
    review = review_csv(source, PROFILE, PERIOD)
    assert review.workorders.kind == "aggregate"
    assert len(review.workorders.rows) == 0
    assert review.workorders.counts() == dict(
        source_rows=2, included=0, needs_review=0, excluded=0, unmapped_rows=2)
    assert "Aggregate counts are not individual work-order records" in review.questions
    assert review.workorders.original_rows[0] == ("PM", "2", "3", "5")
    assert not review.ready_for_inclusion
    assert sources.source_bytes(PROFILE, source.source) == raw


def test_numeric_date_missing_header_and_outside_scope_are_not_accepted():
    numeric = imported("a46-numeric.csv",
        b"WO ID,Site Label,Service When,Current State\n"
        b"00001,North,09/12/2026,Open\n")
    unresolved = review_csv(numeric, PROFILE, PERIOD)
    assert not unresolved.ready_for_inclusion
    assert len(unresolved.unresolved_dates) == 1
    assert review_csv(numeric, PROFILE, PERIOD, numeric_date_order="MDY").ready_for_inclusion
    out_of_period = review_csv(numeric, PROFILE, ReportPeriod(2026, 10),
                               numeric_date_order="MDY")
    assert not out_of_period.ready_for_inclusion
    unknown = imported("a46-unknown.csv",
        b"Site Label,Service When,Current State\nNorth,2026-09-12,Open\n")
    assert review_csv(unknown, PROFILE, PERIOD).workorders.kind == "unresolved"
    with pytest.raises(ValueError, match="CSV"):
        review_csv(replace(unknown, source=replace(unknown.source, suffix=".xlsx")),
                   PROFILE, PERIOD)


def test_legacy_metric_totals_remain_unchanged_by_review_mapping():
    raw = (b"Work Order,Date,Status,Facility,Category\n"
           b"0001,2026-09-03,Completed,Synthetic North Campus,PM\n"
           b"0002,2026-09-05,Open,Synthetic South Campus,Corrective\n")
    source = imported("a46-legacy.csv", raw)
    before, = work_order_evidence(source, PERIOD, PROFILE)
    assert (before.total, before.completed, before.open) == (2, 1, 1)
    assert review_csv(source, PROFILE, PERIOD).ready_for_inclusion
    assert work_order_evidence(source, PERIOD, PROFILE) == (before,)

def test_apptest_typical_csv_needs_no_mapping_changes(monkeypatch, tmp_path):
    from test_monthly_report_work_order_review_ui import app_for, button

    raw = (b"WO ID,Site Label,Service When,Current State,Repair Type,Trade Name\n"
           b"0005,North,2026-09-05,Closed,Preventive,HVAC\n")
    app = app_for(monkeypatch, tmp_path, raw)
    button(app, "Review and correct imported rows").click().run()
    assert not app.exception
    assert not button(app, "Include reviewed rows in Activity").disabled
    assert next(w for w in app.selectbox if w.label == "Work-order ID column").value == 0
    assert next(w for w in app.selectbox if w.label == "Site column").value == 1
    assert next(w for w in app.selectbox if w.label == "Recorded status column").value == 3
    assert not any(e.label.startswith("Resolve CSV source columns:") for e in app.expander)


def test_apptest_duplicate_id_header_opens_unresolved_mapping(monkeypatch, tmp_path):
    from test_monthly_report_work_order_review_ui import app_for, button

    raw = (b"WO ID,WO ID,Site Label,Service When,Current State\n"
           b"0005,ALTERNATE,North,2026-09-05,Closed\n")
    app = app_for(monkeypatch, tmp_path, raw)
    button(app, "Review and correct imported rows").click().run()
    assert not app.exception
    assert button(app, "Include reviewed rows in Activity").disabled
    panels = [e for e in app.expander
              if e.label.startswith("Resolve CSV source columns:")]
    assert len(panels) == 1 and panels[0].proto.expanded
    assert "Work-order ID" in panels[0].label
    assert next(w for w in app.selectbox if w.label == "Work-order ID column").value is None
    assert next(w for w in app.selectbox if w.label == "Site column").value == 2
    next(w for w in app.selectbox if w.label == "Work-order ID column").select(0)
    next(w for w in app.checkbox if w.label.startswith("Rebuild this table")).check()
    button(app, "Apply source mapping").click().run()
    assert not app.exception
    assert not button(app, "Include reviewed rows in Activity").disabled
    draft = app.session_state["draft"]
    bundle = __import__("app.monthly_report_work_order_review_flow",
                        fromlist=["saved_bundle"]).saved_bundle(
                            draft, draft.sources[0].id, "workorders")
    assert bundle["groups"][0]["record"]["review"]["rows"][0]["origin"]["cells"][1] == "ALTERNATE"
