"""Optional report capacity never clears stored values or changes shared scope."""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity, monthly_report_library as library
from app.monthly_report_capacity_inclusion import capacity_inclusion
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_capacity import profile, saved, draft
from test_monthly_report_capacity_scope_task import TASK_APP


def _toggle(app):
    return next(x for x in app.checkbox if x.label == "Include thermal capacity")


@pytest.mark.parametrize("source", ["empty", "shared", "manual"])
def test_omission_survives_shared_first_fill_and_snapshot(profile, source):
    state = saved(profile)
    block = (capacity.capacity_block(profile, state) if source == "shared" else
             ResolvedBlock("thermal_capacity", "This month", rows=(("NH", "Steam", "NR", "lb/hr"),))
             if source == "manual" else ResolvedBlock("thermal_capacity", "Library"))
    omitted = capacity_inclusion(block, False)
    current = draft(profile, omitted)
    assert capacity.resolve_capacity(current) is current
    assert not capacity.can_refresh_capacity(profile, omitted)
    library.save_snapshot(current, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, current.period).draft
    assert reopened.blocks == current.blocks
    assert capacity.resolve_capacity(reopened) is reopened
    restored = capacity_inclusion(reopened.blocks[0], True)
    assert restored.rows == block.rows
    assert restored.extra_tables == block.extra_tables
    assert restored.references == block.references
    assert capacity.load_capacity(profile.contract) == state


def test_reopened_omission_and_site_switch_do_not_share_toggle_state(profile):
    state = saved(profile)
    omitted = capacity_inclusion(capacity.capacity_block(profile, state), False)
    current = draft(profile, omitted)
    library.save_snapshot(current, expected_revision=0)
    app = AppTest.from_string(TASK_APP)
    app.session_state["test_draft"] = library.load_snapshot(profile.contract, profile.key, current.period).draft
    app.run()
    assert not app.exception
    assert not _toggle(app).value
    assert app.session_state["test_draft"].blocks[0] == omitted
    from app.monthly_report_model import Facility
    south = replace(profile, key="south", title="South Hospital", facilities=(Facility("south", "South Hospital"),))
    south_block = capacity.capacity_block(south, state)
    app.session_state["test_draft"] = draft(south, south_block)
    app.run()
    assert not app.exception
    assert _toggle(app).value
    assert app.session_state["test_draft"].blocks[0] == south_block
    assert all(row[0] == "SH" for row in south_block.extra_tables[0].rows)


def test_native_toggle_keeps_same_event_edit_and_restores_table(profile):
    state = saved(profile)
    pinned = capacity.capacity_block(profile, state)
    app = AppTest.from_string(TASK_APP)
    app.session_state["test_draft"] = draft(profile, pinned)
    app.run()
    assert not app.exception
    grid, = [w for w in app.dataframe if w.key.startswith("test_edit_thermal_capacity_")]
    app.session_state[grid.key] = {"edited_rows": {0: {"Required capacity": "NR"}},
                                 "added_rows": [], "deleted_rows": []}
    _toggle(app).uncheck().run()
    assert not app.exception
    omitted = app.session_state["test_draft"].blocks[0]
    assert omitted.source == "Omit"
    assert omitted.extra_tables[0].rows[0][2] == "NR"
    assert not any(w.label == "Thermal capacity file" for w in app.get("file_uploader"))
    assert any(w.label == "Utility result files" for w in app.get("file_uploader"))
    assert not app.dataframe
    app.run()
    assert app.session_state["test_draft"].blocks[0] == omitted
    _toggle(app).check().run()
    assert not app.exception
    restored = app.session_state["test_draft"].blocks[0]
    assert restored.source != "Omit"
    assert restored.extra_tables == omitted.extra_tables
    assert restored.references == omitted.references
    assert capacity.load_capacity(profile.contract) == state


def _output_draft(profile, included):
    block = ResolvedBlock("thermal_capacity", "This month", rows=(("CapacitySentinel", "Steam", "42", "tons"),))
    current = draft(profile, capacity_inclusion(block, included))
    return replace(current, sections=tuple(s for s in current.sections if s.key in {"scorecards", "mbcx"}), blocks=(*current.blocks,
        ResolvedBlock("utility_analysis", "This month", text="UtilitySentinel remains."),
        ResolvedBlock("mbcx_status", "This month", text="CommissioningSentinel remains.")))


@pytest.mark.parametrize("included", [False, True])
def test_capacity_selection_in_word_and_section_preview(profile, included):
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_preview import section_preview_docx
    current = _output_draft(profile, included)
    for raw in (assemble_docx(current, acknowledged_fingerprint=current.fingerprint),
                section_preview_docx(current, "scorecards")):
        doc = Document(BytesIO(raw))
        text = " ".join(doc.element.itertext())
        assert ("CapacitySentinel" in text) is included
        assert "UtilitySentinel" in text
    full = Document(BytesIO(assemble_docx(current, acknowledged_fingerprint=current.fingerprint)))
    assert "CommissioningSentinel" in " ".join(full.element.itertext())


from conftest import requires_libreoffice


@requires_libreoffice
@pytest.mark.parametrize("included", [False, True])
def test_capacity_selection_in_pdf(profile, included):
    import fitz
    from app.monthly_report_docx import assemble_docx, _convert_report_pdf
    current = _output_draft(profile, included)
    raw = assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    pdf, error = _convert_report_pdf(current, raw)
    assert pdf, error
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = " ".join(page.get_text() for page in document)
    assert ("CapacitySentinel" in text) is included
    assert "UtilitySentinel" in text
    assert "CommissioningSentinel" in text
