"""Three-row independent CSV must calculate its own facts, not inherit DOCX prose."""
from dataclasses import replace

from app import monthly_report_sources as sources
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_work_order_csv import work_order_evidence


PERIOD = ReportPeriod(2026, 9)
PROFILE = synthetic_profiles()[0]
CSV = (
    b"Work Order,Date,Status,Facility,Asset\n"
    b"WO-TEST-1001,2026-09-03,Completed,Demo North,PUMP-TEST-02\n"
    b"WO-TEST-1002,2026-09-20,Completed,Demo North,AHU-TEST-07\n"
    b"WO-TEST-1003,2026-09-24,Open,Demo North,VAV-TEST-03\n"
)


def test_actual_ingestion_of_independent_three_row_csv_yields_expected_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    data, _ = sources.ingest(PROFILE, "work_orders.csv", CSV)
    result = work_order_evidence(data, PERIOD, PROFILE)
    assert len(result) == 1
    metrics = result[0]
    assert (metrics.total, metrics.completed, metrics.open) == (3, 2, 1)
    assert "66.7%" in metrics.text
    assert not metrics.needs_site_confirmation
    assert [row[0] for row in metrics.rows] == [
        "WO-TEST-1001", "WO-TEST-1002", "WO-TEST-1003"]
    assert metrics.reference.startswith(data.source.id + ":1:")


def test_missing_site_column_requires_review_but_counts_source_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = CSV.replace(b",Facility,Asset", b",Asset").replace(b",Demo North,", b",")
    data, _ = sources.ingest(PROFILE, "unassigned.csv", raw)
    result, = work_order_evidence(data, PERIOD, PROFILE)
    assert (result.total, result.completed, result.open) == (3, 2, 1)
    assert result.needs_site_confirmation


def test_unknown_status_and_wrong_period_cannot_inflate_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = CSV + b"WO-TEST-1004,2026-10-02,Completed,Demo North,A4\n" + (
        b"WO-TEST-1005,2026-09-25,Unknown,Demo North,A5\n")
    data, _ = sources.ingest(PROFILE, "mixed.csv", raw)
    result, = work_order_evidence(data, PERIOD, PROFILE)
    assert (result.total, result.completed, result.open) == (3, 2, 1)
    assert any("unrecognized status" in n for n in result.notices)


def test_same_name_changed_bytes_not_identical_and_conflicts_excluded(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    data, _ = sources.ingest(PROFILE, "work_orders.csv", CSV)
    changed, _ = sources.ingest(PROFILE, "work_orders.csv", CSV.replace(
        b"WO-TEST-1003,2026-09-24,Open", b"WO-TEST-1003,2026-09-24,Completed"))
    assert data.source.id != changed.source.id
    assert work_order_evidence(changed, PERIOD, PROFILE)[0].completed == 3
    conflicting, _ = sources.ingest(PROFILE, "conflicting.csv",
        CSV + b"WO-TEST-1002,2026-09-20,Open,Demo North,AHU-TEST-07\n")
    result, = work_order_evidence(conflicting, PERIOD, PROFILE)
    assert (result.total, result.completed, result.open) == (2, 1, 1)
    assert any("conflicted" in n for n in result.notices)
