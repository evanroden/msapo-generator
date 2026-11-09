"""Physical generic issue rows survive migration, editing and actual output.

Fixtures are synthetic. AppTest exercises production widgets with only the
Starting file transport substituted; it is not browser/production acceptance.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import MAX_INCLUDED_FOLLOWUPS, followup_limit_message
from app.monthly_report_import import inspect_docx, imported_draft
from app.monthly_report_issues import canonical_issues, issue_key
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, DraftParagraph, ReportDraft, ReportFollowUp, ReportPeriod,
    ReportTable, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_docx
from app.monthly_report_setup import merge_drafts, new_month_draft
from app.monthly_report_start_import import (
    analyze_starting_report, automatic_section_plans, build_starting_import,
)
from tests.conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 11)
COLUMNS = ("Equipment", "Finding")
ROW = ("Heat exchanger", "Leak at flange")
TEXT = "Equipment: Heat exchanger; Finding: Leak at flange"


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    from app import monthly_report_ai as ai

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))

    def forbidden(*args, **kwargs):
        pytest.fail("Generic issue migration must not call an external model")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)


def report(*tables, rows=(), columns=(), text="", follow_ups=()):
    sections = tuple(section for section in default_sections() if section.key == "issues")
    if columns:
        spec = BlockSpec("equipment_issues", "table", False,
                         columns=tuple(ColumnSpec(str(index), title) for index, title in enumerate(columns)))
        sections = tuple(replace(section, blocks=tuple(
            spec if block.key == spec.key else block for block in section.blocks)) for section in sections)
    return ReportDraft(synthetic_profiles()[0], PERIOD, "Synthetic operator", sections,
        (ResolvedBlock("equipment_issues", "This month", text=text, rows=rows,
                       extra_tables=tuple(tables)),), follow_ups=follow_ups, synthetic=True)


def items(draft):
    return tuple(item for item in draft.follow_ups if item.category == "issue")


def word_source(tmp_path, tables):
    profile = synthetic_profiles()[0]
    document = Document()
    document.add_heading(profile.facilities[0].title, 0)
    document.add_paragraph("Monthly Report · November 2026")
    document.add_heading("8 Equipment Performance Issues", 1)
    for columns, rows in tables:
        table = document.add_table(rows=len(rows) + 1, cols=len(columns))
        for row, values in zip(table.rows, (columns, *rows)):
            for cell, value in zip(row.cells, values):
                cell.text = value
    path = tmp_path / "synthetic-generic-issues.docx"
    document.save(path)
    return path


def import_word(path):
    profile = synthetic_profiles()[0]
    inspection = inspect_docx(path)
    analysis = analyze_starting_report(inspection, profile, PERIOD)
    assert analysis.site_relation == "same"
    plans = automatic_section_plans(inspection, analysis)
    assert all(plan["approved"] for plan in plans.values())
    mapped, _ = build_starting_import(path, inspection, plans.values())
    return imported_draft(profile, PERIOD, "Synthetic operator", mapped)


def word_text(raw):
    document = Document(BytesIO(raw))
    return "\n".join([paragraph.text for paragraph in document.paragraphs] + [
        cell.text for table in document.tables for row in table.rows for cell in row.cells])


def assert_no_prices(raw):
    with ZipFile(BytesIO(raw)) as archive:
        xml = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                        if name.endswith(".xml"))
    for amount in ("$412.50", "$825.00"):
        assert amount not in xml


@pytest.mark.parametrize("table_count", [1, 2])
def test_actual_starting_docx_retains_every_row_in_both_word_renderers(tmp_path, table_count):
    columns = (*COLUMNS, "Cost")
    rows = ((*ROW, "$412.50"), (*ROW, "$825.00"))
    path = word_source(tmp_path, ((columns, rows),) * table_count)
    original = path.read_bytes()
    source = import_word(path)
    tables = next(block for block in source.blocks if block.key == "equipment_issues").extra_tables
    assert len(tables) == table_count
    assert len({table.reference for table in tables}) == table_count
    assert all(table.rows == (ROW, ROW) for table in tables)
    current = canonical_issues(source)
    assert len(items(current)) == 2 * table_count
    assert len({item.key for item in items(current)}) == 2 * table_count
    assert all(item.text == TEXT and item.status == "ongoing" for item in items(current))
    assert not next(block for block in current.blocks if block.key == "equipment_issues").extra_tables
    assert canonical_issues(current) == current
    for raw in (assemble_docx(current, acknowledged_fingerprint=current.fingerprint),
                build_native_docx(current, path, section_key="issues")):
        assert word_text(raw).count("Leak at flange") == 2 * table_count
        assert_no_prices(raw)
    assert path.read_bytes() == original
    assert all(table.rows == (ROW, ROW) for table in tables)


@pytest.mark.parametrize("columns,row,expected", [
    (COLUMNS, ROW, TEXT),
    (("Issue", "Status"), ("Valve leak", "Closed"), "Issue: Valve leak; Status: Closed"),
    (("Equipment", "Equipment"), ("Pump", "Bearing noise"), "Equipment: Pump; Equipment: Bearing noise"),
    (("Equipment",), ("Pump", "Bearing noise"), "Equipment: Pump; Detail 2: Bearing noise"),
    (("Equipment", "Reading", "Notes"), ("Pump", "0", ""), "Equipment: Pump; Reading: 0"),
])
def test_unknown_and_ambiguous_schemas_keep_literal_rows_without_inferred_resolution(columns, row, expected):
    original = report(ReportTable(columns, (row, row), "source:generic"))
    result = canonical_issues(original)
    assert len(items(result)) == 2
    assert [item.text for item in items(result)] == [expected, expected]
    assert len({item.key for item in items(result)}) == 2
    assert all(item.status == "ongoing" and not item.evidence_note for item in items(result))
    assert original.blocks[0].extra_tables[0].rows == (row, row)


@pytest.mark.parametrize("reference", ["", "source:shared"])
def test_identical_tables_with_anonymous_or_shared_references_keep_physical_occurrences(reference):
    table = ReportTable(COLUMNS, (ROW, ROW), reference)
    source = report(table, table)
    current = canonical_issues(source)
    assert len(items(current)) == 4
    assert len({item.key for item in items(current)}) == 4
    assert canonical_issues(merge_drafts(current, source)).follow_ups == current.follow_ups


@pytest.mark.parametrize("references", [("", ""), ("source:first", "source:second")])
def test_nonidentical_tables_can_reorder_without_recreating_edited_or_omitted_cards(references):
    first = ReportTable(COLUMNS, (ROW, ROW), references[0])
    other_row = ("Pump", "Bearing noise")
    second = ReportTable(COLUMNS, (other_row, other_row), references[1])
    source = report(first, second)
    current = canonical_issues(source)
    assert len(items(current)) == 4
    first_item, second_item, *remaining = items(current)
    corrected = replace(first_item, text="Operator confirmed flange leak at the north connection.",
                        status="updated", update="Inspection arranged.")
    omitted = replace(second_item, included=False)
    current = replace(current, follow_ups=(corrected, omitted, *remaining))
    reordered = report(second, first)
    fresh = canonical_issues(reordered)
    assert {item.key for item in items(fresh)} == {item.key for item in items(current)}
    replay = canonical_issues(merge_drafts(current, reordered))
    assert replay.follow_ups == current.follow_ups
    assert replay.follow_ups[0] == corrected and replay.follow_ups[1] == omitted


def test_manual_main_rows_and_equal_anonymous_extra_table_remain_separate():
    source = report(ReportTable(COLUMNS, (ROW, ROW)), rows=(ROW, ROW), columns=COLUMNS)
    current = canonical_issues(source)
    assert len(items(current)) == 4
    assert len({item.key for item in items(current)}) == 4
    assert all(item.text == TEXT for item in items(current))
    assert not current.blocks[0].rows and not current.blocks[0].extra_tables
    assert canonical_issues(merge_drafts(current, source)).follow_ups == current.follow_ups


@pytest.mark.parametrize("status,included", [
    ("ongoing", True), ("ongoing", False), ("updated", True),
    ("updated", False), ("resolved", True), ("resolved", False),
])
def test_legacy_collapsed_card_keeps_all_operator_decisions_without_resurrecting_duplicates(status, included):
    # Earlier versions collapsed these rows. Their one existing decision must
    # not be reassigned to an inferred occurrence or undo an explicit omission.
    old = ReportFollowUp(issue_key(TEXT), "issue", "Operator's corrected finding", PERIOD.key,
        status=status, included=included, update="Existing operator update",
        evidence_note="Operator verified the repair.")
    source = report(ReportTable(COLUMNS, (ROW, ROW)))
    result = canonical_issues(replace(source, follow_ups=(old,)))
    assert result.follow_ups == (old,)
    reopened = library.draft_from_dict(json.loads(json.dumps(asdict(result))))
    assert canonical_issues(merge_drafts(reopened, source)).follow_ups == (old,)


def test_known_different_source_cannot_be_consumed_by_a_legacy_card():
    old = ReportFollowUp(issue_key(TEXT), "issue", "Existing other-source correction", PERIOD.key,
                         included=False, references=("source:first",))
    result = canonical_issues(report(ReportTable(COLUMNS, (ROW, ROW), "source:second"),
                                     follow_ups=(old,)))
    assert len(items(result)) == 3
    assert result.follow_ups[0] == old
    assert [item.text for item in result.follow_ups[1:]] == [TEXT, TEXT]
    assert all(item.references == ("source:second",) for item in result.follow_ups[1:])


def test_equal_text_in_an_independent_manual_card_does_not_consume_source_rows():
    manual = ReportFollowUp("manual-issue", "issue", TEXT, PERIOD.key, included=False)
    result = canonical_issues(report(ReportTable(COLUMNS, (ROW, ROW)), follow_ups=(manual,)))
    assert len(items(result)) == 3
    assert result.follow_ups[0] == manual
    assert all(item.included for item in result.follow_ups[1:])


def test_price_filtered_rows_remain_distinct_without_prices_in_actual_word():
    rows = ((*ROW, "$412.50"), (*ROW, "$825.00"))
    source = report(ReportTable((*COLUMNS, "Cost"), rows))
    result = canonical_issues(source)
    assert len(items(result)) == 2
    assert all(item.text == TEXT for item in items(result))
    raw = assemble_docx(result, acknowledged_fingerprint=result.fingerprint)
    assert word_text(raw).count("Leak at flange") == 2
    assert_no_prices(raw)
    assert source.blocks[0].extra_tables[0].rows == rows


def test_blank_and_price_only_rows_do_not_become_fabricated_issues():
    source = report(ReportTable((*COLUMNS, "Cost"), (
        ("", "", ""), ("", "", "$412.50"), (*ROW, ""), (*ROW, ""))))
    result = canonical_issues(source)
    assert len(items(result)) == 2
    assert all(item.text == TEXT for item in items(result))
    assert canonical_issues(merge_drafts(result, source)).follow_ups == result.follow_ups


def test_omitted_source_table_retains_rows_without_creating_cards():
    source = report(ReportTable(COLUMNS, (ROW, ROW)))
    source = replace(source, blocks=(replace(source.blocks[0], source="Omit"),))
    assert canonical_issues(source) == source


def test_unreviewed_ai_table_keeps_existing_evidence_gate():
    source = report(ReportTable(COLUMNS, (ROW, ROW)))
    block = replace(source.blocks[0], ai_written=True,
                    ai_paragraphs=(DraftParagraph("Unsupported finding", (), (), ("Needs review",)),))
    source = replace(source, blocks=(block,))
    assert canonical_issues(source) == source


def test_recognized_register_rows_keep_existing_distinct_keys_and_literal_closed_status():
    row = ("Valve leak", "Closed", "Synthetic technician")
    source = report(ReportTable(("Issue", "Status", "Owner"), (row, row), "source:register"))
    result = canonical_issues(source)
    assert len(items(result)) == 2 and len({item.key for item in items(result)}) == 2
    assert all(item.status == "ongoing" and "Status: Closed" in item.text for item in items(result))
    assert canonical_issues(merge_drafts(result, source)).follow_ups == result.follow_ups


def test_prose_deduplication_and_no_issue_statement_are_unchanged():
    source = report(text="Pump vibration.\n\nPump vibration.\n\nNo current equipment issues.")
    result = canonical_issues(source)
    assert len(items(result)) == 1 and items(result)[0].text == "Pump vibration."
    assert result.blocks[0].text == "No current equipment issues."


@pytest.mark.parametrize("count", [MAX_INCLUDED_FOLLOWUPS, MAX_INCLUDED_FOLLOWUPS + 1])
def test_retention_does_not_silently_truncate_rows_or_raise_the_output_limit(count):
    result = canonical_issues(report(ReportTable(COLUMNS, (ROW,) * count)))
    assert len(items(result)) == count
    assert len({item.key for item in items(result)}) == count
    assert bool(followup_limit_message(result)) == (count > MAX_INCLUDED_FOLLOWUPS)
    if count > MAX_INCLUDED_FOLLOWUPS:
        with pytest.raises(ValueError, match="output limit"):
            assemble_docx(result, acknowledged_fingerprint=result.fingerprint)


START_APP = '''
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_ui import _field
p = synthetic_profiles()[0]
render_section_setup(p.contract, ReportPeriod(2026, 11), "Synthetic operator", _field, identity=p)
'''

ISSUE_APP = '''
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_issues import render_issue_cards
from app.monthly_report_ui import _field
st.session_state['draft'] = render_issue_cards(st.session_state['draft'], 'generic_issue_rows', _field)
if st.button('Save synthetic report'):
    saved = library.save_snapshot(st.session_state['draft'],
        expected_revision=st.session_state.get('revision', 0), entered_editor='Synthetic operator')
    st.session_state['revision'] = saved.revision
'''


def issue_app(draft, revision=0):
    app = AppTest.from_string(ISSUE_APP, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["revision"] = revision
    app.run()
    assert not app.exception
    return app


def test_starting_upload_edit_omit_save_reopen_reimport_and_two_rollovers(tmp_path, monkeypatch):
    from app import monthly_report_section_ui as ui

    path = word_source(tmp_path, ((COLUMNS, (ROW, ROW)),))
    original = path.read_bytes()
    upload = BytesIO(original)
    upload.name, upload.size = path.name, len(original)
    native = ui.st.file_uploader

    def transported(label, *args, **kwargs):
        actual = native(label, *args, **kwargs)
        return upload if label == "Starting report" else actual

    monkeypatch.setattr(ui.st, "file_uploader", transported)
    start = AppTest.from_string(START_APP, default_timeout=30).run()
    assert not start.exception
    assert len(start.get("file_uploader")) >= 1
    next(button for button in start.button if button.label == "Continue to this month’s updates").click().run()
    assert not start.exception and not start.error
    profile = synthetic_profiles()[0]
    source = library.load_imported_draft(profile.contract, profile.key)
    assert source is not None
    app = issue_app(source)
    fields = [field for field in app.text_area if field.label == "Issue description"]
    assert len(fields) == 2
    original_keys = tuple(item.key for item in items(app.session_state["draft"]))
    fields[0].set_value("Operator confirmed flange leak at the north connection.").run()
    next(button for button in app.button if button.label == "Save synthetic report").click().run()
    first = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert first.revision == 1
    assert first.draft.follow_ups[0].text == "Operator confirmed flange leak at the north connection."
    [button for button in app.button if button.label == "Remove from this report"][1].click().run()
    next(button for button in app.button if button.label == "Save synthetic report").click().run()
    assert not app.exception and not app.error
    saved = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert saved.revision == 2
    assert tuple(item.key for item in items(saved.draft)) == original_keys
    assert saved.draft.follow_ups[0].included and not saved.draft.follow_ups[1].included
    assert saved.draft.follow_ups[1].text == TEXT
    assert library.load_snapshot_version(profile.contract, profile.key, PERIOD, 1) == first
    reopened = issue_app(saved.draft, saved.revision)
    assert len([field for field in reopened.text_area if field.label == "Issue description"]) == 1
    reopened.run()
    assert reopened.session_state["draft"] == saved.draft
    assert library.load_snapshot(profile.contract, profile.key, PERIOD) == saved
    replay = canonical_issues(merge_drafts(saved.draft, source))
    assert replay.follow_ups == saved.draft.follow_ups
    # Starting a report leaves its other required sections unfinished. Their
    # normal full-report gate remains; inspect this issue section's output.
    with pytest.raises(ValueError, match="Resolve required block"):
        assemble_docx(replay, acknowledged_fingerprint=replay.fingerprint)
    raw = section_preview_docx(replay, "issues")
    assert word_text(raw).count("Operator confirmed flange leak at the north connection.") == 1
    assert "Leak at flange" not in word_text(raw)
    following = new_month_draft(replay, ReportPeriod(2026, 12))
    later = new_month_draft(following, ReportPeriod(2027, 1))
    for draft in (following, later):
        assert tuple(item.key for item in items(draft)) == original_keys
        assert all(item.included for item in items(draft))
        assert [item.text for item in items(draft)] == [item.text for item in items(saved.draft)]
    assert library.load_snapshot(profile.contract, profile.key, PERIOD) == saved
    assert path.read_bytes() == original


@requires_libreoffice
def test_real_native_pdf_preserves_both_generic_issue_rows_without_prices(tmp_path, monkeypatch):
    import pymupdf as fitz
    from app import pdf_converter

    columns = (*COLUMNS, "Cost")
    path = word_source(tmp_path, ((columns, ((*ROW, "$412.50"), (*ROW, "$825.00"))),))
    original = path.read_bytes()
    draft = canonical_issues(import_word(path))
    assert len(items(draft)) == 2
    assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    raw = build_native_docx(draft, path, section_key="issues")
    assert word_text(raw).count("Leak at flange") == 2
    assert_no_prices(raw)
    output_path = tmp_path / "synthetic-generic-issue-output.docx"
    output_path.write_bytes(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    pdf = pdf_converter.convert_to_pdf(output_path).read_bytes()
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
    assert text.count("Leak at flange") == 2
    assert "$412.50" not in text and "$825.00" not in text
    assert path.read_bytes() == original
    if directory := os.environ.get("INDEPENDENT_OUTPUT"):
        artifacts = Path(directory) / "generic-issue-rows"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "synthetic-issues.docx").write_bytes(raw)
        (artifacts / "synthetic-issues.pdf").write_bytes(pdf)
        (artifacts / "synthetic-source.docx").write_bytes(original)
        (artifacts / "manifest.json").write_text(json.dumps({
            "fixture": "synthetic generic issue rows", "source_unchanged": True,
            "expected_finding_occurrences": 2, "pdf_finding_occurrences": text.count("Leak at flange"),
            "source_sha256": sha256(original).hexdigest(), "docx_sha256": sha256(raw).hexdigest(),
            "pdf_sha256": sha256(pdf).hexdigest(), "commit": os.environ.get("MSAPO_SHA", ""),
            "model_calls": 0,
        }, indent=2))
