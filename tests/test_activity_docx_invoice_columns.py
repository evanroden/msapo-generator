"""DOCX invoice amounts must retain their column meaning through automatic Activity."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
import sys

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_structured_uploads as activity
from app.monthly_report_model import ReportPeriod, ReportSource, ResolvedBlock
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_details import correct_source_details
from app.monthly_report_source_recovery import restore_sources
from tests.test_activity_docx_site_table_boundaries import PROFILE, PERIOD, draft_for, template
from tests.conftest import requires_libreoffice


INVOICE = "18675.50"
ACTION = "Inspected synthetic pump P-1."
TECHNICAL = "Operating pressure was 74 psi."
NARRATIVE = "Completed the independent inspection."
SIBLING = "Calibrated separate sensor Z-4."
MANUAL = "Operator kept the earlier reviewed wording."


def item(text, suffix=".docx"):
    digest = sha256(text.encode()).hexdigest()
    return sources.SourceContent(ReportSource(digest, "synthetic" + suffix, digest, suffix,
        facility="north", service_date="2026-09-04", page_texts=(text,), selected_pages=()))


def original(headings=("Work performed", "Invoice total", "Reading"), rows=((ACTION, INVOICE, TECHNICAL),)):
    doc = Document()
    doc.add_paragraph("Service report\nService date: 2026-09-04")
    doc.add_paragraph(NARRATIVE)
    table = doc.add_table(rows=0, cols=len(headings))
    for row in (headings, *rows):
        for cell, value in zip(table.add_row().cells, row):
            cell.text = value
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize("heading", ["Invoice total", "Vendor invoice total", "Invoice Amount",
                                     "Supplier invoice amount", "Subcontractor invoice total", "Invoice total (USD)",
                                     "Invoice total:", "Invoice total USD", "Vendor invoice amount: [$]",
                                     "Invoice amount (CHF)", "Invoice total CAD"])
@pytest.mark.parametrize("invoice_first", [False, True])
def test_only_vendor_invoice_column_is_excluded_from_native_activity(heading, invoice_first):
    cells = [(heading, INVOICE), ("Work performed", ACTION), ("Reading", TECHNICAL)]
    if not invoice_first:
        cells.reverse()
    source = item("\n".join("\t".join(row) for row in zip(*cells)))
    result = activity.native_update((source,), "activity_summary")
    assert ACTION in result.text and TECHNICAL in result.text and INVOICE not in result.text
    assert result.references == (sources.source_reference(source.source, 1),)
    assert INVOICE in source.source.page_texts[0]


@pytest.mark.parametrize("heading", ["Pressure reading", "Invoice reference", "Invoice date",
                                     "Contract amount", "ENFRA client report amount", "Invoice total (hours)"])
def test_unrelated_technical_and_client_headers_keep_their_existing_extraction(heading):
    text = f"Work performed\t{heading}\n{ACTION}\t{INVOICE}"
    assert list(activity._activity_source_pages(item(text))) == [(1, text)]


def test_prose_mentions_of_invoice_total_do_not_become_table_headers():
    text = "The invoice total was reviewed separately.\n" + ACTION + "\t" + TECHNICAL
    assert list(activity._activity_source_pages(item(text))) == [(1, text)]


def test_empty_invoice_cells_keep_the_ordinary_view():
    text = "Work performed\tInvoice total\n" + ACTION + "\t"
    assert list(activity._activity_source_pages(item(text))) == [(1, text)]


def test_stored_heavily_padded_invoice_lookalike_and_currency_header_finish_within_budget():
    # Isolate the deadline so a regressed matcher cannot hang the suite.
    code = """
from app.monthly_report_structured_uploads import native_update
from app.monthly_report_sources import SourceContent
from app.monthly_report_model import ReportSource
pad = ' ' * 16384
for title, recognized in [('Invoice total' + pad + 'X', False), ('Invoice total' + pad + '(USD)', True)]:
    page = 'Work performed\\t' + title + '\\tReading\\nInspected synthetic pump.\\t18675.50\\tOperating pressure was 74 psi.'
    record = ReportSource('a' * 64, 'stored.docx', 'a' * 64, '.docx', page_texts=(page,))
    text = native_update((SourceContent(record),), 'activity_summary').text
    assert 'Inspected synthetic pump.' in text and 'Operating pressure was 74 psi.' in text
    assert record.page_texts == (page,)
    if recognized:
        assert '18675.50' not in text
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                   timeout=15, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("bands", [1, 2])
@pytest.mark.parametrize("heading", ["Invoice total", "Pressure reading"])
def test_actual_full_width_word_title_above_data_headings(tmp_path, monkeypatch, bands, heading):
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    doc = Document(BytesIO(original(headings=("Work performed", heading, "Reading"))))
    table = doc.tables[0]
    header = table.rows[0]._tr
    for number in range(bands):
        row = table.add_row()
        row.cells[0].merge(row.cells[-1]).text = "Maintenance service detail " + str(number + 1)
        header.addprevious(row._tr)
    stream = BytesIO()
    doc.save(stream)
    source, _ = sources.ingest(PROFILE, "maintenance.docx", stream.getvalue())
    n = next(n for n, p in enumerate(source.source.page_texts, 1) if INVOICE in p)
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    block = activity.native_update((source,), "activity_summary", manual)
    word = Document(BytesIO(_build_native_docx(draft_for(block, (source,)), template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in word.paragraphs)
    response = {"visual_pages": [[source.source.id, n]], "items": [
        {"source": source.source.id, "page": n, "text": ACTION + "\t" + INVOICE, "row": [], "include_page": True},
        {"source": source.source.id, "page": n, "text": TECHNICAL, "row": [], "include_page": True},
    ]}
    read, pages = activity.reader_update((source,), "activity_summary", response, manual)
    for value in (ACTION, TECHNICAL, NARRATIVE, MANUAL, "Maintenance service detail 1"):
        assert value in block.text and value in text
    assert (INVOICE in block.text) == (INVOICE in text) == (INVOICE in read.text) == (heading == "Pressure reading")
    if heading == "Invoice total":
        assert not pages and TECHNICAL in read.text
    assert sources.source_bytes(PROFILE, source.source) == stream.getvalue()


def test_banded_invoice_site_table_requires_original_site_review(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    doc = Document(BytesIO(original(headings=("Site", "Work performed", "Invoice total"),
                                    rows=(("Foreign South", ACTION, INVOICE),))))
    table = doc.tables[0]
    header = table.rows[0]._tr
    row = table.add_row()
    row.cells[0].merge(row.cells[-1]).text = "Maintenance service detail"
    header.addprevious(row._tr)
    stream = BytesIO()
    doc.save(stream)
    source, _ = sources.ingest(PROFILE, "maintenance.docx", stream.getvalue())
    result = activity.native_update((source,), "activity_summary")
    assert ACTION not in result.text and INVOICE not in result.text and NARRATIVE in result.text
    assert activity.reader_sources((source,), "activity_summary") == ()
    assert "site-specific" in activity.reader_notices((source,), "activity_summary")[0]


def test_competing_preamble_before_a_financial_work_schema_is_held_without_treating_data_as_a_heading():
    ambiguous = "Service summary\tRevision B\t\nWork performed\tInvoice total\tReading\n" + ACTION + "\t" + INVOICE + "\t" + TECHNICAL
    source = item(ambiguous)
    source = replace(source, source=replace(source.source, page_texts=(ambiguous, NARRATIVE)))
    result = activity.native_update((source,), "activity_summary")
    assert INVOICE not in result.text and NARRATIVE in result.text
    ordinary = "Work performed\tTechnician note\n" + ACTION + "\tInvoice total"
    assert list(activity._activity_source_pages(item(ordinary))) == [(1, ordinary)]


@pytest.mark.parametrize("work_label,invoice_label", [
    ("Work performed", "Invoice total"), ("Work performed", "Invoice\nTotal"),
    ("Work\nperformed", "Invoice total"), ("Work\nperformed", "Invoice\nTotal"),
])
def test_actual_later_financial_heading_with_multiline_data_cells(tmp_path, monkeypatch, work_label, invoice_label):
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    raw = original(headings=("Service summary", "Revision B", ""),
                   rows=((work_label, invoice_label, "Reading"),
                         (ACTION, INVOICE, TECHNICAL + "\nConfirmed the reading.")))
    source, _ = sources.ingest(PROFILE, "maintenance.docx", raw)
    n = next(n for n, p in enumerate(source.source.page_texts, 1) if INVOICE in p)
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    block = activity.native_update((source,), "activity_summary", manual)
    doc = Document(BytesIO(_build_native_docx(draft_for(block, (source,)), template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert INVOICE not in text and MANUAL in text and NARRATIVE in text
    supplied = {"items": [{"source": source.source.id, "page": n, "text": ACTION + "\t" + INVOICE, "row": []}]}
    old, _ = activity.reader_update((source,), "activity_summary", supplied, manual)
    assert old.text == MANUAL and sources.source_bytes(PROFILE, source.source) == raw


def test_ragged_note_with_a_literal_invoice_label_but_no_later_schema_remains_ordinary():
    text = "Work performed\tTechnician note\n" + ACTION + "\tInvoice total\n" + NARRATIVE
    assert list(activity._activity_source_pages(item(text))) == [(1, text)]


@pytest.mark.parametrize("mode", ["moved", "moved_compact", "same", "site", "literal"])
def test_actual_word_table_with_a_second_heading_or_literal_data_cell(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    second_action = "Adjusted synthetic fan F-2."
    next_total = "45678.91"
    if mode in ("moved", "moved_compact", "site"):
        next_header = ("Site" if mode == "site" else "Reading",
                       "WorkPerformed" if mode == "moved_compact" else "Work performed", "Invoice total")
        later = ("Foreign South" if mode == "site" else "Inspected secondary airflow.", second_action, next_total)
    else:
        next_header = ("Work performed", "Invoice total", "Reading") if mode == "same" else (
            "Inspected panel label.", "273.40", "Invoice total")
        later = (second_action, next_total, "Measured pressure 52 psi.")
    raw = original(rows=((ACTION, INVOICE, TECHNICAL), next_header, later))
    source, _ = sources.ingest(PROFILE, "maintenance.docx", raw)
    page = next(n for n, p in enumerate(source.source.page_texts, 1) if next_total in p)
    block = activity.native_update((source,), "activity_summary")
    word = Document(BytesIO(_build_native_docx(draft_for(block, (source,)), template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in word.paragraphs)
    assert next_total not in text and INVOICE not in text and NARRATIVE in text
    assert (second_action in text) == (mode in ("same", "literal"))
    if mode == "site":
        assert "site-specific" in activity.reader_notices((source,), "activity_summary")[0]
    else:
        payload = {"items": [{"source": source.source.id, "page": page, "text": "\t".join(later), "row": []}]}
        old, _ = activity.reader_update((source,), "activity_summary", payload)
        assert next_total not in old.text
    assert sources.source_bytes(PROFILE, source.source) == raw


@pytest.mark.parametrize("text", [
    f"Work performed\tInvoice\nTotal\n{ACTION}\t{INVOICE}",
    f"Vendor invoice\namount\tWork performed\n{INVOICE}\t{ACTION}",
    f"Work performed\tInvoice total\nInspected pump\nP-1.\t{INVOICE}",
    f"Work performed\tInvoice\nTotal\tReading\n{ACTION}\t{INVOICE}\t{TECHNICAL}",
])
def test_uncertain_physical_cells_cannot_leak_bare_amounts_or_suppress_other_items(text):
    source = item(text)
    source = replace(source, source=replace(source.source, page_texts=(text, NARRATIVE)))
    result = activity.native_update((source,), "activity_summary")
    assert INVOICE not in result.text and NARRATIVE in result.text
    assert source.source.page_texts == (text, NARRATIVE)


def test_original_site_header_still_blocks_the_entire_financial_table():
    source = item(f"Site\tWork performed\tInvoice total\nForeign South\t{ACTION}\t{INVOICE}")
    result = activity.native_update((source,), "activity_summary")
    assert not result.text and not result.references
    assert "site-specific" in activity.reader_notices((source,), "activity_summary")[0]


def test_old_reader_result_drops_invoice_row_and_unredacted_page_keeps_safe_siblings():
    source = item(f"Work performed\tInvoice total\tReading\n{ACTION}\t{INVOICE}\t{TECHNICAL}")
    sibling = item(SIBLING, ".txt")
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    value = {"visual_pages": [[source.source.id, 1]], "items": [
        {"source": source.source.id, "page": 1, "text": ACTION + "\t" + INVOICE, "row": []},
        {"source": source.source.id, "page": 1, "text": TECHNICAL, "row": [], "include_page": True},
        {"source": sibling.source.id, "page": 1, "text": SIBLING, "row": []},
    ]}
    result, pages = activity.reader_update((source, sibling), "activity_summary", value, manual)
    assert result.text == "\n\n".join((MANUAL, TECHNICAL, SIBLING))
    assert not pages
    assert result.references == (sources.source_reference(source.source, 1), sources.source_reference(sibling.source, 1))
    assert ACTION in str(activity.reader_request(PROFILE, (source,), "proposals"))
    value["items"] = [{"source": source.source.id, "page": 1, "text": "Invented source text.", "row": []}]
    with pytest.raises(ValueError, match="not present"):
        activity.reader_update((source,), "activity_summary", value, manual)


def test_same_numeric_value_in_an_independent_technical_cell_keeps_its_context():
    reading = "Measured airflow reading was " + INVOICE + " cfm."
    source = item(f"Work performed\tInvoice total\tReading\n{ACTION}\t{INVOICE}\t{reading}")
    result = activity.native_update((source,), "activity_summary")
    assert reading in result.text and result.text.count(INVOICE) == 1
    payload = {"items": [{"source": source.source.id, "page": 1, "text": reading, "row": []}]}
    accepted, _ = activity.reader_update((source,), "activity_summary", payload)
    assert accepted.text == reading


@pytest.mark.parametrize("previous", [MANUAL, ""])
def test_existing_manual_edit_or_deletion_is_preserved(previous):
    source = item(f"Work performed\tInvoice total\n{ACTION}\t{INVOICE}")
    block = ResolvedBlock("activity_summary", "This month", text=previous,
                          references=(sources.source_reference(source.source, 1),))
    assert activity.native_update((source,), "activity_summary", block) == block


def test_real_docx_source_facility_and_word_exclude_only_the_invoice_amount(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    raw = original()
    contents, messages = sources.ingest_batch(PROFILE, (("maintenance.docx", raw),))
    assert len(contents) == 1 and not messages
    source = contents[0]
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_upload_ui import render_source_details
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state['source'] = render_source_details(st.session_state['source'], st.session_state['profile'], 'invoice-column', field)
""")
    app.session_state["source"], app.session_state["profile"] = source.source, PROFILE
    app.run()
    assert not app.exception
    next(w for w in app.selectbox if w.label == "Source facility").set_value("north")
    next(w for w in app.button if w.label == "Use these source details").click().run()
    assert not app.exception
    source = replace(source, source=app.session_state["source"])
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    result = activity.native_update((source,), "activity_summary", manual)
    doc = Document(BytesIO(_build_native_docx(draft_for(result, (source,)), template(tmp_path), section_key="activity")))
    output = "\n".join(p.text for p in doc.paragraphs)
    for value in (MANUAL, ACTION, TECHNICAL, NARRATIVE):
        assert value in result.text and value in output
    assert INVOICE not in result.text and INVOICE not in output
    assert sources.source_bytes(PROFILE, source.source) == raw and INVOICE in source.source.page_texts[-1]


def test_actual_separated_word_tables_keep_item_numbers_safe_reader_reference_and_visual(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(sources, "_path", lambda p, digest, suffix: tmp_path / (digest + suffix))
    monkeypatch.setattr(library, "_atomic_write", lambda path, raw: path.write_bytes(raw))
    doc = Document(BytesIO(original()))
    doc.add_paragraph(SIBLING)
    image = BytesIO()
    Image.new("RGB", (12, 12), "white").save(image, format="PNG")
    doc.add_picture(BytesIO(image.getvalue()))
    second = doc.add_table(rows=0, cols=2)
    for row in (("Vendor invoice total", "Work performed"), ("99876.25", "Replaced second synthetic seal.")):
        for cell, value in zip(second.add_row().cells, row):
            cell.text = value
    raw = BytesIO()
    doc.save(raw)
    source, _ = sources.ingest(PROFILE, "separate-items.docx", raw.getvalue())
    texts = source.source.page_texts
    first = next(n for n, p in enumerate(texts, 1) if INVOICE in p)
    second = next(n for n, p in enumerate(texts, 1) if "99876.25" in p)
    sibling = texts.index(SIBLING) + 1
    picture = source.image_items[0][0]
    assert first < sibling < picture < second
    block = activity.native_update((source,), "activity_summary")
    assert INVOICE not in block.text and "99876.25" not in block.text
    assert all(sources.source_reference(source.source, n) in block.references for n in (first, second, sibling))
    value = {"visual_pages": [[source.source.id, n] for n in (first, picture, second)],
             "items": [{"source": source.source.id, "page": n, "text": text, "row": [], "include_page": True}
                       for n, text in ((first, ACTION), (picture, "Inspected separate panel."), (second, "Replaced second synthetic seal."))]}
    accepted, pages = activity.reader_update((source,), "activity_summary", value)
    assert pages == {source.source.id: {picture}}
    assert ACTION in accepted.text and "Replaced second synthetic seal." in accepted.text
    assert sources.source_bytes(PROFILE, source.source) == raw.getvalue()


def test_public_storage_history_original_and_public_word_keep_safe_work(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = original()
    contents, messages = sources.ingest_batch(PROFILE, (("maintenance.docx", raw),))
    assert len(contents) == 1 and not messages
    source = replace(contents[0], source=correct_source_details(contents[0].source, PROFILE, date(2026, 9, 4), "north"))
    manual = ResolvedBlock("activity_summary", "This month", text=MANUAL)
    saved = library.save_snapshot(draft_for(manual, (source,)), expected_revision=0, entered_editor="Synthetic Editor")
    prior = library.save_snapshot(replace(saved.draft, period=ReportPeriod(2026, 8)), expected_revision=0, entered_editor="Synthetic Editor")
    restored, missing = restore_sources(PROFILE, saved.draft.sources)
    assert not missing and restored[0].source == source.source
    updated = replace(saved.draft, blocks=(activity.native_update(restored, "activity_summary", manual),))
    library.save_snapshot(updated, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft == updated
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, prior.draft.period) == prior
    doc = Document(BytesIO(build_native_docx(updated, template(tmp_path), section_key="activity")))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert MANUAL in text and ACTION in text and NARRATIVE in text and TECHNICAL in text and INVOICE not in text
    assert sources.source_bytes(PROFILE, restored[0].source) == raw


def test_public_storage_guided_upload_keeps_manual_and_verified_work(monkeypatch, tmp_path):
    import streamlit as st
    from tests.test_monthly_report_activity_intake_commit import setup_app, activity as block, draft, editor
    app, profile = setup_app(monkeypatch, tmp_path)
    editor(app).set_value(MANUAL).run()
    raw = original()
    original_uploader = st.file_uploader
    def uploaded(label, *args, **kwargs):
        widget = original_uploader(label, *args, **kwargs)
        if label != "Add source files":
            return widget
        stream = BytesIO(raw)
        stream.name = "maintenance.docx"
        return [stream]
    monkeypatch.setattr(st, "file_uploader", uploaded)
    app.run()
    assert not app.exception and app.get("file_uploader")
    text = block(app).text
    assert MANUAL in text and ACTION in text and TECHNICAL in text and NARRATIVE in text and INVOICE not in text
    assert sources.source_bytes(profile, draft(app).sources[0]) == raw


@requires_libreoffice
def test_public_storage_converted_pdf_keeps_safe_work_and_reading_without_invoice(monkeypatch, tmp_path):
    import pymupdf as fitz
    from app import pdf_converter
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    raw = original()
    source, _ = sources.ingest(PROFILE, "maintenance.docx", raw)
    source = replace(source, source=correct_source_details(source.source, PROFILE, date(2026, 9, 4), "north"))
    block = activity.native_update((source,), "activity_summary")
    document = build_native_docx(draft_for(block, (source,)), template(tmp_path), section_key="activity")
    path = tmp_path / "invoice-free-activity.docx"
    path.write_bytes(document)
    with fitz.open(pdf_converter.convert_to_pdf(path)) as pdf:
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    assert ACTION in text and TECHNICAL in text and INVOICE not in text
