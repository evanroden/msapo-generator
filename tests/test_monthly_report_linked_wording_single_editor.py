"""One source-linked editor is authoritative; a duplicate echo cannot mask it."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.monthly_report_model import BlockSpec, DraftParagraph, ResolvedBlock


APP = """
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, DraftParagraph, ResolvedBlock
from app.monthly_report_ui import _field

block = ResolvedBlock(
    "activity_summary", "AI",
    text="- Synthetic inspected chiller.",
    ai_paragraphs=(DraftParagraph("Synthetic inspected chiller.", (), ()),))
spec = BlockSpec("activity_summary", "rich_text")
st.session_state["result"] = _edit_content(
    spec, block, None, "qa_linked_text_probe", {}, _field)
"""


def test_linked_wording_remains_unchanged_without_duplicate_echo_or_editor():
    app = AppTest.from_string(APP, default_timeout=15).run()
    assert not app.error and not app.exception
    saved = app.session_state["result"]
    assert saved.text == "- Synthetic inspected chiller."
    assert saved.ai_paragraphs[0].text == "Synthetic inspected chiller."
    assert len(app.text_area) == 0
    assert not app.text
    assert not any("Edit this source-linked wording" in caption.value
                   for caption in app.caption)


def test_single_editor_preserves_evidence_review_path():
    root = Path(__file__).resolve().parents[1]
    guided = (root / "app" / "monthly_report_guided.py").read_text(encoding="utf-8")
    linked = (root / "app" / "monthly_report_ai_ui.py").read_text(encoding="utf-8")
    assert "st.text(block.text)" not in guided
    assert "def edit_linked_paragraphs" in linked
    assert 'st.text_area(' in linked
    assert 'Evidence for paragraph' in linked
