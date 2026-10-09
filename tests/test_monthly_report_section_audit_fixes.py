from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from app.monthly_report_editor import _typed_table
from app.monthly_report_model import BlockSpec, ColumnSpec, ReportSource, default_sections
from app.monthly_report_sources import native_action_lines


def editor_app(key, kind):
    return AppTest.from_string('''
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from PIL import Image
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_ui import _field
raw=BytesIO(); Image.new("RGB", (120,120), "navy").save(raw, "PNG")
assets=st.session_state.setdefault("assets", {"old.png":raw.getvalue()})
block=st.session_state.setdefault("block", ResolvedBlock(KEY, "Library", text="Existing reviewed notes.", asset_hashes=("old.png",), references=("original-source",)))
st.session_state.block=_edit_content(BlockSpec(KEY, KIND), block, SimpleNamespace(profile=synthetic_profiles()[0]), "report_audit", assets, _field)
'''.replace('KEY', repr(key)).replace('KIND', repr(kind))).run()


def test_imported_water_notes_are_visible_and_editable_without_losing_pages():
    app = editor_app("water_reports", "pdf_pages")
    assert not app.exception
    original = app.session_state.block
    notes = next(w for w in app.text_area if w.label == "Notes included in this section")
    assert notes.value == original.text
    notes.set_value("Updated findings and follow-ups.").run()
    assert app.session_state.block.text == "Updated findings and follow-ups."
    assert app.session_state.block.asset_hashes == original.asset_hashes
    assert app.session_state.block.references == original.references
    assert "Replace all report pages with one image (optional)" in {e.label for e in app.expander}


def test_training_photo_appends_and_retains_notes_and_original_sources(monkeypatch):
    incoming = {}
    real_upload = guided.st.file_uploader
    monkeypatch.setattr(guided.st, "file_uploader", lambda label, *a, **kw: incoming.get(label) or real_upload(label, *a, **kw))
    app = editor_app("training_summary", "rich_text")
    raw = BytesIO()
    Image.new("RGB", (120, 120), "green").save(raw, "PNG")
    raw.name, raw.size = "training.png", len(raw.getvalue())
    incoming["Photo to add to this section"] = raw
    app.run()
    next(b for b in app.button if b.label == "Add this photo").click().run()
    block = app.session_state.block
    assert not app.exception
    assert len(block.asset_hashes) == 2 and block.asset_hashes[0] == "old.png"
    assert block.text == "Existing reviewed notes." and block.references == ("original-source",)
    assert len(block.asset_captions) == 2


def test_capital_and_rfi_preserve_unknown_timing_and_original_symbols():
    capital = next(b for s in default_sections() for b in s.blocks if b.key == "capital_renewal")
    assert not capital.stock_text_keys
    timing = BlockSpec("end_of_life", "table", columns=(ColumnSpec("end_date", "Timing", "date"),))
    rows, _ = _typed_table(timing, (("2030",), ("2030-09",), ("Unknown",)))
    assert [r["Timing"] for r in rows] == ["2030", "2030-09", "Unknown"]
    legacy = BlockSpec("rfi_matrix", "table", columns=(ColumnSpec("complete", "Complete", "boolean"),))
    rows, _ = _typed_table(legacy, (("X",), ("✓",), ("",)))
    assert [r["Complete"] for r in rows] == ["X", "✓", None]


def test_completed_work_suggestions_exclude_plans_negation_and_conditions():
    source = ReportSource("a"*64, "service.pdf", "a"*64, ".pdf", "Vendor service",
                          page_texts=("Inspected pump.\nPump has not been repaired.\nRecommend that the seal be replaced.\nValve will be replaced.\nWork wasn't completed.\nIf approved, motor should be replaced.",), selected_pages=(1,))
    assert native_action_lines(source) == (("Inspected pump.", (1,)),)


def test_carried_result_confirmation_is_explicit_and_preserves_text():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_guided import _review_carried_update
from app.monthly_report_model import ReportPeriod, ResolvedBlock
block=st.session_state.setdefault("block", ResolvedBlock("utility_analysis", "Last month", text="Existing utility result.", references=("report-origin:2026-09", "report-period:2026-09")))
st.session_state.block=_review_carried_update(block, ReportPeriod(2026,10), "report_test")
''').run()
    assert any("September 2026" in v.value for v in app.info)
    next(b for b in app.button if b.label == "This update is correct for October 2026").click().run()
    assert app.session_state.block.text == "Existing utility result."
    assert "report-period:2026-10" in app.session_state.block.references
    assert "report-origin:2026-09" in app.session_state.block.references
