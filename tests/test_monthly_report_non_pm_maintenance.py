"""Synthetic tests for non-PM Maintenance from the SAME reviewed Activity source."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json

import pytest

from app.monthly_report_model import (
    Facility, ReportPeriod, ReportProfile, ReportSource, ResolvedBlock,
    default_sections, synthetic_draft,
)
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_work_order_normalized import (
    correct_row, normalize_table, reimport_review, review_record, restore_review,
)
from app.monthly_report_non_pm_maintenance import project_completed_non_pm

PROFILE = ReportProfile(
    "Invented maintenance contract", "p05-synthetic", "Two synthetic facilities",
    (Facility("north", "Synthetic North", ("North",)),
     Facility("south", "Synthetic South", ("South",))), scope_type="multi_site")
PERIOD = ReportPeriod(2026, 9)
COLUMNS = ("Work Order", "Site", "Date", "Closed Date", "Status", "Type", "Trade",
           "Area", "Description", "Asset Tag", "Performed By", "Vendor Invoice Total")


def fixture(columns, rows):
    cells = tuple(tuple(str(value) for value in row) for row in rows)
    encoded = json.dumps((columns, cells), ensure_ascii=False).encode()
    digest = sha256(encoded).hexdigest()
    source = ReportSource(digest, "invented-wo.csv", digest, ".csv")
    content = SourceContent(source, (SourceTable("Invented export", tuple(columns), cells),))
    return normalize_table(content, 1, PROFILE, PERIOD)


def project(review, **kwargs):
    return project_completed_non_pm(review, PROFILE, PERIOD,
                                    expected_revision=review.revision, **kwargs)


def row(wo, *, site="North", work="2026-09-03", closed="2026-09-05",
        status="Closed", category="Repair", performer="ENFRA", task="Inspect pump"):
    return (wo, site, work, closed, status, category, "", "Boiler room",
            task, "P-03", performer, "999.99")


def test_closed_date_governs_month_and_vendor_activity_remains_distinct():
    review = fixture(COLUMNS, (
        row("00001", work="2026-08-20", closed="2026-09-01"),
        row("00002", site="South", closed="2026-09-02", performer="Leased staff"),
        row("00003", closed="2026-09-03", performer="Employee 17"),
        row("00004", closed="2026-09-04", category="PM"),
        row("00005", closed="2026-08-31"),
        row("00006", status="Open"),
    ))
    result = project(review)
    assert result.source_reference == review.source_reference
    assert result.period_key == "2026-09"
    assert [x[0] for x in result.onsite_table.rows] == ["00001"]
    assert result.onsite_table.rows[0] == (
        "00001", "2026-09-01", "Synthetic North — Boiler room", "Inspect pump", "P-03")
    assert [x[0] for x in result.vendor_activity_table.rows] == ["00002"]
    assert result.vendor_activity_table.rows[0][3] == "Vendor/leased (source-stated)"
    assert [(x.work_order, x.disposition) for x in result.candidates] == [
        ("00001", "onsite"), ("00002", "vendor_activity"),
        ("00003", "needs_review"), ("00004", "not_eligible"),
        ("00005", "not_eligible"), ("00006", "not_eligible")]
    assert result.candidates[0].date_basis == "closed date"
    assert result.needs_review[0].performer == ""
    assert result.candidates[0].original.cells[-1] == "999.99"
    assert all("999.99" not in cell for table in (result.onsite_table,
               result.vendor_activity_table) for values in table.rows for cell in values)
    assert restore_review(review_record(review)) == review


def test_fallback_only_when_export_lacks_closed_date_field():
    no_close = tuple(c for c in COLUMNS if c != "Closed Date")
    values = tuple(v for i, v in enumerate(row("00010", work="2026-09-30"))
                   if COLUMNS[i] != "Closed Date")
    original = fixture(no_close, (values,))
    result = project(original)
    assert result.onsite_table.rows[0][1] == "2026-09-30"
    assert result.candidates[0].date_basis.startswith("work-date fallback")
    with_closed = fixture(COLUMNS, (row("00010", closed=""),))
    pending = project(with_closed)
    assert pending.onsite_table is None
    assert "Explicit closed date" in " ".join(pending.needs_review[0].reasons)
    ambiguous = fixture(COLUMNS, (row("00010", closed="09/03/2026"),))
    assert project(ambiguous).onsite_table is None
    # Explicit but unrecognized completion heading must not be treated as absent.
    unexpected = tuple("Closed On" if c == "Closed Date" else c for c in COLUMNS)
    mapped = fixture(unexpected, (row("00011", work="2026-09-03", closed="2026-10-01"),))
    assert mapped.mapping.completed_date is None
    denied = project(mapped)
    assert denied.onsite_table is None
    assert denied.candidates[0].date_basis == "closed-date mapping required"


def test_same_id_across_sites_allowed_but_same_site_duplicate_requires_review():
    two = fixture(COLUMNS, (row("0099"), row("0099", site="South")))
    result = project(two)
    assert [x[0] for x in result.onsite_table.rows] == ["0099", "0099"]
    assert result.onsite_table.rows[0][2].startswith("Synthetic North")
    assert result.onsite_table.rows[1][2].startswith("Synthetic South")
    duplicate = fixture(COLUMNS, (row("0099"), row("0099")))
    assert project(duplicate).onsite_table is None
    assert len(project(duplicate).needs_review) == 2


def test_unknown_type_unknown_performer_and_explicit_review_corrections():
    review = fixture(COLUMNS, (row("0011", status="On hold", category="Other",
                                 performer="Employee 007"),))
    first = project(review)
    assert first.onsite_table is None
    corrected = correct_row(review, review.rows[0].key, {
        "status": "Completed", "work_type": "Repair"}, expected_revision=review.revision)
    updated = project(corrected)
    assert len(updated.needs_review) == 1
    assert "Performer" in " ".join(updated.needs_review[0].reasons)
    approved = project(corrected, corrections={corrected.rows[0].key: {
        "performer": "ENFRA onsite", "task": "Repaired check valve",
        "area": "Plant 2", "tag": "VALVE-02"}})
    assert approved.onsite_table.rows == (
        ("0011", "2026-09-05", "Synthetic North — Plant 2",
         "Repaired check valve", "VALVE-02"),)
    assert approved.candidates[0].original.cells[8] == "Inspect pump"
    assert reimport_review(corrected, review) == corrected
    with pytest.raises(ValueError, match="changed"):
        project_completed_non_pm(corrected, PROFILE, PERIOD,
                                 expected_revision=review.revision)
    with pytest.raises(ValueError, match="explicitly"):
        project(corrected, corrections={corrected.rows[0].key: {"performer": "Evan"}})


def test_site_specific_business_rule_requires_explicit_original_value():
    raw = row("0041", performer="Contract X staff")
    review = fixture(COLUMNS, (raw,))
    assert project(review).onsite_table is None
    classified = project(review, site_performer_rules={
        "north": {"Contract X staff": "Vendor/leased"}})
    assert classified.vendor_activity_table.rows[0][0] == "0041"
    assert classified.vendor_activity_table.rows[0][3] == "Vendor/leased (site-rule)"
    reviewer = project(review, corrections={review.rows[0].key: {"performer": "Vendor/leased"}})
    assert reviewer.vendor_activity_table.rows[0][3] == "Vendor/leased (reviewer-classified)"
    assert classified.onsite_table is None
    with pytest.raises(ValueError, match="site"):
        project(review, site_performer_rules={"uno": {"ENFRA": "ENFRA onsite"}})


def test_site_rules_cannot_invent_or_ambiguously_classify_a_performer():
    missing = fixture(COLUMNS, (row("0051", performer=""),))
    assert project(missing).onsite_table is None
    with pytest.raises(ValueError, match="map sites"):
        project(missing, site_performer_rules=[])
    for blank in ("", "  ", "---"):
        with pytest.raises(ValueError, match="nonempty"):
            project(missing, site_performer_rules={"north": {blank: "ENFRA onsite"}})
    review = fixture(COLUMNS, (row("0052", performer="Contract-X"),))
    with pytest.raises(ValueError, match="conflict"):
        project(review, site_performer_rules={"north": {
            "Contract-X": "ENFRA onsite", "Contract X": "Vendor/leased"}})
    # Equivalent spellings are safe if they all mean the same category.
    result = project(review, site_performer_rules={"north": {
        "Contract-X": "Vendor/leased", "Contract X": "Vendor/leased"}})
    assert result.onsite_table is None
    assert result.vendor_activity_table.rows[0][0] == "0052"


def test_empty_eligible_cohort_does_not_create_blank_maintenance_tables():
    review = fixture(COLUMNS, (row("9001", category="PM"),
                               row("9002", status="Open"),))
    result = project(review)
    assert result.onsite_table is None
    assert result.vendor_activity_table is None
    assert len(result.excluded) == 2
    empty = fixture(COLUMNS, ())
    assert not project(empty).candidates
    assert project(empty).onsite_table is None


def test_120_row_source_order_idempotence_and_true_provenance():
    records = tuple(row(f"{n:06}", site=("North" if n % 2 else "South"),
                        closed=f"2026-09-{n % 28 + 1:02}")
                    for n in range(120))
    review = fixture(COLUMNS, records)
    first = project(review)
    second = project(restore_review(review_record(review)))
    assert first == second
    assert first.onsite_table is not None
    assert len(first.onsite_table.rows) == 120
    assert first.onsite_table.rows[0][0] == "000000"
    assert first.onsite_table.rows[-1][0] == "000119"
    assert len({c.key for c in first.candidates}) == 120
    assert first.candidates[-1].original.row_number == 120


def test_money_in_description_does_not_leak_into_client_table():
    review = fixture(COLUMNS, (row("S1", task="Vendor invoice total $500"),
                               row("S2", task="Replace check valve"),))
    result = project(review)
    assert [r[0] for r in result.onsite_table.rows] == ["S2"]
    assert len(result.needs_review) == 1
    assert result.candidates[0].original.cells[-1] == "999.99"


from conftest import requires_libreoffice


@requires_libreoffice
def test_synthetic_120_calls_render_docx_pdf_with_row_order_and_no_empty_pages(
        tmp_path, monkeypatch):
    import pymupdf
    from docx import Document
    from docx.oxml.ns import qn
    from app import monthly_report_sources as sources, pdf_converter
    from app.monthly_report_docx import generate_report
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    profile = PROFILE
    import csv
    from io import StringIO
    rows = tuple(row(f"MX-{n:03}", closed=f"2026-09-{n % 28 + 1:02}")
                 for n in range(120))
    stream = StringIO(newline="")
    csv.writer(stream).writerows((COLUMNS, *rows))
    raw = stream.getvalue().encode()
    content, _ = sources.ingest(profile, "invented-wo.csv", raw)
    from app.monthly_report_source_scope import correct_scope
    content = replace(content, source=correct_scope(content.source, profile, ("north", "south")))
    review = normalize_table(content, 1, profile, PERIOD)
    projection = project(review)
    section = next(s for s in default_sections() if s.key == "maintenance")
    base = synthetic_draft(profile, PERIOD)
    block = ResolvedBlock("service_calls", "This month",
                          extra_tables=(projection.onsite_table,),
                          references=(review.source_reference,))
    draft = replace(base, sections=(section,), blocks=(block,),
                    sources=(content.source,))
    result = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    assert result.docx and result.pdf and not result.pdf_error
    document = Document(BytesIO(result.docx))
    data_tables = [t for t in document.tables if any("MX-000" in c.text
                                                     for row in t.rows for c in row.cells)]
    assert data_tables
    table = data_tables[0]
    cells = [cell.text for doc_row in table.rows for cell in doc_row.cells]
    assert cells.index("MX-000") < cells.index("MX-119")
    assert any(tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None
               for tr in (table.rows[0]._tr,))
    with pymupdf.open(stream=result.pdf, filetype="pdf") as pdf:
        pages = [page.get_text() for page in pdf]
        joined = "\n".join(pages)
        assert "MX-000" in joined and "MX-119" in joined
        assert joined.find("MX-000") < joined.find("MX-119")
        assert all(text.strip() for text in pages)
        assert all("Task" in text or "Maintenance" in text
                   for text in pages if "MX-" in text)
