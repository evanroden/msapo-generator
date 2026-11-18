"""A84: synthetic stale-write controls and explicit field-level reconciliation."""
from dataclasses import replace
import json

import pytest

from app import monthly_report_library as library
from app.monthly_report_conflict_merge import merge_drafts
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, TrainingSessionTable, default_sections,
)
from app.monthly_report_training import EVENT_COLUMNS, EVENT_REF, MATRIX_REF, load_training, save_training


def draft():
    profile = ReportProfile("Synthetic Collaboration", "north", "North", (Facility("north", "North"),))
    block = ResolvedBlock("activity_summary", "This month", text="Accepted baseline")
    contacts = ResolvedBlock("site_contacts", "This month",
                             rows=(("Alice", "555-0100", "alice@example.test"),
                                   ("Bob", "555-0200", "bob@example.test")))
    matrix = ReportTable(("Team member", "Site", "Safety", "Cooling"),
                         (("Alice", "North", "Pending", "Pending"),
                          ("Bob", "North", "Pending", "Pending")), MATRIX_REF)
    sessions = TrainingSessionTable(EVENT_COLUMNS,
                                   (("Safety", "2026-09-01", "Virtual", "Alice", "1"),
                                    ("Cooling", "2026-09-02", "Virtual", "Bob", "1")),
                                   EVENT_REF, ("event-a", "event-b"))
    training = ResolvedBlock("training_summary", "This month", extra_tables=(matrix, sessions))
    return ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic editor",
                       default_sections(), (block, contacts, training),
                       source_row_reviews=('{"source":"first","state":"reviewed"}',))


def update(d, block_key, **kwargs):
    return replace(d, blocks=tuple(replace(b, **kwargs) if b.key == block_key else b for b in d.blocks))


def block(d, key):
    return next(b for b in d.blocks if b.key == key)


def test_disjoint_report_and_source_edits_merge_without_dropping_baseline():
    base = draft()
    page = update(base, "activity_summary", text="Corrected local summary")
    remote = replace(base, prepared_by="Synthetic second editor")
    merged, conflicts = merge_drafts(base, page, remote)
    assert not conflicts
    assert merged.prepared_by == remote.prepared_by
    assert block(merged, "activity_summary").text == "Corrected local summary"
    assert block(merged, "site_contacts") == block(base, "site_contacts")
    assert merged.source_row_reviews == base.source_row_reviews


def test_same_field_retains_both_original_copies_until_exact_decision():
    base = draft()
    page = update(base, "activity_summary", text="Local approved wording")
    remote = update(base, "activity_summary", text="Newer approved wording")
    merged, conflicts = merge_drafts(base, page, remote)
    assert merged is None
    assert len(conflicts) == 1
    assert conflicts[0].path == "blocks[activity_summary].text"
    assert conflicts[0].before == "Accepted baseline"
    assert block(page, "activity_summary").text == "Local approved wording"
    assert block(remote, "activity_summary").text == "Newer approved wording"
    chosen, unresolved = merge_drafts(base, page, remote, {conflicts[0].path: "this_page"})
    assert not unresolved
    assert block(chosen, "activity_summary").text == "Local approved wording"


def test_contact_cells_merge_by_stable_row_and_identify_exact_conflict():
    base = draft()
    page = update(base, "site_contacts",
                  rows=(("Alice", "555-1111", "alice@example.test"), block(base, "site_contacts").rows[1]))
    remote = update(base, "site_contacts",
                    rows=(block(base, "site_contacts").rows[0],
                          ("Bob", "555-2222", "bob@example.test")))
    merged, conflicts = merge_drafts(base, page, remote)
    assert not conflicts
    assert block(merged, "site_contacts").rows == (
        ("Alice", "555-1111", "alice@example.test"),
        ("Bob", "555-2222", "bob@example.test"),
    )
    same = update(base, "site_contacts",
                  rows=(("Alice", "555-9999", "alice@example.test"), block(base, "site_contacts").rows[1]))
    assert merge_drafts(base, page, same)[0] is None
    path = merge_drafts(base, page, same)[1][0].path
    assert "site_contacts" in path and "row 1: Alice" in path and "column 2" in path


def test_training_matrix_disjoint_rows_merge_but_same_status_requires_choice():
    base = draft()
    initial = block(base, "training_summary")
    matrix, sessions = initial.extra_tables
    page_matrix = replace(matrix, rows=(("Alice", "North", "Completed", "Pending"), matrix.rows[1]))
    remote_matrix = replace(matrix, rows=(matrix.rows[0], ("Bob", "North", "Pending", "Completed")))
    page = update(base, "training_summary", extra_tables=(page_matrix, sessions))
    remote = update(base, "training_summary", extra_tables=(remote_matrix, sessions))
    merged, conflicts = merge_drafts(base, page, remote)
    assert not conflicts
    assert block(merged, "training_summary").extra_tables[0].rows == (
        ("Alice", "North", "Completed", "Pending"),
        ("Bob", "North", "Pending", "Completed"))
    competing_matrix = replace(matrix, rows=(("Alice", "North", "Not required", "Pending"), matrix.rows[1]))
    competing = update(base, "training_summary", extra_tables=(competing_matrix, sessions))
    unresolved, conflicts = merge_drafts(base, page, competing)
    assert unresolved is None
    assert len(conflicts) == 1
    assert "row 1: Alice" in conflicts[0].path and "Safety" in conflicts[0].path


def test_training_row_incarnation_conflicts_and_unchanged_neighbor():
    base = draft()
    matrix, sessions = block(base, "training_summary").extra_tables
    first = replace(sessions, rows=(("Safety", "2026-09-01", "Virtual", "Alice", "2"), sessions.rows[1]),
                    row_tokens=("first-new", "event-b"))
    second = replace(sessions, rows=(("Safety", "2026-09-01", "Virtual", "Alice", "3"), sessions.rows[1]),
                     row_tokens=("second-new", "event-b"))
    page = update(base, "training_summary", extra_tables=(matrix, first))
    remote = update(base, "training_summary", extra_tables=(matrix, second))
    merged, conflicts = merge_drafts(base, page, remote)
    assert merged is None and any("Hours" in c.path for c in conflicts)
    assert any("row_tokens[row 1]" in c.path for c in conflicts)
    choices = {c.path: "this_page" for c in conflicts}
    decided, unresolved = merge_drafts(base, page, remote, choices)
    assert not unresolved
    assert block(decided, "training_summary").extra_tables[1].rows[1] == sessions.rows[1]
    assert block(decided, "training_summary").extra_tables[1].row_tokens[0] == "first-new"


def test_structural_deletion_and_malformed_or_foreign_scopes_fail_closed():
    base = draft()
    page = update(base, "site_contacts", rows=block(base, "site_contacts").rows[:1])
    remote = update(base, "site_contacts", rows=(block(base, "site_contacts").rows[0],
                                                ("Bob", "555-9876", "bob@example.test")))
    assert merge_drafts(base, page, remote)[0] is None
    foreign = replace(base, period=ReportPeriod(2026, 10))
    with pytest.raises(ValueError, match="different report"):
        merge_drafts(base, base, foreign)
    with pytest.raises(ValueError, match="three complete"):
        merge_drafts(base, {}, base)


def test_source_correction_collision_is_atomic_and_requires_review():
    base = draft()
    ours = replace(base, source_row_reviews=('{"source":"first","state":"corrected A"}',))
    theirs = replace(base, source_row_reviews=('{"source":"first","state":"corrected B"}',))
    merged, conflicts = merge_drafts(base, ours, theirs)
    assert merged is None and [c.path for c in conflicts] == ["source_row_reviews"]


def test_standing_training_manifest_interruption_preserves_prior_revision(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    base = draft()
    profile = base.profile
    table = block(base, "training_summary").extra_tables[0]
    first = save_training(profile, table, expected_revision=0, actor="Synthetic editor")
    original = library._atomic_write

    def interrupted(path, content):
        if path.name == "manifest.json" and "training" in str(path):
            raise OSError("Synthetic interrupted write")
        return original(path, content)

    changed = replace(table, rows=(("Alice", "North", "Completed", "Pending"), table.rows[1]))
    monkeypatch.setattr(library, "_atomic_write", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        save_training(profile, changed, expected_revision=first["revision"], actor="Synthetic editor")
    assert load_training(profile.contract) == first
    monkeypatch.setattr(library, "_atomic_write", original)
    after = save_training(profile, changed, expected_revision=first["revision"], actor="Synthetic editor")
    assert after["revision"] == 2
    assert after["sites"]["north"]["rows"][1] == first["sites"]["north"]["rows"][1]
    with pytest.raises(library.RevisionConflict):
        save_training(profile, table, expected_revision=1, actor="Synthetic stale editor")


def test_source_review_distinct_receipts_merge_without_decoding_or_dropping():
    base = draft()
    base = replace(base, source_row_reviews=())
    def receipt(source, state):
        return json.dumps({"schema": 1, "kind": "training", "scope": "synthetic-scope",
                           "source_id": source, "source_fingerprint": "a" * 64,
                           "table": 1, "state": state}, sort_keys=True)
    first = receipt("synthetic-source-a", "human-approved-a")
    second = receipt("synthetic-source-b", "human-approved-b")
    page = replace(base, source_row_reviews=(first,))
    remote = replace(base, source_row_reviews=(second,))
    merged, conflicts = merge_drafts(base, page, remote)
    assert not conflicts and merged.source_row_reviews == (second, first)
    older = replace(base, source_row_reviews=(first,))
    ours = replace(older, source_row_reviews=(receipt("synthetic-source-a", "corrected-on-page"),))
    newer = replace(older, source_row_reviews=(receipt("synthetic-source-a", "corrected-newer"),))
    unresolved, conflicts = merge_drafts(older, ours, newer)
    assert unresolved is None and len(conflicts) == 1
    assert "source synthetic-source-a" in conflicts[0].path
    assert first == older.source_row_reviews[0]


def test_contact_matrix_same_site_different_people_are_independent():
    base = draft()
    rows = (("North", "Client manager", "Alice", "555-0101", "alice@example.test"),
            ("North", "Client engineer", "Bob", "555-0102", "bob@example.test"))
    base = replace(base, blocks=(*base.blocks, ResolvedBlock("contact_matrix", "This month", rows=rows)))
    local = update(base, "contact_matrix", rows=(("North", "Client manager", "Alice", "555-1111",
                                                 "alice@example.test"), rows[1]))
    remote = update(base, "contact_matrix", rows=(rows[0], ("North", "Client engineer", "Bob",
                                                           "555-0102", "bob+corrected@example.test")))
    merged, conflicts = merge_drafts(base, local, remote)
    assert not conflicts
    assert block(merged, "contact_matrix").rows[0][3] == "555-1111"
    assert block(merged, "contact_matrix").rows[1][4] == "bob+corrected@example.test"
    stale = update(base, "contact_matrix", rows=(("North", "Client manager", "Alice", "555-2222",
                                                 "alice@example.test"), rows[1]))
    _, collisions = merge_drafts(base, local, stale)
    assert "row 1: North" in collisions[0].path
    assert "column 4" in collisions[0].path


def test_duplicate_contact_identity_cannot_be_positionally_merged():
    base = draft()
    duplicate_rows = (("North", "Client", "Alice", "111", ""),
                      ("North", "Client", "Alice", "222", ""))
    base = replace(base, blocks=(*base.blocks, ResolvedBlock("contact_matrix", "This month",
                                                             rows=duplicate_rows)))
    ours = update(base, "contact_matrix", rows=(("North", "Client", "Alice", "111", "first@example.test"),
                                                duplicate_rows[1]))
    theirs = update(base, "contact_matrix", rows=(duplicate_rows[0],
                                                  ("North", "Client", "Alice", "222", "second@example.test")))
    merged, conflicts = merge_drafts(base, ours, theirs)
    assert merged is None and [c.path for c in conflicts] == ["blocks[contact_matrix].rows"]
