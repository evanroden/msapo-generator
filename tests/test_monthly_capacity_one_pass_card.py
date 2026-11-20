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


def _complete_export_draft(current):
    """Supply unrelated required sections with synthetic data for full export.

    Keep the production preflight gate intact: only the fixture was incomplete.
    """
    from app.monthly_report_model import OrgChartNode
    return replace(current, blocks=(
        *current.blocks,
        ResolvedBlock("org_chart", "This month", org_nodes=(
            OrgChartNode("synthetic-lead", "Synthetic Site Lead", "Site Lead"),)),
        ResolvedBlock("activity_summary", "This month", text="Synthetic monthly activity."),
        ResolvedBlock("equipment_issues", "This month", text="Synthetic equipment follow-up."),
        ResolvedBlock("training_summary", "This month", text="Synthetic training summary."),
    ))


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



def test_stale_reuse_action_does_not_adopt_changed_standing_revision(profile, monkeypatch):
    original = saved(profile)
    current = draft(profile, ResolvedBlock("thermal_capacity", "This month"))
    app = _app(monkeypatch, current)
    stale, = [button for button in app.button if button.label == "Use approved capacity in this report"]
    # Another reviewer publishes a newer contract revision after the button
    # is displayed, before this native action is delivered.
    newer = saved(profile, CSV.replace(b"1200", b"1350"), revision=1)
    stale.click().run()
    assert not app.exception
    assert app.session_state["test_block"] == current.blocks[0]
    assert capacity.load_capacity(profile.contract) == newer
    fresh, = [button for button in app.button if button.label == "Use approved capacity in this report"]
    assert fresh.id != stale.id
    fresh.click().run()
    assert not app.exception
    assert app.session_state["test_block"].extra_tables[0].rows[0][2] == "1350"
    assert capacity.load_capacity(profile.contract) == newer

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
    export_draft = _complete_export_draft(replace(next_month, blocks=(restored,)))
    document = Document(BytesIO(assemble_docx(
        export_draft, acknowledged_fingerprint=export_draft.fingerprint)))
    rows = [tuple(cell.text for cell in row.cells) for table in document.tables for row in table.rows]
    assert ("NH", "Chilled water", "NR", "1600", "tons") in rows
    assert ("NH", "Steam", "40000", "50000", "lb/hr") in rows
    assert all(row[0] != "SH" for row in rows if row)


from conftest import requires_libreoffice


@requires_libreoffice
def test_two_sites_native_columns_units_and_unknown_survive_real_docx_pdf(profile):
    """Converts synthetic output with the actual report writer; no mocked renderer."""
    import hashlib
    import json
    import os
    from pathlib import Path

    import pymupdf as fitz
    from app.monthly_report_docx import assemble_docx, _convert_report_pdf

    raw = CSV.replace(b"1200", b"NR")
    state = saved(profile, raw)
    both = replace(profile, key="both", title="North and South Hospitals",
                   facilities=(Facility("north", "North Hospital"),
                               Facility("south", "South Hospital")),
                   scope_type="multi_site")
    block = capacity.capacity_block(both, state)
    assert block.extra_tables[0].columns == (
        "Facility", "Service", "Required capacity", "Available capacity", "Units")
    current = _complete_export_draft(draft(both, block))
    word = assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    document = Document(BytesIO(word))
    tables = [[tuple(cell.text for cell in row.cells) for row in table.rows]
              for table in document.tables]
    expected_header = ("Facility", "Service", "Required capacity", "Available capacity", "Units")
    matched = [table for table in tables if table and table[0] == expected_header]
    assert len(matched) == 1
    assert matched[0][1:] == [
        ("NH", "Chilled water", "NR", "1600", "tons"),
        ("NH", "Steam", "40000", "50000", "lb/hr"),
        ("SH", "Chilled water", "800", "1000", "tons"),
        ("SH", "Steam", "20000", "24000", "lb/hr"),
    ]
    pdf, error = _convert_report_pdf(current, word)
    assert pdf, error
    with fitz.open(stream=pdf, filetype="pdf") as rendered:
        page_count = len(rendered)
        pdf_text = " ".join(" ".join(page.get_text().split()) for page in rendered)
    for part in ("Facility", "Required", "Available", "NR", "1600",
                 "Chilled water", "Steam", "tons", "lb/hr", "NH", "SH"):
        assert part in pdf_text
    assert capacity.load_capacity(profile.contract) == state
    if output_dir := os.environ.get("INDEPENDENT_OUTPUT"):
        folder = Path(output_dir) / "a76-capacity"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "two-sites.docx").write_bytes(word)
        (folder / "two-sites.pdf").write_bytes(pdf)
        (folder / "manifest.json").write_text(json.dumps({
            "word_sha256": hashlib.sha256(word).hexdigest(),
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "pdf_pages": page_count,
            "native_columns": expected_header,
            "site_keys": ["north", "south"],
            "unknown_cell": "NR",
        }, indent=2) + "\n")
