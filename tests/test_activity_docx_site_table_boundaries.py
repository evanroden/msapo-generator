"""DOCX site tables require mapping; other items and saved work stay intact.

Portable ingest supplies only a real temporary path and atomic writer. Actual
public-storage/cache/history/guided/Word tests remain enabled for Linux.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_recovery import restore_sources

PROFILE, PERIOD = synthetic_profiles()[0], ReportPeriod(2026, 9)
LOCAL = "Inspected target pump P-1."
FOREIGN = "Repaired foreign pump F-9."
SAFE = "Calibrated independent panel S-4."
MANUAL = "Operator retained previously verified wording."


def original(heading="Site", *, rows=None, narrative=SAFE, header_only=False,
             site_last=False, action_heading="Work performed"):
    doc = Document()
    doc.add_paragraph("Service report\nService date: 2026-09-04")
    if narrative:
        doc.add_paragraph(narrative)
    table = doc.add_table(rows=1, cols=2)
    headings = (action_heading, heading) if site_last else (heading, action_heading)
    for cell, value in zip(table.rows[0].cells, headings):
        cell.text = value
    if not header_only:
        values = rows if rows is not None else ((PROFILE.facilities[0].title, LOCAL), ("Foreign South", FOREIGN))
        for values in values:
            if site_last:
                values = values[::-1]
            for cell, value in zip(table.add_row().cells, values):
                cell.text = value
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.fixture
def ingest(monkeypatch, tmp_path):
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
    monkeypatch.setattr(sources, "_path", lambda profile, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", write)
    def read(**kwargs):
        raw = original(**kwargs)
        content, attachments = sources.ingest(PROFILE, "synthetic-maintenance report.docx", raw)
        assert not attachments and sources.source_bytes(PROFILE, content.source) == raw
        assert content.tables == ()  # Do not invent a new cached source schema.
        return content, raw
    return read


def draft_for(block, contents):
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor",
        (SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),)),),
        (block,), sources=tuple(c.source for c in contents), synthetic=True)


def template(tmp_path):
    path = tmp_path / "synthetic-template.docx"
    doc = Document()
    doc.add_heading("2 Monthly Activity Summary", 1)
    doc.add_paragraph("Placeholder")
    doc.save(path)
    return path


def content(text, *, suffix=".docx", identity="a"):
    digest = identity * 64
    return sources.SourceContent(ReportSource(digest, "synthetic" + suffix, digest, suffix,
        page_texts=(text,), selected_pages=(1,), facility="north", service_date="2026-09-04"))


@pytest.mark.parametrize("heading", ["Site", "Facility", "Building", "Location", "Client", "Customer", "Hospital", "Facility Name", "SiteID"])
def test_actual_docx_table_is_held_while_same_file_narrative_keeps_item_reference(ingest, heading):
    item, raw = ingest(heading=heading)
    before = asdict(item)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and FOREIGN not in result.text and LOCAL not in result.text
    assert result.references == (sources.source_reference(item.source, 2),)
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]
    assert structured.reader_sources((item,), "activity_summary") == ()
    assert structured.reader_batches(PROFILE, (item,), "activity_summary") == ()
    assert asdict(item) == before and sources.source_bytes(PROFILE, item.source) == raw


@pytest.mark.parametrize("heading", ["Asset", "Technician", "Site inspection notes", "Location observations"])
def test_ordinary_non_site_table_headings_retain_native_behavior(ingest, heading):
    item, _ = ingest(heading=heading)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and LOCAL in result.text and FOREIGN in result.text
    assert not structured.reader_notices((item,), "activity_summary")


@pytest.mark.parametrize("text", [
    "Inspected site controls.\tVerified local operation.",
    "Site\tWork performed",  # No data row establishes a source table.
    "\n\t\n", "", "Site inspection\tWork performed\nNorth\t" + LOCAL,
    "Inspected local control panel.\nSite\t" + LOCAL,
])
def test_tabbed_prose_header_only_and_blank_items_do_not_create_new_reader_hold(text):
    item = content(text)
    assert not structured.reader_notices((item,), "activity_summary")
    assert structured.reader_sources((item,), "activity_summary") == (item,)


@pytest.mark.parametrize("rows", [
    (("Foreign South", FOREIGN),),
    (("Foreign\nSouth", FOREIGN),),
    (("Foreign South", FOREIGN + "\nThe fan did not start."),),
    (("", FOREIGN),),
    (("Foreign South", ""), ("Foreign South", FOREIGN)),
])
def test_real_blank_and_multiline_word_cells_cannot_bypass_site_header(ingest, rows):
    item, _ = ingest(rows=rows)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and FOREIGN not in result.text
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]


def test_real_source_details_do_not_authorize_individual_foreign_rows_and_word(ingest, tmp_path):
    item, raw = ingest()
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state['source'] = render_source_details(st.session_state['source'], st.session_state['profile'], 'docx-tables', field)
''')
    app.session_state["source"], app.session_state["profile"] = item.source, PROFILE
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    next(w for w in app.button if w.label == "Use these source details").click().run()
    assert not app.exception
    item = replace(item, source=app.session_state["source"])
    assert item.source.facility == "north"
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    result = structured.native_update((item,), "activity_summary", manual)
    doc = Document(BytesIO(_build_native_docx(draft_for(result, (item,)), template(tmp_path), section_key="activity")))
    output = "\n".join(p.text for p in doc.paragraphs)
    assert MANUAL in output and SAFE in output and FOREIGN not in output and LOCAL not in output
    assert sources.source_bytes(PROFILE, item.source) == raw


@pytest.mark.parametrize("manual", [MANUAL, ""])
def test_existing_source_references_preserve_manual_work_and_deliberate_deletions(ingest, manual):
    item, raw = ingest()
    previous = ResolvedBlock("activity_summary", "This month", text=manual,
        references=tuple(sources.source_reference(item.source, n) for n in range(1, len(item.source.page_texts) + 1)))
    assert structured.native_update((item,), "activity_summary", previous) == previous
    assert sources.source_bytes(PROFILE, item.source) == raw


def test_reader_rejects_old_table_result_without_discarding_safe_sibling_or_manual(ingest):
    item, _ = ingest()
    sibling = content("Inspected separate pump Z-1.", identity="b")
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    value = {"items": [
        {"source": item.source.id, "page": 3, "text": FOREIGN, "row": []},
        {"source": sibling.source.id, "page": 1, "text": sibling.source.page_texts[0], "row": []},
    ]}
    result, pages = structured.reader_update((item, sibling), "activity_summary", value, manual)
    assert result.text == MANUAL + "\n\n" + sibling.source.page_texts[0]
    assert result.references == (sources.source_reference(sibling.source, 1),) and not pages
    with pytest.raises(ValueError, match="site-specific"):
        structured.reader_update((item,), "activity_summary", {"items": value["items"][:1]}, manual)
    payload = structured.reader_batches(PROFILE, (item, sibling), "activity_summary")
    assert item.source.id not in str(payload) and sibling.source.id in str(payload)


def test_counted_work_order_notice_keeps_its_existing_precedence(monkeypatch, ingest):
    item, _ = ingest()
    from app import monthly_report_work_order_csv as work_orders
    # Route precedence only: no claim that this seam normalizes DOCX work orders.
    monkeypatch.setattr(work_orders, "is_work_order_source", lambda value: True)
    notice = structured.reader_notices((item,), "activity_summary")[0]
    assert "Review counted work-order rows" in notice and "site-specific" not in notice


@pytest.mark.parametrize("selected", [(), (2,), (3,), (999,), (0,), ("invalid",)])
def test_client_page_selection_is_not_reinterpreted_as_narrative_reader_selection(ingest, selected):
    item, _ = ingest()
    item = replace(item, source=replace(item.source, selected_pages=selected))
    before = asdict(item)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and FOREIGN not in result.text
    assert result.references == (sources.source_reference(item.source, 2),)
    assert structured.reader_sources((item,), "activity_summary") == ()
    assert asdict(item) == before  # No selection mutation or invented scope.


def test_affected_file_reader_hold_remains_whole_file_even_for_safe_subset(ingest):
    item, _ = ingest()
    payload = structured.reader_request(PROFILE, (item,), "activity_summary", ((item.source.id, 2),))
    assert item.source.id not in str(payload) and SAFE not in str(payload)


def test_unaffected_reader_page_subset_keeps_original_numbers_and_existing_invalid_ref_behavior():
    item = content(LOCAL)
    item = replace(item, source=replace(item.source, page_texts=(LOCAL, SAFE), selected_pages=()))
    before = asdict(item)
    payload = structured.reader_request(PROFILE, (item,), "activity_summary", ((item.source.id, 2), (item.source.id, 999)))
    text = str(payload)
    assert SAFE in text and LOCAL not in text and f"SOURCE {item.source.id} PAGE 2" in text
    assert "PAGE 999" not in text and asdict(item) == before


def test_real_header_only_table_does_not_create_a_new_hold(ingest):
    item, _ = ingest(header_only=True)
    assert not structured.reader_notices((item,), "activity_summary")
    assert SAFE in structured.native_update((item,), "activity_summary").text


@pytest.mark.parametrize("heading", ["Site\nName", "Facility\nName", "Location\nCode"])
@pytest.mark.parametrize("site_last", [False, True])
def test_multiline_site_identity_heading_in_either_physical_column_is_held(ingest, heading, site_last, tmp_path):
    item, raw = ingest(heading=heading, site_last=site_last)
    before = asdict(item)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and FOREIGN not in result.text and LOCAL not in result.text
    assert result.references == (sources.source_reference(item.source, 2),)
    assert structured.reader_sources((item,), "activity_summary") == ()
    output = Document(BytesIO(_build_native_docx(draft_for(result, (item,)), template(tmp_path), section_key="activity")))
    assert FOREIGN not in "\n".join(p.text for p in output.paragraphs)
    assert asdict(item) == before and sources.source_bytes(PROFILE, item.source) == raw


@pytest.mark.parametrize("site_last", [False, True])
@pytest.mark.parametrize("heading", ["Site", "Site\nName"])
def test_line_break_in_neighboring_work_heading_does_not_hide_site_table(ingest, site_last, heading):
    item, _ = ingest(heading=heading, action_heading="Work\nperformed", site_last=site_last)
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and FOREIGN not in result.text
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]


def test_multiline_header_only_and_unrelated_tabbed_prose_still_do_not_establish_table(ingest):
    item, _ = ingest(heading="Site\nName", header_only=True)
    assert not structured.reader_notices((item,), "activity_summary")
    for text in ("Inspected site\ncontrols\tVerified local operation.\nCompleted synthetic inspection.",
                 "Site inspection\nnotes\tWork performed\nNorth\t" + LOCAL):
        ordinary = content(text)
        assert not structured.reader_notices((ordinary,), "activity_summary")


@pytest.mark.parametrize("suffix,heading,identity,work", [
    (".txt", "Site inspection notes", "Pump P-1", LOCAL),
    (".pdf", "Site", "Foreign South", FOREIGN),
    (".eml", "Site", "Foreign South", FOREIGN),
])
def test_other_source_formats_keep_existing_behavior(suffix, heading, identity, work):
    item = content(heading + "\tWork performed\n" + identity + "\t" + work, suffix=suffix)
    assert work in structured.native_update((item,), "activity_summary").text
    assert not structured.reader_notices((item,), "activity_summary")


def test_public_storage_cached_original_history_and_word_preserve_manual_data(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = original()
    item, _ = sources.ingest(PROFILE, "synthetic-maintenance report.docx", raw)
    item = replace(item, source=correct_source_details(item.source, PROFILE, date(2026, 9, 4), "north"))
    original_source = item.source
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    historical = library.save_snapshot(replace(draft_for(manual, (item,)), period=ReportPeriod(2026, 8)), expected_revision=0, entered_editor="Synthetic Editor")
    saved = library.save_snapshot(draft_for(manual, (item,)), expected_revision=0, entered_editor="Synthetic Editor")
    cache = sources._path(PROFILE, item.source.sha256, ".json")
    cache_bytes = cache.read_bytes()
    restored, missing = restore_sources(PROFILE, (original_source,))
    assert not missing and restored[0].source == original_source
    result = structured.native_update(restored, "activity_summary", manual)
    assert SAFE in result.text and FOREIGN not in result.text
    current = replace(saved.draft, blocks=(result,))
    library.save_snapshot(current, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft == current
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, historical.draft.period) == historical
    assert cache.read_bytes() == cache_bytes and sources.source_bytes(PROFILE, original_source) == raw
    output = Document(BytesIO(build_native_docx(current, template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in output.paragraphs)
    assert MANUAL in text and SAFE in text and FOREIGN not in text


def test_public_storage_guided_upload_shows_notice_keeps_native_narrative_and_manual(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor
    from app import monthly_report_ai as ai
    app, profile = setup_app(monkeypatch, tmp_path)
    editor(app).set_value(MANUAL).run()
    raw = original()
    uploader = st.file_uploader
    def uploaded(label, *args, **kwargs):
        native = uploader(label, *args, **kwargs)
        if label != "Add source files":
            return native
        stream = BytesIO(raw)
        stream.name = "synthetic-maintenance report.docx"
        return [stream]
    monkeypatch.setattr(st, "file_uploader", uploaded)
    monkeypatch.setattr(ai, "request_json", lambda *a: pytest.fail("Blocked file must not reach paid reader"))
    app.run()
    assert not app.exception and app.get("file_uploader")
    assert any("site-specific" in w.value for w in app.warning)
    assert MANUAL in activity(app).text and SAFE in activity(app).text and FOREIGN not in activity(app).text
    assert editor(app).value == activity(app).text
    assert sources.source_bytes(profile, draft(app).sources[0]) == raw


def test_three_column_multiline_site_row_is_held_at_ingest_and_activity(ingest):
    doc = Document()
    doc.add_paragraph(SAFE)
    table = doc.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ("Site", "Work performed", "Status")):
        cell.text = value
    for cell, value in zip(table.add_row().cells,
                           ("Foreign South", "Repaired foreign pump\nF-9.", "Complete")):
        cell.text = value
    stream = BytesIO()
    doc.save(stream)
    raw = stream.getvalue()
    item, attachments = sources.ingest(PROFILE, "synthetic-multiline.docx", raw)
    assert not attachments and sources.source_bytes(PROFILE, item.source) == raw
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text
    assert "Repaired foreign pump" not in result.text and "F-9." not in result.text
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]
    assert structured.reader_sources((item,), "activity_summary") == ()


def test_multiline_header_before_site_column_is_held(ingest):
    doc = Document()
    doc.add_paragraph(SAFE)
    table = doc.add_table(rows=1, cols=3)
    for cell, value in zip(table.rows[0].cells, ("Asset", "Work\nperformed", "Site")):
        cell.text = value
    for cell, value in zip(table.add_row().cells,
                           ("P-1", "Repaired foreign pump.", "Foreign South")):
        cell.text = value
    stream = BytesIO()
    doc.save(stream)
    raw = stream.getvalue()
    item, attachments = sources.ingest(PROFILE, "synthetic-multiline-header.docx", raw)
    assert not attachments and sources.source_bytes(PROFILE, item.source) == raw
    result = structured.native_update((item,), "activity_summary")
    assert SAFE in result.text and "Repaired foreign pump" not in result.text
    assert "site-specific" in structured.reader_notices((item,), "activity_summary")[0]
    assert structured.reader_sources((item,), "activity_summary") == ()
