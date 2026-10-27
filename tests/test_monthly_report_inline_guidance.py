"""Compact Monthly hints: fewer repeated captions without losing decisions or help.

All test content is synthetic. This checks the ordinary editor only; the
source-import review retains the original, fuller section guidance.
"""
import inspect
import re

from streamlit.testing.v1 import AppTest

from app import monthly_report_guided
from app.monthly_report_model import default_sections
from app.monthly_report_section_help import (
    _EDITOR_GUIDANCE,
    editor_section_guidance,
    editor_section_heading_help,
    section_help,
)


def _words(text):
    return len(re.findall(r"\b[\w’-]+\b", text))


def test_every_standard_section_has_an_explicit_editor_copy_decision():
    keys = {section.key for section in default_sections()}
    assert set(_EDITOR_GUIDANCE) == keys
    # No new UI tasks or tooltips are needed for self-explanatory sections.
    assert {key for key in keys if not editor_section_guidance(key)} == {
        "organization", "activity", "subcontractors"
    }
    # Full source-review help must survive separately, including omissions.
    for key in keys:
        assert section_help(key).guidance
    assert "outage procedures" in section_help("organization").guidance
    assert "vendor contacts" in section_help("subcontractors").guidance


def test_inline_word_count_reduces_by_at_least_thirty_percent():
    keys = [section.key for section in default_sections()]
    before = sum(_words(section_help(key).guidance) for key in keys)
    after = sum(_words(editor_section_guidance(key)) for key in keys)
    assert before > 0
    assert after * 10 <= before * 7


def test_inline_copy_preserves_relevant_scope_and_safety():
    terms = {
        "scorecards": ("unknown capacity", "NR", "confirmed"),
        "mbcx": ("Add monitoring results or a brief status update.",),
        "maintenance": ("ENFRA", "onsite", "vendor", "Monthly Activity Summary"),
        "water": ("out-of-range", "follow-up"),
        "issues": ("this report only",),
        "capital": ("unknown dates blank",),
        "proposals": ("prices", "legal-only"),
        "training": ("completed", "hospital/client", "hours"),
        "rfi": ("request for information", "confirmed"),
    }
    for section, required in terms.items():
        text = editor_section_guidance(section)
        for phrase in required:
            assert phrase.casefold() in text.casefold(), (section, phrase)
    assert editor_section_guidance("mbcx") == "Add monitoring results or a brief status update."
    heading_help = editor_section_heading_help("mbcx")
    assert all(term in heading_help for term in ("MBCx", "monitoring-based commissioning", "verified"))
    assert all(editor_section_heading_help(key) is None
               for key in _EDITOR_GUIDANCE if key != "mbcx")
    # Unrecognized imported/design variant sections retain source help.
    assert editor_section_guidance("unrecognized") == section_help("unrecognized").guidance


def test_guidance_is_used_conditionally_in_the_actual_workflow():
    source = inspect.getsource(monthly_report_guided.render_guided_workflow)
    assert "guidance = editor_section_guidance(section.key)" in source
    assert "if guidance:\n                    st.caption(guidance)" in source
    assert "st.caption(section_help(section.key).guidance)" not in source
    assert "help=editor_section_heading_help(section.key)" in source


def test_native_caption_inventory_does_not_add_any_actions():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_model import default_sections
from app.monthly_report_section_help import editor_section_guidance
for section in default_sections():
    guidance = editor_section_guidance(section.key)
    if guidance:
        st.caption(guidance)
""").run()
    assert not app.exception
    assert [caption.value for caption in app.get("caption")] == [
        editor_section_guidance(section.key)
        for section in default_sections()
        if editor_section_guidance(section.key)
    ]
    assert not app.button and not app.checkbox and not app.radio


def test_mbcx_existing_heading_and_exact_single_caption_render_with_help():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_section_help import editor_section_guidance, editor_section_heading_help
st.subheader("MBCx Reports", help=editor_section_heading_help("mbcx"))
st.caption(editor_section_guidance("mbcx"))
""").run()
    assert not app.exception
    assert [item.value for item in app.get("subheader")] == ["MBCx Reports"]
    assert [item.value for item in app.get("caption")] == [
        "Add monitoring results or a brief status update."
    ]
    assert not app.button and not app.checkbox
