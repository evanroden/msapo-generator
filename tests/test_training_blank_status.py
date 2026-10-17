"""Legacy blank requirements stay distinct from an explicit recorded status."""
from dataclasses import asdict, replace
from datetime import date
import json

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)
from app.monthly_report_training import (
    EVENT_REF, MATRIX_REF, add_event, load_training, save_training, seed_matrix,
    validate_matrix,
)


APP = '''
import streamlit as st
from app.monthly_report_training_ui import render_training
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
st.session_state['blocks'] = render_training(st.session_state['draft'], st.session_state['blocks'], 'blank_status', field)
'''


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def matrix():
    return ReportTable(
        ("Team member", "Site", "Safety", "Operations"),
        (("Sam", "Site A", "", "Pending"),
         ("Samira", "Site A", "Completed", "Not required"),
         ("Jo", "Site A", "Not recorded", "")), MATRIX_REF,
    )


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    from app import monthly_report_directory as directory
    monkeypatch.setattr(directory, "load_directory", lambda *_: None)
    profile = ReportProfile("Synthetic Blank Training", "a", "Site A", (Facility("a", "Site A"),))
    table = matrix()
    # A real legacy manifest is deliberately read through the production loader.
    # The old save validator itself cannot create this valid historical state.
    stored = {"schema": 1, "revision": 4, "actor": "Earlier Editor", "updated_at": "2026-09-01",
              "sites": {"a": {"columns": list(table.columns[2:]),
                               "rows": [[row[0], *row[2:]] for row in table.rows]},
                        "b": {"columns": ["Safety"], "rows": [["Sam", "Completed"]]}}}
    from app.monthly_report_training import _path
    library._atomic_write(_path(profile.contract) / "manifest.json", library._json(stored))
    other = replace(profile, contract="Unrelated Synthetic Contract")
    other_stored = {"schema": 1, "revision": 1,
                    "sites": {"a": {"columns": ["Safety"], "rows": [["Sam", "Not required"]]}}}
    library._atomic_write(_path(other.contract) / "manifest.json", library._json(other_stored))
    period = ReportPeriod(2026, 9)
    event = add_event(None, title="Known September session", when=date(2026, 9, 3),
                      mode="Virtual", participants=["Jo"], hours="", period=period)
    block = ResolvedBlock("training_summary", "This month", text="Keep this monthly note.",
                          extra_tables=(table, event))
    draft = ReportDraft(profile, period, "Synthetic Editor", default_sections(), (block,))
    return draft, table, event, stored, other


def open_app(draft, block):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["blocks"] = {block.key: block}
    app.run()
    return app


def current(app):
    return app.session_state["blocks"]["training_summary"]


def current_matrix(app):
    return next(table for table in current(app).extra_tables if table.reference == MATRIX_REF)


def standing_bytes():
    return {str(path): path.read_bytes() for path in (library._root() / "training").rglob("*.json")}


def test_blank_is_valid_and_roundtrips_without_inferring_a_similar_person_status(legacy):
    draft, table, _, stored, _ = legacy
    assert validate_matrix(table) == table
    assert library.block_from_dict(asdict(draft.blocks[0])) == draft.blocks[0]
    assert seed_matrix(draft.profile, ResolvedBlock("training_summary", "This month"), stored) == table
    assert table.rows[0][2] == "" and table.rows[1][2] == "Completed"


@pytest.mark.parametrize("origin", ["report", "standing"])
def test_native_training_caller_preserves_blank_on_display_reload_and_monthly_edit(legacy, origin):
    draft, table, event, stored, _ = legacy
    block = draft.blocks[0] if origin == "report" else replace(draft.blocks[0], extra_tables=(event,))
    before = standing_bytes()
    app = open_app(draft, block)
    assert not app.exception and not app.error
    assert current_matrix(app) == table
    assert widget(app, "multiselect", "Participants").options == ["Sam", "Samira", "Jo"]
    assert standing_bytes() == before
    app.run()
    widget(app, "text_area", "Training notes").set_value("An unrelated monthly correction.").run()
    assert not app.exception and not app.error
    assert current_matrix(app) == table and event in current(app).extra_tables
    assert load_training(draft.profile.contract) == stored and standing_bytes() == before
    saved = library.save_snapshot(replace(draft, blocks=(current(app),)), expected_revision=0,
                                  entered_editor=draft.prepared_by)
    reopened = open_app(saved.draft, saved.draft.blocks[0])
    assert not reopened.exception and not reopened.error
    assert current_matrix(reopened) == table
    assert current(reopened).text == "An unrelated monthly correction."
    assert standing_bytes() == before


def grid_edit(app, row, **changes):
    """Deliver a native data-editor delta; production grid conversion still runs."""
    app.session_state[app.dataframe[0].key] = {
        "edited_rows": {row: changes}, "added_rows": [], "deleted_rows": [],
    }


def test_native_status_options_keep_raw_blank_and_new_requirement_default(legacy):
    draft, table, event, stored, _ = legacy
    app = open_app(draft, draft.blocks[0])
    config = json.loads(app.dataframe[0].proto.columns)["Safety"]
    options = {option["value"]: option["label"] for option in config["type_config"]["options"]}
    assert set(options) == {"", "Not recorded", "Pending", "Completed", "Not required"}
    assert options[""] != options["Not recorded"] and "Not recorded" in options[""]
    assert config["default"] == "Not recorded"
    widget(app, "text_input", "Requirement name").set_value("New requirement")
    widget(app, "button", "Add requirement").click().run()
    assert not app.exception and not app.error
    expected = replace(table, columns=(*table.columns, "New requirement"),
                       rows=tuple((*row, "Not recorded") for row in table.rows))
    assert current_matrix(app) == expected and event in current(app).extra_tables
    latest = load_training(draft.profile.contract)
    assert latest["revision"] == stored["revision"] + 1
    assert latest["sites"]["b"] == stored["sites"]["b"]
    before = standing_bytes()
    app.run()
    assert current_matrix(app) == expected and standing_bytes() == before


@pytest.mark.parametrize("new_status", ["Completed", ""])
def test_native_other_cell_edit_saves_only_selected_site_preserving_all_status_meanings(legacy, new_status):
    draft, table, event, stored, other = legacy
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    previous_snapshot = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    other_before = load_training(other.contract)
    app = open_app(draft, draft.blocks[0])
    grid_edit(app, 0, Operations=new_status)
    app.run()
    assert not app.exception and not app.error
    expected = replace(table, rows=(("Sam", "Site A", "", new_status), *table.rows[1:]))
    assert current_matrix(app) == expected and event in current(app).extra_tables
    latest = load_training(draft.profile.contract)
    assert latest["revision"] == stored["revision"] + 1
    assert latest["sites"]["a"]["rows"] == [[row[0], *row[2:]] for row in expected.rows]
    assert latest["sites"]["b"] == stored["sites"]["b"]
    assert load_training(other.contract) == other_before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == previous_snapshot == saved
    before = standing_bytes()
    app.run()
    assert not app.exception and not app.error
    assert current_matrix(app) == expected and standing_bytes() == before


def test_concurrent_standing_save_rejects_stale_cell_then_explicit_reload_keeps_blank_and_monthly_work(legacy):
    draft, table, event, stored, _ = legacy
    app = open_app(draft, draft.blocks[0])
    newer = replace(table, rows=(("Sam", "Site A", "", "Not required"), *table.rows[1:]))
    saved = save_training(draft.profile, newer, expected_revision=stored["revision"], actor="Other Editor")
    before = standing_bytes()
    grid_edit(app, 0, Safety="Pending")
    widget(app, "text_area", "Training notes").set_value("Keep the same-action monthly correction.").run()
    assert not app.exception and app.error
    assert current_matrix(app) == table and event in current(app).extra_tables
    assert current(app).text == "Keep the same-action monthly correction."
    assert load_training(draft.profile.contract) == saved and standing_bytes() == before
    old_grid = app.dataframe[0].key
    widget(app, "button", "Reload saved training matrix").click().run()
    assert not app.exception and not app.error
    assert current_matrix(app) == newer and event in current(app).extra_tables
    assert current(app).text == "Keep the same-action monthly correction."
    assert app.dataframe[0].key != old_grid
    assert standing_bytes() == before


def test_failed_native_cell_save_preserves_blank_and_monthly_note_until_original_edit_is_retried(legacy, monkeypatch):
    from app import monthly_report_training_ui as ui
    draft, table, event, stored, _ = legacy
    app = open_app(draft, draft.blocks[0])
    before = standing_bytes()
    original = ui.save_training

    def fail(*args, **kwargs):
        raise OSError("Synthetic training storage unavailable")

    monkeypatch.setattr(ui, "save_training", fail)
    grid_edit(app, 0, Operations="Completed")
    widget(app, "text_area", "Training notes").set_value("Monthly correction while storage is unavailable.").run()
    assert not app.exception and any("storage unavailable" in error.value for error in app.error)
    assert current_matrix(app) == table and event in current(app).extra_tables
    assert current(app).text == "Monthly correction while storage is unavailable."
    assert load_training(draft.profile.contract) == stored and standing_bytes() == before
    monkeypatch.setattr(ui, "save_training", original)
    app.run()
    assert not app.exception and not app.error
    expected = replace(table, rows=(("Sam", "Site A", "", "Completed"), *table.rows[1:]))
    assert current_matrix(app) == expected and event in current(app).extra_tables
    assert current(app).text == "Monthly correction while storage is unavailable."
    assert load_training(draft.profile.contract)["revision"] == stored["revision"] + 1
