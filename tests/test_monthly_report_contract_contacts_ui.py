"""Contract-wide contact UI integration, with synthetic records only."""

from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app.monthly_report_model import ReportPeriod, SectionSpec, synthetic_draft, synthetic_profiles


DIRECTORY_APP = """
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
"""

CONTACTS_APP = """
import streamlit as st
from app.monthly_report_directory_ui import review_contacts
from app.monthly_report_ui import _field
st.session_state["synthetic_draft"] = review_contacts(
    st.session_state["synthetic_draft"], "synthetic", _field, {})
"""


def seed_contract_contacts(monkeypatch, tmp_path, *, contract="Synthetic Contract"):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    contact = directory.DirectoryContact(
        "Asset Manager", "Synthetic Contract Lead", "202-555-0100", "lead@example.invalid", "synthetic-summary:B4"
    )
    return directory.save_directory(contract, (), contract_contacts=(contact,), expected_revision=0,
                                    actor="Synthetic Editor", confirmed=True)


def review_saved(app):
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not app.exception
    return app


def test_contract_only_saved_directory_review_and_save_retains_contacts(monkeypatch, tmp_path):
    initial = seed_contract_contacts(monkeypatch, tmp_path)
    app = review_saved(AppTest.from_string(DIRECTORY_APP).run())
    assert any("lead@example.invalid" in str(frame.value) for frame in app.dataframe)
    assert not any(choice.label == "Site contacts to edit" for choice in app.selectbox)
    assert any("Contract-wide contacts" in text.value for text in app.markdown)
    assert next(button for button in app.button if button.label == "Save contract directory").disabled
    next(box for box in app.checkbox if box.label ==
         "I reviewed all included sites and contacts and confirm this shared save").check().run()
    assert not next(button for button in app.button if button.label == "Save contract directory").disabled
    next(button for button in app.button if button.label == "Save contract directory").click().run()
    assert not app.exception
    saved = directory.load_directory(initial.contract)
    assert saved.revision == 2
    assert saved.actor == "Synthetic Reviewer"
    assert saved.sites == ()
    assert saved.contract_contacts == initial.contract_contacts
    assert directory.load_directory(initial.contract, 1) == initial
    assert any("Directory saved" in message.value for message in app.success)


def test_contract_only_contacts_apply_and_undo_without_site_selection_or_membership_change(monkeypatch, tmp_path):
    profile = synthetic_profiles()[1]
    initial = seed_contract_contacts(monkeypatch, tmp_path, contract=profile.contract)
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    draft = replace(draft, sections=(SectionSpec("organization", "3", "Organization", (directory.CONTACT_SPEC,)),),
                    blocks=(), prepared_by="Synthetic Reviewer")
    app = AppTest.from_string(CONTACTS_APP)
    app.session_state["synthetic_draft"] = draft
    app.run()
    assert not app.exception
    assert not app.selectbox and not app.multiselect
    assert not app.warning
    assert any("contract-wide contacts only" in caption.value for caption in app.caption)
    assert any(profile.contract + " (contract-wide)" in str(frame.value) for frame in app.dataframe)
    assert next(button for button in app.button if button.label == "Use reviewed contact table").disabled
    next(box for box in app.checkbox if box.label ==
         "Replace this report’s contact matrix with this reviewed directory table").check().run()
    next(button for button in app.button if button.label == "Use reviewed contact table").click().run()
    assert not app.exception
    applied = app.session_state["synthetic_draft"]
    assert applied.profile == draft.profile
    assert applied.profile.facilities == draft.profile.facilities
    block = next(block for block in applied.blocks if block.key == "contact_matrix")
    assert len(block.rows) == 1
    assert block.rows[0][0] == profile.contract + " (contract-wide)"
    assert block.rows[0][2] == initial.contract_contacts[0].name
    assert not any(reference.startswith("directory-site:") for reference in block.references)
    assert directory.load_directory(profile.contract) == initial
    next(button for button in app.button if button.label == "Undo contact table update").click().run()
    assert not app.exception
    assert app.session_state["synthetic_draft"] == draft
    assert directory.load_directory(profile.contract) == initial


@pytest.mark.parametrize("actor", ["", "   "])
def test_staged_batch_workbook_cannot_bypass_blank_editor_gate(monkeypatch, actor):
    def forbidden(*args, **kwargs):
        raise AssertionError("Blank editors must not read contacts or prepare the staged workbook")

    monkeypatch.setattr(directory, "directory_contracts", forbidden)
    monkeypatch.setattr(directory, "load_directory", forbidden)
    monkeypatch.setattr(directory, "inspect_workbook", forbidden)
    monkeypatch.setattr(batch, "prepare_workbook", forbidden)
    app = AppTest.from_string(DIRECTORY_APP)
    app.session_state["report_directory_actor"] = actor
    app.session_state["report_directory_mode"] = "Import all contract contacts"
    app.session_state["report_directory_workbook"] = (
        b"synthetic staged workbook", directory.DirectoryWorkbook("a" * 64, (), ())
    )
    app.run()
    assert not app.exception
    assert not app.radio and not app.dataframe and not app.get("data_editor")
    assert not app.get("file_uploader")
    assert [button.label for button in app.button] == ["Back to monthly reports"]
    assert any("Enter your name" in message.value for message in app.info)


def test_clearing_editor_in_batch_mode_closes_import_before_any_directory_read(monkeypatch):
    app = AppTest.from_string(DIRECTORY_APP).run()
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Import all contract contacts").run()
    assert not app.exception
    assert app.get("file_uploader")

    def forbidden(*args, **kwargs):
        raise AssertionError("Clearing the editor must close batch access before reading contacts")

    monkeypatch.setattr(directory, "directory_contracts", forbidden)
    monkeypatch.setattr(directory, "load_directory", forbidden)
    monkeypatch.setattr(batch, "prepare_workbook", forbidden)
    app.session_state["report_directory_workbook"] = (
        b"synthetic staged workbook", directory.DirectoryWorkbook("a" * 64, (), ())
    )
    app.text_input("report_directory_actor").set_value("").run()
    assert not app.exception
    assert not app.radio and not app.dataframe and not app.get("file_uploader")
    assert [button.label for button in app.button] == ["Back to monthly reports"]
