"""Full-workbook review UX, using only synthetic directory contacts."""

from dataclasses import dataclass, replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app import monthly_report_directory_batch_ui as ui


@dataclass(frozen=True)
class Entry:
    contract: str = "Synthetic Contract"
    expected_revision: int = 2
    sites: tuple = ()
    contract_contacts: tuple = ()
    source_sheets: tuple = ("Active Contracts",)
    conflicts: tuple = ()
    changed: bool = True
    existing: bool = True

    @property
    def can_save(self):
        return self.changed and not self.conflicts


@dataclass(frozen=True)
class Plan:
    workbook_sha256: str = "a" * 64
    entries: tuple = ()
    notices: tuple = ()
    exclusions: tuple = ()
    mappings: tuple = ()


@dataclass(frozen=True)
class Result:
    saved: tuple = ()
    unchanged: tuple = ()
    blocked: tuple = ()
    failed: tuple = ()


APP = """
import streamlit as st
from app.monthly_report_directory_batch_ui import render_batch
actor = st.text_input("Editor", key="test_actor")
render_batch(st.session_state["test_inspection"], b"synthetic workbook", actor, "test")
"""


@pytest.fixture
def plan():
    contact = directory.DirectoryContact("Manager", "Synthetic Manager", "202-555-0100", "manager@example.invalid")
    site = directory.DirectorySite("synthetic-site", "Synthetic Site", contacts=(contact,))
    return Plan(entries=(Entry(sites=(site,), contract_contacts=(contact,)),))


def launch(monkeypatch, plan, actor="Synthetic Editor"):
    monkeypatch.setattr(batch, "prepare_workbook", lambda inspection: plan)
    app = AppTest.from_string(APP)
    app.session_state["test_actor"] = actor
    app.session_state["test_inspection"] = directory.DirectoryWorkbook("a" * 64, (), ())
    return app.run()


def save_button(app):
    return next(button for button in app.button if button.label == "Save all reviewed contacts")


def confirm(app):
    return next(box for box in app.checkbox if box.label.startswith("I reviewed"))


def test_blank_actor_never_prepares_or_exposes_preview(monkeypatch, plan):
    app = launch(monkeypatch, plan, actor="")
    assert not app.exception and not app.dataframe and not app.checkbox
    def forbidden(*args, **kwargs):
        raise AssertionError("Must not read saved directories before an editor name")
    monkeypatch.setattr(batch, "prepare_workbook", forbidden)
    app.run()
    assert not app.exception and not app.dataframe


def test_summary_keeps_contract_contacts_separate_from_sites(monkeypatch, plan):
    app = launch(monkeypatch, plan)
    assert not app.exception
    summary = app.dataframe[0].value
    assert summary.iloc[0]["Contact scope"] == "Contract and sites"
    assert summary.iloc[0]["Sites"] == 1
    assert summary.iloc[0]["Contract contacts"] == 1
    assert summary.iloc[0]["Site contacts"] == 1
    details = app.dataframe[-1].value
    assert set(details["Applies to"]) == {"Contract-wide", "Synthetic Site"}
    assert save_button(app).disabled


def test_confirmation_binds_editor_and_exact_reviewed_snapshot(monkeypatch, plan):
    app = launch(monkeypatch, plan)
    confirm(app).check().run()
    assert not save_button(app).disabled
    old_key = confirm(app).key
    app.text_input("test_actor").set_value("Another Synthetic Editor").run()
    assert not app.exception and save_button(app).disabled
    assert confirm(app).key != old_key


def test_save_uses_original_reviewed_revision_and_cannot_replay(monkeypatch, plan):
    app = launch(monkeypatch, plan)
    newer = replace(plan, entries=(replace(plan.entries[0], expected_revision=7),))
    monkeypatch.setattr(batch, "prepare_workbook", lambda inspection: newer)
    calls = []
    def save(reviewed, raw, **kwargs):
        calls.append((reviewed, raw, kwargs))
        return Result(saved=("Synthetic Contract",))
    monkeypatch.setattr(batch, "save_workbook_plan", save)
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception
    assert calls == [(plan, b"synthetic workbook", {"actor": "Synthetic Editor", "confirmed": True})]
    assert save_button(app).disabled
    assert any("Saved contacts for 1 contract." in msg.value for msg in app.success)
    app.run()
    assert len(calls) == 1


def test_refresh_requires_fresh_confirmation_even_when_plan_is_identical(monkeypatch, plan):
    app = launch(monkeypatch, plan)
    confirm(app).check().run()
    key = confirm(app).key
    next(button for button in app.button if button.label == "Refresh directory preview").click().run()
    assert not app.exception and save_button(app).disabled
    assert confirm(app).key != key and not confirm(app).value


def test_exact_reimport_shows_noop_without_save(monkeypatch, plan):
    plan = replace(plan, entries=(replace(plan.entries[0], changed=False),))
    app = launch(monkeypatch, plan)
    assert not app.exception and save_button(app).disabled
    assert any("already matches" in msg.value for msg in app.success)


def test_blocked_and_partial_results_are_not_reported_as_full_success(monkeypatch, plan):
    blocked = replace(plan.entries[0], contract="Synthetic Blocked", conflicts=("Ambiguous site match",))
    plan = replace(plan, entries=(*plan.entries, blocked))
    app = launch(monkeypatch, plan)
    assert any("will not be saved" in msg.value for msg in app.warning)
    monkeypatch.setattr(batch, "save_workbook_plan", lambda *args, **kwargs: Result(
        saved=("Synthetic Contract",), unchanged=("Synthetic Current",),
        blocked=(("Synthetic Blocked", "Ambiguous site match"),),
        failed=(("Synthetic Changed", "Directory changed since preview"),)))
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception and save_button(app).disabled
    assert any("Successful saves above remain available" in msg.value for msg in app.error)
    assert any("1 contract already matches" in msg.value for msg in app.info)
    assert any("not saved" in msg.value for msg in app.warning)


def test_save_error_preserves_reviewed_data(monkeypatch, plan):
    app = launch(monkeypatch, plan)
    def fail(*args, **kwargs):
        raise ValueError("Workbook changed after review")
    monkeypatch.setattr(batch, "save_workbook_plan", fail)
    confirm(app).check().run()
    save_button(app).click().run()
    assert not app.exception
    assert any("Workbook changed after review" in msg.value for msg in app.error)
    assert app.dataframe[0].value.iloc[0]["Saved revision"] == 2


def test_summary_contract_only_record_does_not_invent_a_site(plan):
    plan = replace(plan, entries=(replace(plan.entries[0], sites=()),))
    row = ui._summary_rows(plan)[0]
    assert row["Contact scope"] == "Contract"
    assert row["Sites"] == 0 and row["Site names"] == ""


def test_mapping_preview_shows_alias_destination_and_excluded_records(monkeypatch, plan):
    entry = plan.entries[0]
    site = replace(entry.sites[0], title="Synthetic Canonical Site", source="a" * 64 + ":Synthetic Sites!B1")
    mapping = batch.WorksheetMapping("Synthetic Sites", "site", 1, 1, 0,
                                    (batch.ContactRows("Manager", 2, 0, 4),), (("B1", "Synthetic Site Alias"),))
    plan = replace(plan, entries=(replace(entry, sites=(site,)),), mappings=(mapping,),
                   exclusions=(batch.WorkbookExclusion("Unfinished Sites", "No populated contact records"),))
    app = launch(monkeypatch, plan)
    assert not app.exception
    tables = [table.value for table in app.dataframe]
    mappings = next(table for table in tables if "Directory name" in table.columns)
    assert mappings.iloc[0]["Workbook site name"] == "Synthetic Site Alias"
    assert mappings.iloc[0]["Directory name"] == "Synthetic Canonical Site"
    role_rows = next(table for table in tables if "Phone row" in table.columns)
    assert role_rows.iloc[0]["Phone row"] == "Absent"
    assert any("excluded" in msg.value for msg in app.warning)
