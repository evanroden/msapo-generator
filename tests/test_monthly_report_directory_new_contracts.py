"""Batch import proposes, but never silently creates, unknown contracts (Refs #288, G2-directory-3).

An Active Contracts column whose heading is not a catalog contract, a saved
directory contract or a reviewed alias used to become a new contract and
landing card as soon as the import was confirmed, so a renamed or misspelled
column sat beside the real contract. Synthetic contacts only.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, summary, workbook
from test_monthly_report_directory_batch_ui import APP, Entry, Plan, Result, confirm, save_button


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(batch.contract_catalog, "contract_names", lambda: ("Synthetic Catalog Contract",))


def prepared(*sheets, **aliases):
    raw = workbook(sheets)
    return raw, batch.prepare_workbook(directory.inspect_workbook(raw), **aliases)


def save(plan, raw, **options):
    return batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=True, **options)


def flags(plan):
    return {entry.contract: entry.new_contract for entry in plan.entries}


def test_only_unknown_headings_are_proposed_as_new_contracts():
    directory.save_directory("Synthetic Saved Contract", (), expected_revision=0, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Administrator"),))
    _, plan = prepared(("Active Contracts", summary(
        B6="Synthetic Catalog Contract", C6="Synthetic Saved Contract", C9="Synthetic Saved Lead",
        D6="SYNTHETIC ALIAS HEADING", D9="Synthetic Alias Lead", E6="Synthetic Catalog Contract Hwy", E9="Synthetic Variant Lead")),
        contract_aliases={"SYNTHETIC ALIAS HEADING": "Synthetic Aliased Contract"})
    assert flags(plan) == {"Synthetic Aliased Contract": False, "Synthetic Catalog Contract": False,
                           "Synthetic Catalog Contract Hwy": True, "Synthetic Saved Contract": False}


def test_confirming_the_import_alone_never_creates_a_proposed_contract():
    raw, plan = prepared(("Active Contracts", summary(
        B6="Synthetic Catalog Contract", C6="Synthetic Catalog Contract Hwy", C9="Synthetic Variant Lead")),
        ("Synthetic Catalog Contract Hwy Sites", detail()))
    result = save(plan, raw)
    assert result.saved == ("Synthetic Catalog Contract",)
    assert result.not_created == ("Synthetic Catalog Contract Hwy",)
    assert directory.directory_contracts() == ("Synthetic Catalog Contract",)
    assert directory.load_directory("Synthetic Catalog Contract Hwy") is None


def test_a_selected_proposal_is_created_once_and_is_known_afterwards():
    raw, plan = prepared(("Active Contracts", summary(B6="Synthetic New Account")), ("Synthetic New Account Sites", detail()))
    result = save(plan, raw, create=("Synthetic New Account",))
    assert result.saved == ("Synthetic New Account",) and not result.not_created
    state = directory.load_directory("Synthetic New Account")
    assert [site.title for site in state.sites] == ["Synthetic North"]
    assert state.contract_contacts[0].name == "Synthetic Executive"
    again = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert flags(again) == {"Synthetic New Account": False}
    assert save(again, raw).unchanged == ("Synthetic New Account",)


def test_create_cannot_name_a_known_or_unreviewed_contract():
    raw, plan = prepared(("Active Contracts", summary(B6="Synthetic Catalog Contract", C6="Synthetic New Account",
                                                      C9="Synthetic New Lead")))
    for name in ("Synthetic Catalog Contract", "Synthetic Unreviewed"):
        with pytest.raises(ValueError, match="unreviewed contract"):
            save(plan, raw, create=(name,))
    assert not directory.directory_contracts()


@pytest.fixture
def proposal_app(monkeypatch):
    contact = directory.DirectoryContact("Manager", "Synthetic Manager", "202-555-0100", "manager@example.invalid")
    plan = Plan(entries=(Entry(contract="Synthetic New Account", expected_revision=0, contract_contacts=(contact,),
                               existing=False, new_contract=True),))
    calls = []

    def record(reviewed, raw, **kwargs):
        calls.append(kwargs)
        return Result(saved=kwargs["create"])
    monkeypatch.setattr(batch, "prepare_workbook", lambda inspection: plan)
    monkeypatch.setattr(batch, "save_workbook_plan", record)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["test_actor"] = "Synthetic Editor"
    app.session_state["test_inspection"] = directory.DirectoryWorkbook("a" * 64, (), ())
    return app.run(), calls


def test_review_requires_selecting_a_proposed_contract_before_save(proposal_app):
    app, calls = proposal_app
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Result"] == "New contract: select below to create"
    assert any("only created when selected" in msg.value for msg in app.warning)
    assert not any("already matches" in msg.value for msg in app.success)
    assert confirm(app).disabled and save_button(app).disabled
    app.multiselect[0].select("Synthetic New Account").run()
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception
    assert calls == [{"actor": "Synthetic Editor", "confirmed": True, "create": ("Synthetic New Account",)}]


def test_changing_the_selection_requires_a_fresh_confirmation(proposal_app):
    app, _ = proposal_app
    app.multiselect[0].select("Synthetic New Account").run()
    confirm(app).check().run()
    assert not save_button(app).disabled
    app.multiselect[0].unselect("Synthetic New Account").run()
    assert save_button(app).disabled
    app.multiselect[0].select("Synthetic New Account").run()
    assert not confirm(app).value and save_button(app).disabled


def test_a_mixed_plan_saves_known_contracts_without_selecting_proposals(monkeypatch):
    known = Entry()
    new = replace(known, contract="Synthetic New Account", expected_revision=0, existing=False, new_contract=True)
    calls = []
    monkeypatch.setattr(batch, "prepare_workbook", lambda inspection: Plan(entries=(known, new)))
    monkeypatch.setattr(batch, "save_workbook_plan", lambda reviewed, raw, **kwargs: calls.append(kwargs) or Result(
        saved=("Synthetic Contract",), not_created=("Synthetic New Account",)))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["test_actor"] = "Synthetic Editor"
    app.session_state["test_inspection"] = directory.DirectoryWorkbook("a" * 64, (), ())
    app.run()
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception and calls[0]["create"] == ()
    assert any("1 proposed new contract was not selected and not created." in msg.value for msg in app.info)
