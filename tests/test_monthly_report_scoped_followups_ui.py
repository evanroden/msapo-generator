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


def test_unchanged_issue_is_directly_editable_without_routine_confirmation():
    app = workspace()
    assert not app.exception
    original_proposal = app.session_state["draft"].follow_ups[1]
    assert original_proposal.status == "ongoing"  # Not normalized in another section.
    assert len([w for w in app.text_area if w.label == "Issue description"]) == 1
    assert not app.multiselect and not app.checkbox
    assert [value.label for value in app.radio] == ["Section"]
    assert not any("Controls renewal" in value.value for value in app.markdown)
    assert not any(b.label in ("Still open", "Confirm update") for b in app.button)
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)
    assert draft.follow_ups[1] == original_proposal
    app.run()
    assert app.session_state["draft"] == draft


def test_resolving_opens_evidence_and_requires_it_without_omitting_the_issue():
    app = workspace()
    next(w for w in app.selectbox if w.label == "Issue status").set_value("resolved").run()
    assert not app.exception
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].status == "resolved" and draft.follow_ups[0].included
    assert any("Add evidence" in value.value for value in app.warning)
    next(value for value in app.text_area if value.label == "Evidence or explanation for the status").set_value(
        "Inspection confirmed that replacement bearings corrected the vibration."
    ).run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)
    assert draft.follow_ups[0].included
    app.run()
    assert app.session_state["draft"].follow_ups[0].status == "resolved"


def test_proposal_has_decisions_and_explicit_omission_preserving_issue_edits():
    app = workspace()
    next(w for w in app.text_area if w.label == "Issue description").set_value("Corrected pump finding.").run()
    original_issue = app.session_state["draft"].follow_ups[0]
    app.radio[0].set_value("proposal").run()
    assert not app.text_area
    button(app, "Confirm unchanged").click().run()
    confirmed = app.session_state["draft"].follow_ups[1]
    assert confirmed.status == "declined" and not problems(confirmed, app.session_state["draft"])
    assert app.session_state["draft"].follow_ups[0] == original_issue
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


def test_edit_survives_section_switch_without_repeated_issue_confirmation():
    app = workspace()
    next(value for value in app.text_area if value.label == "Issue update").set_value(
        "A vibration survey is scheduled."
    ).run()
    original = app.session_state["draft"].follow_ups[0]
    # The direct edit is October's review (#281): no separate confirmation.
    assert not problems(original, app.session_state["draft"])
    app.radio[0].set_value("proposal").run()
    app.radio[0].set_value("issue").run()
    assert app.session_state["draft"].follow_ups[0] == original
    assert next(w for w in app.text_area if w.label == "Issue update").value == "A vibration survey is scheduled."
    app.session_state["draft"] = replace(app.session_state["draft"], period=ReportPeriod(2026, 11))
    app.run()
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].reviewed_fingerprint != confirmation(draft.follow_ups[0], draft.period)
    # October's stamp does not make the same wording November's update.
    assert any("current for November 2026" in message for message in problems(draft.follow_ups[0], draft))
    assert button(app, "Confirm update for November 2026")


def test_missing_source_cannot_be_silently_dropped_by_opening_editor():
    app = workspace()
    draft = app.session_state["draft"]
    issue = replace(draft.follow_ups[0], status="updated", references=("missing-source#page=1",))
    app.session_state["draft"] = replace(draft, follow_ups=(issue, draft.follow_ups[1]))
    app.run()
    assert app.session_state["draft"].follow_ups[0].references == issue.references
    assert any("source changed" in p for p in problems(app.session_state["draft"].follow_ups[0], app.session_state["draft"]))
    next(value for value in app.checkbox if value.label == "Remove unavailable source links").check().run()
    assert not app.session_state["draft"].follow_ups[0].references
    assert any("Add evidence" in p for p in problems(app.session_state["draft"].follow_ups[0], app.session_state["draft"]))
    next(value for value in app.text_area if value.label == "Evidence or explanation for the status").set_value(
        "A site inspection verified the entered update."
    ).run()
    draft = app.session_state["draft"]
    assert not problems(draft.follow_ups[0], draft)


def test_returning_resolved_issue_stays_omitted_until_explicitly_reincluded():
    app = workspace()
    draft = app.session_state["draft"]
    issue = replace(draft.follow_ups[0], status="resolved", evidence_note="Verified repair.", included=False)
    app.session_state["draft"] = replace(draft, follow_ups=(issue, draft.follow_ups[1]))
    app.run()
    assert not app.session_state["draft"].follow_ups[0].included
    assert not any(w.label == "Issue description" for w in app.text_area)
    button(app, "Include again").click().run()
    app.run()
    assert next(w for w in app.selectbox if w.label == "Issue status").value == "resolved"
    next(w for w in app.selectbox if w.label == "Issue status").set_value("ongoing").run()
    draft = app.session_state["draft"]
    assert draft.follow_ups[0].included and not problems(draft.follow_ups[0], draft)
