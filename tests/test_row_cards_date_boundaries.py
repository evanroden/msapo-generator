"""Extreme source dates remain correctable without overflowing native calendars."""
from dataclasses import replace
from datetime import date

import pytest

from app import monthly_report_library as library
from app.monthly_report_row_cards_ui import _field_default
from test_monthly_report_row_cards_ui import workspace, button, field


EXTREME_DATES = (
    "0001-01-01", "0004-02-29", "0010-12-31",
    "9990-01-01", "9996-02-29", "9999-12-31",
)


def source_rows(value):
    return (("00042", value, "Synthetic plant", "Inspect equipment", "P-0007"),
            ("00043", "2026-09-14", "Other area", "Retain other work", "P-0008"))


@pytest.mark.parametrize("value", EXTREME_DATES)
def test_outside_native_ten_year_bounds_uses_exact_source_text(value):
    assert _field_default(value, "date") == value


@pytest.mark.parametrize("value,expected", [
    ("", None), ("2026-09-12", date(2026, 9, 12)),
    ("2024-02-29", date(2024, 2, 29)),
    ("9989-12-31", date(9989, 12, 31)),
    ("0011-01-01", date(11, 1, 1)),
    ("Unknown", "Unknown"), ("2026-02-30", "2026-02-30"),
])
def test_supported_and_unknown_date_defaults_keep_existing_behavior(value, expected):
    assert _field_default(value, "date") == expected


@pytest.mark.parametrize("value", EXTREME_DATES)
def test_extreme_date_opens_and_closes_without_losing_source_or_sibling(value):
    app = workspace("service_calls", source_rows(value))
    original = app.session_state["block"]
    button(app, "Edit onsite call").click().run()
    assert not app.exception
    assert field(app, "Finish Date").value == value
    assert not app.date_input
    assert button(app, "Close editing")
    assert app.session_state["block"] == original
    identity = field(app, "Finish Date").proto.id
    app.run()
    assert not app.exception
    assert field(app, "Finish Date").proto.id == identity
    button(app, "Close editing").click().run()
    assert not app.exception and app.session_state["block"] == original
    button(app, "Edit onsite call").click().run()
    assert field(app, "Finish Date").value == value


@pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31"])
@pytest.mark.parametrize("correction", ["2026-09-12", ""])
def test_correction_or_clear_survives_same_event_close_and_snapshot_history(
        value, correction, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = workspace("service_calls", source_rows(value))
    original = app.session_state["block"]
    draft = app.session_state["draft"]
    before = replace(draft, blocks=tuple(b for b in draft.blocks if b.key != original.key)
                     + (original,))
    library.save_snapshot(before, expected_revision=0, entered_editor=before.prepared_by)
    button(app, "Edit onsite call").click().run()
    assert not app.exception
    identity = field(app, "Finish Date").proto.id
    field(app, "Finish Date").set_value(correction).run()
    assert not app.exception
    assert field(app, "Finish Date").proto.id == identity
    assert not app.date_input  # Keep the mounted editor type during correction.
    field(app, "Task Code-Description", "text_area").set_value("Operator corrected date")
    button(app, "Close editing").click().run()
    assert not app.exception
    edited = app.session_state["block"]
    assert edited.rows == (("00042", correction, "Synthetic plant",
                            "Operator corrected date", "P-0007"), original.rows[1])
    assert edited.references == original.references
    after = replace(before, blocks=tuple(edited if b.key == edited.key else b
                                         for b in before.blocks))
    library.save_snapshot(after, expected_revision=1, entered_editor=after.prepared_by)
    restored = library.load_snapshot(after.profile.contract, after.profile.key, after.period)
    assert restored.draft == after
    assert library.load_snapshot_version(before.profile.contract, before.profile.key,
                                         before.period, 1).draft == before
    fresh = workspace("service_calls", next(b for b in restored.draft.blocks if b.key == "service_calls").rows)
    button(fresh, "Edit onsite call").click().run()
    assert not fresh.exception
    assert field(fresh, "Finish Date", "date_input").value == (
        date(2026, 9, 12) if correction else None)


@pytest.mark.parametrize("value", ["2026-09-12", "2024-02-29", ""])
def test_ordinary_date_and_blank_still_use_the_native_calendar(value):
    app = workspace("service_calls", source_rows(value))
    original = app.session_state["block"]
    button(app, "Edit onsite call").click().run()
    assert not app.exception
    assert field(app, "Finish Date", "date_input").value == (
        date.fromisoformat(value) if value else None)
    button(app, "Close editing").click().run()
    assert app.session_state["block"] == original


def test_extreme_date_edit_conflict_retains_both_versions():
    app = workspace("service_calls", source_rows("9999-12-31"))
    original = app.session_state["block"]
    button(app, "Edit onsite call").click().run()
    assert not app.exception
    field(app, "Finish Date").set_value("2026-09-12")
    current = replace(original, rows=(
        ("00042", "2026-09-13", "Synthetic plant", "Other editor's correction", "P-0007"),
        original.rows[1]))
    app.session_state["block"] = current
    app.run()
    assert not app.exception
    assert app.session_state["block"] == current
    assert any("Both versions" in warning.value for warning in app.warning)
    assert app.dataframe[0].value.iloc[0]["Finish Date"] == "2026-09-13"
    assert app.dataframe[1].value.iloc[0]["Finish Date"] == "2026-09-12"
    button(app, "Keep current table").click().run()
    assert not app.exception and app.session_state["block"] == current


def test_editing_sibling_does_not_normalize_extreme_date():
    app = workspace("service_calls", source_rows("0001-01-01"))
    original = app.session_state["block"]
    button(app, "Edit onsite call", 1).click().run()
    assert not app.exception
    field(app, "Area").set_value("Corrected other area")
    button(app, "Close editing").click().run()
    assert not app.exception
    edited = app.session_state["block"]
    assert edited.rows[0] == original.rows[0]
    assert edited.rows[1] == ("00043", "2026-09-14", "Corrected other area",
                             "Retain other work", "P-0008")
    assert edited.references == original.references
