"""Native proposal uploads preserve every explicit decision for human review.

All sources are invented in memory. The UI test uses the real upload and row
edit owners, substituting only the file-uploader transport; it is not a real
browser acceptance test. DOCX assertions inspect generated document content.
"""
from dataclasses import replace
from datetime import date
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import json
import os
from pathlib import Path

from docx import Document
from openpyxl import Workbook
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_followups import confirmation, seed_followups
from app.monthly_report_model import (
    ColumnSpec, ReportDraft, ReportPeriod, ResolvedBlock,
    default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_sources import ingest, source_bytes
from app.monthly_report_structured_uploads import native_update
from tests.conftest import requires_libreoffice


SCOPE = "Replace synthetic actuator"


def _file(suffix, headings, rows):
    if suffix == ".csv":
        text = StringIO(newline="")
        csv.writer(text).writerows((headings, *rows))
        return text.getvalue().encode()
    stream = BytesIO()
    if suffix == ".xlsx":
        workbook = Workbook()
        for row in (headings, *rows):
            workbook.active.append(row)
        workbook.save(stream)
    else:
        document = Document()
        table = document.add_table(rows=len(rows) + 1, cols=len(headings))
        for target, values in zip(table.rows, (headings, *rows)):
            for cell, value in zip(target.cells, values):
                cell.text = value
        document.save(stream)
    return stream.getvalue()


def _content(tmp_path, monkeypatch, headings, rows, suffix=".csv"):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    profile = synthetic_profiles()[0]
    raw = _file(suffix, headings, rows)
    content, attachments = ingest(profile, "synthetic-proposals" + suffix, raw)
    assert not attachments
    assert source_bytes(profile, content.source) == raw
    return profile, raw, content


def _draft(profile, block, source, columns=None):
    section = next(section for section in default_sections() if section.key == "proposals")
    if columns is not None:
        spec = replace(section.blocks[0], columns=tuple(
            ColumnSpec(f"column_{index}", title) for index, title in enumerate(columns)))
        section = replace(section, blocks=(spec,))
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Reviewer",
                       (section,), (block,), sources=(source,))


@pytest.mark.parametrize("suffix", [".csv", ".xlsx", ".docx"])
@pytest.mark.parametrize("headings", [
    ("Scope", "Status", "Decision"),
    ("Scope", "Status", "Status"),
])
def test_native_upload_keeps_conflicting_decision_cells(tmp_path, monkeypatch, suffix, headings):
    profile, original, content = _content(tmp_path, monkeypatch, headings,
        ((SCOPE, "Pending", "Declined"),), suffix)
    block = native_update((content,), "proposals")
    assert len(block.rows) == 1
    assert "Pending" in block.rows[0][-1] and "Declined" in block.rows[0][-1]
    carried = new_month_draft(_draft(profile, block, content.source), ReportPeriod(2026, 10))
    item, = carried.follow_ups
    assert item.status == "not_confirmed"
    assert "Pending" in item.text and "Declined" in item.text
    assert not item.reviewed_fingerprint
    assert source_bytes(profile, content.source) == original


@pytest.mark.parametrize("first,second", [
    ("Pending", ""), ("Pending", "Awaiting board"),
    ("", "Declined"), ("Pending", "Pending for review"),
])
def test_blank_or_unknown_competing_decision_is_visible(tmp_path, monkeypatch, first, second):
    profile, _, content = _content(tmp_path, monkeypatch, ("Scope", "Status", "Decision"),
                                   ((SCOPE, first, second),))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == "not_confirmed"
    assert "Status" in item.text and "Decision" in item.text
    for value in (first, second):
        if value:
            assert value in item.text


@pytest.mark.parametrize("headings,row,expected", [
    (("Scope", "Status", "Decision"), (SCOPE, "Declined", "Rejected"), "declined"),
    (("Scope", "Decision", "Status"), (SCOPE, "Pending", "Pending"), "pending"),
    (("Scope", "Proposal Status", "Approval Decision"), (SCOPE, "On hold", "On hold"), "on_hold"),
    (("Scope", "Status"), (SCOPE, "Approved"), "approved"),
    (("Scope", "Vendor"), (SCOPE, "Synthetic Controls"), "not_confirmed"),
])
def test_consistent_single_and_absent_decisions_keep_existing_meaning(tmp_path, monkeypatch, headings, row, expected):
    profile, _, content = _content(tmp_path, monkeypatch, headings, (row,))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == expected
    assert SCOPE in item.text
    assert not item.reviewed_fingerprint
    assert native_update((content,), "proposals", block) == block


def test_explicit_approval_fields_conflict_even_when_source_order_changes(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Approval Decision", "Scope", "Proposal Status"),
        (("Declined", SCOPE, "Pending"),))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == "not_confirmed"
    assert "Declined" in item.text and "Pending" in item.text


def test_scope_wording_and_status_notes_do_not_become_decision_columns(tmp_path, monkeypatch):
    scope = SCOPE + "; Status: Approved"
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", "Status", "Decision note"), ((scope, "Pending", "May be declined later"),))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == "pending"
    assert item.text == "Scope: " + scope


def test_six_column_native_layout_keeps_each_exact_decision_field(tmp_path, monkeypatch):
    columns = ("Proposal ID", "Facility", "Scope", "Status", "Decision", "Technical Notes")
    profile = synthetic_profiles()[0]
    row = ("P-001", profile.facilities[0].title, SCOPE, "Pending", "Declined", "Retain existing wiring")
    profile, _, content = _content(tmp_path, monkeypatch, columns, (row,), ".xlsx")
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == (row,)
    item, = seed_followups(_draft(profile, block, content.source, columns))
    assert item.status == "not_confirmed"
    assert "Status: Pending" in item.text and "Decision: Declined" in item.text
    assert "Retain existing wiring" in item.text


def test_reordered_native_decisions_preserve_their_literal_aliases(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Decision", "Scope", "Status", "Vendor"),
        (("Rejected", SCOPE, "Declined", "Synthetic Controls"),))
    columns = ("Scope", "Vendor", "Status", "Decision")
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == ((SCOPE, "Synthetic Controls", "Declined", "Rejected"),)
    item, = seed_followups(_draft(profile, block, content.source, columns))
    assert item.status == "declined"


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("headings,decisions,columns,expected", [
    (("Scope", "Status (2)", "Status"), ("Declined", "Pending"),
     ("Scope", "Status", "Status (2)"), ("Pending", "Declined")),
    (("Scope", "Status", "STATUS"), ("Pending", "Declined"),
     ("Scope", "STATUS", "Status"), ("Declined", "Pending")),
    (("Scope", "STATUS", "Status"), ("Pending", "Declined"),
     ("Scope", "Status", "Status (3)"), ("Declined", "Pending")),
], ids=["numbered-before-base", "reordered-case-variants", "exact-before-duplicate-fallback"])
def test_native_reordering_preserves_unique_exact_source_headings(
        tmp_path, monkeypatch, suffix, headings, decisions, columns, expected):
    profile, _, content = _content(tmp_path, monkeypatch, headings, ((SCOPE, *decisions),), suffix)
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == ((SCOPE, *expected),)
    carried = new_month_draft(_draft(profile, block, content.source, columns), ReportPeriod(2026, 10))
    item, = carried.follow_ups
    assert item.status == "not_confirmed"
    assert "Pending" in item.text and "Declined" in item.text


def test_third_decision_cannot_disappear_into_two_decision_slots(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", "Status", "Decision", "Approval Status"),
        ((SCOPE, "Pending", "Pending", "Declined"),))
    columns = ("Scope", "Status", "Decision")
    block = native_update((content,), "proposals", table_columns=columns)
    assert len(block.rows[0]) == len(columns)
    assert "Approval Status: Declined" in "\n".join(block.rows[0])
    item, = seed_followups(_draft(profile, block, content.source, columns))
    assert item.status == "not_confirmed"
    assert "Pending" in item.text and "Declined" in item.text


def test_csv_duplicate_occurrences_fit_native_physical_column_names(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Proposal ID", "Scope", "Status", "Status"),
        (("P-002", SCOPE, "Pending", "Declined"),))
    assert content.tables[0].columns == ("Proposal ID", "Scope", "Status", "Status (2)")
    columns = ("Proposal ID", "Scope", "Status", "Status (4)")
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == (("P-002", SCOPE, "Pending", "Declined"),)
    item, = seed_followups(_draft(profile, block, content.source, columns))
    assert item.status == "not_confirmed"


@pytest.mark.parametrize("decisions", [("Pending", "Declined"), ("Pending", "Pending", "Declined")])
def test_occurrence_named_native_slots_cannot_hide_the_last_decision(tmp_path, monkeypatch, decisions):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", *("Status" for _ in decisions)), ((SCOPE, *decisions),))
    columns = content.tables[0].columns
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == ((SCOPE, *decisions),)
    carried = new_month_draft(_draft(profile, block, content.source, columns), ReportPeriod(2026, 10))
    item, = carried.follow_ups
    assert item.status == "not_confirmed"
    assert "Pending" in item.text and "Declined" in item.text


def test_case_variants_are_still_competing_explicit_decisions(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", "Status", "status"), ((SCOPE, "Pending", "Declined"),))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == "not_confirmed"
    assert "Pending" in item.text and "Declined" in item.text


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("headings", [
    ("Scope", "Status", "STATUS", "Status"),
    ("Scope", "STATUS", "Status", "Status"),
])
def test_mixed_spelling_duplicate_does_not_hide_its_final_decision(tmp_path, monkeypatch, suffix, headings):
    row = (SCOPE, "Pending", "Pending", "Declined")
    profile, _, content = _content(tmp_path, monkeypatch, headings, (row,), suffix)
    assert content.tables[0].columns[-1] == "Status (2)"
    for columns in (None, content.tables[0].columns):
        block = native_update((content,), "proposals", table_columns=columns)
        if columns is not None:
            assert block.rows == (row,)
        carried = new_month_draft(_draft(profile, block, content.source, columns), ReportPeriod(2026, 10))
        item, = carried.follow_ups
        assert item.status == "not_confirmed"
        assert "Pending" in item.text and "Declined" in item.text


@pytest.mark.parametrize("heading", ["Decision (2026)", "Decision date", "Work status"])
def test_contextual_headings_are_not_additional_proposal_decisions(tmp_path, monkeypatch, heading):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", "Status", heading), ((SCOPE, "Pending", "Declined"),))
    block = native_update((content,), "proposals")
    item, = seed_followups(_draft(profile, block, content.source))
    assert item.status == "pending"
    assert item.text == "Scope: " + SCOPE


def test_native_layout_without_decision_slot_keeps_its_shape(tmp_path, monkeypatch):
    profile, _, content = _content(tmp_path, monkeypatch,
        ("Scope", "Vendor", "Status", "Decision"),
        ((SCOPE, "Synthetic Controls", "Pending", "Declined"),))
    columns = ("Scope", "Vendor")
    block = native_update((content,), "proposals", table_columns=columns)
    assert block.rows == ((SCOPE, "Synthetic Controls"),)
    item, = seed_followups(_draft(profile, block, content.source, columns))
    assert item.status == "not_confirmed"


def test_retained_decision_wording_cannot_bypass_price_filter(tmp_path, monkeypatch):
    _, _, content = _content(tmp_path, monkeypatch, ("Scope", "Status", "Decision"),
                              ((SCOPE, "Pending", "Declined at $1,200"),))
    # This is priced prose rather than a price-only column. Retaining its
    # evidence must still encounter the existing whole-row price guard.
    assert native_update((content,), "proposals").rows == ()


def test_capital_rows_keep_their_existing_mapping(tmp_path, monkeypatch):
    profile = synthetic_profiles()[0]
    _, _, content = _content(tmp_path, monkeypatch,
        ("Facility", "Recommendation", "Priority", "Status", "Cost"),
        ((profile.facilities[0].title, SCOPE, "1", "Under review", "$1,200"),))
    block = native_update((content,), "capital_renewal",
                          table_columns=("Facility", "Priority", "Recommendation", "Status"))
    assert block.rows == ((profile.facilities[0].title, "1", SCOPE, "Under review"),)


UPLOAD_APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_row_cards_ui import edit_row_cards
from app.monthly_report_upload_ui import render_structured_uploads
from app.monthly_report_ui import _field
draft = st.session_state['draft']
blocks = {block.key: block for block in draft.blocks}
sources, additions, _ = render_structured_uploads(
    draft.profile, draft.period, 'proposal_evidence', _field, 'proposals', blocks=blocks)
blocks.update(additions)
spec = next(spec for section in draft.sections for spec in section.blocks if spec.key == 'proposals')
blocks['proposals'] = edit_row_cards(spec, blocks['proposals'], 'proposal_evidence', _field)
draft = replace(draft, blocks=tuple(blocks.values()), sources=sources)
st.session_state['draft'] = draft
st.session_state['proposal_evidence_draft'] = draft
'''


FOLLOWUP_APP = '''
import streamlit as st
from app.monthly_report_followups import render_followups
from app.monthly_report_ui import _field
st.session_state['draft'] = render_followups(
    st.session_state['draft'], 'proposal_evidence_followup', _field, category='proposal')
'''


def test_upload_row_edit_save_reopen_and_two_rollovers_preserve_evidence(tmp_path, monkeypatch):
    from app import monthly_report_ai as ai, monthly_report_structured_uploads as structured
    from app import monthly_report_upload_ui as upload_ui, receipt_jobs

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(ai, "cached", lambda *args: None)

    def forbidden(*args, **kwargs):
        pytest.fail("A native proposal upload must not initiate an external reader")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(structured, "read_batches", forbidden)
    monkeypatch.setattr(receipt_jobs, "start_receipt", forbidden)
    raw = _file(".csv", ("Scope", "Status", "Decision"), ((SCOPE, "Pending", "Declined"),))
    upload = BytesIO(raw)
    upload.name = "synthetic-proposals.csv"
    monkeypatch.setattr(upload_ui.st, "file_uploader", lambda *args, **kwargs: [upload])
    profile = synthetic_profiles()[0]
    section = next(section for section in default_sections() if section.key == "proposals")
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Reviewer", (section,),
                        (ResolvedBlock("proposals", "This month"),))
    app = AppTest.from_string(UPLOAD_APP, default_timeout=20)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    imported = app.session_state["draft"]
    assert len(imported.blocks[0].rows) == 1
    assert "Pending" in imported.blocks[0].rows[0][-1]
    assert "Declined" in imported.blocks[0].rows[0][-1]
    library.save_snapshot(imported, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, imported.period).draft
    content, _ = ingest(profile, upload.name, raw)
    assert native_update((content,), "proposals", reopened.blocks[0]) == reopened.blocks[0]
    next(button for button in app.button if button.label == "Edit proposal").click().run()
    assert not app.exception
    status = next(widget for widget in (*app.text_input, *app.text_area) if widget.label == "Status")
    assert "Pending" in status.value and "Declined" in status.value
    next(widget for widget in (*app.text_input, *app.text_area)
         if widget.label == "Scope").set_value(SCOPE + "; retain bracket")
    next(button for button in app.button if button.label == "Close editing").click().run()
    assert not app.exception
    app.run()
    assert not app.exception
    authored = app.session_state["draft"]
    assert authored.blocks[0].rows[0][2] == SCOPE + "; retain bracket"
    assert authored.blocks[0].rows[0][3] == imported.blocks[0].rows[0][3]
    assert source_bytes(profile, authored.sources[0]) == raw

    library.save_snapshot(authored, expected_revision=1)
    reopened = library.load_snapshot(profile.contract, profile.key, authored.period).draft
    first = new_month_draft(reopened, ReportPeriod(2026, 10))
    item, = first.follow_ups
    assert item.status == "not_confirmed" and not item.reviewed_fingerprint
    assert "Pending" in item.text and "Declined" in item.text and "retain bracket" in item.text

    review = AppTest.from_string(FOLLOWUP_APP, default_timeout=20)
    review.session_state["draft"] = first
    review.run()
    assert not review.exception
    next(button for button in review.button if button.label == "Update proposal").click().run()
    next(widget for widget in review.radio if widget.label == "Proposal decision").set_value("on_hold").run()
    next(button for button in review.button if button.label == "Confirm update").click().run()
    assert not review.exception
    confirmed = review.session_state["draft"]
    chosen, = confirmed.follow_ups
    assert chosen.status == "on_hold"
    assert chosen.text == item.text
    assert chosen.reviewed_fingerprint == confirmation(chosen, confirmed.period)
    library.save_snapshot(confirmed, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, confirmed.period).draft
    second = new_month_draft(reopened, ReportPeriod(2026, 11))
    final, = second.follow_ups
    assert (final.key, final.text, final.status) == (chosen.key, chosen.text, "on_hold")
    assert not final.reviewed_fingerprint
    assert library.load_snapshot(profile.contract, profile.key, authored.period).draft == authored
    assert library.load_snapshot_version(profile.contract, profile.key, authored.period, 1).draft == imported
    assert source_bytes(profile, authored.sources[0]) == raw


def _output_draft(tmp_path, monkeypatch):
    from app.monthly_report_source_details import correct_source_details

    profile, original, content = _content(tmp_path, monkeypatch,
        ("Scope", "Status", "Decision", "Cost"), ((SCOPE, "Pending", "Declined", "$1,200"),))
    corrected = correct_source_details(content.source, profile, date(2026, 9, 15), profile.facilities[0].key)
    content = replace(content, source=corrected)
    block = native_update((content,), "proposals")
    draft = _draft(profile, block, content.source)
    return original, content.source, draft


def test_generated_docx_retains_conflicting_literals_without_prices(tmp_path, monkeypatch):
    from app.monthly_report_docx import assemble_docx

    original, source, draft = _output_draft(tmp_path, monkeypatch)
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    document = Document(BytesIO(raw))
    cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    assert any("Pending" in cell and "Declined" in cell for cell in cells)
    assert SCOPE in cells
    assert "$1,200" not in "\n".join(cells)
    assert source_bytes(draft.profile, source) == original


@requires_libreoffice
def test_generated_pdf_retains_conflicting_literals_without_prices(tmp_path, monkeypatch):
    import pymupdf as fitz
    from app import pdf_converter
    from app.monthly_report_docx import assemble_docx

    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    original, source, draft = _output_draft(tmp_path, monkeypatch)
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    path = tmp_path / "synthetic-proposal-decision-evidence.docx"
    path.write_bytes(raw)
    pdf_bytes = pdf_converter.convert_to_pdf(path).read_bytes()
    target = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path))) / "proposal-import-decision-evidence"
    target.mkdir(parents=True, exist_ok=True)
    (target / "proposals.docx").write_bytes(raw)
    (target / "proposals.pdf").write_bytes(pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
        assert "Status: Pending; Decision: Declined" in text
        assert SCOPE in text
        assert "1,200" not in text and "1200" not in text
        for number, page in enumerate(document, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(target / f"proposals-page-{number}.png")
        pages = len(document)
    unchanged = source_bytes(draft.profile, source) == original
    (target / "manifest.json").write_text(json.dumps({
        "docx_sha256": sha256(raw).hexdigest(), "pdf_sha256": sha256(pdf_bytes).hexdigest(),
        "pages": pages, "source_unchanged": unchanged,
        "fixture": "synthetic native proposal upload with competing decision columns",
    }, indent=2))
    assert unchanged
