"""Carried numeric source cells remain correctable without losing original text."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import BlockSpec, ColumnSpec, ResolvedBlock
from app.monthly_report_row_cards_ui import _field_default
from test_monthly_report_row_cards_ui import SCRIPT, button, field


def workspace(value):
    spec = BlockSpec("proposals", "table", columns=(
        ColumnSpec("task", "Task"), ColumnSpec("hours", "Hours", "number")))
    block = ResolvedBlock("proposals", "This month", rows=(
        ("Synthetic carried task", value), ("Other task", "2.5")),
        references=("synthetic-original-source",))
    script = SCRIPT.replace("INITIAL", repr(block)).replace("SPEC", repr(spec))
    return AppTest.from_string(script).run(), spec, block


@pytest.mark.parametrize("value", ["NaN", "inf", "-Infinity", "1e309", "-1e309"])
def test_nonfinite_source_opens_as_literal_text_and_survives_close_reopen_and_correction(
        value, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app, spec, original = workspace(value)
    assert not app.exception
    button(app, "Edit proposal").click().run()
    assert not app.exception
    hours = field(app, "Hours")
    assert hours.value == value
    assert not app.number_input
    identity = hours.proto.id
    button(app, "Close editing").click().run()
    assert not app.exception and app.session_state["block"] == original
    button(app, "Edit proposal").click().run()
    assert field(app, "Hours").value == value
    assert field(app, "Hours").proto.id == identity
    field(app, "Hours").set_value("3.25").run()
    # It remains the same text editor while the previously unknown cell is open.
    assert field(app, "Hours").proto.id == identity
    assert not app.number_input
    button(app, "Close editing").click().run()
    edited = app.session_state["block"]
    assert edited.rows == (("Synthetic carried task", "3.25"), original.rows[1])
    assert edited.references == original.references
    draft = app.session_state["draft"]
    section = next(section for section in draft.sections if section.key == "proposals")
    draft = replace(draft, sections=(replace(section, blocks=(spec,)),), blocks=(edited,))
    library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft == draft
    fresh, _, _ = workspace(value)
    fresh.session_state["block"] = edited
    fresh.run()
    button(fresh, "Edit proposal").click().run()
    assert not fresh.exception
    assert field(fresh, "Hours", "number_input").value == 3.25


@pytest.mark.parametrize("kind", ["number", "currency"])
@pytest.mark.parametrize("value", ["NaN", " inf ", "-Infinity", "1e309", "-1e309"])
def test_nonfinite_defaults_preserve_exact_source_text(kind, value):
    assert _field_default(value, kind) == value


@pytest.mark.parametrize("value,expected", [("", None), ("0", 0.0), ("1.25", 1.25), ("-3", -3.0)])
def test_finite_and_blank_cells_keep_native_numeric_controls(value, expected):
    app, _, original = workspace(value)
    button(app, "Edit proposal").click().run()
    assert not app.exception
    assert field(app, "Hours", "number_input").value == expected
    button(app, "Close editing").click().run()
    assert app.session_state["block"] == original
