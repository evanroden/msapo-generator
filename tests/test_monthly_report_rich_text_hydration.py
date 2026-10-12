"""Streamlit must not turn a hydrated saved Activity value into empty text.

A blank widget mounted before saved-draft hydration is NOT a user edit.
A user explicitly deleting text remains a valid, persistent edit.
"""
import pytest
from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ResolvedBlock
from app.monthly_report_ui import _field
from app.monthly_report_editor import _signature

block = st.session_state.setdefault(
    "canonical_block",
    ResolvedBlock("activity_summary", "This month",
                  text="Three September work orders: 3 total, 2 completed, 1 open (66.7%)."))
spec = BlockSpec("activity_summary", "rich_text")
editor_key = "hydration_probe_edit_activity_summary_text_" + _signature(block.references)
st.session_state.setdefault(editor_key, "")
result = _edit_content(spec, block, None, "hydration_probe", {}, _field)
st.session_state["result"] = result
st.session_state["canonical_block"] = result
st.session_state["editor_key"] = editor_key
'''


def test_committed_activity_text_wins_over_unedited_blank_widget_mount():
    app = AppTest.from_string(APP, default_timeout=15).run()
    assert not app.error and not app.exception
    expected = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    assert editor.value == expected
    assert app.session_state["result"].text == expected
    with pytest.raises(KeyError):
        _ = app.session_state[app.session_state["editor_key"] + "_explicitly_edited"]
    app.run()
    assert next(widget for widget in app.text_area if widget.label == "Activity summary").value == expected
    assert app.session_state["result"].text == expected


def test_explicit_clear_and_replacement_are_not_reverted_by_hydration_guard():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("").run()
    assert not app.error and not app.exception
    marker = app.session_state["editor_key"] + "_explicitly_edited"
    with pytest.raises(KeyError):
        _ = app.session_state[marker]
    assert app.session_state["result"].text == ""
    app.run()
    assert app.session_state["result"].text == ""
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("A current, deliberate updated work-order statement.").run()
    assert app.session_state["result"].text == "A current, deliberate updated work-order statement."


def test_stale_blank_cannot_erase_a_previous_explicit_operator_edit():
    app = AppTest.from_string(APP, default_timeout=15).run()
    new_text = "Verified September pump work with a manual correction."
    next(w for w in app.text_area if w.label == "Activity summary").set_value(new_text).run()
    assert app.session_state["canonical_block"].text == new_text
    key = app.session_state["editor_key"]
    with pytest.raises(KeyError):
        _ = app.session_state[key + "_explicitly_edited"]
    # Generate/preview rerender can present a stale frontend empty widget
    # without a user callback. It must not change the authoritative draft.
    app.session_state[key] = ""
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == new_text
    assert app.session_state["canonical_block"].text == new_text


def test_unacknowledged_nonempty_widget_mismatch_does_not_overwrite_external_draft():
    app = AppTest.from_string(APP, default_timeout=15).run()
    key = app.session_state["editor_key"]
    from dataclasses import replace
    latest = "Reviewed source text arrived from another editor."
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"], text=latest)
    app.session_state[key] = "Obsolete mounted widget data."
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == latest
    assert app.session_state["canonical_block"].text == latest


def test_a_deliberate_empty_clear_and_reentry_both_stay_authoritative():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    editor.set_value("").run()
    assert app.session_state["canonical_block"].text == ""
    for _ in range(2):
        app.run()
        assert app.session_state["canonical_block"].text == ""
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Re-entered current-month work.").run()
    assert app.session_state["canonical_block"].text == "Re-entered current-month work."
    app.run()
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Re-entered current-month work.")
