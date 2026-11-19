"""Synthetic roster-shaped Training evidence and duplicate-completion regressions.

These rows are fabricated. The saved originals and original physical row
references must remain intact when duplicate *events* collapse to one output.
"""
from dataclasses import replace

import pytest

from app.monthly_report_model import ResolvedBlock
from app.monthly_report_training import EVENT_REF
from app.monthly_report_training_import import (
    accepted_training_block, correct_training_row, exclude_training_row,
    restore_training_review, training_review_record, review_training_event_source,
)
from test_monthly_report_training_import import PROFILE, PERIOD, ingest, reviewed


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return tmp_path


def test_singular_roster_staff_scope_and_exact_event_duplicates(storage):
    original = (
        b"Course,Date,Method,Attendee,Hours,Completion Status,Staff type\n"
        b"Pump orientation,2026-09-13,In person,Alice,1,Completed,Hospital staff\n"
        b"Pump orientation,2026-09-13,In person,Alice,1,Completed,Hospital staff\n"
        b"Pump orientation,2026-09-13,In person,Morgan; Jordan,1,Completed,Service provider\n"
    )
    content = ingest("synthetic_training_roster.csv", original)
    review = reviewed(content, "events")
    assert review.ready_for_import
    assert len(review.rows) == 3, "Every physical source row remains inspectable"
    assert [row.origin.row_number for row in review.rows] == [2, 3, 4]
    assert review.rows[0].values[3] == "Hospital/client staff: Alice"
    assert review.rows[1].values[3] == "Hospital/client staff: Alice"
    assert review.rows[2].values[3] == "Service provider staff: Morgan; Service provider staff: Jordan"
    assert all(not row.issues and not row.excluded for row in review.rows)
    receipt = training_review_record(review)
    assert restore_training_review(receipt) == review
    original_block = ResolvedBlock("training_summary", "This month",
                                   text="Human-authored technical Training notes")
    block = accepted_training_block(review, original_block,
                                    expected_block_fingerprint=original_block.fingerprint)
    events = next(t for t in block.extra_tables if t.reference == EVENT_REF)
    assert len(events.rows) == 2, "One identical attendance record must not double-count completion"
    assert events.rows[0] == (
        "Pump orientation", "2026-09-13", "In person", "Hospital/client staff: Alice", "1")
    assert events.rows[1] == (
        "Pump orientation", "2026-09-13", "In person", "Service provider staff: Morgan; Service provider staff: Jordan", "1")
    assert block.text == original_block.text
    assert block.references == (review.source.reference,)
    assert accepted_training_block(review, block, expected_block_fingerprint=block.fingerprint) == block
    from app import monthly_report_sources as sources
    assert sources.source_bytes(PROFILE, content.source) == original


def test_roster_fails_closed_on_unverified_completion_hours_staff_role_and_old_dates(storage):
    original = (
        b"Course,Date,Format,Participant,Hours,Status,Participant type\n"
        b"Current safe session,2026-09-12,Virtual,Alice,,Completed,Client staff\n"
        b"Prior completed session,2026-08-12,Virtual,Alice,1,Completed,Client staff\n"
        b"Pending instructor visit,2026-09-12,Virtual,Bob,1,Scheduled,Service provider\n"
        b"Invalid duration,2026-09-12,Virtual,Casey,-3,Completed,Client staff\n"
        b"Unknown staffing group,2026-09-12,Virtual,Lee,1,Completed,Outside agency\n"
    )
    review = reviewed(ingest("synthetic_roster_with_gaps.csv", original), "events")
    assert len(review.rows) == 5 and not review.ready_for_import
    assert review.rows[0].values[4] == "" and not review.rows[0].issues
    assert "Historical/other-month" in " ".join(review.rows[1].issues)
    assert "does not show completed" in " ".join(review.rows[2].issues)
    assert "Hours must be positive" in " ".join(review.rows[3].issues)
    assert "staff type" in " ".join(review.rows[4].issues).lower()
    original_unknown = review.rows[-1].origin.cells
    corrected_unknown = correct_training_row(
        review, review.rows[-1].key, {"Participants": "Service provider staff: Lee"},
        expected_revision=review.revision, profile=PROFILE, period=PERIOD)
    assert not corrected_unknown.rows[-1].issues
    assert corrected_unknown.rows[-1].origin.cells == original_unknown
    review = corrected_unknown
    for row in review.rows[1:]:
        review = exclude_training_row(review, row.key, expected_revision=review.revision)
    assert review.ready_for_import
    current = ResolvedBlock("training_summary", "This month")
    accepted = accepted_training_block(review, current,
                                       expected_block_fingerprint=current.fingerprint)
    assert next(t.rows for t in accepted.extra_tables if t.reference == EVENT_REF) == (
        ("Current safe session", "2026-09-12", "Virtual", "Hospital/client staff: Alice", ""),)
    # A second view's current receipt must reject the previous view's stale edit.
    stale_revision = review.revision
    updated = correct_training_row(
        review, review.rows[0].key, {"Hours": "1"},
        expected_revision=stale_revision, profile=PROFILE, period=PERIOD)
    assert updated.revision != stale_revision
    with pytest.raises(ValueError, match="changed"):
        correct_training_row(
            updated, updated.rows[0].key, {"Hours": "2"},
            expected_revision=stale_revision, profile=PROFILE, period=PERIOD)
    assert restore_training_review(training_review_record(updated)) == updated


def test_older_saved_review_cannot_bypass_new_staff_role_scope(storage):
    original = (
        b"Course,Date,Method,Attendee,Hours,Status,Personnel type\n"
        b"Generator safety,2026-09-08,Virtual,Morgan,1,Completed,Vendor\n"
    )
    review = reviewed(ingest("prior_undifferentiated_roster.csv", original), "events")
    assert review.ready_for_import
    legacy = replace(review, rows=(
        replace(review.rows[0], values=(
            "Generator safety", "2026-09-08", "Virtual", "Morgan", "1")),))
    assert not legacy.rows[0].issues, "This simulates a valid older, undifferentiated receipt"
    checked = review_training_event_source(legacy, PROFILE)
    assert not checked.ready_for_import
    assert "staff type label" in " ".join(checked.rows[0].issues)
    block = ResolvedBlock("training_summary", "This month")
    with pytest.raises(ValueError, match="Review"):
        accepted_training_block(checked, block, expected_block_fingerprint=block.fingerprint)
    corrected = correct_training_row(
        checked, checked.rows[0].key, {"Participants": "Service provider staff: Morgan"},
        expected_revision=checked.revision, profile=PROFILE, period=PERIOD)
    assert corrected.ready_for_import
    assert corrected.rows[0].origin.cells[-1] == "Vendor"


REQUIREMENTS_HEADER = b"Team member,Site,Safety refresher,Operations update\n"


def test_exact_repeated_requirement_rows_import_as_one_row(storage):
    original = (REQUIREMENTS_HEADER
                + b"Alice Smith,North,Completed,\n"
                + b"Jo,South,Pending,Not required\n"
                + b"Alice Smith,North,Completed,\n")
    content = ingest("synthetic_requirements_repeat.csv", original)
    review = reviewed(content, "requirements", source_year=2026)
    assert review.ready_for_import
    assert len(review.rows) == 3, "Every physical source row remains inspectable"
    assert all(not row.issues and not row.excluded for row in review.rows)
    block = ResolvedBlock("training_summary", "This month", text="Human-authored note")
    updated = accepted_training_block(
        review, block, expected_block_fingerprint=block.fingerprint)
    matrix, = updated.extra_tables
    assert matrix.rows == (("Alice Smith", "Site North", "Completed", ""),
                           ("Jo", "Site South", "Pending", "Not required"))
    assert updated.text == block.text
    assert updated.references == (review.source.reference,)
    assert accepted_training_block(
        review, updated, expected_block_fingerprint=updated.fingerprint) == updated
    from app import monthly_report_sources as sources
    assert sources.source_bytes(PROFILE, content.source) == original


@pytest.mark.parametrize("repeat", [
    b"Alice Smith,North,Pending,\n",     # conflicting status
    b"alice smith,North,Completed,\n",   # same person, different case
    b"Alice  Smith,North,Completed,\n",  # same person, different spacing
], ids=["status", "case", "spacing"])
def test_other_repeated_requirement_identities_stay_in_review(storage, repeat):
    content = ingest("synthetic_requirements_conflict.csv",
                     REQUIREMENTS_HEADER + b"Alice Smith,North,Completed,\n" + repeat)
    review = reviewed(content, "requirements", source_year=2026)
    assert not review.ready_for_import
    assert all("Duplicate Training source row needs review." in row.issues
               for row in review.rows)
    block = ResolvedBlock("training_summary", "This month")
    with pytest.raises(ValueError, match="Review unknown Training rows"):
        accepted_training_block(review, block, expected_block_fingerprint=block.fingerprint)
    kept = exclude_training_row(review, review.rows[1].key, expected_revision=review.revision)
    assert kept.ready_for_import
    matrix, = accepted_training_block(
        kept, block, expected_block_fingerprint=block.fingerprint).extra_tables
    assert matrix.rows == (("Alice Smith", "Site North", "Completed", ""),)
