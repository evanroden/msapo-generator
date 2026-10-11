"""Automatic shared-contact edits use row identity, not matching a person's name."""
from dataclasses import replace

import pytest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[1]
    sites = (
        directory.DirectorySite("north", profile.facilities[0].title, contacts=(
            directory.DirectoryContact("Operator", "Jordan Example", "111", "north@example.invalid"),)),
        directory.DirectorySite("south", profile.facilities[1].title, contacts=(
            directory.DirectoryContact("Operator", "Jordan Example", "222", "south@example.invalid"),)),
    )
    state = directory.save_directory(profile.contract, sites, expected_revision=0,
                                     actor="Synthetic Editor", confirmed=True)
    block, missing = directory.contact_block(state, profile.facilities)
    assert not missing
    return profile, state, replace(block, source="Library")


def test_auto_contact_edit_updates_only_intended_site_and_preserves_old_report(setup):
    profile, state, before = setup
    historical = synthetic_draft(profile, ReportPeriod(2026, 9))
    historical = replace(historical, blocks=(*historical.blocks, before))
    snap = library.save_snapshot(historical, expected_revision=0,
                                 entered_editor="Synthetic Editor")
    rows = list(before.rows)
    rows[0] = (rows[0][0], rows[0][1], rows[0][2], "999", rows[0][4])
    edited = replace(before, source="This month", rows=tuple(rows))
    result = directory.automatically_keep_directory_contact_edits(
        profile, before, edited, "Synthetic Editor")
    assert result is not None and result.rows[0][3] == "999"
    assert result.source == "Library"
    latest = directory.load_directory(profile.contract)
    assert latest.revision == 2
    assert latest.sites[0].contacts[0].phone == "999"
    assert latest.sites[1].contacts[0].phone == "222"
    assert directory.contact_block(latest, profile.facilities)[0].rows[0][3] == "999"
    assert library.load_snapshot(profile.contract, profile.key, historical.period) == snap
    assert directory.automatically_keep_directory_contact_edits(profile, result, result, "Synthetic Editor") is None


def test_newer_unrelated_site_edit_is_preserved_under_revision_change(setup):
    profile, state, before = setup
    south = replace(state.sites[1], contacts=(replace(state.sites[1].contacts[0], phone="333"),))
    directory.save_directory(profile.contract, (state.sites[0], south),
                             expected_revision=1, actor="Second Editor", confirmed=True)
    changed = list(before.rows)
    changed[0] = (changed[0][0], changed[0][1], "North New Name", changed[0][3], changed[0][4])
    directory.automatically_keep_directory_contact_edits(
        profile, before, replace(before, source="This month", rows=tuple(changed)), "Synthetic Editor")
    latest = directory.load_directory(profile.contract)
    assert latest.revision == 3
    assert latest.sites[0].contacts[0].name == "North New Name"
    assert latest.sites[1].contacts[0].phone == "333"


def test_same_site_conflict_rejects_old_write_without_changing_history(setup):
    profile, state, before = setup
    changed_north = replace(state.sites[0], contacts=(replace(state.sites[0].contacts[0], phone="555"),))
    directory.save_directory(profile.contract, (changed_north, state.sites[1]),
                             expected_revision=1, actor="Other Editor", confirmed=True)
    rows = list(before.rows)
    rows[0] = (rows[0][0], rows[0][1], rows[0][2], "999", rows[0][4])
    with pytest.raises(library.RevisionConflict):
        directory.automatically_keep_directory_contact_edits(
            profile, before, replace(before, source="This month", rows=tuple(rows)),
            "Synthetic Editor")
    assert directory.load_directory(profile.contract).revision == 2
    assert directory.load_directory(profile.contract).sites[0].contacts[0].phone == "555"


def test_report_only_or_unmatched_contact_is_not_promoted(setup):
    profile, _, before = setup
    edited = replace(before, source="This month", rows=before.rows + ((
        profile.facilities[0].title, "Temp", "Synthetic", "123", ""),))
    assert directory.automatically_keep_directory_contact_edits(profile, before, edited, "Synthetic Editor") is None
    assert directory.automatically_keep_directory_contact_edits(
        profile, replace(before, references=(), source="This month"), edited, "Synthetic Editor") is None
    assert directory.load_directory(profile.contract).revision == 1


def test_remove_all_report_contacts_keeps_intent_and_does_not_delete_directory(setup):
    from app.monthly_report_model import ReportDraft, default_sections
    profile, state, before = setup
    historical = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor",
                             default_sections(), (before,), synthetic=True)
    saved = library.save_snapshot(historical, expected_revision=0,
                                  entered_editor="Synthetic Editor")
    removed = replace(before, source="This month", rows=())
    this_month = replace(historical, blocks=(removed,))
    assert directory.automatically_keep_directory_contact_edits(
        profile, before, removed, "Synthetic Editor") is None
    assert directory.apply_defaults(this_month) == this_month
    assert directory.load_directory(profile.contract).revision == state.revision
    assert library.load_snapshot(profile.contract, profile.key, historical.period) == saved
    # First use next month, with no reviewed contact block, still gets the
    # correct two site-scoped people rather than a permanently empty directory.
    fresh = replace(historical, period=ReportPeriod(2026, 10), blocks=())
    loaded = directory.apply_defaults(fresh)
    rows = next(b.rows for b in loaded.blocks if b.key == "contact_matrix")
    assert rows == before.rows


def test_explicit_report_contact_omit_cannot_be_repopulated_automatically(setup):
    from app.monthly_report_model import ReportDraft, default_sections
    profile, _, before = setup
    excluded = replace(before, source="Omit", rows=())
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor",
                        default_sections(), (excluded,), synthetic=True)
    assert directory.apply_defaults(draft) == draft


def test_pure_site_contact_reorder_is_report_only_not_a_standing_identity_edit(setup):
    profile, original, _ = setup
    north = replace(original.sites[0], contacts=(
        *original.sites[0].contacts,
        directory.DirectoryContact("Supervisor", "Casey Example", "333", "casey@example.invalid"),
    ))
    revised = directory.save_directory(
        profile.contract, (north, original.sites[1]), expected_revision=1,
        actor="Synthetic Editor", confirmed=True)
    block, missing = directory.contact_block(revised, profile.facilities)
    assert not missing
    before = replace(block, source="Library")
    rows = list(before.rows)
    assert rows[0][0] == rows[1][0] == profile.facilities[0].title
    rows[0], rows[1] = rows[1], rows[0]
    reordered = replace(before, source="This month", rows=tuple(rows))
    assert directory.automatically_keep_directory_contact_edits(
        profile, before, reordered, "Synthetic Editor") is None
    assert reordered.rows != before.rows  # The monthly layout may stay reordered.
    final = directory.load_directory(profile.contract)
    assert final.revision == revised.revision
    assert final.sites[0].contacts == north.contacts
