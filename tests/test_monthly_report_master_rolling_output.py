"""Native rolling WO grids are checked in real Word and rendered PDF output."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO
import re

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


def render_fixture(tmp_path, monkeypatch):
    path = master_source(tmp_path / "native-rolling-master.docx")
    # Exercise the same immutable pin used by an installed master.  A fake
    # digest fails once the installer verifies that the original exists.
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    original = path.read_bytes()
    digest = sha256(original).hexdigest()
    master_dir = tmp_path / "data" / "monthly_reports" / "designs" / "master"
    master_dir.mkdir(parents=True)
    (master_dir / (digest + ".docx")).write_bytes(original)
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
    coverage = tuple(CoveredMonth(site, metric, month, source.source_reference)
        for site, metric, month in (
            ("n", "pm_received", "2026-11"),
            ("n", "pm_received", "2026-12"),
            ("n", "pm_closed", "2027-01"),
            ("s", "non_pm_received", "2026-12")))
    counts = tally_reviewed_months((source,), PERIOD, SITES,
        approved_revisions={source.source_reference: source.revision},
        pm_categories=("Preventive",), closed_statuses=("Finished",),
        covered_months=coverage,
        coverage_approvals={(item.site, item.metric, item.month): source.source_reference
                            for item in coverage})
    tables = bind_template_grids(counts, PERIOD, shapes, bound, SITES)
    profile = ReportProfile("Entirely invented contract", "rolling-output",
        "Two QA facilities", SITES, scope_type="multi_site",
        template="enfra_master:" + digest)
    draft = ReportDraft(profile, PERIOD, "Synthetic reviewer",
        profile_sections(profile),
        (ResolvedBlock("work_orders", "This month", extra_tables=tables),),
        synthetic=True)
    return path, draft, tables


def render_four_frame_fixture(tmp_path, monkeypatch):
    source = Document()
    source.add_heading("MONTHLY ACTIVITY SUMMARY", 1)
    source.add_paragraph("WORK ORDER STATUS")
    for metric in METRICS:
        source.add_paragraph(LABELS[metric])
        table = source.add_table(rows=3, cols=13)
        for col, value in enumerate((LABELS[metric], *rolling_labels(PERIOD))):
            table.cell(0, col).text = value
        table.cell(1, 0).text = "PREVIOUS SOURCE NORTH"
        table.cell(2, 0).text = "PREVIOUS SOURCE SOUTH"
    path = tmp_path / "four-metric-master.docx"
    source.save(path)
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    digest = sha256(path.read_bytes()).hexdigest()
    master_dir = tmp_path / "data" / "monthly_reports" / "designs" / "master"
    master_dir.mkdir(parents=True)
    (master_dir / (digest + ".docx")).write_bytes(path.read_bytes())
    frames = tuple(shape for shape in from_inspection(inspect_docx(path))
                   if shape.slot == "work_orders" and len(shape.columns) == 13)
    assert len(frames) == 4
    source_review = review("synthetic:four-frames", (
        Row("n", "n", "N-1", "2026-12-05", "", "Open", "Non-PM"),
        Row("s", "s", "S-1", "2026-12-06", "", "Open", "Non-PM")))
    coverage = tuple(CoveredMonth(site.key, "non_pm_received", "2026-12", source_review.source_reference)
                     for site in SITES)
    counts = tally_reviewed_months((source_review,), PERIOD, SITES,
        approved_revisions={source_review.source_reference: source_review.revision},
        covered_months=coverage,
        coverage_approvals={(v.site, v.metric, v.month): source_review.source_reference for v in coverage})
    bindings = {frame.reference: (("n", "s"), metric) for frame, metric in zip(frames, METRICS)}
    tables = bind_template_grids(counts, PERIOD, frames, bindings, SITES)
    profile = ReportProfile("Entirely invented contract", "rolling-four-output",
        "Two QA facilities", SITES, scope_type="multi_site", template="enfra_master:" + digest)
    draft = ReportDraft(profile, PERIOD, "Synthetic reviewer", profile_sections(profile),
        (ResolvedBlock("work_orders", "This month", extra_tables=tables),), synthetic=True)
    return path, draft, tables


def test_four_native_grids_render_two_distinct_site_rows(tmp_path, monkeypatch):
    path, draft, tables = render_four_frame_fixture(tmp_path, monkeypatch)
    original = path.read_bytes()
    doc = Document(BytesIO(build_native_docx(draft, path, master=True)))
    assert len(doc.tables) == 4
    for word, expected in zip(doc.tables, tables):
        assert [cell.text for cell in word.rows[0].cells] == list(expected.columns)
        assert [[cell.text for cell in row.cells] for row in word.rows[1:]] == [list(row) for row in expected.rows]
    assert [doc.tables[1].cell(row, 11).text for row in (1, 2)] == ["1", "1"]
    assert [doc.tables[0].cell(row, 11).text for row in (1, 2)] == ["", ""]
    assert path.read_bytes() == original


def test_reviewed_source_counts_reach_the_actual_native_word_grid(tmp_path, monkeypatch):
    from app import monthly_report_sources as sources
    from app import monthly_report_work_order_review_flow as flow
    from app.monthly_report_rolling_workflow import publish

    path, draft, existing = render_four_frame_fixture(tmp_path, monkeypatch)
    original = path.read_bytes()
    source, _ = sources.ingest(draft.profile, 'synthetic-work-orders.csv',
        b'Work Order,Site,Received Date,Closed Date,Status,Type\n'
        b'N-1,n,2026-12-05,2027-01-03,Closed,Non-PM\n')
    block = replace(draft.blocks[0], extra_tables=tuple(replace(table, rows=()) for table in existing))
    draft = replace(draft, blocks=(block,), sources=(source.source,))
    bundle = flow.prepare_bundle(draft, source)
    bundle = flow.confirm_coverage(draft, bundle, table_number=1, site='n',
        start_month='2026-12', end_month='2027-01',
        evidence='Synthetic export range and closed dates checked', confirmed=True)
    draft = flow.store_bundle(draft, bundle)
    report = publish(draft, bundle, expected_revision=flow.revision(bundle),
        expected_block=block.fingerprint, group_index=0,
        metrics=('non_pm_received', 'non_pm_closed'), confirmed=True, as_of=date(2027, 2, 1))
    word = Document(BytesIO(build_native_docx(report, path, master=True)))
    assert word.tables[1].cell(1, 11).text == '1'  # December received.
    assert word.tables[3].cell(1, 12).text == '1'  # January closed.
    assert word.tables[1].cell(2, 11).text == ''   # South is not confirmed.
    assert path.read_bytes() == original


@requires_libreoffice
def test_four_native_grids_render_both_sites_in_pdf(tmp_path, monkeypatch):
    path, draft, _ = render_four_frame_fixture(tmp_path, monkeypatch)
    docx_path = tmp_path / "four-metric-output.docx"
    docx_path.write_bytes(build_native_docx(draft, path, master=True))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    pdf_path = pdf_converter.convert_to_pdf(docx_path)
    with pymupdf.open(pdf_path) as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    for label in ("North QA", "South QA", "PM Received", "Non-PM Received",
                  "PM Closed", "Non-PM Closed", "Dec 2026", "Jan 2027"):
        assert label in text
    assert "PREVIOUS SOURCE" not in text


def test_actual_native_docx_has_both_sites_exact_month_labels_and_values(tmp_path, monkeypatch):
    path, draft, tables = render_fixture(tmp_path, monkeypatch)
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
    path, draft, _ = render_fixture(tmp_path, monkeypatch)
    docx_path = tmp_path / "rolling-output.docx"
    docx_path.write_bytes(build_native_docx(draft, path, master=True))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    pdf_path = pdf_converter.convert_to_pdf(docx_path)
    with pymupdf.open(pdf_path) as document:
        assert len(document) >= 1
        text = "\n".join(page.get_text() for page in document)
    # Word may wrap at a word boundary inside a narrow cell. A newline at a
    # space is readable, but a break inside a word ("Nort h" or "Rece ived")
    # must still fail these whole-label checks.
    readable = " ".join(text.split())
    for expected in ("North QA", "South QA", "PM Received", "Non-PM Received",
                     "PM Closed", "Non-PM Closed", "Dec 2026", "Jan 2027"):
        assert expected in readable
    assert re.search(r"(?<!Non-)PM Received", readable)
    assert re.search(r"(?<!Non-)PM Closed", readable)
    assert "PREVIOUS SOURCE VALUE" not in readable
    assert pdf_path.read_bytes().startswith(b"%PDF-")
