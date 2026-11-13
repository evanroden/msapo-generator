"""Native rolling WO grids are checked in real Word and rendered PDF output."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest

from app import pdf_converter
from app.monthly_report_import import inspect_docx
from app.monthly_report_master_tables import from_inspection
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
    profile_sections,
)
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_work_order_rolling import (
    METRICS, CoveredMonth, bind_template_grids, rolling_labels,
    tally_reviewed_months,
)
from tests.conftest import requires_libreoffice
from test_monthly_report_work_order_rolling import Row, review


PERIOD = ReportPeriod(2027, 1)
SITES = (Facility("n", "North QA"), Facility("s", "South QA"))
LABELS = {
    "pm_received": "PM Received", "non_pm_received": "Non-PM Received",
    "pm_closed": "PM Closed", "non_pm_closed": "Non-PM Closed",
}


def master_source(path):
    source = Document()
    source.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    source.add_paragraph("WORK ORDER STATUS")
    for site in SITES:
        for metric in METRICS:
            source.add_paragraph(site.title + " " + LABELS[metric])
            table = source.add_table(rows=2, cols=13)
            for col, value in enumerate((LABELS[metric], *rolling_labels(PERIOD))):
                table.cell(0, col).text = value
            for col in range(13):
                table.cell(1, col).text = "PREVIOUS SOURCE VALUE" if col == 0 else ""
    source.save(path)
    return path


def render_fixture(tmp_path):
    path = master_source(tmp_path / "native-rolling-master.docx")
    shapes = tuple(shape for shape in from_inspection(inspect_docx(path))
                   if shape.slot == "work_orders" and len(shape.columns) == 13)
    assert len(shapes) == 8  # Do not quietly skip a native location/metric.
    bound = {shape.reference: (SITES[index // 4].key, METRICS[index % 4])
             for index, shape in enumerate(shapes)}
    rows = (
        Row("a", "n", "WO-1", "2026-12-30", "2027-01-02", "Completed", "PM"),
        Row("b", "s", "WO-1", "2026-12-31", "", "Open", "Non-PM"),
    )
    source = review("synthetic:rolling", rows)
    coverage = (CoveredMonth("n", "pm_received", "2026-11", source.source_reference),)
    counts = tally_reviewed_months((source,), PERIOD, SITES,
        approved_revisions={source.source_reference: source.revision},
        pm_categories=("Preventive",), closed_statuses=("Finished",),
        covered_months=coverage,
        coverage_approvals={("n", "pm_received", "2026-11"): source.source_reference})
    tables = bind_template_grids(counts, PERIOD, shapes, bound, SITES)
    profile = ReportProfile("Entirely invented contract", "rolling-output",
        "Two QA facilities", SITES, scope_type="multi_site",
        template="enfra_master:" + "a" * 64)
    draft = ReportDraft(profile, PERIOD, "Synthetic reviewer",
        profile_sections(profile),
        (ResolvedBlock("work_orders", "This month", extra_tables=tables),),
        synthetic=True)
    return path, draft, tables


def test_actual_native_docx_has_both_sites_exact_month_labels_and_values(tmp_path):
    path, draft, tables = render_fixture(tmp_path)
    original = path.read_bytes()
    doc = Document(BytesIO(build_native_docx(draft, path, master=True)))
    assert len(doc.tables) == 8
    expected = {(site, metric): table for (site, metric), table in
                zip(((site.key, metric) for site in SITES for metric in METRICS), tables)}
    for index, (site, metric) in enumerate(
            (site, metric) for site in SITES for metric in METRICS):
        word = doc.tables[index]
        assert [cell.text for cell in word.rows[0].cells] == list(
            expected[(site.key, metric)].columns)
        assert [cell.text for cell in word.rows[1].cells] == list(
            expected[(site.key, metric)].rows[0])
    assert doc.tables[0].cell(1, 11).text == "1"  # North PM Dec received
    assert doc.tables[2].cell(1, 12).text == "1"  # North PM Jan closed
    assert doc.tables[4].cell(1, 11).text == ""   # South PM unknown, not 0
    assert doc.tables[5].cell(1, 11).text == "1"  # South non-PM Dec
    assert doc.tables[0].cell(1, 10).text == "0"  # Approved Nov coverage
    assert path.read_bytes() == original
    assert "PREVIOUS SOURCE VALUE" not in "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells)


@requires_libreoffice
def test_actual_pdf_reflects_word_tables_without_missing_site_or_fabricated_counts(tmp_path, monkeypatch):
    path, draft, _ = render_fixture(tmp_path)
    docx_path = tmp_path / "rolling-output.docx"
    docx_path.write_bytes(build_native_docx(draft, path, master=True))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    pdf_path = pdf_converter.convert_to_pdf(docx_path)
    with pymupdf.open(pdf_path) as document:
        assert len(document) >= 1
        text = "\n".join(page.get_text() for page in document)
    for expected in ("North QA", "South QA", "PM Received", "Non-PM Received",
                     "PM Closed", "Non-PM Closed", "Dec 2026", "Jan 2027"):
        assert expected in text
    assert "PREVIOUS SOURCE VALUE" not in text
    assert pdf_path.read_bytes().startswith(b"%PDF-")
