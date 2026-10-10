"""New shared contacts require a reviewed source site, role and name."""
from dataclasses import replace
import pytest
from app import monthly_report_directory as directory
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_library import RevisionConflict

@pytest.fixture
def scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[1]
    north = directory.DirectorySite("north", profile.facilities[0].title, contacts=(
        directory.DirectoryContact("Operator", "Jordan Example", "111", "north@example.invalid"),))
    south = directory.DirectorySite("south", profile.facilities[1].title, contacts=(
        directory.DirectoryContact("Operator", "Jordan Example", "222", "south@example.invalid"),))
    state = directory.save_directory(profile.contract, (north,south), expected_revision=0,
                                     actor="Synthetic Editor", confirmed=True)
    block, missing = directory.contact_block(state, profile.facilities)
    assert not missing
    return profile, state, replace(block, source="Library")

def test_append_site_contact_fills_future_matrix_without_changing_other_site(scoped):
    profile, state, before = scoped
    new = (profile.facilities[0].title, "Plant Engineer", "Alex Example", "555-0123", "alex@example.invalid")
    edited = replace(before, source="This month", rows=(*before.rows, new))
    shared = directory.automatically_keep_directory_contact_edits(profile,before,edited,"Synthetic Editor")
    assert shared and new in shared.rows
    latest = directory.load_directory(profile.contract)
    assert latest.revision == 2
    assert latest.sites[0].contacts[1].source == f"report:{profile.key}"
    assert latest.sites[1].contacts[0].phone == "222"
    future, missing = directory.contact_block(latest,profile.facilities)
    assert not missing and new in future.rows

def test_blank_and_unmatched_rows_not_promoted(scoped):
    profile, _, before = scoped
    bad = (
      (profile.facilities[0].title, "", "", "", ""),
      ("Unknown site", "Engineer", "Alex", "111", ""),
      (profile.facilities[0].title, "Engineer", "", "111", ""),
    )
    for row in bad:
        assert directory.automatically_keep_directory_contact_edits(
           profile,before,replace(before,source="This month",rows=(*before.rows,row)),
           "Synthetic Editor") is None
    assert directory.load_directory(profile.contract).revision == 1

def test_same_name_at_other_site_stays_distinct(scoped):
    profile, _, before = scoped
    new = (profile.facilities[1].title, "Engineer", "Jordan Example", "444", "other@example.invalid")
    directory.automatically_keep_directory_contact_edits(profile,before,
       replace(before,source="This month",rows=(*before.rows,new)),"Synthetic Editor")
    sites=directory.load_directory(profile.contract).sites
    assert len(sites[0].contacts)==1 and len(sites[1].contacts)==2
    assert sites[0].contacts[0].name==sites[1].contacts[-1].name
    assert sites[0].contacts[0].phone!=sites[1].contacts[-1].phone

def test_stale_same_site_rejects_new_contact_without_mutating_directory(scoped):
    profile,state,before=scoped
    changed=replace(state.sites[0],contacts=(*state.sites[0].contacts,
        directory.DirectoryContact("Other", "Concurrent Person")))
    directory.save_directory(profile.contract,(changed,state.sites[1]),
        expected_revision=1,actor="Second Editor",confirmed=True)
    new=(profile.facilities[0].title,"Technician","New Person","777","")
    with pytest.raises(RevisionConflict):
        directory.automatically_keep_directory_contact_edits(profile,before,
            replace(before,source="This month",rows=(*before.rows,new)),
            "Synthetic Editor")
    assert directory.load_directory(profile.contract).revision==2
