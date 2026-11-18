"""A76 synthetic one-pass approved capacity reuse and report-only controls."""
from dataclasses import replace
from io import BytesIO

from docx import Document
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity, monthly_report_capacity_ui as ui
from app.monthly_report_capacity_inclusion import capacity_inclusion
from app.monthly_report_model import Facility, ReportPeriod, ResolvedBlock
from app.monthly_report_setup import new_month_draft
from test_monthly_report_capacity import CSV, draft, profile, saved
from test_monthly_report_capacity_ui import APP


def _app(monkeypatch, current):
    monkeypatch.setattr(ui.st, "file_uploader", lambda *a, **kw: None)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = current
    return app.run()


def test_empty_saved_report_can_reuse_approved_capacity_in_one_click(profile, monkeypatch):
    standing = saved(profile)
    current = draft(profile, ResolvedBlock("thermal_capacity", "This month"))
    app = _app(monkeypatch, current)
    assert not app.exception
    action, = [button for button in app.button if button.label == "Use approved capacity in this report"]
    assert not action.disabled
    action.click().run()
    assert not app.exception
    block = app.session_state["test_block"]
    assert block == capacity.capacity_block(profile, standing)
    assert len(block.extra_tables) == 1
    assert block.extra_tables[0].columns == ("Facility", "Service", "Required capacity", "Available capacity", "Units")
    assert block.extra_tables[0].rows == (
        ("NH", "Chilled water", "1200", "1600", "tons"),
        ("NH", "Steam", "40000", "50000", "lb/hr"))
    assert capacity.load_capacity(profile.contract) == standing
    app.run()
    assert not any(b.label.startswith("Use approved capacity") for b in app.button)


def test_outdated_shared_copy_refreshes_without_changing_manual_override_or_other_site(profile, monkeypatch):
    standing = saved(profile)
    old = capacity.capacity_block(profile, standing)
    latest = saved(profile, CSV.replace(b"1200", b"1350"), revision=1)
    app = _app(monkeypatch, draft(profile, old))
    assert not app.exception
    button, = [b for b in app.button if b.label == "Use latest approved capacity in this report"]
    button.click().run()
    assert not app.exception
    block = app.session_state["test_block"]
    assert block.extra_tables[0].rows[0] == ("NH", "Chilled water", "1350", "1600", "tons")
    assert capacity.load_capacity(profile.contract) == latest

    manual = ResolvedBlock("thermal_capacity", "This month",
                           rows=(("NH", "Steam", "NR", "lb/hr"),))
    app.session_state["test_draft"] = draft(profile, manual)
    app.run()
    assert not app.exception
    assert not [b for b in app.button if b.label.startswith("Use ") and "approved capacity" in b.label]
    assert app.session_state["test_block"] == manual

    other = replace(profile, key="elsewhere", title="Elsewhere",
                    facilities=(Facility("elsewhere", "Elsewhere"),))
    app.session_state["test_draft"] = draft(other, ResolvedBlock("thermal_capacity", "This month"))
    app.run()
    assert not app.exception
    assert not [b for b in app.button if "approved capacity" in b.label]
    assert capacity.load_capacity(profile.contract) == latest


def test_excluded_capacity_and_unknown_values_roll_forward_without_standing_mutation(profile):
    from app import monthly_report_library as library
    state = saved(profile, CSV.replace(b"1200", b"NR"))
    approved = capacity.capacity_block(profile, state)
    assert approved.extra_tables[0].rows[0][2] == "NR"
    omitted = capacity_inclusion(approved, False)
    current = draft(profile, omitted)
    library.save_snapshot(current, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, current.period).draft
    next_month = new_month_draft(reopened, ReportPeriod(2026, 10))
    assert next_month.blocks[0].source == "Omit"
    assert next_month.blocks[0].extra_tables == approved.extra_tables
    assert capacity.resolve_capacity(next_month) is next_month
    restored = capacity_inclusion(next_month.blocks[0], True)
    assert restored.extra_tables[0].rows[0] == ("NH", "Chilled water", "NR", "1600", "tons")
    assert capacity.load_capacity(profile.contract) == state

    from app.monthly_report_docx import assemble_docx
    document = Document(BytesIO(assemble_docx(
        replace(next_month, blocks=(restored,)),
        acknowledged_fingerprint=replace(next_month, blocks=(restored,)).fingerprint)))
    rows = [tuple(cell.text for cell in row.cells) for table in document.tables for row in table.rows]
    assert ("NH", "Chilled water", "NR", "1600", "tons") in rows
    assert ("NH", "Steam", "40000", "50000", "lb/hr") in rows
    assert all(row[0] != "SH" for row in rows if row)
