"""Exact compact site identities retain spreadsheet Activity review boundaries."""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import os
from pathlib import Path
import tempfile

from docx import Document
from openpyxl import Workbook
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec, synthetic_profiles
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_details import correct_source_details

PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
TARGET = "Inspected target pump P-1."
FOREIGN = "Repaired foreign pump F-9."
SAFE = "Inspected separate fan F-2 at 1200 rpm."


def spreadsheet(columns, rows, suffix):
    if suffix == ".csv":
        stream = StringIO(newline="")
        csv.writer(stream).writerows((columns, *rows))
        return stream.getvalue().encode()
    book = Workbook()
    book.active.append(columns)
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def parsed(columns, rows, suffix=".csv"):
    raw = spreadsheet(columns, rows, suffix)
    tables = sources._spreadsheet(raw, suffix)
    pages = tuple("\n".join("\t".join(row) for row in (table.columns, *table.rows)) for table in tables)
    digest = sha256(raw).hexdigest()
    source = sources.suggest_facts(ReportSource(digest, "synthetic-maintenance report" + suffix,
        digest, suffix, page_texts=pages, selected_pages=tuple(range(1, len(pages) + 1))), PROFILE)
    return sources.SourceContent(source, tables), raw


def scoped(heading, suffix=".csv"):
    content, raw = parsed(("Work performed", heading), ((TARGET, "north"), (FOREIGN, "foreign")), suffix)
    source = correct_source_details(content.source, PROFILE, date(2026, 9, 4), "north")
    return replace(content, source=source), raw


def draft_for(block, contents):
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor",
        (SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),)),),
        (block,), sources=tuple(c.source for c in contents), synthetic=True)


def template(tmp_path):
    path = tmp_path / "synthetic-design.docx"
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Old activity placeholder.")
    doc.save(path)
    return path


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("heading", ["SiteID", "FacilityName", "LocationKey", "CustomerCode", "ClientName",
                                     "HospitalID", "BuildingCode", "siteid", "FACILITYNAME", "SiteID (2)"])
def test_compact_site_columns_require_review_even_with_explicit_source_scope(suffix, heading):
    content, _ = scoped(heading, suffix)
    original = asdict(content)
    manual = ResolvedBlock("activity_summary", "This month", text="Retained operator observation.")
    assert structured.native_update((content,), "activity_summary", manual) == manual
    assert not structured.reader_sources((content,), "activity_summary")
    assert "site-specific" in structured.reader_notices((content,), "activity_summary")[0]
    assert not structured.reader_batches(PROFILE, (content,), "activity_summary")
    assert structured.reader_sources((content,), "capital_renewal") == (content,)
    assert asdict(content) == original


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("heading", ["Site ID", "Facility Name", "Customer location", "Site_Name"])
def test_existing_separated_site_columns_stay_blocked(suffix, heading):
    content, _ = scoped(heading, suffix)
    assert not structured.native_update((content,), "activity_summary").text
    assert not structured.reader_sources((content,), "activity_summary")


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("heading", ["AssetID", "TechnicianName", "JobLocationNotes", "Website", "OnsiteWork",
                                     "SiteVisits", "LocationNote", "SiteIDValue"])
def test_non_site_camel_words_and_substrings_are_not_newly_blocked(suffix, heading):
    content, _ = scoped(heading, suffix)
    result = structured.native_update((content,), "activity_summary")
    assert TARGET in result.text and FOREIGN in result.text
    assert structured.reader_sources((content,), "activity_summary") == (content,)
    assert not structured.reader_notices((content,), "activity_summary")


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_old_reader_results_and_requests_exclude_only_blocked_source(suffix):
    blocked, _ = scoped("SiteID", suffix)
    safe, _ = parsed(("Work performed",), ((SAFE,),), suffix)
    payload = {"items": [{"source": c.source.id, "page": 1, "text": text, "row": [], "include_page": False}
                         for c, text in ((blocked, FOREIGN), (safe, SAFE))]}
    result, pages = structured.reader_update((blocked, safe), "activity_summary", payload)
    assert result.text == SAFE and not pages
    assert result.references == (sources.source_reference(safe.source, 1),)
    request = str(structured.reader_request(PROFILE, (blocked, safe), "activity_summary"))
    assert blocked.source.id not in request and safe.source.id in request
    with pytest.raises(ValueError, match="site-specific"):
        structured.reader_update((blocked,), "activity_summary", {"items": payload["items"][:1]})


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("manual", ["Operator deliberately corrected this source.", ""])
def test_reviewed_manual_work_and_deliberate_deletion_are_unchanged(suffix, manual):
    content, _ = scoped("FacilityName", suffix)
    existing = ResolvedBlock("activity_summary", "This month", text=manual,
                             references=(sources.source_reference(content.source, 1),))
    corrected = replace(content, source=replace(content.source, vendor="Reviewed Vendor"))
    assert structured.native_update((corrected,), "activity_summary", existing) == existing


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_safe_sibling_keeps_technical_values_and_parent_price_policy_in_native_word(suffix, tmp_path):
    blocked, _ = scoped("LocationKey", suffix)
    safe, _ = parsed(("Technician notes", "Flow rate (gpm)", "Invoice total"), ((SAFE, "1200", "4600"),), suffix)
    original = asdict(safe)
    manual = ResolvedBlock("activity_summary", "This month", text="Operator retained previous work.")
    result = structured.native_update((blocked, safe), "activity_summary", manual)
    assert FOREIGN not in result.text and TARGET not in result.text
    assert SAFE in result.text and "1200" in result.text and "4600" not in result.text
    path = template(tmp_path)
    before = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(draft_for(result, (blocked, safe)), path, section_key="activity")))
    text = "\n".join(p.text for p in output.paragraphs)
    assert manual.text in text and SAFE in text and "1200" in text
    assert FOREIGN not in text and "4600" not in text
    assert path.read_bytes() == before and asdict(safe) == original


def test_recognized_csv_keeps_vendor_date_pending_status_and_price_exclusion():
    content, _ = parsed(("Vendor", "Event date", "Work performed", "Status", "Invoice total"),
        (("Synthetic Mechanical", "2026-09-04", TARGET, "Pending", "4600"),))
    assert structured.native_update((content,), "activity_summary").text == (
        "2026-09-04 · Synthetic Mechanical — " + TARGET + " (Status: Pending)")


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_native_source_detail_controls_do_not_waive_row_site_mapping(suffix):
    content, _ = scoped("FacilityName", suffix)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state['source'] = render_source_details(st.session_state['source'], st.session_state['profile'], 'compact', field)
''')
    app.session_state["source"] = replace(content.source, facility="", scope_review="")
    app.session_state["profile"] = PROFILE
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    next(w for w in app.button if w.label == "Use these source details").click().run()
    assert not app.exception and app.session_state["source"].facility == "north"
    reviewed = replace(content, source=app.session_state["source"])
    assert not structured.native_update((reviewed,), "activity_summary").text
    assert "site-specific" in structured.reader_notices((reviewed,), "activity_summary")[0]


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_actual_ingest_retains_original_bytes_with_portable_writer_seam(suffix, monkeypatch, tmp_path):
    # Actual ingest/parser/suggestions/integrity reads, but not real storage or locks.
    def write(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    monkeypatch.setattr(sources, "_path", lambda profile, digest, ext: tmp_path / (digest + ext))
    monkeypatch.setattr(library, "_atomic_write", write)
    raw = spreadsheet(("Work performed", "SiteID"), ((TARGET, "north"), (FOREIGN, "foreign")), suffix)
    content, attachments = sources.ingest(PROFILE, "synthetic-maintenance report" + suffix, raw)
    assert not attachments and content.source.sha256 == sha256(raw).hexdigest()
    before = asdict(content)
    assert not structured.native_update((content,), "activity_summary").text
    assert asdict(content) == before and sources.source_bytes(PROFILE, content.source) == raw


def test_public_storage_reopen_history_and_word_keep_existing_work(monkeypatch, tmp_path):
    """Enabled unmodified persistence/output path; Linux fcntl required."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = spreadsheet(("Work performed", "SiteID"), ((FOREIGN, "foreign"),), ".csv")
    content, _ = sources.ingest(PROFILE, "synthetic-maintenance report.csv", raw)
    manual = ResolvedBlock("activity_summary", "This month", text="Previous operator observation.")
    saved = library.save_snapshot(draft_for(manual, (content,)), expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    result = structured.native_update((content,), "activity_summary", reopened.blocks[0])
    assert result == manual
    current = replace(reopened, blocks=(result,))
    library.save_snapshot(current, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert sources.source_bytes(PROFILE, content.source) == raw
    text = "\n".join(p.text for p in Document(BytesIO(build_native_docx(current, template(tmp_path), section_key="activity"))).paragraphs)
    assert manual.text in text and FOREIGN not in text


def test_public_storage_guided_upload_notice_keeps_safe_sibling_and_manual(monkeypatch, tmp_path):
    """Normal guided renderer, real storage, native upload-message seam only."""
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor
    app, profile = setup_app(monkeypatch, tmp_path)
    manual = "Operator retained previous work."
    editor(app).set_value(manual).run()
    bad = spreadsheet(("Work performed", "SiteID"), ((FOREIGN, "foreign"),), ".csv")
    safe = spreadsheet(("Work performed",), ((SAFE,),), ".csv")
    original = st.file_uploader
    def uploaded(label, *args, **kwargs):
        native = original(label, *args, **kwargs)
        if label != "Add source files":
            return native
        streams = []
        for filename, raw in (("mixed-maintenance report.csv", bad), ("safe-maintenance report.csv", safe)):
            stream = BytesIO(raw)
            stream.name = filename
            streams.append(stream)
        return streams
    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception and len(app.get("file_uploader")) >= 1
    assert any("site-specific" in w.value for w in app.warning)
    assert activity(app).text == manual + "\n\n" + SAFE
    assert editor(app).value == activity(app).text
    for source in draft(app).sources:
        assert sources.source_bytes(profile, source) == (bad if source.sha256 == sha256(bad).hexdigest() else safe)
