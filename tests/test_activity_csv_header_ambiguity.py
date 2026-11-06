"""Competing CSV Activity fields cannot silently authorize one source value."""
import csv
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO, StringIO

from docx import Document
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock,
    SectionSpec, synthetic_profiles,
)
from app.monthly_report_native_layout import _build_native_docx, build_native_docx


COLUMNS = ("Work performed", "Vendor", "Event date", "Status")
ROW = ("Repaired pump P-1.", "Synthetic Vendor", "2026-09-12", "Completed")
CONFLICTS = ((0, "Actions", "Did not repair pump P-1."),
             (1, "Contractor", "Different Vendor"),
             (2, "Service date", "2026-08-12"),
             (3, "Completion status", "Cancelled"))
PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)


def csv_bytes(columns=COLUMNS, row=ROW):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerows((columns, row))
    return stream.getvalue().encode()


def parsed(columns=COLUMNS, row=ROW):
    raw = csv_bytes(columns, row)
    digest = sha256(raw).hexdigest()
    tables = sources._spreadsheet(raw, ".csv")
    pages = tuple("\n".join("\t".join(values) for values in (table.columns, *table.rows))
                  for table in tables)
    source = ReportSource(digest, "synthetic-activity.csv", digest, ".csv",
                          page_texts=pages, selected_pages=(1,))
    return sources.SourceContent(sources.suggest_facts(source, PROFILE), tables)


def reader_item(content, text=ROW[0]):
    return {"source": content.source.id, "page": 1, "text": text, "row": []}


def draft_for(block, contents):
    section = SectionSpec("activity", "2", "Monthly Activity Summary",
                          (BlockSpec("activity_summary", "rich_text"),))
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor", (section,), (block,),
                       sources=tuple(content.source for content in contents), synthetic=True)


def template(tmp_path):
    document = Document()
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Prior activity placeholder")
    path = tmp_path / "synthetic-activity.docx"
    document.save(path)
    return path


@pytest.mark.parametrize("index, alias, conflict", CONFLICTS)
@pytest.mark.parametrize("duplicate", [True, False], ids=["adapter_suffix", "supported_alias"])
def test_competing_supported_fields_require_mapping_without_losing_cells(index, alias, conflict, duplicate):
    heading = COLUMNS[index] if duplicate else alias
    content = parsed((*COLUMNS, heading), (*ROW, conflict))
    original = asdict(content)
    assert content.tables[0].columns[-1] == heading + (" (2)" if duplicate else "")
    assert structured._csv_activity_entries(content) == ()  # None would trigger generic fallback.
    block = structured.native_update((content,), "activity_summary")
    assert not block.text and not block.references
    assert structured.reader_sources((content,), "activity_summary") == ()
    assert any("column" in notice.casefold() for notice in structured.reader_notices((content,), "activity_summary"))
    with pytest.raises(ValueError, match="column"):
        structured.reader_update((content,), "activity_summary", {"items": [reader_item(content)]})
    assert asdict(content) == original


@pytest.mark.parametrize("heading", ["Status (2)", "Status (10)", "Status (2) (2)", "Work performed (2)"])
def test_literal_adapter_shaped_heading_stays_unresolved(heading):
    index = 0 if heading.startswith("Work") else 3
    columns = tuple(heading if n == index else value for n, value in enumerate(COLUMNS))
    content = parsed(columns)
    assert structured._csv_activity_entries(content) == ()
    assert not structured.native_update((content,), "activity_summary").text
    assert content.tables[0].columns == columns and content.tables[0].rows == (ROW,)


@pytest.mark.parametrize("heading", ["Status Notes (2)", "Status (1)", "Status(2)", "Status (02)", "Status 2"])
def test_unknown_and_non_adapter_headings_keep_existing_mapping(heading):
    content = parsed((*COLUMNS, heading), (*ROW, "Unknown source detail"))
    block = structured.native_update((content,), "activity_summary")
    assert block.text == "2026-09-12 · Synthetic Vendor — Repaired pump P-1. (Status: Completed)"
    assert not structured.reader_notices((content,), "activity_summary")
    assert content.tables[0].rows[0][-1] == "Unknown source detail"


@pytest.mark.parametrize("columns, row, expected", [
    (("Work performed",), (ROW[0],), ROW[0]),
    (("Work performed", "Vendor"), ROW[:2], "Synthetic Vendor — " + ROW[0]),
    (("Work performed", "Event date"), (ROW[0], "09/10/2026"), ROW[0]),
    (("Work performed", "Status"), (ROW[0], "Open"), ROW[0] + " (Status: Open)"),
])
def test_missing_optional_fields_and_ambiguous_date_values_keep_current_behavior(columns, row, expected):
    content = parsed(columns, row)
    assert structured.native_update((content,), "activity_summary").text == expected
    assert structured.reader_sources((content,), "activity_summary") == (content,)


def test_generic_unknown_schema_keeps_its_existing_route():
    content = parsed(("Notes", "Status", "Status"), (ROW[0], "Completed", "Cancelled"))
    assert structured._csv_activity_entries(content) is None
    assert structured.reader_sources((content,), "activity_summary") == (content,)


def test_ambiguous_action_never_uses_generic_price_contact_fallback(monkeypatch):
    content = parsed((*COLUMNS, "Actions", "Price", "Contact"),
                     (*ROW, "Did not repair pump P-1.", "5600", "person@example.invalid"))
    calls = []
    monkeypatch.setattr(structured, "_activity_lines", lambda *args, **kwargs: calls.append(args) or ())
    block = structured.native_update((content,), "activity_summary")
    assert not calls and not block.text and not block.references
    assert content.tables[0].rows[0][-2:] == ("5600", "person@example.invalid")


def test_safe_sibling_survives_native_and_old_mixed_reader_results():
    bad = parsed((*COLUMNS, "Status"), (*ROW, "Cancelled"))
    safe = parsed(("Work performed",), ("Inspected separate fan F-2.",))
    block = structured.native_update((bad, safe), "activity_summary")
    assert block.text == "Inspected separate fan F-2."
    assert block.references == (sources.source_reference(safe.source, 1),)
    assert structured.reader_sources((bad, safe), "activity_summary") == (safe,)
    result, pages = structured.reader_update((bad, safe), "activity_summary",
        {"items": [reader_item(bad), reader_item(safe, "Inspected separate fan F-2.")]})
    assert result.text == "Inspected separate fan F-2." and not pages
    assert result.references == block.references


@pytest.mark.parametrize("text", ["Deliberately edited Activity wording.", ""])
def test_existing_manual_text_and_source_deletions_are_not_rewritten(text):
    content = parsed((*COLUMNS, "Status"), (*ROW, "Cancelled"))
    reference = sources.source_reference(content.source, 1)
    existing = ResolvedBlock("activity_summary", "This month", text=text, references=(reference,))
    result = structured.native_update((content,), "activity_summary", existing)
    assert result == existing
    assert structured.reader_sources((content,), "proposals") == (content,)


@pytest.mark.parametrize("heading, value, reason", [("Site", "Other Site", "site-specific"),
                                                   ("Work Order", "WO-1", "work-order")])
def test_existing_site_and_workorder_routes_remain_authoritative(heading, value, reason):
    content = parsed((*COLUMNS, "Status", heading), (*ROW, "Cancelled", value))
    assert not structured.native_update((content,), "activity_summary").text
    assert reason in structured.reader_notices((content,), "activity_summary")[0]


def test_actual_native_word_preserves_manual_and_safe_sibling_only(tmp_path):
    bad = parsed((*COLUMNS, "Status"), (*ROW, "Cancelled"))
    safe = parsed(("Work performed",), ("Inspected separate fan F-2.",))
    manual = ResolvedBlock("activity_summary", "This month", text="Retained manual observation.")
    result = structured.native_update((bad, safe), "activity_summary", manual)
    path = template(tmp_path)
    original = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(draft_for(result, (bad, safe)), path, section_key="activity")))
    text = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert "Retained manual observation." in text and "Inspected separate fan F-2." in text
    assert "Repaired pump P-1." not in text and "Completed" not in text
    assert path.read_bytes() == original


def test_public_storage_reopen_preserves_original_history_and_word(monkeypatch, tmp_path):
    """Enabled real storage/public native Word case, requiring Linux fcntl."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = csv_bytes((*COLUMNS, "Status"), (*ROW, "Cancelled"))
    content, _ = sources.ingest(PROFILE, "synthetic-activity.csv", raw)
    manual = ResolvedBlock("activity_summary", "This month", text="Retained manual observation.")
    saved = library.save_snapshot(draft_for(manual, (content,)), expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    result = structured.native_update((content,), "activity_summary", reopened.blocks[0])
    assert result == manual
    next_draft = replace(reopened, blocks=(result,))
    library.save_snapshot(next_draft, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert sources.source_bytes(PROFILE, content.source) == raw
    output = Document(BytesIO(build_native_docx(next_draft, template(tmp_path), section_key="activity")))
    text = "\n".join(paragraph.text for paragraph in output.paragraphs)
    assert "Retained manual observation." in text and ROW[0] not in text


def test_public_storage_guided_upload_shows_mapping_notice_and_keeps_safe_work(monkeypatch, tmp_path):
    """Normal guided renderer, real persistence, native upload-message seam."""
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor

    app, profile = setup_app(monkeypatch, tmp_path / "guided")
    manual = "Operator retained existing valve noise."
    editor(app).set_value(manual).run()
    bad_raw = csv_bytes((*COLUMNS, "Status"), (*ROW, "Cancelled"))
    safe_raw = csv_bytes(("Work performed",), ("Inspected separate fan F-2.",))
    original_uploader = st.file_uploader
    original_routes = structured.reader_sources
    routed = []

    def uploaded(label, *args, **kwargs):
        native = original_uploader(label, *args, **kwargs)
        if label != "Add source files":
            return native
        streams = []
        for filename, raw in (("ambiguous-maintenance report.csv", bad_raw),
                              ("safe-maintenance report.csv", safe_raw)):
            stream = BytesIO(raw)
            stream.name = filename
            streams.append(stream)
        return streams

    def observe_routes(contents, destination):
        selected = original_routes(contents, destination)
        if destination == "activity_summary":
            routed.append(tuple(content.source.id for content in selected))
        return selected

    monkeypatch.setattr(st, "file_uploader", uploaded)
    monkeypatch.setattr(structured, "reader_sources", observe_routes)
    app.run()
    assert not app.exception
    assert len(app.get("file_uploader")) >= 1
    assert any("ambiguous Activity CSV columns" in notice.value for notice in app.warning)
    assert activity(app).text == manual + "\n\nInspected separate fan F-2."
    assert editor(app).value == activity(app).text
    assert (sha256(safe_raw).hexdigest(),) in routed
    assert all(sha256(bad_raw).hexdigest() not in ids for ids in routed)
    # setup_app rejects any automatic paid read; original bytes remain usable.
    current = draft(app)
    assert len(current.sources) == 2
    for source in current.sources:
        assert sources.source_bytes(profile, source) == (bad_raw if source.id == sha256(bad_raw).hexdigest() else safe_raw)
