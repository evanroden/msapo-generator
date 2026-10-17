"""Review regressions: first staff entry, consecutive removal and browser gates."""
from dataclasses import replace
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path
import re

import pytest

from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)
from app.monthly_report_training import EVENT_REF, MATRIX_REF, add_event, load_training
from test_monthly_report_training_retention import training, current, widget, assert_work
from test_training_blank_status import open_app, grid_edit, current_matrix, standing_bytes


def two_sessions(training):
    app, draft, matrix, event, stored, saved = training
    events = add_event(event, title=event.rows[0][0], when=date(2026, 9, 1),
                       mode="Virtual", participants=["Other Hospital Tech"], hours="", period=draft.period)
    block = replace(current(app), extra_tables=(matrix, events))
    app.session_state["blocks"] = {block.key: block}
    app.run()
    assert not app.exception and not app.error
    return app, matrix, events


def test_each_consecutive_remove_works_on_its_first_native_action(training):
    app, matrix, events = two_sessions(training)
    buttons = [button for button in app.button if button.label.startswith("Remove session:")]
    buttons[1].click().run()
    assert not app.exception and not app.error
    assert next(table.rows for table in current(app).extra_tables if table.reference == EVENT_REF) == events.rows[:1]
    remaining = [button for button in app.button if button.label.startswith("Remove session:")]
    assert len(remaining) == 1
    widget(app, "text_area", "Training notes").set_value("Keep the note delivered with the second removal.")
    remaining[0].click().run()
    assert_work(app, "Keep the note delivered with the second removal.")
    assert current(app).extra_tables == (matrix,)
    assert not [button for button in app.button if button.label.startswith("Remove session:")]


def test_same_day_session_remove_names_identify_the_distinct_sessions(training):
    app, _, _ = two_sessions(training)
    labels = [button.label for button in app.button if button.label.startswith("Remove session:")]
    assert len(labels) == len(set(labels)) == 2
    assert "In person" in labels[0] and "Synthetic Hospital Tech" in labels[0]
    assert "Virtual" in labels[1] and "Other Hospital Tech" in labels[1]


def test_queued_removal_rejects_a_changed_session_collection(training):
    from app.monthly_report_editor import _signature
    app, _, events = two_sessions(training)
    key = next(button.key for button in app.button if button.label.startswith("Remove session:"))
    request_key = key.split("_remove_session_", 1)[0] + "_remove_session_request"
    before = current(app)
    # A delayed callback still carries the previous collection, not authority
    # to remove the row now occupying its old position.
    app.session_state[request_key] = (_signature(events.rows[:1]), 0)
    widget(app, "text_area", "Training notes").set_value("Keep the edit accompanying a stale removal.").run()
    assert not app.exception and not app.error
    assert any("Training sessions changed" in item.value for item in app.warning)
    assert current(app).extra_tables == before.extra_tables
    assert_work(app, "Keep the edit accompanying a stale removal.")


def test_first_staff_row_uses_new_cell_defaults_without_display_writes(tmp_path, monkeypatch):
    from app import monthly_report_directory as directory
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(directory, "load_directory", lambda *_: None)
    profile = ReportProfile("Synthetic First Staff", "a", "Site A", (Facility("a", "Site A"),))
    matrix = ReportTable(("Team member", "Site", "Safety", "Operations"), (), MATRIX_REF)
    block = ResolvedBlock("training_summary", "This month", extra_tables=(matrix,))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor", default_sections(), (block,))
    before = standing_bytes()
    app = open_app(draft, block)
    assert not app.exception and not app.error
    app.run()
    assert standing_bytes() == before
    grid_edit(app, 0, **{"Team member": "New Hospital Staff", "Site": "Site A"})
    app.run()
    assert not app.exception and not app.error
    assert current_matrix(app).rows == (("New Hospital Staff", "Site A", "Not recorded", "Not recorded"),)
    saved = load_training(profile.contract)
    app.run()
    assert load_training(profile.contract) == saved


@pytest.mark.parametrize("event", ["pull_request", "push"])
@pytest.mark.parametrize("dependency", [
    "scripts/workspace_browser_observations.py",
    "scripts/qa_monthly_live.py",
    "scripts/qa_workflow_route_observations.py",
    ".streamlit/config.toml",
    "run_web.py",
    "pages/2_Smartsheet_PO.py",
    "tests/test_workspace_layout.py",
    "tests/test_monthly_report_grid_loading.py",
])
def test_training_shared_runtime_changes_trigger_each_browser_gate(event, dependency):
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/adaptive-workspaces.yml").read_text()
    triggers = workflow.split("\npermissions:", 1)[0]
    sections = re.split(r"^  (pull_request|push):\n", triggers, flags=re.MULTILINE)
    body = dict(zip(sections[1::2], sections[2::2]))[event]
    patterns = re.findall(r"^      - '([^']+)'$", body, flags=re.MULTILINE)
    assert any(fnmatchcase(dependency, pattern) for pattern in patterns), (event, dependency)
