"""A proposal decision is independent of equipment issue resolution."""

from dataclasses import asdict, replace
from io import BytesIO
import json

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import confirmation, normalize_proposal, problems, report_text
from app.monthly_report_library import draft_from_dict
from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft


def proposal_draft(decision):
    section = next(s for s in default_sections() if s.key == "proposals")
    return ReportDraft(
        synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Operator", (section,),
        (ResolvedBlock("proposals", "This month", rows=(("North", "Synthetic Vendor", "Replace valve", decision),)),),
    )


@pytest.mark.parametrize("label,status", [
    ("Pending", "pending"), ("Approved", "approved"), ("Declined", "declined"),
    ("On hold", "on_hold"), ("Not confirmed", "not_confirmed"),
])
def test_rollover_preserves_real_decision_in_printed_report(label, status):
    original = proposal_draft(label)
    current = new_month_draft(original, ReportPeriod(2026, 10))
    item, = current.follow_ups
    assert item.status == status and item.included
    assert "Status:" not in item.text
    item = replace(item, reviewed_fingerprint=confirmation(item, current.period))
    current = replace(current, follow_ups=(item,))
    assert not problems(item, current)
    text = "\n".join(p.text for p in Document(BytesIO(assemble_docx(current))).paragraphs)
    assert label + " — Facility: North" in text
    assert "Ongoing —" not in text and "Resolved —" not in text
    assert draft_from_dict(json.loads(json.dumps(asdict(current)))) == current
    following = new_month_draft(current, ReportPeriod(2026, 11))
    assert following.follow_ups[0].status == status
    assert original.blocks[0].rows[0][-1] == label


@pytest.mark.parametrize("label", ["Option B", "Alternative", "Not approved", "Pending or declined", ""])
def test_unknown_and_alternative_labels_do_not_become_decisions(label):
    current = new_month_draft(proposal_draft(label), ReportPeriod(2026, 10))
    item, = current.follow_ups
    assert item.status == "not_confirmed" and label in item.text


def test_legacy_decision_is_detached_and_updating_it_cannot_print_two_statuses():
    legacy = ReportFollowUp("stable-id", "proposal", "Scope: Replace valve; Status: Declined", "2026-09")
    normalized = normalize_proposal(legacy)
    assert normalized.key == legacy.key and normalized.status == "declined"
    assert legacy.status == "ongoing" and "Status: Declined" in legacy.text
    updated = replace(normalized, status="approved")
    assert report_text(updated) == "Approved — Scope: Replace valve"
    assert "Declined" not in report_text(updated)


def test_conflicting_structured_decisions_remain_visible_and_unconfirmed():
    item = ReportFollowUp("stable-id", "proposal", "Scope: Replace valve; Status: Pending; Decision: Declined", "2026-09")
    normalized = normalize_proposal(item)
    assert normalized.status == "not_confirmed" and normalized.text == item.text


def test_proposal_can_be_explicitly_archived_without_claiming_work_completed():
    current = new_month_draft(proposal_draft("Declined"), ReportPeriod(2026, 10))
    item = replace(current.follow_ups[0], included=False)
    item = replace(item, reviewed_fingerprint=confirmation(item, current.period))
    assert not problems(item, current)
    current = replace(current, follow_ups=(item,))
    assert not new_month_draft(current, ReportPeriod(2026, 11)).follow_ups
    assert item.status == "declined"


def test_proposal_ui_has_decisions_and_archiving_without_issue_resolution():
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportPeriod, synthetic_profiles
from app.monthly_report_followups import render_followups
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
item = ReportFollowUp("stable-id", "proposal", "Scope: Replace valve; Status: Declined", "2026-09")
draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 10), "Synthetic Operator", (), (), follow_ups=(item,))
st.session_state.setdefault("draft", draft)
st.session_state["draft"] = render_followups(st.session_state["draft"], "synthetic", field)
''').run()
    assert not app.exception
    assert app.radio[0].label == "Proposal decision" and app.radio[0].value == "declined"
    assert "Resolved" not in app.radio[0].options
    app.radio[0].set_value("approved").run()
    assert report_text(app.session_state["draft"].follow_ups[0]) == "Approved — Scope: Replace valve"
    next(c for c in app.checkbox if c.label == "Leave this proposal out of the report").check().run()
    assert not app.session_state["draft"].follow_ups[0].included
    assert not app.exception
