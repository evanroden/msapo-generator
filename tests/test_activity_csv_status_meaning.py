"""A financial status cannot silently turn an incomplete CSV event into work."""
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


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
ACTION = "Replaced pump P-1."
SAFE_ACTION = "Inspected valve V-2."
STATUS = "Not completed; awaiting $500 approval"
HEADERS = ("Work performed", "Status", "Vendor", "Event date", "Price")
BAD = (ACTION, STATUS, "Synthetic Vendor", "2026-09-12", "$500")
GOOD = (SAFE_ACTION, "Open", "Synthetic Vendor", "2026-09-13", "$100")
SAFE_LINE = "2026-09-13 · Synthetic Vendor — Inspected valve V-2. (Status: Open)"


def csv_bytes(rows=(BAD, GOOD), columns=HEADERS):
    stream = StringIO(newline="")
    csv.writer(stream).writerows((columns, *rows))
    return stream.getvalue().encode()


def parsed(rows=(BAD, GOOD), columns=HEADERS):
    raw = csv_bytes(rows, columns)
    digest = sha256(raw).hexdigest()
    tables = sources._spreadsheet(raw, ".csv")
    pages = tuple("\n".join("\t".join(row) for row in (table.columns, *table.rows)) for table in tables)
    source = ReportSource(digest, "synthetic-maintenance report.csv", digest, ".csv", page_texts=pages)
    return sources.SourceContent(sources.suggest_facts(source, PROFILE), tables)


def item(content, text=ACTION):
    return {"source": content.source.id, "page": 1, "text": text, "row": []}


@pytest.mark.parametrize("heading", ["Status", "Work status", "Completion status"])
@pytest.mark.parametrize("status", [STATUS, "Cancelled because the USD 500 quote was rejected",
                                    "Not completed; quote amount 500", "Pending; fee: 500",
                                    "Completed; invoice total $500"])
def test_priced_status_holds_whole_row_and_preserves_safe_same_file_row(heading, status):
    content = parsed(((ACTION, status, *BAD[2:]), GOOD), (HEADERS[0], heading, *HEADERS[2:]))
    before = asdict(content)
    result = structured.native_update((content,), "activity_summary")
    assert result.text == SAFE_LINE
    assert result.references == (sources.source_reference(content.source, 1),)
    assert asdict(content) == before
    notice, = structured.reader_notices((content,), "activity_summary")
    assert "status includes pricing" in notice and "Review the original" in notice
    assert status not in notice and "$500" not in notice
    assert structured.reader_sources((content,), "activity_summary") == ()


@pytest.mark.parametrize("status", ["", "Completed", "Not completed; awaiting approval",
                                    "Pending: pressure 1200 psi", "Open: asset ID 1234567890",
                                    "Cancelled; quote reference Q-500"])
def test_nonfinancial_status_and_separate_price_column_keep_existing_work(status):
    content = parsed(((ACTION, status, *BAD[2:]),))
    expected = "2026-09-12 · Synthetic Vendor — " + ACTION
    if status:
        expected += " (Status: " + status + ")"
    assert structured.native_update((content,), "activity_summary").text == expected
    assert structured.reader_notices((content,), "activity_summary") == ()
    assert structured.reader_sources((content,), "activity_summary") == (content,)


@pytest.mark.parametrize("columns,row", [
    (("Work performed",), (ACTION,)),
    (("Work performed", "Approval notes"), (ACTION, STATUS)),
])
def test_absent_or_unrecognized_optional_status_does_not_change_schema(columns, row):
    content = parsed((row,), columns)
    assert structured.native_update((content,), "activity_summary").text == ACTION
    assert structured.reader_notices((content,), "activity_summary") == ()


def test_unknown_schema_and_other_destinations_keep_existing_routes():
    unknown = parsed(((ACTION, STATUS),), ("Notes", "Status"))
    assert structured.reader_notices((unknown,), "activity_summary") == ()
    assert structured.reader_sources((unknown,), "activity_summary") == (unknown,)
    content = parsed()
    assert structured.reader_sources((content,), "proposals") == (content,)
    assert structured.reader_notices((content,), "proposals") == ()
    xlsx = replace(content, source=replace(content.source, suffix=".xlsx"))
    assert structured.reader_notices((xlsx,), "activity_summary") == ()


def test_contact_redaction_keeps_nonfinancial_negative_status():
    content = parsed(((ACTION, "Not completed; contact person@example.invalid", *BAD[2:]),))
    result = structured.native_update((content,), "activity_summary")
    assert result.text.endswith("(Status: Not completed; contact [contact omitted])")
    assert "person@example.invalid" not in result.text
    assert structured.reader_notices((content,), "activity_summary") == ()


def test_only_unsafe_row_cannot_create_text_or_reference():
    content = parsed((BAD,))
    result = structured.native_update((content,), "activity_summary")
    assert not result.text and not result.references
    assert structured.reader_batches(PROFILE, (content,), "activity_summary") == ()


def test_safe_sibling_and_native_rows_survive_old_mixed_reader_results():
    bad = parsed()
    sibling = parsed((("Inspected separate fan F-3.",),), ("Work performed",))
    block = structured.native_update((bad, sibling), "activity_summary")
    assert block.text == SAFE_LINE + "\n\nInspected separate fan F-3."
    assert structured.reader_sources((bad, sibling), "activity_summary") == (sibling,)
    result, pages = structured.reader_update((bad, sibling), "activity_summary",
        {"items": [item(bad), item(bad, SAFE_ACTION), item(sibling, "Inspected separate fan F-3.")]}, block)
    assert result == block and not pages
    assert result.references == (sources.source_reference(bad.source, 1), sources.source_reference(sibling.source, 1))
    request = repr(structured.reader_request(PROFILE, (bad, sibling), "activity_summary"))
    assert bad.source.id not in request and sibling.source.id in request
    batches = structured.reader_batches(PROFILE, (bad, sibling), "activity_summary")
    assert bad.source.id not in repr(batches) and sibling.source.id in repr(batches)


def test_sole_unsafe_reader_result_requires_review_without_reintroducing_action():
    content = parsed()
    with pytest.raises(ValueError, match="status includes pricing"):
        structured.reader_update((content,), "activity_summary", {"items": [item(content)]})
    with pytest.raises(ValueError, match="unknown source"):
        structured.reader_update((content,), "activity_summary",
                                 {"items": [{"source": "f" * 64, "page": 1, "text": ACTION}]})


@pytest.mark.parametrize("text", ["Operator retained a deliberate correction.", ""])
def test_manual_corrections_and_deletions_keep_existing_receipt(text):
    content = parsed()
    existing = ResolvedBlock("activity_summary", "This month", text=text,
                             references=(sources.source_reference(content.source, 1),))
    corrected = replace(content, source=replace(content.source, vendor="Corrected Vendor"))
    assert structured.native_update((corrected,), "activity_summary", existing) == existing


@pytest.mark.parametrize("heading,value,reason", [("Site", "Another Site", "site-specific"),
                                                  ("Work Order", "WO-1", "work-order"),
                                                  ("Status", "Completed", "ambiguous Activity CSV columns")])
def test_existing_scope_and_header_guards_keep_notice_priority(heading, value, reason):
    content = parsed(((*BAD, value),), (*HEADERS, heading))
    assert not structured.native_update((content,), "activity_summary").text
    assert reason in structured.reader_notices((content,), "activity_summary")[0]


def draft_for(block, contents):
    section = SectionSpec("activity", "2", "Monthly Activity Summary", (BlockSpec("activity_summary", "rich_text"),))
    return ReportDraft(PROFILE, PERIOD, "Synthetic Editor", (section,), (block,),
                       sources=tuple(content.source for content in contents), synthetic=True)


def template(tmp_path):
    path = tmp_path / "synthetic-activity.docx"
    document = Document()
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph("Prior placeholder")
    document.save(path)
    return path


def test_actual_word_keeps_manual_and_safe_rows_without_incomplete_event(tmp_path):
    content = parsed()
    manual = ResolvedBlock("activity_summary", "This month", text="Retained manual words.")
    result = structured.native_update((content,), "activity_summary", manual)
    path = template(tmp_path)
    before = path.read_bytes()
    document = Document(BytesIO(_build_native_docx(draft_for(result, (content,)), path, section_key="activity")))
    text = "\n".join(p.text for p in document.paragraphs)
    assert manual.text in text and SAFE_LINE in text
    assert ACTION not in text and "$500" not in text
    assert path.read_bytes() == before


def test_public_storage_history_and_word_retain_original_and_safe_work(monkeypatch, tmp_path):
    """Enabled real Linux persistence/public Word, with no persistence seam."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = csv_bytes()
    content, _ = sources.ingest(PROFILE, "synthetic-maintenance report.csv", raw)
    manual = ResolvedBlock("activity_summary", "This month", text="Retained manual words.")
    saved = library.save_snapshot(draft_for(manual, (content,)), expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    result = structured.native_update((content,), "activity_summary", reopened.blocks[0])
    assert result.text == manual.text + "\n\n" + SAFE_LINE
    updated = replace(reopened, blocks=(result,))
    library.save_snapshot(updated, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert updated.sources == saved.draft.sources
    assert sources.source_bytes(PROFILE, content.source) == raw
    document = Document(BytesIO(build_native_docx(updated, template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in document.paragraphs)
    assert manual.text in text and SAFE_LINE in text and ACTION not in text


def test_public_storage_guided_upload_shows_notice_and_keeps_safe_rows(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity, draft, editor

    app, profile = setup_app(monkeypatch, tmp_path / "guided")
    manual = "Operator retained an observation."
    editor(app).set_value(manual).run()
    raw = csv_bytes()
    sibling_raw = csv_bytes((("Inspected separate fan F-3.",),), ("Work performed",))
    original_uploader, original_routes = st.file_uploader, structured.reader_sources
    routed = []

    def uploaded(label, *args, **kwargs):
        native = original_uploader(label, *args, **kwargs)
        if label != "Add source files":
            return native
        streams = []
        for filename, body in (("synthetic-maintenance report.csv", raw), ("safe-maintenance report.csv", sibling_raw)):
            stream = BytesIO(body)
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
    assert any("status includes pricing" in warning.value for warning in app.warning)
    assert activity(app).text == manual + "\n\n" + SAFE_LINE + "\n\nInspected separate fan F-3."
    assert editor(app).value == activity(app).text
    assert (sha256(sibling_raw).hexdigest(),) in routed
    assert all(sha256(raw).hexdigest() not in ids for ids in routed)
    assert len(draft(app).sources) == 2
    for source in draft(app).sources:
        assert sources.source_bytes(profile, source) == (raw if source.id == sha256(raw).hexdigest() else sibling_raw)
