"""Directory attribution gate and recoverable removal, using synthetic contacts."""

from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_directory_ui as ui
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


DIRECTORY_APP = """
from app.monthly_report_directory_ui import render_directory
from app.monthly_report_ui import _field
render_directory(_field)
"""


def seed_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    contact = directory.DirectoryContact("Manager", "Synthetic Manager", "202-555-0100", "manager@example.invalid")
    site = directory.DirectorySite("synthetic-site", "Synthetic Site", contacts=(contact,))
    return directory.save_directory("Synthetic Contract", (site,), expected_revision=0, actor="Synthetic Editor", confirmed=True)


def enter_directory(app):
    app.text_input("report_directory_actor").set_value("Synthetic Reviewer").run()
    app.radio("report_directory_mode").set_value("Review saved directory").run()
    assert not app.exception
    return app


def test_empty_name_never_lists_loads_or_renders_saved_directory(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved directory must not be read before a name is entered")

    monkeypatch.setattr(directory, "directory_contracts", forbidden)
    monkeypatch.setattr(directory, "load_directory", forbidden)
    app = AppTest.from_string(DIRECTORY_APP)
    # Navigating straight to the review task cannot bypass the gate.
    app.session_state["report_directory_mode"] = "Review saved directory"
    app.run()
    assert not app.exception
    assert not app.radio and not app.dataframe and not app.get("data_editor")
    assert [b.label for b in app.button] == ["Back to monthly reports"]
    assert any("Enter your name" in message.value for message in app.info)
    app.text_input("report_directory_actor").set_value("   ").run()
    assert not app.exception and not app.dataframe


def test_clearing_name_closes_directory_before_any_read(monkeypatch, tmp_path):
    seed_directory(monkeypatch, tmp_path)
    app = enter_directory(AppTest.from_string(DIRECTORY_APP).run())
    assert any("manager@example.invalid" in str(table.value) for table in app.dataframe)
    assert any("not a login" in caption.value for caption in app.caption)

    def forbidden(*args, **kwargs):
        raise AssertionError("Clearing the editor name must close saved data immediately")

    monkeypatch.setattr(directory, "directory_contracts", forbidden)
    monkeypatch.setattr(directory, "load_directory", forbidden)
    app.text_input("report_directory_actor").set_value("").run()
    assert not app.exception
    assert not app.dataframe and not app.get("data_editor")
    assert not any(b.label in ("Save contract directory", "Restore directory", "Archive contact list") for b in app.button)


def test_archive_and_restore_require_confirmation_and_retain_contacts(monkeypatch, tmp_path):
    initial = seed_directory(monkeypatch, tmp_path)
    app = enter_directory(AppTest.from_string(DIRECTORY_APP).run())
    archive_button = next(b for b in app.button if b.label == "Archive contact list")
    assert archive_button.disabled
    next(c for c in app.checkbox if c.label == "Archive this contract’s contact list").check().run()
    next(b for b in app.button if b.label == "Archive contact list").click().run()
    assert not app.exception
    assert directory.load_directory(initial.contract) is None
    archived = directory.load_directory(initial.contract, include_archived=True)
    assert archived.archived and archived.revision == 2 and archived.sites == initial.sites
    assert directory.load_directory(initial.contract, 1) == initial
    assert not any(b.label == "Save contract directory" for b in app.button)
    assert next(b for b in app.button if b.label == "Restore directory").disabled
    next(c for c in app.checkbox if c.label == "Restore this directory version as a new revision").check().run()
    next(b for b in app.button if b.label == "Restore directory").click().run()
    assert not app.exception
    restored = directory.load_directory(initial.contract)
    assert not restored.archived and restored.revision == 3 and restored.sites == initial.sites
    assert directory.load_directory(initial.contract, 2).archived


def test_nameless_report_does_not_read_directory_contact_suggestions(monkeypatch):
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), prepared_by="")

    def forbidden(*args, **kwargs):
        raise AssertionError("Contact comparison must not load a directory for a nameless report")

    monkeypatch.setattr(directory, "load_directory", forbidden)
    monkeypatch.setattr(ui.st, "caption", lambda *args, **kwargs: None)
    assert ui.review_contacts(draft, "synthetic", lambda key, default: key, {}) == draft


def test_contract_choices_merge_catalog_case_and_whitespace_variants(monkeypatch):
    monkeypatch.setattr(ui.contracts, "contract_names", lambda: ("Synthetic Contract",))
    monkeypatch.setattr(directory, "directory_contracts", lambda: (" synthetic   contract ", "SYNTHETIC CONTRACT", "Another Contract"))
    assert ui.contract_choices() == ["Synthetic Contract", "Another Contract"]
