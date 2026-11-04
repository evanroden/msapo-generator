"""Keep spreadsheet price context out of new Activity without changing sources.

Synthetic public ingest and guided-widget tests exercise real extraction,
storage and Word output. PDF conversion has the repository's renderer gate.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import json
import os
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from openpyxl import Workbook
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_source_details import correct_source_details
from tests.conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 11)
ACTION = "Inspected pump P-TEST-42 at 128 psi."


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from app import monthly_report_ai as ai

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))

    def forbidden(*args, **kwargs):
        pytest.fail("Native spreadsheet Activity must not call an external model")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)


def spreadsheet(sheets, suffix=".xlsx", *, currency=False):
    if suffix == ".csv":
        assert len(sheets) == 1
        output = StringIO()
        csv.writer(output).writerows((sheets[0][1], *sheets[0][2]))
        return output.getvalue().encode()
    workbook = Workbook()
    for index, (title, columns, rows) in enumerate(sheets):
        sheet = workbook.active if index == 0 else workbook.create_sheet()
        sheet.title = title
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
        if currency:
            for column, heading in enumerate(columns, 1):
                if heading == "Invoice total":
                    for row in range(2, len(rows) + 2):
                        sheet.cell(row, column).number_format = '$#,##0.00;($#,##0.00)'
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def ingest(sheets, suffix=".xlsx", *, currency=False, filename=None):
    profile = synthetic_profiles()[0]
    raw = spreadsheet(sheets, suffix, currency=currency)
    filename = filename or "synthetic-maintenance-report" + suffix
    content, attachments = sources.ingest(profile, filename, raw)
    assert not attachments
    return profile, content, raw, filename


def extract(content, existing=None):
    original = asdict(content)
    result = structured.native_update((content,), "activity_summary", existing)
    assert asdict(content) == original
    return result


def unchanged_source(profile, content, raw, filename):
    assert sources.source_bytes(profile, content.source) == raw
    assert content.source.sha256 == sha256(raw).hexdigest()
    cached, attachments = sources.ingest(profile, filename, raw)
    assert not attachments and cached == content


def report(profile, content, existing=None):
    reviewed = replace(content, source=correct_source_details(
        content.source, profile, None, profile.facilities[0].key))
    block = extract(reviewed, existing)
    return ReportDraft(profile, PERIOD, "Synthetic operator",
        tuple(section for section in default_sections() if section.key == "activity"),
        (block,), sources=(reviewed.source,))


def word_text(raw):
    document = Document(BytesIO(raw))
    return "\n".join([paragraph.text for paragraph in document.paragraphs] + [
        cell.text for table in document.tables for row in table.rows for cell in row.cells])


def assert_word_values(raw):
    text = word_text(raw)
    assert ACTION in text and "1200" in text
    assert "4600" not in text and "Invoice total" not in text
    with ZipFile(BytesIO(raw)) as archive:
        xml = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                        if name.endswith(".xml"))
    assert "4600" not in xml


@pytest.mark.parametrize("heading,value,currency", [
    ("Invoice total", 1200, False),
    ("Invoice total", 0, False),
    ("Amount due", -1200, False),
    ("Subtotal", "(1,200.50)", False),
    ("Unit price", 12.5, False),
    ("Cost", 2026, False),
    ("Invoice total", 1200, True),
])
def test_public_workbook_ingest_filters_declared_money_before_narrative_extraction(heading, value, currency):
    profile, content, raw, filename = ingest((("Service visit", ("Work performed", heading),
                                             ((ACTION, value),)),), currency=currency)
    result = extract(content)
    amount = content.tables[0].rows[0][1]
    assert ACTION in result.text
    assert amount not in result.text
    assert heading not in result.text
    assert result.references == (sources.source_reference(content.source, 1),)
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_unrecognized_action_header_keeps_work_and_excludes_price_cells(suffix):
    profile, content, raw, filename = ingest((("Service visit", ("Technician notes", "Invoice total"),
                                             ((ACTION, 4600),)),), suffix)
    result = extract(content)
    assert ACTION in result.text and "4600" not in result.text
    unchanged_source(profile, content, raw, filename)


def test_recognized_csv_mapper_keeps_its_existing_vendor_date_status_contract():
    profile, content, raw, filename = ingest((("Service visit",
        ("Vendor", "Event date", "Work performed", "Status", "Invoice total", "Flow rate (gpm)"),
        (("Synthetic Mechanical", "2026-11-05", ACTION, "Pending", 4600, 1200),)),), ".csv")
    result = extract(content)
    assert result.text == "2026-11-05 · Synthetic Mechanical — " + ACTION + " (Status: Pending)"
    assert "4600" not in result.text and "1200" not in result.text
    assert result.references == (sources.source_reference(content.source, 1),)
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("heading,value", [
    ("Flow rate (gpm)", 1200), ("Motor RPM", 1750), ("Hours", 2.5),
    ("Invoice number", "INV-1200"), ("Pressure (psi)", 128), ("Temperature (F)", 72.4),
])
def test_nonmonetary_numeric_columns_remain_in_workbook_activity(heading, value):
    profile, content, raw, filename = ingest((("Technical readings", ("Work performed", heading),
                                             ((ACTION, value),)),))
    result = extract(content)
    assert ACTION in result.text
    assert heading in result.text
    assert str(value) in result.text
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("text", [
    "Inspected pump; repair quotation pending.",
    "Inspected pump; no repair costs were reported.",
    "Inspected pump; cost estimate is pending.",
])
def test_unpriced_body_wording_is_not_reinterpreted_as_a_price_heading(text):
    profile, content, raw, filename = ingest((("Service visit", ("Work performed", "Invoice total"),
                                             ((text, None),)),))
    result = extract(content)
    assert text in result.text
    unchanged_source(profile, content, raw, filename)


def test_equal_numeric_values_are_filtered_by_column_not_by_number():
    profile, content, raw, filename = ingest((("Readings", ("Work performed", "Flow rate (gpm)", "Invoice total"),
                                             ((ACTION, 1200, 1200),)),))
    result = extract(content)
    assert result.text.count("1200") == 1
    assert "Flow rate (gpm)" in result.text and "Invoice total" not in result.text
    unchanged_source(profile, content, raw, filename)


def test_multisheet_unknown_schemas_keep_each_original_page_reference_and_technical_values():
    profile, content, raw, filename = ingest((
        ("First visit", ("Technician notes", "Flow rate (gpm)", "Invoice total"), ((ACTION, 1200, 4600),)),
        ("Second visit", ("Observations", "Motor RPM", "Amount due"),
         (("Tested motor P-TEST-99; replacement remains pending.", 1750, 8800),)),
    ))
    result = extract(content)
    assert ACTION in result.text and "Tested motor P-TEST-99" in result.text
    assert "replacement remains pending" in result.text
    assert "1200" in result.text and "1750" in result.text
    assert "4600" not in result.text and "8800" not in result.text
    assert set(result.references) == {sources.source_reference(content.source, 1),
                                      sources.source_reference(content.source, 2)}
    assert extract(content, result) == result
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("columns,rows", [
    (("Work performed", "Invoice total"), (("", 1200),)),
    (("Work performed", "Invoice total"), (("", None), (None, None))),
    (("Invoice total",), ((1200,), (4600,))),
])
def test_price_only_or_blank_sheet_never_fabricates_activity_from_headings(columns, rows):
    profile, content, raw, filename = ingest((("No work recorded", columns, rows),))
    result = extract(content)
    assert not result.text and not result.references
    unchanged_source(profile, content, raw, filename)


def test_price_only_first_sheet_does_not_renumber_later_technical_evidence():
    profile, content, raw, filename = ingest((
        ("Invoice", ("Work performed", "Invoice total"), (("", 8800),)),
        ("Service visit", ("Work performed", "Flow rate (gpm)", "Invoice total"),
         ((ACTION, 1200, 4600),)),
    ))
    result = extract(content)
    assert ACTION in result.text and "1200" in result.text
    assert "4600" not in result.text and "8800" not in result.text
    assert result.references == (sources.source_reference(content.source, 2),)
    unchanged_source(profile, content, raw, filename)


def test_ambiguous_money_column_cannot_leak_bare_values_beside_safe_work():
    profile, content, raw, filename = ingest((("Service visit",
        ("Work performed", "Description / Cost", "Flow rate (gpm)"), ((ACTION, 4600, 1200),)),))
    result = extract(content)
    assert ACTION in result.text and "1200" in result.text
    assert "4600" not in result.text and "Description / Cost" not in result.text
    unchanged_source(profile, content, raw, filename)


def test_duplicate_price_headers_keep_their_physical_values_out_of_activity():
    profile, content, raw, filename = ingest((("Service visit",
        ("Work performed", "Invoice total", "Invoice total", "Flow rate (gpm)"),
        ((ACTION, 4600, 8800, 1200),)),))
    assert content.tables[0].columns[1:3] == ("Invoice total", "Invoice total (2)")
    result = extract(content)
    assert ACTION in result.text and "1200" in result.text
    assert "4600" not in result.text and "8800" not in result.text
    unchanged_source(profile, content, raw, filename)


def test_multiline_negative_outcome_survives_price_column_removal():
    text = "Inspected pump P-TEST-42 and it\nwould not stabilize at 128 psi."
    profile, content, raw, filename = ingest((("Service visit", ("Technician notes", "Invoice total"),
                                             ((text, 4600),)),))
    result = extract(content)
    assert "Inspected pump P-TEST-42 and it would not stabilize at 128 psi." in result.text
    assert "4600" not in result.text
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("site_heading", ["Facility", "Customer location"])
def test_row_specific_sites_still_require_mapping_before_native_or_reader_routes(suffix, site_heading):
    profile, content, raw, filename = ingest((("Mixed sites",
        (site_heading, "Work performed", "Invoice total"),
        (("Foreign South", ACTION, 4600),)),), suffix)
    existing = ResolvedBlock("activity_summary", "This month", text="Previously verified operator work.")
    assert extract(content, existing) == existing
    assert not structured.reader_sources((content,), "activity_summary")
    assert structured.reader_notices((content,), "activity_summary")
    assert not structured.reader_batches(profile, (content,), "activity_summary")
    assert structured.reader_sources((content,), "capital_renewal") == (content,)
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_cmms_records_stay_on_the_reviewed_work_order_route(suffix):
    profile, content, raw, filename = ingest((("Work orders",
        ("Work Order", "Status", "Event date", "Work performed", "Invoice total"),
        (("WO-42", "Completed", "2026-11-05", ACTION, 4600),)),), suffix)
    existing = ResolvedBlock("activity_summary", "This month", text="Existing operator work.")
    assert extract(content, existing) == existing
    assert not structured.reader_sources((content,), "activity_summary")
    assert any("work-order" in notice for notice in structured.reader_notices((content,), "activity_summary"))
    unchanged_source(profile, content, raw, filename)


@pytest.mark.parametrize("manual", ["Operator's deliberately corrected wording.", ""])
def test_same_source_replay_and_metadata_correction_preserve_manual_edit_or_clear(manual):
    profile, content, raw, filename = ingest((("Service visit", ("Work performed", "Invoice total"),
                                             ((ACTION, 4600),)),))
    initial = extract(content)
    edited = replace(initial, text=manual)
    corrected = replace(content, source=correct_source_details(
        content.source, profile, date(2026, 11, 7), profile.facilities[0].key))
    assert corrected.source.fingerprint != content.source.fingerprint
    assert extract(content, edited) == edited
    assert extract(corrected, edited) == edited
    unchanged_source(profile, content, raw, filename)


def test_existing_manual_price_text_and_saved_history_are_not_silently_rewritten():
    profile, content, raw, filename = ingest((("Service visit", ("Work performed", "Invoice total"),
                                             ((ACTION, 4600),)),))
    old = ResolvedBlock("activity_summary", "This month", text="Earlier operator note: invoice total 9900.")
    historical = ReportDraft(profile, PERIOD, "Synthetic operator",
        tuple(section for section in default_sections() if section.key == "activity"), (old,))
    saved = library.save_snapshot(historical, expected_revision=0, entered_editor="Synthetic operator")
    current = report(profile, content, old)
    assert current.blocks[0].text.startswith(old.text)
    assert ACTION in current.blocks[0].text and "4600" not in current.blocks[0].text
    assert library.load_snapshot(profile.contract, profile.key, PERIOD) == saved
    assert library.load_snapshot_version(profile.contract, profile.key, PERIOD, 1) == saved
    with pytest.raises(ValueError, match="(?i)price|pricing|amount"):
        assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    unchanged_source(profile, content, raw, filename)


def test_changed_bytes_under_one_filename_add_new_work_without_replaying_old_rows():
    profile, first, original, filename = ingest((("Visit", ("Technician notes", "Invoice total"),
                                                ((ACTION, 4600),)),))
    _, second, revised, _ = ingest((("Visit", ("Technician notes", "Invoice total"),
                                     (("Replaced drive belts on P-TEST-99.", 8800),)),), filename=filename)
    assert first.source.id != second.source.id
    current = extract(second, extract(first))
    assert current.text.count(ACTION) == 1
    assert current.text.count("Replaced drive belts on P-TEST-99.") == 1
    assert "4600" not in current.text and "8800" not in current.text
    assert set(current.references) == {sources.source_reference(first.source, 1), sources.source_reference(second.source, 1)}
    unchanged_source(profile, first, original, filename)
    unchanged_source(profile, second, revised, filename)


def native_word(draft, tmp_path):
    document = Document()
    document.add_paragraph(draft.profile.facilities[0].title)
    document.add_paragraph("November 2026")
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Old activity placeholder.")
    path = tmp_path / "synthetic-activity-design.docx"
    document.save(path)
    original = path.read_bytes()
    raw = build_native_docx(draft, path, section_key="activity")
    assert path.read_bytes() == original
    return raw


def output_fixture():
    profile, content, raw, filename = ingest((("Service visit",
        ("Work performed", "Flow rate (gpm)", "Invoice total"), ((ACTION, 1200, 4600),)),))
    return profile, content, raw, filename, report(profile, content)


def test_actual_compatibility_and_native_word_keep_readings_and_exclude_amounts(tmp_path):
    profile, content, original, filename, draft = output_fixture()
    for raw in (assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint), native_word(draft, tmp_path)):
        assert_word_values(raw)
    unchanged_source(profile, content, original, filename)


def test_actual_guided_upload_edit_save_history_reopen_and_clear_preserve_work(tmp_path, monkeypatch):
    from tests.test_monthly_report_activity_intake_commit import APP, setup_app, activity, draft, editor

    app, profile = setup_app(monkeypatch, tmp_path / "guided")
    manual = "Operator confirmed existing valve noise."
    editor(app).set_value(manual).run()
    next(widget for widget in app.text_input if widget.label == "Prepared by").set_value("Synthetic Reviewer").run()
    next(button for button in app.button if button.label == "Save shared version").click().run()
    assert not app.exception
    period = draft(app).period
    first = library.load_snapshot(profile.contract, profile.key, period)
    assert first.revision == 1
    original = spreadsheet((("Service visit", ("Work performed", "Flow rate (gpm)", "Invoice total"),
                             ((ACTION, 1200, 4600),)),))
    native_uploader = st.file_uploader

    def uploaded(label, *args, **kwargs):
        emitted = native_uploader(label, *args, **kwargs)
        if label == "Add source files":
            stream = BytesIO(original)
            stream.name = "synthetic-maintenance report.xlsx"
            return [stream]
        return emitted

    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    next(widget for widget in app.selectbox if widget.label == "Source facility").select(profile.facilities[0].key)
    next(button for button in app.button if button.label == "Use these source details").click().run()
    assert not app.exception and not app.error
    assert len(app.get("file_uploader")) >= 1
    current = draft(app)
    assert activity(app).text.startswith(manual)
    assert ACTION in activity(app).text and "1200" in activity(app).text
    assert "4600" not in activity(app).text
    assert editor(app).value == activity(app).text
    assert_word_values(assemble_docx(current, acknowledged_fingerprint=current.fingerprint))
    source = current.sources[0]
    assert "4600" in "\n".join(source.page_texts)
    assert sources.source_bytes(profile, source) == original
    corrected = manual + "\n\nOperator verified pump P-TEST-42; replacement remains pending."
    editor(app).set_value(corrected).run()
    next(button for button in app.button if button.label == "Save shared version").click().run()
    second = library.load_snapshot(profile.contract, profile.key, period)
    assert second.revision == 2
    assert next(block.text for block in second.draft.blocks if block.key == "activity_summary") == corrected
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == first
    monkeypatch.setattr(st, "file_uploader", native_uploader)
    app.run()
    assert not app.exception and activity(app).text == corrected
    reopened = AppTest.from_string(APP, default_timeout=45).run()
    assert not reopened.exception and editor(reopened).value == corrected
    monkeypatch.setattr(st, "file_uploader", uploaded)
    reopened.run()
    assert not reopened.exception and activity(reopened).text == corrected
    next(button for button in reopened.button if button.label == "Clear Activity for this report").click().run()
    reopened.run()
    assert not reopened.exception and not activity(reopened).text
    next(button for button in reopened.button if button.label == "Save shared version").click().run()
    third = library.load_snapshot(profile.contract, profile.key, period)
    assert third.revision == 3
    assert not next(block.text for block in third.draft.blocks if block.key == "activity_summary")
    assert library.load_snapshot_version(profile.contract, profile.key, period, 1) == first
    assert library.load_snapshot_version(profile.contract, profile.key, period, 2) == second
    assert sources.source_bytes(profile, source) == original


@requires_libreoffice
def test_real_native_pdf_keeps_technical_values_without_invoice_amounts(tmp_path, monkeypatch):
    import fitz
    from app import pdf_converter

    profile, content, original, filename, draft = output_fixture()
    assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    raw = native_word(draft, tmp_path)
    assert_word_values(raw)
    path = tmp_path / "synthetic-activity-output.docx"
    path.write_bytes(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    pdf = pdf_converter.convert_to_pdf(path).read_bytes()
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert ACTION in text and "1200" in text
    assert "4600" not in text and "Invoice total" not in text
    unchanged_source(profile, content, original, filename)
    artifacts = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "spreadsheet-activity-prices"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "synthetic-source.xlsx").write_bytes(original)
    (artifacts / "activity.docx").write_bytes(raw)
    (artifacts / "activity.pdf").write_bytes(pdf)
    (artifacts / "manifest.json").write_text(json.dumps({
        "synthetic_only": True, "commit": os.environ.get("MSAPO_SHA", ""),
        "source_sha256": sha256(original).hexdigest(), "docx_sha256": sha256(raw).hexdigest(),
        "pdf_sha256": sha256(pdf).hexdigest(), "source_unchanged": True,
        "technical_value_retained": "1200" in text, "invoice_amount_absent": "4600" not in text,
        "model_calls": 0,
    }, indent=2))
