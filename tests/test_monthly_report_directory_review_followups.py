"""Follow-ups from the automated review of the merged directory repairs (Refs #288).

Copied-site detection compares whole people sets, stays near-linear, ignores
retired sites and reads each directory once; a phone note is information; a
reviewed alias names its canonical contract and saved sites win over catalog
sites in single-sheet import. Synthetic contacts only.
"""
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, prepared, summary, workbook

APP = """
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
"""
SUMMARY = summary(C6="Synthetic Other", C9="Synthetic Other Lead")
REGIONAL = {"A13": "Regional Manager", "B13": "Synthetic Regional Manager"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def sites(plan):
    return {entry.contract: [site.title for site in entry.sites] for entry in plan.entries}


def test_same_named_sites_sharing_one_regional_manager_stay_in_their_contracts():
    _, plan = prepared(("Active Contracts", SUMMARY),
                       ("Synthetic Contract Sites", detail(B6="Main Campus", **REGIONAL)),
                       ("Synthetic Other Sites", detail(B6="Main Campus", B9="Synthetic Other Site Lead", **REGIONAL)))
    assert sites(plan) == {"Synthetic Contract": ["Main Campus"], "Synthetic Other": ["Main Campus"]}
    assert not plan.exclusions


def test_a_heading_repeated_across_many_worksheets_is_checked_near_linearly(monkeypatch):
    lead = directory.DirectoryContact("Facility Director", "Synthetic Shared Lead")
    details = [(SimpleNamespace(name=f"Synthetic Tab {tab}"), f"Synthetic Contract {tab}", None,
                tuple(directory.DirectorySite(f"s{tab}-{column}", "Main Campus", contacts=(lead,),
                                              source=f"x:Synthetic Tab {tab}!C{column}") for column in range(50)))
               for tab in range(6)]
    calls = []
    people = batch._people
    monkeypatch.setattr(batch, "_people", lambda site: calls.append(site) or people(site))
    repeated = batch._repeated_sites(details)
    assert len(repeated) == 300 and len(calls) == 300
    assert len(repeated["x:Synthetic Tab 0!C0"]) == 5


def test_a_retired_saved_site_is_not_ownership_evidence():
    directory.save_directory("Synthetic Contract", (directory.DirectorySite("south", "Synthetic South", active=False),),
                             expected_revision=0, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Administrator"),))
    copied = detail(C6="Synthetic South", C9="Synthetic South Lead")
    _, plan = prepared(("Active Contracts", SUMMARY), ("Synthetic Contract Sites", copied),
                       ("Synthetic Other Sites", copied))
    excluded = {(x.worksheet, x.column) for x in plan.exclusions}
    assert {("Synthetic Contract Sites", "C6"), ("Synthetic Other Sites", "C6")} <= excluded


def test_ownership_and_the_plan_use_one_directory_read(monkeypatch):
    directory.save_directory("Synthetic Contract", (directory.DirectorySite("north", "Synthetic North"),),
                             expected_revision=0, actor="Synthetic Editor", confirmed=True)
    reads = []
    load = directory.load_directory
    monkeypatch.setattr(directory, "load_directory", lambda contract, *a, **k: reads.append(contract) or load(contract, *a, **k))
    _, plan = prepared(("Active Contracts", SUMMARY), ("Synthetic Contract Sites", detail()),
                       ("Synthetic Other Sites", detail()))
    assert sites(plan)["Synthetic Contract"] == ["Synthetic North"]
    assert sorted(reads) == ["Synthetic Contract", "Synthetic Other"]


@pytest.mark.parametrize(("saved", "incoming", "same"), [
    ("202-555-0100", "202-555-0100 (after hours)", False),
    ("202-555-0100", "Call 202-555-0100", False),
    ("202-555-0100", "(202) 555-0100 x12", False),
    ("202-555-0100 ext. 12", "(202) 555-0100 x12", True),
])
def test_phone_notes_are_information_not_formatting(saved, incoming, same):
    assert directory.same_contact_value("phone", saved, incoming) is same


def test_single_sheet_import_keeps_a_new_phone_note():
    saved = directory.DirectoryContact("Executive Director", "Synthetic Executive", "202-555-0100")
    incoming = directory.DirectoryContact("Executive Director", "Synthetic Executive", "202-555-0100 (after hours)")
    merged, = directory.proposed_contacts((saved,), (incoming,))
    assert merged.phone == "202-555-0100 (after hours)"


def _single_sheet(raw):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["report_directory_workbook"] = (raw, directory.inspect_workbook(raw))
    app.run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    assert not app.exception
    return app


def _save(app):
    next(box for box in app.checkbox if box.label ==
         "I reviewed all included sites and contacts and confirm this shared save").check().run()
    next(button for button in app.button if button.label == "Save contract directory").click().run()
    assert not app.exception


def test_an_alias_for_a_new_contract_suggests_its_canonical_name(monkeypatch):
    monkeypatch.setitem(batch.CONTRACT_ALIASES, "SYNTHETIC NEW ALIAS", "Synthetic Canonical New")
    sheet = directory.inspect_workbook(workbook((("SYNTHETIC NEW ALIAS Sites", detail()),))).sheets[0]
    assert batch.worksheet_contract(sheet) == "Synthetic Canonical New"
    app = _single_sheet(workbook((("SYNTHETIC NEW ALIAS Sites", detail()),)))
    assert next(box for box in app.selectbox if box.label == "Save under contract").value == "Add another contract"
    assert next(box for box in app.text_input if box.label == "Contract name").value == "Synthetic Canonical New"
    _save(app)
    assert directory.directory_contracts() == ("Synthetic Canonical New",)


def test_a_saved_site_wins_over_the_catalog_site_in_single_sheet_import():
    from app.monthly_report_directory_ui import _suggested_site
    saved = directory.DirectorySite("saved-raw", "SYNTH RAW SITE")
    catalog = directory.DirectorySite("canonical", "Synthetic Canonical Site")
    column = directory.DirectorySite("column", "SYNTH RAW SITE")
    aliases = {"synth raw site": "Synthetic Canonical Site"}
    assert _suggested_site(column, (saved, catalog), aliases, {"saved-raw"}) == ("Synthetic Canonical Site", saved)
    assert _suggested_site(column, (saved, catalog), aliases)[1] is None  # unknown saved state stays ambiguous
