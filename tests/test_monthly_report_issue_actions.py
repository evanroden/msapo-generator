"""Bulk omission is reversible only against the exact resulting report."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportDraft, ReportFollowUp, ReportSource
from test_monthly_report_issue_cards import draft_for


SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_editor import _grid
from app.monthly_report_issues import apply_issue_action, render_issue_cards
from app.monthly_report_model import ResolvedBlock
from app.monthly_report_ui import _field
draft = render_issue_cards(st.session_state["draft"], "issue_actions", _field,
                           defer_actions=True)
# This normal native grid is deliberately rendered AFTER the issue controls,
# as Training/RFI are in the ordered workspace. Its delivered delta must be
# applied before an Undo is allowed to touch the issue selection.
rows = _grid("later_native_grid", [{"Request": "Original request"}],
             num_rows="dynamic", hide_index=True)
block = ResolvedBlock("rfi_matrix", "This month",
                      rows=tuple((str(row.get("Request") or ""),) for row in rows))
draft = replace(draft, blocks=tuple(b for b in draft.blocks if b.key != block.key) + (block,))
st.session_state["draft"] = apply_issue_action(draft, "issue_actions")
'''


def button(app, label):
    return next(item for item in app.button if item.label == label)


def workspace():
    original = draft_for()
    omitted = ReportFollowUp("omitted", "issue", "Already left out.", original.period.key,
                             status="updated", included=False, evidence_note="Prior inspection.")
    proposal = ReportFollowUp("proposal", "proposal", "Existing proposal.", original.period.key,
                              status="pending")
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["draft"] = replace(original, follow_ups=(omitted, proposal))
    app.run()
    assert not app.exception
    return app


def test_same_native_submission_is_kept_before_clear_and_exact_selection_can_be_undone():
    app = workspace()
    before = app.session_state["draft"]
    description = next(item for item in app.text_area if item.label == "Issue description")
    description.set_value("Delivered correction before leaving out the list.")
    button(app, "Clear issues from this report").click().run()
    assert not app.exception
    cleared = app.session_state["draft"]
    issue = next(item for item in cleared.follow_ups if item.key.startswith("follow-"))
    assert issue.text == "Delivered correction before leaving out the list."
    assert not any(item.included for item in cleared.follow_ups if item.category == "issue")
    assert cleared.blocks == before.blocks and cleared.sources == before.sources
    assert next(item for item in cleared.follow_ups if item.category == "proposal") == before.follow_ups[1]
    app.run()
    button(app, "Undo Clear issues").click().run()
    assert not app.exception
    restored = app.session_state["draft"]
    assert [(item.key, item.included) for item in restored.follow_ups] == [
        (item.key, item.included) for item in before.follow_ups]
    assert next(item for item in restored.follow_ups if item.key == issue.key).text == issue.text
    assert next(item for item in restored.follow_ups if item.key == "omitted").evidence_note == "Prior inspection."
    assert restored.blocks == before.blocks and restored.sources == before.sources


def test_pending_native_grid_delta_after_issue_controls_prevents_undo():
    app = workspace()
    button(app, "Clear issues from this report").click().run()
    app.run()
    assert not button(app, "Undo Clear issues").disabled
    app.session_state["later_native_grid"] = {
        "edited_rows": {0: {"Request": "Newly delivered request"}},
        "added_rows": [], "deleted_rows": [],
    }
    button(app, "Undo Clear issues").click().run()
    assert not app.exception
    current = app.session_state["draft"]
    assert not any(item.included for item in current.follow_ups if item.category == "issue")
    assert next(block for block in current.blocks if block.key == "rfi_matrix").rows == (("Newly delivered request",),)
    assert any("report changed after Clear" in item.value for item in app.warning)
    app.run()
    assert button(app, "Undo Clear issues").disabled
    assert button(app, "Include again")


@pytest.mark.parametrize("reset", [True, False])
def test_held_native_undo_cannot_rebind_to_another_identical_clear(reset):
    app = workspace()
    before = app.session_state["draft"]
    button(app, "Clear issues from this report").click().run()
    app.run()
    old_undo = button(app, "Undo Clear issues")
    cleared_a = app.session_state["draft"]

    # Keep the ACTUAL old native button, rather than calling its old Python
    # callback. An identical report can have the same content fingerprint
    # after reset or another Clear/Undo/Clear cycle. A reused native ID would
    # deliver the delayed click to the CURRENT callback's arguments.
    if reset:
        app.session_state["draft"] = before
        app.session_state["issue_actions_rich_text_epoch"] = "new-editor-incarnation"
        app.run()
    else:
        button(app, "Undo Clear issues").click().run()
        app.run()
    button(app, "Clear issues from this report").click().run()
    app.run()
    cleared_b = app.session_state["draft"]
    assert cleared_b.fingerprint == cleared_a.fingerprint
    old_undo.click().run()
    assert not app.exception
    assert app.session_state["draft"] == cleared_b

    button(app, "Undo Clear issues").click().run()
    assert not app.exception
    assert app.session_state["draft"] == before


@pytest.mark.parametrize("change", ["source", "epoch", "month"])
def test_delayed_clear_cannot_cross_source_reset_or_month(change):
    app = workspace()
    old_button = button(app, "Clear issues from this report")
    current = app.session_state["draft"]
    if change == "source":
        current = replace(current, sources=(ReportSource(
            "new-source", "synthetic.pdf", "b" * 64, ".pdf", page_texts=("New inspection.",)),))
    elif change == "epoch":
        app.session_state["issue_actions_rich_text_epoch"] = "new-editor-incarnation"
    else:
        current = replace(current, period=replace(current.period, month=10))
    app.session_state["draft"] = current
    old_button.click().run()
    assert not app.exception
    assert app.session_state["draft"] == current
    assert any("report or its sources changed" in item.value for item in app.warning)
    assert "after" not in app.session_state["issue_actions_issue_clear_undo"]


def test_held_native_clear_is_retired_after_clear_and_undo_but_fresh_clear_works():
    app = workspace()
    before = app.session_state["draft"]
    old_clear = button(app, "Clear issues from this report")
    button(app, "Clear issues from this report").click().run()
    app.run()
    button(app, "Undo Clear issues").click().run()
    app.run()
    assert app.session_state["draft"] == before

    old_clear.click().run()
    assert not app.exception
    assert app.session_state["draft"] == before
    button(app, "Clear issues from this report").click().run()
    assert not app.exception
    assert not any(item.included for item in app.session_state["draft"].follow_ups
                   if item.category == "issue")


def test_later_report_edit_disables_undo_without_losing_individual_recovery():
    app = workspace()
    button(app, "Clear issues from this report").click().run()
    current = replace(app.session_state["draft"], prepared_by="Corrected attribution")
    app.session_state["draft"] = current
    app.run()
    assert button(app, "Undo Clear issues").disabled
    assert app.session_state["draft"] == current
    button(app, "Include again").click().run()
    assert app.session_state["draft"].follow_ups[0].included
    assert app.session_state["draft"].prepared_by == current.prepared_by


def test_guided_clear_and_undo_refresh_only_after_the_authoritative_draft_commits(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    app = monthly(monkeypatch, tmp_path)
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Synthetic Editor").run()
    key, current = next((key, value) for key, value in app.session_state.filtered_state.items()
                        if key.startswith("report_guided_") and key.endswith("_draft")
                        and isinstance(value, ReportDraft))
    issue = ReportFollowUp("synthetic-issue", "issue", "Retain this finding.", current.period.key)
    current = replace(current, follow_ups=(issue,))
    app.session_state[key] = current
    app.run()
    next(item for item in app.text_area if item.label == "Issue description").set_value("Delivered guided correction.")
    button(app, "Clear issues from this report").click().run()
    assert not app.exception
    cleared = app.session_state[key]
    assert cleared.follow_ups[0].text == "Delivered guided correction."
    assert not cleared.follow_ups[0].included
    assert not any(item.label == "Issue description" for item in app.text_area)
    button(app, "Undo Clear issues").click().run()
    assert not app.exception
    restored = app.session_state[key]
    assert restored.follow_ups[0].included
    assert next(item for item in app.text_area if item.label == "Issue description").value == "Delivered guided correction."
    assert restored.blocks == cleared.blocks and restored.sources == cleared.sources
