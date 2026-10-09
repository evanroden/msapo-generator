"""Carried records are edited once, within their own report section."""

from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_followups import confirmation, problems
from app.monthly_report_model import ReportPeriod


def workspace():
    return AppTest.from_string('''
import streamlit as st
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, synthetic_profiles
from app.monthly_report_followups import render_followups
from app.monthly_report_ui import _field, preserve_report_draft_state, restore_report_draft_state
restore_report_draft_state()
issue = ReportFollowUp("pump", "issue", "Pump vibration remains under investigation.", "2026-09")
proposal = ReportFollowUp("controls", "proposal", "Scope: Controls renewal; Status: Declined", "2026-09")
draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), "Synthetic Editor", (), (), follow_ups=(issue, proposal))
st.session_state.setdefault("draft", draft)
category = st.radio("Section", ("issue", "proposal"))
st.session_state["draft"] = render_followups(st.session_state["draft"], "synthetic", _field, category=category)
preserve_report_draft_state()
''').run()


def button(app, label):
    return next(value for value in app.button if value.label == label)


def test_unchanged_issue_requires_one_action_and_does_not_touch_other_category():
    app = workspace()
    assert not app.exception
    original_proposal = app.session_state["draft"].follow_ups[1]
    assert original_proposal.status == "ongoing"  # Not normalized in another section.
    assert not app.text_area and not app.multiselect and not app.checkbox
    assert [value.label for value in app.radio] == ["Section"]
    assert not any("Controls renewal" in value.value for value in app.markdown)
    button(app, "Still open").click().run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)
    assert draft.follow_ups[1] == original_proposal
    assert not app.text_area


def test_resolving_opens_evidence_and_requires_it_without_omitting_the_issue():
    app = workspace()
    button(app, "Mark resolved").click().run()
    assert not app.exception
    assert button(app, "Confirm update").disabled
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].status == "resolved" and draft.follow_ups[0].included
    assert any("Add evidence" in value.value for value in app.warning)
    next(value for value in app.text_area if value.label == "Evidence or explanation for the status").set_value(
        "Inspection confirmed that replacement bearings corrected the vibration."
    ).run()
    assert not button(app, "Confirm update").disabled
    button(app, "Confirm update").click().run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)
    assert draft.follow_ups[0].included
    app.run()
    assert not app.text_area


def test_proposal_has_decisions_and_explicit_omission_preserving_issue_edits():
    app = workspace()
    button(app, "Still open").click().run()
    original_issue = app.session_state["draft"].follow_ups[0]
    app.radio[0].set_value("proposal").run()
    assert not app.text_area
    button(app, "Update proposal").click().run()
    decision = next(value for value in app.radio if value.label == "Proposal decision")
    assert decision.value == "declined" and "Resolved" not in decision.options
    decision.set_value("approved").run()
    next(value for value in app.checkbox if value.label == "Leave this proposal out of the report").check().run()
    button(app, "Confirm update").click().run()
    draft = app.session_state["draft"]
    assert draft.follow_ups[0] == original_issue
    assert draft.follow_ups[1].status == "approved"
    assert not draft.follow_ups[1].included and not problems(draft.follow_ups[1], draft)


def test_edit_survives_section_switch_and_confirmation_is_period_bound():
    app = workspace()
    button(app, "Update issue").click().run()
    next(value for value in app.text_area if value.label == "What changed this month?").set_value(
        "A vibration survey is scheduled."
    ).run()
    button(app, "Confirm update").click().run()
    original = app.session_state["draft"].follow_ups[0]
    app.radio[0].set_value("proposal").run()
    app.radio[0].set_value("issue").run()
    assert app.session_state["draft"].follow_ups[0] == original
    assert not app.text_area
    app.session_state["draft"] = replace(app.session_state["draft"], period=ReportPeriod(2026, 11))
    app.run()
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].reviewed_fingerprint != confirmation(draft.follow_ups[0], draft.period)
    button(app, "Still open").click().run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)


def test_missing_source_cannot_be_silently_dropped_by_opening_editor():
    app = workspace()
    draft = app.session_state["draft"]
    issue = replace(draft.follow_ups[0], status="updated", references=("missing-source#page=1",))
    app.session_state["draft"] = replace(draft, follow_ups=(issue, draft.follow_ups[1]))
    app.run()
    assert app.session_state["draft"].follow_ups[0].references == issue.references
    assert button(app, "Still correct").disabled and button(app, "Confirm update").disabled
    next(value for value in app.checkbox if value.label == "Remove unavailable source links").check().run()
    assert not app.session_state["draft"].follow_ups[0].references
    assert button(app, "Confirm update").disabled  # An update still needs evidence.
    next(value for value in app.text_area if value.label == "Evidence or explanation for the status").set_value(
        "A site inspection verified the entered update."
    ).run()
    button(app, "Confirm update").click().run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)


def test_returning_resolved_issue_stays_omitted_until_explicitly_reincluded():
    app = workspace()
    draft = app.session_state["draft"]
    issue = replace(draft.follow_ups[0], status="resolved", evidence_note="Verified repair.", included=False)
    app.session_state["draft"] = replace(draft, follow_ups=(issue, draft.follow_ups[1]))
    app.run()
    button(app, "Still correct").click().run()
    assert not app.session_state["draft"].follow_ups[0].included
    button(app, "Update issue").click().run()
    next(value for value in app.radio if value.label == "Current status").set_value("ongoing").run()
    assert button(app, "Confirm update").disabled
    assert not app.session_state["draft"].follow_ups[0].included
    button(app, "Include this issue again").click().run()
    button(app, "Confirm update").click().run()
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].included and not problems(draft.follow_ups[0], draft)
