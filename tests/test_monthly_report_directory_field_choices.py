"""Changed directory details are reviewable choices, not a blocked contract (Refs #288, G2-directory-8).

A replaced person, a changed phone or a changed address blocked every update
for that contract, with no way to accept the workbook value. Saved values are
now kept by default, the rest of the contract can be saved, and each change is
applied only when explicitly accepted. Synthetic contacts only.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import detail, prepared, save, summary
from test_monthly_report_directory_batch_ui import APP, Entry, Plan, Result, confirm, save_button


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def accept_all(plan, raw, *ids):
    chosen = ids or tuple(change.id for entry in plan.entries for change in entry.changes)
    return batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=True, accept=chosen)


def saved():
    return directory.load_directory("Synthetic Contract")


def changed_workbook():
    """A replaced executive, a site lead's new phone, a new site address and a new site."""
    raw, first = prepared()
    save(first, raw)
    return prepared(("Active Contracts", summary(B9="Synthetic Replacement", B10="", B11="")),
                    ("Synthetic Contract Sites", detail(B7="200 Example Way", B10="202-555-0199",
                                                        C6="Synthetic South", C9="Synthetic South Lead")))


def test_changes_are_listed_and_other_updates_save_while_saved_values_stay():
    raw, plan = changed_workbook()
    entry = plan.entries[0]
    assert not entry.conflicts and entry.changed
    assert {(c.applies_to, c.detail, c.saved, c.workbook) for c in entry.changes} == {
        ("Contract-wide", "Executive Director", "Synthetic Executive · 202-555-0100 · executive@example.invalid",
         "Synthetic Replacement"),
        ("Synthetic North", "Facility Director", "Synthetic Site Lead · 202-555-0101 · site@example.invalid",
         "Synthetic Site Lead · 202-555-0199 · site@example.invalid"),
        ("Synthetic North", "Address", "100 Example Way", "200 Example Way")}
    assert save(plan, raw).saved == ("Synthetic Contract",)
    state = saved()
    assert [s.title for s in state.sites] == ["Synthetic North", "Synthetic South"]
    assert state.contract_contacts[0].name == "Synthetic Executive"
    assert (state.sites[0].address, state.sites[0].contacts[0].phone) == ("100 Example Way", "202-555-0101")


def test_accepted_changes_replace_only_the_chosen_values():
    raw, plan = changed_workbook()
    assert accept_all(plan, raw).saved == ("Synthetic Contract",)
    state = saved()
    replacement = state.contract_contacts[0]
    # A replaced person never inherits the previous person's phone or email.
    assert (replacement.name, replacement.phone, replacement.email) == ("Synthetic Replacement", "", "")
    north = state.sites[0]
    assert north.address == "200 Example Way"
    assert (north.contacts[0].name, north.contacts[0].phone, north.contacts[0].email) == (
        "Synthetic Site Lead", "202-555-0199", "site@example.invalid")


@pytest.mark.parametrize("scope", ["contract", "site"])
@pytest.mark.parametrize(("field", "cell", "value"), [
    ("phone", "B10", "202-555-0199"),
    ("email", "B11", "updated@example.invalid"),
])
def test_accepting_a_partial_contact_update_keeps_omitted_details(scope, field, cell, value):
    raw, first = prepared()
    save(first, raw)
    before = saved().contract_contacts[0] if scope == "contract" else saved().sites[0].contacts[0]
    partial = {"B9": "", "B10": "", "B11": "", cell: value}
    raw, plan = prepared(
        ("Active Contracts", summary(**(partial if scope == "contract" else {}))),
        ("Synthetic Contract Sites", detail(**(partial if scope == "site" else {}))))
    change, = plan.entries[0].changes
    assert save(plan, raw).unchanged == ("Synthetic Contract",)
    assert accept_all(plan, raw, change.id).saved == ("Synthetic Contract",)
    after = saved().contract_contacts[0] if scope == "contract" else saved().sites[0].contacts[0]
    expected = replace(before, **{field: value})
    assert (after.name, after.phone, after.email) == (expected.name, expected.phone, expected.email)
    assert saved().revision == 2


def test_one_accepted_change_leaves_the_others_as_saved():
    raw, plan = changed_workbook()
    address = next(c for c in plan.entries[0].changes if c.detail == "Address")
    accept_all(plan, raw, address.id)
    state = saved()
    assert state.sites[0].address == "200 Example Way"
    assert state.contract_contacts[0].name == "Synthetic Executive"
    assert state.sites[0].contacts[0].phone == "202-555-0101"


def test_a_change_only_import_is_unchanged_until_a_change_is_accepted():
    raw, first = prepared()
    save(first, raw)
    raw, plan = prepared(("Active Contracts", summary()), ("Synthetic Contract Sites", detail(B10="202-555-0199")))
    entry = plan.entries[0]
    assert not entry.changed and entry.can_save and len(entry.changes) == 1
    assert save(plan, raw).unchanged == ("Synthetic Contract",)
    assert saved().revision == 1
    assert accept_all(plan, raw).saved == ("Synthetic Contract",)
    assert saved().revision == 2 and saved().sites[0].contacts[0].phone == "202-555-0199"


def test_unreviewed_or_stale_changes_are_refused():
    raw, plan = changed_workbook()
    with pytest.raises(ValueError, match="unreviewed change"):
        accept_all(plan, raw, "0" * 16)
    entry = plan.entries[0]
    change = next(c for c in entry.changes if c.applies_to == "Contract-wide")
    stale = replace(plan, entries=(replace(entry, contract_contacts=()),))
    result = accept_all(stale, raw, change.id)
    assert result.failed and not result.saved and saved().revision == 1


def test_ambiguous_and_contradictory_records_still_block():
    raw, first = prepared(("Active Contracts", summary(A13="Executive Director", B13="Synthetic Second Executive")),
                          ("Synthetic Contract Sites", detail()))
    save(first, raw)
    raw, plan = prepared(("Active Contracts", summary(B9="Synthetic Replacement", A13="Executive Director",
                                                      B13="Synthetic Other Replacement")),
                         ("Synthetic Contract Sites", detail()))
    entry = plan.entries[0]
    assert any("more than one saved contact has role" in c for c in entry.conflicts) and not entry.can_save


@pytest.fixture
def change_app(monkeypatch):
    change = batch.ProposedChange("c" * 16, "", "Contract-wide", "Executive Director", "Synthetic Executive",
                                  "Synthetic Replacement")
    plan = Plan(entries=(Entry(changed=False, changes=(change,)),))
    calls = []

    def record(reviewed, raw, **kwargs):
        calls.append(kwargs)
        return Result(saved=("Synthetic Contract",))
    monkeypatch.setattr(batch, "prepare_workbook", lambda inspection: plan)
    monkeypatch.setattr(batch, "save_workbook_plan", record)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["test_actor"] = "Synthetic Editor"
    app.session_state["test_inspection"] = directory.DirectoryWorkbook("a" * 64, (), ())
    return app.run(), calls


def test_review_lists_changes_and_saves_only_selected_workbook_values(change_app):
    app, calls = change_app
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Result"] == "Changed details below"
    changes = next(table.value for table in app.dataframe if "Workbook" in table.value.columns)
    assert (changes.iloc[0]["Saved"], changes.iloc[0]["Workbook"]) == ("Synthetic Executive", "Synthetic Replacement")
    assert not any("already matches" in msg.value for msg in app.success)
    assert confirm(app).disabled and save_button(app).disabled
    app.multiselect[0].select("c" * 16).run()
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception
    assert calls == [{"actor": "Synthetic Editor", "confirmed": True, "create": (), "accept": ("c" * 16,)}]
