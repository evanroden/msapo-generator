"""Explicit Training decisions survive storage without altering their originals."""
from dataclasses import replace
from datetime import date
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_training_review_flow as flow
from app.monthly_report_training_import import restore_training_review
from app.monthly_report_model import (Facility, ReportProfile, ReportPeriod, ReportDraft,
    ResolvedBlock, SectionSpec, BlockSpec)
from app.monthly_report_training import EVENT_REF, add_event, load_training
from app.monthly_report_source_scope import correct_scope

CSV = (b"Topic,Date,Method,Participants,Hours,Status,Unknown evidence\n"
       b"Current drill,2026-09-13,Virtual,Alice,,Completed,Original A\n"
       b"Prior drill,2026-08-11,In person,Bob,2,Completed,Original B\n"
       b"Incomplete,,,,,Pending,Original C\n")


def report(raw=CSV, name="training.csv"):
    profile = ReportProfile("Invented Training Review", "north", "Synthetic North",
                            (Facility("north", "Synthetic North"),))
    content, _ = sources.ingest(profile, name, raw)
    source = correct_scope(content.source, profile, ("north",))
    section = SectionSpec("training", "12", "Training Summary", (BlockSpec("training_summary", "rich_text"),))
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", (section,),
        (ResolvedBlock("training_summary", "This month", text="Manual notes"),), sources=(source,), synthetic=True)


@pytest.fixture(autouse=True)
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))


def prepared(draft):
    value = flow.prepare_review(draft, draft.sources[0], 1)
    return flow.store_review(draft, value), value


def selected(draft, value):
    original = flow.revision(value)
    review = restore_training_review(value["record"])
    for row in review.rows:
        value = flow.change_row(draft, value, row.key,
            dict(zip((*review.normalized_columns, "Completion status"), (*row.values, row.status))),
            excluded=row.values[0] == "Incomplete", historical=row.values[0] == "Prior drill")
    return flow.store_review(draft, value, original), value


def publish(draft, value, **kwargs):
    return flow.publish_review(draft, value, expected_revision=flow.revision(value),
                               expected_block=draft.blocks[0].fingerprint, **kwargs)


def test_known_current_and_deliberate_history_publish_once_with_unknowns_preserved():
    draft, value = prepared(report())
    draft, value = selected(draft, value)
    accepted = publish(draft, value)
    block = accepted.blocks[0]
    events = next(t for t in block.extra_tables if t.reference == EVENT_REF)
    history = next(t for t in block.extra_tables if t.reference.startswith("training:history:"))
    assert events.rows == (("Current drill", "2026-09-13", "Virtual", "Alice", ""),)
    assert history.rows == (("Prior drill", "2026-08-11", "In person", "Bob", "2"),)
    assert history.columns[0] == "Historical training"
    saved = flow.saved_review(accepted, accepted.sources[0], 1)
    original = restore_training_review(saved["record"])
    assert original.rows[-1].origin.cells[-1] == "Original C"
    assert original.rows[-1].excluded
    assert sources.source_bytes(accepted.profile, accepted.sources[0]) == CSV
    assert load_training(accepted.profile.contract)["revision"] == 0
    assert publish(accepted, saved) == accepted


def test_snapshot_reopen_receipt_and_repeat_import_preserve_later_manual_deletion():
    draft, value = selected(*prepared(report()))
    accepted = publish(draft, value)
    saved = library.save_snapshot(accepted, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(accepted.profile.contract, accepted.profile.key, accepted.period).draft
    assert reopened == saved.draft
    edited = replace(reopened, blocks=(replace(reopened.blocks[0], text="Later author note", extra_tables=()),))
    receipt = flow.saved_review(edited, edited.sources[0], 1)
    assert publish(edited, receipt) == edited
    assert restore_training_review(receipt["record"]).rows[0].values[-1] == ""


def test_stale_publication_and_stale_review_cannot_change_newer_values():
    draft, value = selected(*prepared(report()))
    newer = replace(draft, blocks=(replace(draft.blocks[0], text="Newer work"),))
    with pytest.raises(ValueError, match="Training changed"):
        flow.publish_review(newer, value, expected_revision=flow.revision(value),
                            expected_block=draft.blocks[0].fingerprint)
    with pytest.raises(ValueError, match="saved Training review changed"):
        flow.store_review(draft, value, "stale")
    assert newer.blocks[0].text == "Newer work"


def test_unknown_and_false_completion_cannot_be_included_as_history():
    draft, value = prepared(report(CSV.replace(b"Bob,2,Completed", b"Bob,2,Pending")))
    draft, value = selected(draft, value)
    with pytest.raises(ValueError, match="historical dates, completion"):
        publish(draft, value)
    assert not draft.blocks[0].extra_tables


def test_corrupt_or_replaced_original_blocks_acceptance(tmp_path):
    draft, value = selected(*prepared(report()))
    path = sources._path(draft.profile, draft.sources[0].sha256, ".csv")
    path.chmod(0o600)  # Deliberately corrupt only this isolated synthetic original.
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        publish(draft, value)
    assert not draft.blocks[0].extra_tables


def test_changed_source_or_period_never_borrows_old_decisions():
    draft, value = selected(*prepared(report()))
    with pytest.raises(ValueError, match="different report or month"):
        flow.store_review(replace(draft, period=ReportPeriod(2026, 10)), value)
    with pytest.raises(ValueError, match="source changed"):
        flow.store_review(replace(draft, sources=(replace(draft.sources[0], filename="different.csv"),)), value)


def test_history_only_has_truthful_dates_and_no_current_session():
    draft, value = prepared(report(b"Topic,Date,Method,Participants,Hours,Status\nOld drill,2026-08-11,Virtual,Alice,,Completed\n"))
    review = restore_training_review(value["record"])
    row = review.rows[0]
    changed = flow.change_row(draft, value, row.key,
        dict(zip((*review.normalized_columns, "Completion status"), (*row.values, row.status))), historical=True)
    draft = flow.store_review(draft, changed, flow.revision(value))
    accepted = publish(draft, changed)
    assert len(accepted.blocks[0].extra_tables) == 1
    assert accepted.blocks[0].extra_tables[0].reference.startswith("training:history:")


def test_current_and_history_word_output_has_each_selected_row_once():
    from app.monthly_report_docx import assemble_docx
    draft, value = selected(*prepared(report()))
    accepted = publish(draft, value)
    raw = assemble_docx(accepted, acknowledged_fingerprint=accepted.fingerprint)
    doc = Document(BytesIO(raw))
    cells = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert cells.count("Current drill") == cells.count("Prior drill") == 1
    assert "Historical training" in cells and "2026-08-11" in cells
    assert "Incomplete" not in cells and "Original C" not in cells


def test_two_month_rollovers_cannot_turn_history_or_requirements_into_current_events():
    from app.monthly_report_setup import new_month_draft
    draft, value = selected(*prepared(report()))
    accepted = publish(draft, value)
    october = new_month_draft(accepted, ReportPeriod(2026, 10))
    november = new_month_draft(october, ReportPeriod(2026, 11))
    for later in (october, november):
        assert not later.source_row_reviews
        assert not any(t.rows for b in later.blocks for t in b.extra_tables)
    assert accepted.blocks[0].extra_tables[0].rows


def test_corrected_published_review_replaces_exact_previous_rows_without_duplicates():
    draft, value = selected(*prepared(report()))
    accepted = publish(draft, value)
    previous = flow.saved_review(accepted, accepted.sources[0], 1)
    review = restore_training_review(previous["record"])
    changed = flow.change_row(accepted, previous, review.rows[0].key, {"Hours": "1.25"})
    accepted = flow.store_review(accepted, changed, flow.revision(previous))
    updated = publish(accepted, changed)
    event = next(t for t in updated.blocks[0].extra_tables if t.reference == EVENT_REF)
    assert event.rows == (("Current drill", "2026-09-13", "Virtual", "Alice", "1.25"),)
    assert len(updated.blocks[0].extra_tables) == 2
    assert updated.blocks[0].text == "Manual notes"


def test_corrected_source_review_preserves_conflicting_manual_report_edit():
    draft, value = selected(*prepared(report()))
    accepted = publish(draft, value)
    previous = flow.saved_review(accepted, accepted.sources[0], 1)
    review = restore_training_review(previous["record"])
    changed = flow.change_row(accepted, previous, review.rows[0].key, {"Hours": "1.25"})
    accepted = flow.store_review(accepted, changed, flow.revision(previous))
    newer = replace(accepted, blocks=(replace(accepted.blocks[0], text="Manual after import"),))
    with pytest.raises(ValueError, match="edited after this import"):
        publish(newer, changed)
    assert restore_training_review(changed["record"]).rows[0].values[-1] == "1.25"
    assert newer.blocks[0].text == "Manual after import"


def test_raw_source_table_replacement_is_explicit_and_occurs_once():
    from app.monthly_report_model import ReportTable
    draft, value = selected(*prepared(report()))
    review = restore_training_review(value["record"])
    raw = ReportTable(review.source.columns, review.source.rows, review.source.reference)
    draft = replace(draft, blocks=(replace(draft.blocks[0], extra_tables=(raw,)),))
    with pytest.raises(ValueError, match="Confirm replacing"):
        publish(draft, value)
    assert draft.blocks[0].extra_tables == (raw,)
    accepted = publish(draft, value, replace_source=True)
    assert raw not in accepted.blocks[0].extra_tables
    assert len(accepted.blocks[0].extra_tables) == 2
    assert sources.source_bytes(draft.profile, draft.sources[0]) == CSV


def test_requirement_replacement_preserves_manual_events_and_shared_state():
    from app.monthly_report_model import ReportTable
    from app.monthly_report_training import year_matrix_reference
    draft = report(b"Team member,Site,Safety\nAlice,Synthetic North,Completed\n")
    events = add_event(None, title="Manual drill", when=date(2026, 9, 2), mode="Virtual",
                       participants=("Bob",), hours="", period=draft.period)
    old = ReportTable(("Team member", "Site", "Old requirement"),
                     (("Bob", "Synthetic North", "Pending"),), year_matrix_reference(2026))
    draft = replace(draft, blocks=(replace(draft.blocks[0], extra_tables=(old, events)),))
    value = flow.prepare_review(draft, draft.sources[0], 1, 2026)
    draft = flow.store_review(draft, value)
    with pytest.raises(ValueError, match="different standing"):
        publish(draft, value)
    accepted = publish(draft, value, replace_matrix=True)
    assert events in accepted.blocks[0].extra_tables
    assert old not in accepted.blocks[0].extra_tables
    assert load_training(draft.profile.contract)["revision"] == 0
