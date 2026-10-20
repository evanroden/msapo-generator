"""Copied site headings never land in two contracts (Refs #288, G2-directory-10).

The batch only excluded a tab whose whole set of headings equalled another
tab, so a copy with one extra column imported the copied sites into both
contracts, while two contracts that each had a "Main Campus" were both
excluded. Synthetic contacts only.
"""
import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, prepared, summary, workbook

SUMMARY = summary(C6="Synthetic Other", C9="Synthetic Other Lead")
CONTRACT = detail(C6="Synthetic South", C9="Synthetic South Lead")
COPY = detail(C6="Synthetic South", C9="Synthetic South Lead", D6="Synthetic East", D9="Synthetic East Lead")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def sites(plan):
    return {entry.contract: [site.title for site in entry.sites] for entry in plan.entries}


def excluded(plan):
    return {(x.worksheet, x.column) for x in plan.exclusions}


def test_copied_columns_are_excluded_by_cell_and_the_extra_site_is_kept():
    _, plan = prepared(("Active Contracts", SUMMARY), ("Synthetic Contract Sites", CONTRACT), ("Synthetic Other Sites", COPY))
    assert sites(plan) == {"Synthetic Contract": [], "Synthetic Other": ["Synthetic East"]}
    assert excluded(plan) == {("Synthetic Contract Sites", "B6"), ("Synthetic Contract Sites", "C6"),
                              ("Synthetic Other Sites", "B6"), ("Synthetic Other Sites", "C6")}
    reason = next(x.reason for x in plan.exclusions if (x.worksheet, x.column) == ("Synthetic Other Sites", "C6"))
    assert reason.startswith("Synthetic South also appears on worksheet Synthetic Contract Sites.")
    assert all(entry.contract_contacts for entry in plan.entries)


def test_same_named_sites_with_different_people_stay_in_their_own_contracts():
    _, plan = prepared(("Active Contracts", SUMMARY), ("Synthetic Contract Sites", detail(B6="Main Campus")),
                       ("Synthetic Other Sites", detail(B6="Main Campus", B9="Synthetic Other Site Lead")))
    assert sites(plan) == {"Synthetic Contract": ["Main Campus"], "Synthetic Other": ["Main Campus"]}
    assert not plan.exclusions


def test_a_site_already_saved_for_one_contract_stays_there_and_not_in_the_copy():
    directory.save_directory("Synthetic Contract", (directory.DirectorySite("south", "Synthetic South"),),
                             expected_revision=0, actor="Synthetic Editor", confirmed=True)
    _, plan = prepared(("Active Contracts", SUMMARY), ("Synthetic Contract Sites", CONTRACT), ("Synthetic Other Sites", COPY))
    assert sites(plan) == {"Synthetic Contract": ["Synthetic South"], "Synthetic Other": ["Synthetic East"]}
    assert excluded(plan) == {("Synthetic Contract Sites", "B6"), ("Synthetic Other Sites", "B6"), ("Synthetic Other Sites", "C6")}


def test_a_reviewed_site_alias_resolves_the_repeated_heading_for_its_contract():
    raw = workbook((("Active Contracts", SUMMARY), ("Synthetic Contract Sites", CONTRACT), ("Synthetic Other Sites", COPY)))
    plan = batch.prepare_workbook(directory.inspect_workbook(raw),
                                  site_aliases={"Synthetic Other": {"Synthetic North": "Synthetic North"}})
    assert sites(plan) == {"Synthetic Contract": [], "Synthetic Other": ["Synthetic North", "Synthetic East"]}
    assert ("Synthetic Other Sites", "B6") not in excluded(plan)


def test_two_tabs_of_the_same_contract_are_not_treated_as_copies():
    _, plan = prepared(("Active Contracts", summary()), ("Synthetic Contract Sites", detail()),
                       ("2 - Synthetic Contract", detail(B6="Synthetic North Annex", C6="Synthetic North", C9="Synthetic Site Lead")))
    assert not plan.exclusions
    assert "Synthetic North Annex" in sites(plan)["Synthetic Contract"]
