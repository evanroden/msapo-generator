"""Rejected off-page native issue callbacks stay copyable, never replayed.

Unlike a pending edit, the first delivery can arrive after the canonical row
has changed and the editor navigated to another page.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, synthetic_profiles,
)

SCRIPT = '''
import streamlit as st
from app.monthly_report_followups import render_followups
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["draft"] = render_followups(st.session_state["draft"],
                                             "offpage", field, category="issue")
'''


def workspace():
    rows = tuple(
        ReportFollowUp(f"issue-{n}", "issue", f"Damper issue {n}", "2026-10",
                       evidence_note=f"Evidence note {n}")
        for n in range(30)
    )
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic operator", (), (), follow_ups=rows,
                        synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == "Issue page").value == 1
    return app


@pytest.mark.parametrize(("label", "value", "field"), [
    ("Issue description", "Delayed description from old row", "text"),
    ("Issue status", "resolved", "status"),
    ("Issue update", "Delayed update from old row", "update"),
    ("Evidence or explanation for the status", "Delayed evidence from old row", "evidence_note"),
])
def test_rejected_offpage_field_is_copyable_and_cannot_replay_on_aba(label, value, field):
    app = workspace()
    before = app.session_state["draft"]
    old = before.follow_ups[0]
    native = next(w for w in
                  (*app.text_area, *app.selectbox)
                  if w.label == label)
    native.set_value(value)
    changed = replace(old, text="Canonical correction by another editor")
    current = replace(before, follow_ups=(changed, *before.follow_ups[1:]))
    app.session_state["draft"] = current
    next(w for w in app.selectbox if w.label == "Issue page").set_value(2).run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups == current.follow_ups
    copies = [w.proto.code_text for w in app.get("code") if str(value) in w.proto.code_text]
    assert len(copies) == 1
    assert not [k for k in app.session_state.filtered_state
                if k.startswith("offpage_issue_issue-0_") and k.endswith("_change")]

    # Restoration of the exact previous row is not consent to apply its callback.
    app.session_state["draft"] = before
    next(w for w in app.selectbox if w.label == "Issue page").set_value(1).run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0] == old
    assert len([w for w in app.get("code") if str(value) in w.proto.code_text]) == 1

    # A fresh, deliberate edit still applies without erasing old recovery.
    next(w for w in app.text_area if w.label == "Issue description").set_value(
        "Fresh deliberate correction").run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0].text == "Fresh deliberate correction"
    assert len([w for w in app.get("code") if str(value) in w.proto.code_text]) == 1


def test_unlink_choice_is_kept_when_the_page_changes_in_the_same_event():
    rows = tuple(
        ReportFollowUp(f"issue-{n}", "issue", f"Damper issue {n}", "2026-10",
                       references=("removed-synthetic-source:1:digest",) if n == 0 else ())
        for n in range(30)
    )
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic operator", (), (), follow_ups=rows, synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    next(w for w in app.checkbox if w.label == "Remove unavailable source links").check()
    next(w for w in app.selectbox if w.label == "Issue page").set_value(2)
    app.run()  # both choices arrive in one event; the issue's card is now off-page
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0].references == ()
    assert app.session_state["draft"].follow_ups[1:] == rows[1:]


def test_offpage_unlink_never_applies_to_an_independently_replaced_issue():
    rows = tuple(
        ReportFollowUp(f"issue-{n}", "issue", f"Damper issue {n}", "2026-10",
                       references=("removed-synthetic-source:1:digest",) if n == 0 else ())
        for n in range(30)
    )
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10),
                        "Synthetic operator", (), (), follow_ups=rows, synthetic=True)
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    next(w for w in app.checkbox if w.label == "Remove unavailable source links").check()
    next(w for w in app.selectbox if w.label == "Issue page").set_value(2)
    # The canonical issue is replaced independently before this delivery commits.
    replaced = replace(rows[0], text="Independently saved damper wording")
    app.session_state["draft"] = replace(draft, follow_ups=(replaced, *rows[1:]))
    app.run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0] == replaced  # its links are untouched
