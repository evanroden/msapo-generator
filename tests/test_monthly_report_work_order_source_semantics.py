"""Source semantics safeguards for the existing CSV/XLSX work-order path."""
from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile
from app.monthly_report_work_order_csv import is_work_order_source, work_order_evidence
from app.monthly_report_work_order_normalized import normalize_table, suggest_mapping

PROFILE = ReportProfile("Synthetic source semantics", "semantic-test", "One site",
    (Facility("alpha", "Example Alpha", ("Alpha",)),))
PERIOD = ReportPeriod(2026, 9)


def test_received_date_is_accepted_without_using_closed_date(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = (b"Work Order #,Received Date,Closed Date,Status,Site\n"
           b"W-1,2026-09-02,2026-10-03,Closed,Alpha\n")
    content, _ = sources.ingest(PROFILE, "received.csv", raw)
    normalized = normalize_table(content, 1, PROFILE, PERIOD)
    assert normalized.mapping.work_date == 1
    assert normalized.mapping.completed_date == 2
    assert normalized.rows[0].work_date == "2026-09-02"
    assert normalized.rows[0].completed_date == "2026-10-03"
    evidence, = work_order_evidence(content, PERIOD, PROFILE)
    assert evidence.total == 1


def test_completed_date_alone_is_not_a_work_date(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = b"Work Order #,Closed Date,Status,Site\nW-2,2026-09-02,Closed,Alpha\n"
    content, _ = sources.ingest(PROFILE, "closed-only.csv", raw)
    assert not is_work_order_source(content)
    assert work_order_evidence(content, PERIOD, PROFILE) == ()
    review = normalize_table(content, 1, PROFILE, PERIOD)
    assert review.mapping.work_date is None
    assert "work_date needs review" in review.rows[0].issues


def test_same_site_identical_case_duplicate_is_conflict_not_silent_dedup(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = (b"Work Order #,Received Date,Status,Site\n"
           b"AB-3,2026-09-02,Closed,Alpha\n"
           b"ab-3,2026-09-02,Closed,Alpha\n"
           b"UNIQUE,2026-09-04,Open,Alpha\n")
    content, _ = sources.ingest(PROFILE, "duplicates.csv", raw)
    evidence, = work_order_evidence(content, PERIOD, PROFILE)
    assert evidence.total == 1 and evidence.open == 1
    assert any("conflicted" in notice for notice in evidence.notices)
    normalized = normalize_table(content, 1, PROFILE, PERIOD)
    assert all("duplicate work-order identity" in row.issues for row in normalized.rows[:2])


def test_summary_identifier_and_semantically_different_headers_need_review(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    raw = (b"Work Order #,Created On,Origin,Assigned,Received Date,Status,Site\n"
           b"TOTAL,2026-09-02,Origin-01,Staff,2026-09-02,Open,Alpha\n")
    content, _ = sources.ingest(PROFILE, "headers.csv", raw)
    mapping = suggest_mapping(content.tables[0].columns)
    assert mapping.work_date == 4  # Created On is not assumed to mean received.
    assert mapping.site == 6  # Origin is not assumed to mean a facility.
    assert mapping.status == 5  # Assigned is not a completed/open state.
    record = normalize_table(content, 1, PROFILE, PERIOD)
    assert "summary/title row needs review" in record.rows[0].issues
    assert record.rows[0].origin.cells[1:4] == ("2026-09-02", "Origin-01", "Staff")
