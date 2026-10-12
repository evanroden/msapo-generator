"""Streamlit must not turn a hydrated saved Activity value into empty text.

A blank widget mounted before saved-draft hydration is NOT a user edit.
A user explicitly deleting text remains a valid, persistent edit.
"""
from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ResolvedBlock
from app.monthly_report_ui import _field
from app.monthly_report_editor import _signature

block = ResolvedBlock(
    "activity_summary", "This month",
    text="Three September work orders: 3 total, 2 completed, 1 open (66.7%).")
spec = BlockSpec("activity_summary", "rich_text")
editor_key = "hydration_probe_edit_activity_summary_text_" + _signature(block.references)
st.session_state.setdefault(editor_key, "")
result = _edit_content(spec, block, None, "hydration_probe", {}, _field)
st.session_state["result"] = result
st.session_state["editor_key"] = editor_key
'''


def test_committed_activity_text_wins_over_unedited_blank_widget_mount():
    app = AppTest.from_string(APP, default_timeout=15).run()
    assert not app.error and not app.exception
    expected = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    assert editor.value == expected
    assert app.session_state["result"].text == expected
    assert not app.session_state.get(app.session_state["editor_key"] + "_explicitly_edited", False)
    app.run()
    assert next(widget for widget in app.text_area if widget.label == "Activity summary").value == expected
    assert app.session_state["result"].text == expected


def test_explicit_clear_and_replacement_are_not_reverted_by_hydration_guard():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("").run()
    assert not app.error and not app.exception
    marker = app.session_state["editor_key"] + "_explicitly_edited"
    assert app.session_state[marker] is True
    assert app.session_state["result"].text == ""
    app.run()
    assert app.session_state["result"].text == ""
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("A current, deliberate updated work-order statement.").run()
    assert app.session_state["result"].text == "A current, deliberate updated work-order statement."
