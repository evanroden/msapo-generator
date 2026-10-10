"""An older monthly report cannot erase newer shared client-staff training."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock, default_sections
from app.monthly_report_training import MATRIX_REF, load_training, save_training, validate_matrix, matrix_differs_from_current_standing
from app import monthly_report_training_ui as ui


APP = """
import streamlit as st
from app.monthly_report_training_ui import render_training
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["blocks"] = render_training(st.session_state["draft"], st.session_state["blocks"], "test", field)
"""


def sample():
    profile = ReportProfile("Synthetic Training Isolation", "north-and-south", "Synthetic group",
                            (Facility("north", "North"), Facility("south", "South")), "multi_site")
    previous = ReportTable(("Team member", "Site", "Fire Safety"), (
        ("Person One", "North", "Pending"),), MATRIX_REF)
    newer = ReportTable(previous.columns, (
        *previous.rows, ("Person Two", "North", "Not recorded"),
        ("South Person", "South", "Pending")), MATRIX_REF)
    return profile, previous, newer


def test_old_snapshot_edit_requires_current_training_before_shared_write(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app import monthly_report_directory as directory
    monkeypatch.setattr(directory, "load_directory", lambda *_: None)
    profile, previous, newer = sample()
    original_block = ResolvedBlock("training_summary", "This month", text="Keep this historical note",
                                   extra_tables=(previous,))
    old_report = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor",
                             default_sections(), (original_block,))
    save_training(profile, previous, expected_revision=0, actor="Synthetic Editor")
    saved = library.save_snapshot(old_report, expected_revision=0, entered_editor="Synthetic Editor")
    save_training(profile, newer, expected_revision=1, actor="Second Editor")

    assert matrix_differs_from_current_standing(profile, original_block,
                                                 load_training(profile.contract))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = old_report
    app.session_state["blocks"] = {"training_summary": original_block}
    app.run()
    assert not app.exception
    assert any("older training matrix" in item.value for item in app.warning)

    original_grid = ui._grid
    def stale_edit(key, rows, **kwargs):
        return [dict(row, **{"Fire Safety": "Completed"}) for row in rows]
    monkeypatch.setattr(ui, "_grid", stale_edit)
    app.run()
    assert not app.exception
    assert any("Reload saved training" in item.value for item in app.error)
    assert load_training(profile.contract)["revision"] == 2
    assert load_training(profile.contract)["sites"]["north"]["rows"] == [
        ["Person One", "Pending"], ["Person Two", "Not recorded"]]
    assert library.load_snapshot(profile.contract, profile.key, old_report.period) == saved

    monkeypatch.setattr(ui, "_grid", original_grid)
    next(b for b in app.button if b.label == "Reload saved training matrix").click().run()
    assert not app.exception and not app.error
    current = app.session_state["blocks"]["training_summary"]
    assert current.text == original_block.text
    assert newer in current.extra_tables

    monkeypatch.setattr(ui, "_grid", stale_edit)
    app.run()
    assert not app.exception and not app.error
    revised = load_training(profile.contract)
    assert revised["revision"] == 3
    assert revised["sites"]["north"]["rows"] == [
        ["Person One", "Completed"], ["Person Two", "Completed"]]
    assert revised["sites"]["south"]["rows"] == [["South Person", "Completed"]]
    assert library.load_snapshot(profile.contract, profile.key, old_report.period) == saved


def test_course_and_person_names_normalize_whitespace_and_case():
    profile, previous, newer = sample()
    double = replace(previous, columns=("Team member", "Site", "Safety Check", " safety   check "))
    with pytest.raises(ValueError, match="unique"):
        validate_matrix(double)
    duplicate = replace(previous, rows=(
        ("Person One", "North", "Pending"), (" PERSON  one ", " north ", "Completed")))
    with pytest.raises(ValueError, match="one row"):
        validate_matrix(duplicate)
    validate_matrix(newer)  # the same name at two different sites is permitted


def test_report_only_matrix_without_matching_standing_rows_is_not_reclassified():
    profile, previous, _ = sample()
    block = ResolvedBlock("training_summary", "This month", extra_tables=(previous,))
    assert not matrix_differs_from_current_standing(profile, block, {"sites": {}})
    assert not matrix_differs_from_current_standing(profile, block, {"sites": {"other": {"rows": []}}})
