"""Competing event fields stay unresolved after spreadsheet heading numbering."""
from dataclasses import asdict, replace
from datetime import date
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import monthly_report_training_review_flow as flow
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_source_scope import correct_scope
from app.monthly_report_training import add_event
from app.monthly_report_training_import import (
    accepted_training_block, restore_training_review, training_review_record,
)
from test_training_event_site_scope import (
    APP, COLUMNS, EVENT, PERIOD, PROFILE, click, draft_for, parsed_draft,
    prepare, publish, spreadsheet_bytes, template, widget,
)


CONFLICTS = (
    ("Topic", "Different source topic"),
    ("Date", "2026-08-13"),
    ("Format", "In person"),
    ("Participants", "Other Staff"),
    ("Hours", "8"),
    ("Status", "Cancelled"),
)


def conflict_bytes(suffix, heading="Status", value="Cancelled", event=EVENT):
    return spreadsheet_bytes(suffix, (*COLUMNS, heading), ((*event, value),))


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("heading, conflict", CONFLICTS)
def test_real_parser_duplicate_event_fields_require_review(monkeypatch, suffix, heading, conflict):
    raw = conflict_bytes(suffix, heading, conflict)
    draft, value, request = prepare(parsed_draft(monkeypatch, raw, suffix))
    current = restore_training_review(value["record"])
    assert current.original_columns[-1] == heading + " (2)"
    assert not current.ready_for_import
    assert any("column" in message.casefold() for message in current.issues)
    assert current.rows[0].origin.cells == (*EVENT, conflict)
    assert current.source.rows[0] == (*EVENT, conflict)
    with pytest.raises(ValueError, match="Review"):
        publish(draft, value, request)
    assert not draft.blocks[0].extra_tables


@pytest.mark.parametrize("alias", ["Course", "Training Date", "Method", "Attendees", "Duration Hours", "Completion Status"])
def test_existing_distinct_alias_ambiguity_policy_remains_closed(monkeypatch, alias):
    draft, value, _ = prepare(parsed_draft(monkeypatch, conflict_bytes(".csv", alias, "Competing source value")))
    current = restore_training_review(value["record"])
    assert not current.ready_for_import
    assert current.original_columns[-1] == alias
    assert current.source.rows[0][-1] == "Competing source value"
    assert not draft.blocks[0].extra_tables


@pytest.mark.parametrize("heading", ["Hours (2)", "Hours (10)", "Hours (2) (2)"])
def test_authored_adapter_shaped_event_heading_cannot_authorize_a_choice(monkeypatch, heading):
    # An authored spelling identical to adapter output supplies no authority
    # to choose or ignore the number; preserve it and require source review.
    columns = tuple(heading if name == "Hours" else name for name in COLUMNS)
    raw = spreadsheet_bytes(".csv", columns, (EVENT,))
    _, value, _ = prepare(parsed_draft(monkeypatch, raw))
    current = restore_training_review(value["record"])
    assert not current.ready_for_import
    assert current.original_columns[4] == heading
    assert current.rows[0].origin.cells[4] == "1"


@pytest.mark.parametrize("heading", ["Status Notes (2)", "Hours (1)", "Hours(2)", "Hours (02)", "Hours 2"])
def test_unrelated_headings_do_not_create_event_ambiguity(monkeypatch, heading):
    _, value, _ = prepare(parsed_draft(monkeypatch, conflict_bytes(".csv", heading, "Unknown source detail")))
    current = restore_training_review(value["record"])
    assert current.ready_for_import
    assert current.rows[0].values == EVENT[:5]
    assert current.unmapped_cells(current.rows[0].key)[-1] == (6, heading, "Unknown source detail")


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("optional", [True, False])
def test_unique_headers_and_unknown_optional_values_keep_current_behavior(monkeypatch, suffix, optional):
    columns, event = (COLUMNS, EVENT) if optional else (COLUMNS[:4] + COLUMNS[5:], EVENT[:4] + EVENT[5:])
    draft, value, request = prepare(parsed_draft(monkeypatch, spreadsheet_bytes(suffix, columns, (event,)), suffix))
    current = restore_training_review(value["record"])
    assert current.ready_for_import
    accepted = publish(draft, value, request)
    assert accepted.blocks[0].extra_tables[0].rows[0] == (*EVENT[:4], "1" if optional else "")
    assert accepted.blocks[0].text == "Manual notes"


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("heading, conflict", [CONFLICTS[0], CONFLICTS[1], CONFLICTS[4], CONFLICTS[5]])
def test_actual_review_controls_refuse_ambiguous_new_and_old_receipts(monkeypatch, suffix, retained, heading, conflict):
    draft = parsed_draft(monkeypatch, conflict_bytes(suffix, heading, conflict), suffix)
    if retained:
        draft, value, _ = prepare(draft)
        current = restore_training_review(value["record"])
        old = replace(current, issues=())
        draft = flow.store_review(draft, {**value, "record": training_review_record(old)}, flow.revision(value))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    if not retained:
        click(app, "Review this Training table")
    before = app.session_state["draft"]
    assert any("column" in item.value.casefold() for item in app.info)
    assert any(conflict in item.value for item in app.text)
    # Merely viewing an old receipt must not persist a migration or new revision.
    if retained:
        assert before == draft
    click(app, "Include reviewed Training rows")
    assert app.session_state["draft"] == before
    assert any("Review" in item.value for item in app.warning)
    widget(app, "text_input", "Hours").set_value("1.5")
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    assert not app.session_state["draft"].blocks[0].extra_tables


def test_old_historical_receipt_cannot_bypass_conflicting_status(monkeypatch):
    event = (EVENT[0], "2026-08-13", *EVENT[2:])
    draft, value, request = prepare(parsed_draft(monkeypatch, conflict_bytes(".csv", event=event)))
    current = restore_training_review(value["record"])
    old = replace(current, issues=())
    old_value = {**value, "record": training_review_record(old), "history": [old.rows[0].key]}
    retained = flow.store_review(draft, old_value, flow.revision(value))
    with pytest.raises(ValueError, match="Review"):
        publish(retained, old_value, request)
    assert retained.blocks == draft.blocks
    assert flow.encoded(flow.saved_review(retained, retained.sources[0], 1)) == flow.encoded(old_value)


def test_prior_published_rows_and_later_edits_are_never_rewritten(monkeypatch):
    draft, value, request = prepare(parsed_draft(monkeypatch, conflict_bytes(".csv")))
    current = restore_training_review(value["record"])
    old = replace(current, issues=())
    block = accepted_training_block(old, draft.blocks[0], expected_block_fingerprint=draft.blocks[0].fingerprint)
    legacy = {**value, "record": training_review_record(old)}
    legacy = {**legacy, "published": {"decision": flow.revision((legacy["record"], [], False)),
        "block": block.fingerprint, "before": asdict(draft.blocks[0]),
        "replace_source": False, "replace_matrix": False}}
    saved = flow.store_review(replace(draft, blocks=(block,)), legacy, flow.revision(value))
    edited = replace(saved, blocks=(replace(block, text="Later manual note", extra_tables=()),))
    assert publish(saved, legacy, request) == saved
    assert publish(edited, legacy, request) == edited


def test_refused_import_preserves_manual_session_and_actual_word(monkeypatch, tmp_path):
    draft = parsed_draft(monkeypatch, conflict_bytes(".csv"))
    manual = add_event(None, title="Existing accepted session", when=date(2026, 9, 2),
        mode="In person", participants=("Existing Staff",), hours="", period=PERIOD)
    draft = replace(draft, blocks=(replace(draft.blocks[0], extra_tables=(manual,)),))
    prepared, value, request = prepare(draft)
    with pytest.raises(ValueError, match="Review"):
        publish(prepared, value, request)
    assert prepared.blocks == draft.blocks
    path = template(tmp_path)
    before = path.read_bytes()
    output = Document(BytesIO(_build_native_docx(prepared, path, section_key="training")))
    rows = [tuple(cell.text for cell in row.cells) for table in output.tables for row in table.rows]
    assert rows.count(manual.rows[0]) == 1
    assert not any(EVENT[0] in row for row in rows)
    assert path.read_bytes() == before


def test_public_storage_ambiguous_receipt_history_and_corrected_source(tmp_path, monkeypatch):
    """Real ingestion/save/history/public output remains a required Linux check."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    raw = conflict_bytes(".csv")
    content, _ = sources.ingest(PROFILE, "ambiguous.csv", raw)
    content = replace(content, source=correct_scope(content.source, PROFILE, ("north",)))
    draft, value, request = prepare(draft_for(content))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    receipt = flow.saved_review(reopened, reopened.sources[0], 1)
    with pytest.raises(ValueError, match="Review"):
        publish(reopened, receipt, request)
    corrected_raw = spreadsheet_bytes(".csv", COLUMNS, (EVENT,))
    corrected, _ = sources.ingest(PROFILE, "corrected.csv", corrected_raw)
    corrected = replace(corrected, source=correct_scope(corrected.source, PROFILE, ("north",)))
    next_draft = replace(reopened, sources=(corrected.source, *reopened.sources))
    prepared, reviewed, next_request = prepare(next_draft)
    accepted = publish(prepared, reviewed, next_request)
    library.save_snapshot(accepted, expected_revision=saved.revision, entered_editor="Synthetic Editor")
    assert library.load_snapshot_version(PROFILE.contract, PROFILE.key, PERIOD, saved.revision) == saved
    assert sources.source_bytes(PROFILE, content.source) == raw
    assert sources.source_bytes(PROFILE, corrected.source) == corrected_raw
    output = Document(BytesIO(build_native_docx(accepted, template(tmp_path), section_key="training")))
    rows = [tuple(cell.text for cell in row.cells) for table in output.tables for row in table.rows]
    assert rows.count(EVENT[:5]) == 1
