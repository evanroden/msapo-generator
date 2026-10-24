"""Batch import keeps metadata rows and unfinished tabs out of contract scope (Refs #288).

G2-directory-4: an earlier, equally filled Region/account-code row was chosen as
the header, so contracts and sites were named after regions.
G2-directory-5: one unreadable worksheet aborted the whole batch preview.
Synthetic contacts only.
"""
import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, prepared, save, summary


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


@pytest.mark.parametrize("label", ["Region", "Account Code", "Area"])
def test_a_metadata_row_above_the_contract_row_never_names_a_contract(label):
    raw, plan = prepared(("Active Contracts", {"A5": label, "B5": "Synthetic Gulf", **summary()}),
                         ("Synthetic Contract Sites", detail()))
    assert [entry.contract for entry in plan.entries] == ["Synthetic Contract"]
    assert save(plan, raw).saved == ("Synthetic Contract",)
    assert "Synthetic Gulf" not in directory.directory_contracts()


def test_a_region_row_above_the_facility_row_never_names_a_site():
    raw, plan = prepared(("Active Contracts", summary()),
                         ("Synthetic Contract Sites", {"A5": "Region", "B5": "Synthetic Gulf", **detail()}))
    assert [site.title for site in plan.entries[0].sites] == ["Synthetic North"]


def test_one_unreadable_tab_is_excluded_by_name_and_the_batch_continues():
    unfinished = {"A6": "Facility", "A9": "Facility Director", "A10": "Phone", "A11": "Email"}
    raw, plan = prepared(("Active Contracts", summary()), ("Synthetic Contract Sites", detail()),
                         ("2 - Synthetic Contract", unfinished))
    assert [entry.contract for entry in plan.entries] == ["Synthetic Contract"]
    assert [site.title for site in plan.entries[0].sites] == ["Synthetic North"]
    excluded = [x for x in plan.exclusions if x.worksheet == "2 - Synthetic Contract"]
    assert len(excluded) == 1 and "Review it separately" in excluded[0].reason
    assert save(plan, raw).saved == ("Synthetic Contract",)


def test_an_unreadable_summary_tab_does_not_block_detail_tabs():
    unreadable = {"A6": "Contract", "A9": "Executive Director", "A10": "Phone", "A11": "Email"}
    directory.save_directory("Synthetic Contract", (), expected_revision=0, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Administrator"),))
    raw, plan = prepared(("Active Contracts", unreadable), ("Synthetic Contract Sites", detail()))
    assert [x.worksheet for x in plan.exclusions] == ["Active Contracts"]
    assert [site.title for site in plan.entries[0].sites] == ["Synthetic North"]
