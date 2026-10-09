"""Report-scoped inline contacts: no cross-contract or single-site fallback."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_ui as ui
from app.monthly_report_model import Facility

APP = '''
import streamlit as st
from app.monthly_report_directory_ui import render_selected_directory
from app.monthly_report_model import Facility
render_selected_directory("Rochester Regional Health", (
    Facility("unity", "Unity Hospital"), Facility("ush", "Unity Specialty Hospital")),
    st.session_state.get("actor", "Synthetic Editor"), "report")
'''


def seed(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    sites = tuple(directory.DirectorySite(key, title, contacts=(directory.DirectoryContact(
        "Manager", name, email=key + "@example.invalid"),)) for key, title, name in (
        ("unity", "Unity Hospital", "Synthetic Unity Person"),
        ("ush", "Unity Specialty Hospital", "Synthetic USH Person"),
        ("other", "Other RRH Site", "Excluded Person")))
    state = directory.save_directory("Rochester Regional Health", sites, expected_revision=0,
                                     actor="Synthetic Seeder", confirmed=True)
    other = directory.save_directory("Adventist Health", (directory.DirectorySite("elsewhere", "Elsewhere",
        contacts=(directory.DirectoryContact("Manager", "Excluded Adventist Person"),)),),
        expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    return state, other


def test_both_selected_sites_visible_no_contract_or_site_dropdown(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    app = AppTest.from_string(APP, default_timeout=20).run()
    assert not app.exception and not app.selectbox and not app.radio
    frames = [frame.value for frame in app.dataframe]
    assert frames[0]["Site"].tolist() == ["Unity Hospital", "Unity Specialty Hospital"]
    text = " ".join(str(frame) for frame in frames)
    assert "Synthetic Unity Person" in text and "Synthetic USH Person" in text
    assert "Excluded" not in text and "Adventist" not in text


def test_save_updates_both_selected_sites_and_preserves_other_records(monkeypatch, tmp_path):
    initial, other = seed(monkeypatch, tmp_path)
    original_grid = ui._grid
    def edit_grid(key, rows, **kwargs):
        result = original_grid(key, rows, **kwargs)
        if "_contacts_unity" in key or "_contacts_ush" in key:
            result = [dict(row, Phone="202-555-0199") for row in result]
        return result
    monkeypatch.setattr(ui, "_grid", edit_grid)
    app = AppTest.from_string(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == "Save these contacts").click().run()
    assert not app.exception
    saved = directory.load_directory(initial.contract)
    assert saved.revision == 2 and saved.actor == "Synthetic Editor"
    assert [s.contacts[0].phone for s in saved.sites[:2]] == ["202-555-0199"] * 2
    assert saved.sites[2] == initial.sites[2]
    assert directory.load_directory(other.contract) == other
    assert directory.load_directory(initial.contract, 1) == initial


def test_inline_blank_name_does_not_load_saved_contacts(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No saved contact reads without attribution")
    monkeypatch.setattr(directory, "load_directory", forbidden)
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["actor"] = " "
    app.run()
    assert not app.exception and not app.dataframe and not app.button


def test_inactive_or_ambiguous_site_never_falls_back(monkeypatch, tmp_path):
    import pytest
    state, _ = seed(monkeypatch, tmp_path)
    state = replace(state, sites=(replace(state.sites[0], active=False), *state.sites[1:]))
    with pytest.raises(ValueError, match="needs to be resolved"):
        ui.selected_directory_sites(state, (Facility("unity", "Unity Hospital"),))


def test_inline_save_conflict_keeps_concurrent_revision(monkeypatch, tmp_path):
    initial, _ = seed(monkeypatch, tmp_path)
    original_save = directory.save_directory
    def concurrent_save(contract, sites, **kwargs):
        original_save(contract, initial.sites, expected_revision=1,
                      actor="Concurrent Editor", confirmed=True)
        return original_save(contract, sites, **kwargs)
    monkeypatch.setattr(directory, "save_directory", concurrent_save)
    app = AppTest.from_string(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == "Save these contacts").click().run()
    assert not app.exception
    assert any("Someone changed this directory" in error.value for error in app.error)
    saved = directory.load_directory(initial.contract)
    assert saved.revision == 2 and saved.actor == "Concurrent Editor"
    assert saved.sites == initial.sites
