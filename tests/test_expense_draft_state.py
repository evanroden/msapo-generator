"""The expense draft mirror must preserve operator input without resurrecting
transient state.

``preserve_expense_draft_state`` exists because Streamlit deletes widget keys for
widgets that did not render, so switching to the Purchase Order workflow would
otherwise wipe a half-finished expense report. The mirror previously only ever
*added* keys, and ``restore_expense_draft_state`` re-injects everything it holds
via ``setdefault``. Any key the workflow deliberately popped therefore came back
on the very next rerun and could never be dismissed.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app import expense_ui
from app.expense_ui import (
    preserve_expense_draft_state,
    restore_expense_draft_state,
)


@pytest.fixture
def session(monkeypatch):
    """A plain dict stands in for st.session_state (same accessors used here)."""
    state: dict = {}
    monkeypatch.setattr(expense_ui.st, "session_state", state)
    return state


def test_operator_input_survives_switching_to_the_other_workflow(session):
    """The original guarantee must not regress."""
    session.update(
        {
            "_expense_workflow_rendered": True,
            "expense_employee_name": "Evan Roden",
            "expense_employee_number": "1001",
        }
    )
    preserve_expense_draft_state()

    # Streamlit drops the un-rendered expense widgets while the PO page shows.
    session.pop("expense_employee_name")
    session.pop("expense_employee_number")
    session["_expense_workflow_rendered"] = False
    preserve_expense_draft_state()
    restore_expense_draft_state()

    assert session["expense_employee_name"] == "Evan Roden"
    assert session["expense_employee_number"] == "1001"


def test_a_dismissed_generation_error_does_not_come_back(session):
    """Defence 1: known transient keys are never mirrored in the first place."""
    session.update(
        {
            "_expense_workflow_rendered": True,
            "expense_employee_name": "Evan Roden",
            "expense_generation_error": "LibreOffice fell over",
            "expense_email_error": "attachment too large",
        }
    )
    preserve_expense_draft_state()

    snapshot = session["expense_draft_snapshot"]
    assert "expense_generation_error" not in snapshot
    assert "expense_email_error" not in snapshot

    # The operator fixes the problem; the handler clears the errors.
    session.pop("expense_generation_error")
    session.pop("expense_email_error")
    preserve_expense_draft_state()
    restore_expense_draft_state()

    assert "expense_generation_error" not in session
    assert "expense_email_error" not in session
    assert session["expense_employee_name"] == "Evan Roden"


def test_a_recall_caption_does_not_come_back(session):
    """The 'recalled from history' captions are popped when the operator edits."""
    session.update(
        {
            "_expense_workflow_rendered": True,
            "expense_employee_number_recalled_for_abc": True,
            "expense_approver_recalled_abc": True,
        }
    )
    preserve_expense_draft_state()
    session.pop("expense_employee_number_recalled_for_abc")
    session.pop("expense_approver_recalled_abc")
    preserve_expense_draft_state()
    restore_expense_draft_state()

    assert "expense_employee_number_recalled_for_abc" not in session
    assert "expense_approver_recalled_abc" not in session


def test_every_popped_expense_key_is_excluded_from_the_mirror():
    """Statically enforce the invariant the whole design rests on.

    The mirror is deliberately never rebuilt from the live session (there is no
    trustworthy "the expense widgets rendered last run" signal — see the comment
    in preserve_expense_draft_state), so a transient key is safe ONLY if an
    exclusion fragment keeps it out of the snapshot in the first place. This
    scans the module for every key the workflow pops and fails if any of them
    would be mirrored, which is what makes adding a new dismissible banner or
    error safe for the next author.
    """
    source = Path(expense_ui.__file__).read_text(encoding="utf-8")
    popped = set(re.findall(r'session_state\.pop\(\s*[\'"](expense_[^\'"]*)', source))
    popped |= set(
        re.findall(r'session_state\.pop\(\s*f[\'"](expense_[^\'"{]*)', source)
    )

    assert popped, "expected to find popped expense_* keys to check"

    fragments = _exclusion_fragments()
    unprotected = sorted(
        key
        for key in popped
        if not any(fragment in key for fragment in fragments)
    )

    assert not unprotected, (
        "These keys are popped by the workflow but would still be mirrored into "
        "expense_draft_snapshot, so restore_expense_draft_state() will resurrect "
        f"them forever: {unprotected}. Add a covering fragment to "
        "excluded_fragments in preserve_expense_draft_state."
    )


def _exclusion_fragments() -> tuple[str, ...]:
    """Read the live exclusion list out of the function under test."""
    source = inspect.getsource(preserve_expense_draft_state)
    block = source.split("excluded_fragments = (", 1)[1].split(")", 1)[0]
    return tuple(re.findall(r'"([^"]+)"', block))
