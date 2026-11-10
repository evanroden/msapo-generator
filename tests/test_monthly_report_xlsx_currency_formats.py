"""Retain a workbook's monetary evidence without formatting or revising reports.

All workbooks and source caches here are synthetic. Public ingestion is the
contract: retain the stored number and a currency marker, not Excel's rounded
display. Widget tests use AppTest's upload transport; PDF uses the hosted gate.
"""
from dataclasses import asdict, replace
from datetime import date, time
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles.numbers import BUILTIN_FORMATS
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_content_policy import contains_price, page_allowed, page_fingerprint
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_recovery import restore_sources
from tests.conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 11)
FINANCIAL_ACTION = "Inspected pump P-TEST-42."
TECHNICAL_ACTION = "Tested valve V-TEST-43 at 128 psi."
MANUAL = "Operator confirmed existing valve noise."
FILENAME = "synthetic-maintenance report.xlsx"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from app import monthly_report_ai as ai

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))

    def forbidden(*args, **kwargs):
        pytest.fail("Synthetic workbook ingestion must not call an external model")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)


def workbook_bytes(value=4600, number_format='$#,##0.00', *, technical_sheet=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "First visit"
    sheet.append(("Work performed", "Recorded value"))
    sheet.append((FINANCIAL_ACTION, value))
    sheet["B2"].number_format = number_format
    if technical_sheet:
        sheet = workbook.create_sheet("Technical readings")
        sheet.append(("Work performed", "Recorded value"))
        sheet.append((TECHNICAL_ACTION, 1200))
        sheet["B2"].number_format = '0.00" gpm"'
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def ingest(raw, filename=FILENAME):
    profile = synthetic_profiles()[0]
    content, attachments = sources.ingest(profile, filename, raw)
    assert not attachments
    assert content.source.sha256 == sha256(raw).hexdigest()
    assert sources.source_bytes(profile, content.source) == raw
    return profile, content


def monetary_cell(content, marker, stored):
    value = content.tables[0].rows[0][1]
    assert marker in value, "The original currency evidence must survive public XLSX ingestion"
    assert stored in value, "Currency evidence must not round or replace the stored numeric value"
    assert contains_price(value), "Existing report price gates must recognize the retained marker"
    assert value in content.source.page_texts[0]
    return value


@pytest.mark.parametrize("value,number_format,marker", [
    (1200.375, '$#,##0.00', "$"),
    (1200, '"$"#,##0', "$"),
    (-1200.375, r'\$#,##0.00', "$"),
    (1200, '[$$-409]#,##0.00', "$"),
    (1200, '[$€-407]#,##0.00', "€"),
    (1200, '[$USD-409]#,##0.00', "USD"),
    (1200, '[$GBP-809]#,##0.00', "GBP"),
    (1200, '"USD" #,##0.00', "USD"),
    (1200.375, '0.00" EUR"', "EUR"),
    (1200, '£0.00', "£"),
    (1200, BUILTIN_FORMATS[5], "$"),
    (-1200, BUILTIN_FORMATS[8], "$"),
    (-1200.375, BUILTIN_FORMATS[42], "$"),
    (0, BUILTIN_FORMATS[42], "$"),
    (1200, '_("$"* #,##0.00_);_("$"* \\(#,##0.00\\);_("$"* "-"??_);_(@_)', "$"),
    (-1200, '0;"USD"0', "USD"),
    (0, '"USD"0;0', "USD"),
    (0, '0;0;"EUR"0', "EUR"),
    (1200, '"USD;"0;0', "USD"),
    (1200.123456789, '"USD;"0.00;0', "USD"),
    (-1200.125, '0"days;";"USD"0', "USD"),
    (1200, r'"USD"\;0;0', "USD"),
    (1200, '"USD @"0', "USD"),
    (1200, r'\@"USD"0', "USD"),
    (1200, "0*$", "$"),
    (1000, '[>=1000]"USD"0;0', "USD"),
    (1001, '[>1000]"USD"0;0', "USD"),
    (-1, '[<0]"USD"0;0', "USD"),
    (0, '[<=0]"USD"0;0', "USD"),
    (0, '[=0]"USD"0;0', "USD"),
    (1, '[<>0]"USD"0;0', "USD"),
    (-7, '[>=1000]"USD"0;[<0]"EUR"0;0', "EUR"),
])
def test_public_ingest_retains_only_active_currency_marker_and_stored_number(value, number_format, marker):
    raw = workbook_bytes(value, number_format)
    profile, content = ingest(raw)
    monetary_cell(content, marker, str(value))
    assert content.tables[0].columns == ("Work performed", "Recorded value")
    assert content.tables[0].rows[0][0] == FINANCIAL_ACTION
    cached, attachments = sources.ingest(profile, FILENAME, raw)
    assert not attachments and cached == content
    assert sources.source_bytes(profile, content.source) == raw


@pytest.mark.parametrize("value", [1200.375, -1200.375, 0])
def test_real_builtin_accounting_44_retains_currency_for_every_numeric_sign(value):
    raw = workbook_bytes(value, BUILTIN_FORMATS[44])
    namespace = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(raw)) as archive:
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        cell = next(node for node in sheet.findall(".//s:c", namespace) if node.get("r") == "B2")
        styles = ElementTree.fromstring(archive.read("xl/styles.xml"))
        style = styles.find("s:cellXfs", namespace)[int(cell.get("s"))]
        assert style.get("numFmtId") == "44", "Exercise the actual built-in style, not a custom approximation"
    profile, content = ingest(raw)
    monetary_cell(content, "$", str(value))
    assert sources.source_bytes(profile, content.source) == raw


@pytest.mark.parametrize("value,number_format,expected", [
    (1200.375, "General", "1200.375"),
    (1200.375, "0.00", "1200.375"),
    (0.125, "0.0%", "0.125"),
    (1200, "0.00E+00", "1200"),
    (1.25, "# ?/?", "1.25"),
    (42, "000000", "42"),
    (1200, '0.00" gpm"', "1200"),
    (1200, BUILTIN_FORMATS[37], "1200"),
    (-1200, BUILTIN_FORMATS[41], "-1200"),
    (0, BUILTIN_FORMATS[43], "0"),
    (1200, "[$-409]0.00", "1200"),
    (1200, "_$0.00", "1200"),
    (1200, '0;"USD"0', "1200"),
    (-1200, '"USD"0;0', "-1200"),
    (1200, '0;0;"EUR"0', "1200"),
    (0, '"USD"0;"USD"0;0', "0"),
    (1200, '0;0;0;"USD "@', "1200"),
    (-1200, '0.00;"USD "@', "-1200"),
    (1200, '"USD "@', "1200"),
    (1200, '0";units";"USD"0', "1200"),
    (1200.125, '0"days;";"USD"0', "1200.125"),
    (999, '[>=1000]"USD"0;0', "999"),
    (1000, '[>1000]"USD"0;0', "1000"),
    (7, '[>=1000]"USD"0;[<0]"EUR"0;0', "7"),
    ("1200", '"USD"0', "1200"),
    (True, '"USD"0', "Yes"),
    (False, '"USD"0', "No"),
    (None, '"USD"0', ""),
    (date(2026, 11, 4), "yyyy-mm-dd", "2026-11-04"),
    (time(3, 15, 30), "hh:mm:ss", "03:15:30"),
])
def test_nonfinancial_or_inactive_formats_preserve_existing_raw_cell_contract(value, number_format, expected):
    raw = workbook_bytes(value, number_format)
    _, content = ingest(raw)
    assert content.tables[0].rows[0][1] == expected
    assert not contains_price(content.tables[0].rows[0][1])


@pytest.mark.parametrize("number_format", [
    '0;0;[>=1]"USD"0',
    '[>1000]"USD"0;[<0]"EUR"0',
    '0" USD"@',
    '0;0" USD"@',
])
def test_unsupported_financial_condition_layout_requires_review_instead_of_guessing(number_format):
    with pytest.raises(ValueError, match="(?i)(currency|number format|financial).*(format|review|support)|format.*(currency|review|support)"):
        ingest(workbook_bytes(500, number_format))


@pytest.mark.parametrize("value", [1200.125, -1200.125])
def test_mixed_date_and_currency_sections_require_review_without_reversing_date_conversion(value):
    with pytest.raises(ValueError, match="(?i)(currency|number format|financial).*(format|review|support)|format.*(currency|review|support)"):
        ingest(workbook_bytes(value, 'yyyy-mm-dd;"USD"0'))


def formula_bytes(cached, number_format):
    raw = workbook_bytes("=1000+200", number_format)
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(output, "w") as changed:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(data)
                cell = next(node for node in root.iter(namespace + "c") if node.get("r") == "B2")
                value = cell.find(namespace + "v")
                assert value is not None
                value.text = cached
                data = ElementTree.tostring(root, encoding="utf-8")
            changed.writestr(item, data)
    return output.getvalue()


@pytest.mark.parametrize("cached,number_format,marker", [
    ("9876.54321", '"USD"0.00', "USD"),
    ("9876.54321", '0.00" gpm"', None),
    (None, '"USD"0.00', None),
])
def test_formula_uses_only_original_cached_result_and_never_recalculates(cached, number_format, marker):
    raw = formula_bytes(cached, number_format)
    profile, content = ingest(raw)
    if marker:
        monetary_cell(content, marker, cached)
    else:
        assert content.tables[0].rows[0][1] == (cached or "")
    assert any("never executed" in notice for notice in content.source.notices)
    assert sources.source_bytes(profile, content.source) == raw
    original = load_workbook(BytesIO(raw), data_only=False)
    assert original.active["B2"].value == "=1000+200"
    original.close()


def legacy_extraction(profile, content, raw, currency_policy="missing"):
    """Install a structurally valid pre-format-policy extraction, not a report."""
    table = replace(content.tables[0], rows=((FINANCIAL_ACTION, "4600"),))
    old_source = replace(content.source, page_texts=(
        "Work performed\tRecorded value\n" + FINANCIAL_ACTION + "\t4600",),
        actions="", facts=())
    old = replace(content, source=old_source, tables=(table,))
    cache = sources._path(profile, content.source.sha256, ".json")
    payload = {
        "schema": 1, "client_page_policy": 1, "native_action_policy": 1,
        "vendor_passage_policy": 7, **asdict(old),
    }
    if currency_policy != "missing":
        payload["xlsx_currency_policy"] = currency_policy
    library._atomic_write(cache, library._json(payload))
    assert sources.source_bytes(profile, old.source) == raw
    return old, cache


@pytest.mark.parametrize("currency_policy", ["missing", True, "1", 1.0, -1, []])
def test_legacy_xlsx_cache_rebuilds_currency_evidence_without_rewriting_original(currency_policy):
    raw = workbook_bytes()
    profile, content = ingest(raw)
    old, cache = legacy_extraction(profile, content, raw, currency_policy)
    before_cache = cache.read_bytes()
    original = sources._path(profile, content.source.sha256, ".xlsx")
    original_stat = (original.stat().st_mtime_ns, original.stat().st_ino)
    fresh, _ = sources.ingest(profile, "renamed-workbook.xlsx", raw)
    monetary_cell(fresh, "$", "4600")
    assert fresh.source.filename == "renamed-workbook.xlsx"
    assert fresh.source.id == old.source.id
    assert cache.read_bytes() != before_cache
    assert original.read_bytes() == raw
    assert (original.stat().st_mtime_ns, original.stat().st_ino) == original_stat
    stamp = json.loads(cache.read_text())["xlsx_currency_policy"]
    assert type(stamp) is int and stamp == 1
    warm_bytes, warm_mtime = cache.read_bytes(), cache.stat().st_mtime_ns
    warm, _ = sources.ingest(profile, "renamed-again.xlsx", raw)
    assert warm.tables == fresh.tables
    assert warm.source.page_texts == fresh.source.page_texts
    assert warm.source.filename == "renamed-again.xlsx"
    assert cache.read_bytes() == warm_bytes and cache.stat().st_mtime_ns == warm_mtime


@pytest.mark.parametrize("filename,raw", [
    ("synthetic-reading.csv", b"Work performed,Recorded value\nInspected pump.,4600\n"),
    ("synthetic-reading.txt", b"Inspected pump; reading 4600.\n"),
])
def test_healthy_non_xlsx_cache_is_unchanged_by_currency_policy(filename, raw):
    profile, content = ingest(raw, filename)
    cache = sources._path(profile, content.source.sha256, ".json")
    original = sources._path(profile, content.source.sha256, content.source.suffix)
    before = (cache.read_bytes(), cache.stat().st_mtime_ns, original.stat().st_mtime_ns)
    again, attachments = sources.ingest(profile, filename, raw)
    assert not attachments and again == content
    assert (cache.read_bytes(), cache.stat().st_mtime_ns, original.stat().st_mtime_ns) == before


def test_cache_upgrade_does_not_rewrite_pinned_saved_evidence_reviews_or_manual_history():
    raw = workbook_bytes()
    profile, content = ingest(raw)
    old, cache = legacy_extraction(profile, content, raw)
    captioned = replace(old.source, captions=((1, "Operator's prior caption"),))
    saved_source = replace(captioned, client_page_reviews=((1, page_fingerprint(captioned, 1)),))
    assert page_allowed(saved_source, 1)
    manual = ResolvedBlock("activity_summary", "This month", text="Previously saved manual reading 4600.",
        references=(sources.source_reference(saved_source, 1),))
    report = ReportDraft(profile, PERIOD, "Synthetic operator",
        tuple(section for section in default_sections() if section.key == "activity"),
        (manual,), sources=(saved_source,))
    first = library.save_snapshot(report, expected_revision=0, entered_editor="Synthetic operator")
    before = asdict(first)
    restored, missing = restore_sources(profile, first.draft.sources)
    assert not missing and len(restored) == 1
    assert restored[0].source == saved_source
    assert restored[0].source.fingerprint == saved_source.fingerprint
    assert restored[0].source.page_texts == old.source.page_texts
    assert restored[0].source.client_page_reviews == saved_source.client_page_reviews
    assert page_allowed(restored[0].source, 1)
    assert contains_price(restored[0].tables[0].rows[0][1])
    assert asdict(library.load_snapshot(profile.contract, profile.key, PERIOD)) == before
    assert library.load_snapshot_version(profile.contract, profile.key, PERIOD, 1) == first
    replay, notices = sources.ingest_batch(profile, ((FILENAME, raw),), restored)
    assert replay == restored and any("Duplicate skipped" in item for item in notices)
    assert sources.source_bytes(profile, saved_source) == raw


def report(profile, content, existing=None):
    reviewed = replace(content, source=correct_source_details(
        content.source, profile, None, profile.facilities[0].key))
    before = asdict(reviewed)
    block = structured.native_update((reviewed,), "activity_summary", existing)
    assert asdict(reviewed) == before
    return ReportDraft(profile, PERIOD, "Synthetic operator",
        tuple(section for section in default_sections() if section.key == "activity"),
        (block,), sources=(reviewed.source,))


def output_fixture():
    raw = workbook_bytes(technical_sheet=True)
    profile, content = ingest(raw)
    existing = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    return profile, content, raw, report(profile, content, existing)


def word_text(raw):
    document = Document(BytesIO(raw))
    return "\n".join([paragraph.text for paragraph in document.paragraphs] + [
        cell.text for table in document.tables for row in table.rows for cell in row.cells])


def assert_output_values(text):
    assert MANUAL in text and TECHNICAL_ACTION in text and "1200" in text
    assert "4600" not in text, "An unlabeled currency-formatted amount must not become client Activity"


def native_word(draft, tmp_path):
    document = Document()
    document.add_paragraph(draft.profile.facilities[0].title)
    document.add_paragraph("November 2026")
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Old activity placeholder.")
    path = tmp_path / "synthetic-currency-design.docx"
    document.save(path)
    original = path.read_bytes()
    result = build_native_docx(draft, path, section_key="activity")
    assert path.read_bytes() == original
    return result


def test_new_activity_and_both_word_routes_keep_technical_sheet_but_gate_currency_evidence(tmp_path):
    profile, content, original, draft = output_fixture()
    block = draft.blocks[0]
    for raw in (assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint), native_word(draft, tmp_path)):
        assert_output_values(word_text(raw))
    assert_output_values(block.text)
    assert block.references == (sources.source_reference(draft.sources[0], 2),)
    assert sources.source_bytes(profile, content.source) == original
    monetary_cell(content, "$", "4600")


@pytest.mark.parametrize("manual", ["Operator's corrected reading remains 4600.", ""])
def test_same_source_replay_keeps_deliberate_manual_edit_or_clear(manual):
    profile, content, original, initial = output_fixture()
    edited = replace(initial.blocks[0], text=manual)
    corrected = replace(content, source=correct_source_details(
        content.source, profile, date(2026, 11, 7), profile.facilities[0].key))
    assert structured.native_update((corrected,), "activity_summary", edited) == edited
    assert sources.source_bytes(profile, content.source) == original


def test_actual_guided_upload_edit_save_history_reopen_replay_and_clear(tmp_path, monkeypatch):
    from tests.test_monthly_report_activity_intake_commit import APP, setup_app, activity, draft, editor

    app, profile = setup_app(monkeypatch, tmp_path / "guided")
    editor(app).set_value(MANUAL).run()
    next(widget for widget in app.text_input if widget.label == "Prepared by").set_value("Synthetic Reviewer").run()
    next(button for button in app.button if button.label == "Save shared version").click().run()
    assert not app.exception
    period = draft(app).period
    first = library.load_snapshot(profile.contract, profile.key, period)
    assert first.revision == 1
    original = workbook_bytes(technical_sheet=True)
    native_uploader = st.file_uploader

    def uploaded(label, *args, **kwargs):
        emitted = native_uploader(label, *args, **kwargs)
        if label == "Add source files":
            stream = BytesIO(original)
            stream.name = FILENAME
            return [stream]
        return emitted

    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    next(widget for widget in app.selectbox if widget.label == "Source facility").select(profile.facilities[0].key)
    next(button for button in app.button if button.label == "Use these source details").click().run()
    assert not app.exception and not app.error
    assert len(app.get("file_uploader")) >= 1
    current = draft(app)
    assert_output_values(word_text(assemble_docx(current, acknowledged_fingerprint=current.fingerprint)))
    assert_output_values(activity(app).text)
    assert editor(app).value == activity(app).text
    source = current.sources[0]
    assert contains_price(source.page_texts[0])
    assert "1200" in source.page_texts[1] and not contains_price(source.page_texts[1])
    assert sources.source_bytes(profile, source) == original
    corrected = MANUAL + "\n\nOperator verified valve V-TEST-43; replacement remains pending."
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
def test_real_native_pdf_gates_currency_and_retains_technical_numbers(tmp_path, monkeypatch):
    import pymupdf as fitz
    from app import pdf_converter

    profile, content, original, draft = output_fixture()
    assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    raw = native_word(draft, tmp_path)
    assert_output_values(word_text(raw))
    path = tmp_path / "synthetic-currency-output.docx"
    path.write_bytes(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    pdf = pdf_converter.convert_to_pdf(path).read_bytes()
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert_output_values(text)
    assert sources.source_bytes(profile, content.source) == original
    artifacts = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "xlsx-currency-formats"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "synthetic-source.xlsx").write_bytes(original)
    (artifacts / "activity.docx").write_bytes(raw)
    (artifacts / "activity.pdf").write_bytes(pdf)
    (artifacts / "manifest.json").write_text(json.dumps({
        "synthetic_only": True, "commit": os.environ.get("MSAPO_SHA", ""),
        "source_sha256": sha256(original).hexdigest(), "docx_sha256": sha256(raw).hexdigest(),
        "pdf_sha256": sha256(pdf).hexdigest(), "source_unchanged": True,
        "technical_value_retained": "1200" in text, "currency_amount_absent": "4600" not in text,
        "model_calls": 0,
    }, indent=2))
