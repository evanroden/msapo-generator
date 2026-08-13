"""Collapsing the expense report-details block must not remove functionality.

Step 2 collapses into a single expander once the account's confirmed history has
supplied every detail. The guarantee under test is that this is PLACEMENT ONLY:
every field is still rendered, still carries its value, and is still editable.

Two methodology notes, both learned the hard way and recorded in
docs/COMMIT_NOTES_2026-08-12_TOUCH_AND_RENDERER_RELIABILITY.md section 7:

* Seed through ``expense_draft_snapshot`` BEFORE entering the workflow. Writing a
  widget key via ``session_state`` after that widget has rendered is unsupported:
  the approver ``selectbox`` (``index=None``, ``accept_new_options=True``)
  re-initialises to ``None``, discarding the write, and its ``on_change`` then
  clears the paired email -- so one bad write cascades into two empty fields and
  the collapsed path never engages.
* Assert on caption text, not ``app.expander``, which returns an empty list under
  ``AppTest`` even where expanders render.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
RRH = "Rochester Regional Health"
TOKEN = hashlib.sha256(RRH.encode("utf-8")).hexdigest()[:10]

_COLLAPSED_MARKER = "Every detail below stays editable"

# Every control the step-2 block owns.
_TEXT_FIELDS = (
    "Employee name *",
    "Employee number *",
    "Employee Home Business Unit",
    "Contract administrator / approver email *",
)
_SELECT_FIELDS = (
    "Account / contract *",
    "Contract administrator / approver name *",
)


def _labels(app: AppTest) -> set[str]:
    found = {field.label for field in app.text_input}
    found |= {field.label for field in app.selectbox}
    found |= {field.label for field in app.radio}
    found |= {field.label for field in app.date_input}
    return found


def _captions(app: AppTest) -> list[str]:
    return [caption.value for caption in app.caption]


def test_details_stay_expanded_while_something_still_needs_a_value():
    """Baseline: nothing remembered, so the operator sees the fields directly."""
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()

    assert not any(_COLLAPSED_MARKER in text for text in _captions(app)), (
        "the block collapsed even though details were outstanding"
    )
    labels = _labels(app)
    for label in _TEXT_FIELDS + _SELECT_FIELDS:
        assert label in labels, f"{label} missing on the expanded path"


def test_every_detail_field_survives_the_collapsed_path():
    """The important one: with everything remembered, nothing may disappear."""
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()

    # Seed the mirror while still on the purchase-order page, so
    # restore_expense_draft_state() injects the values before the expense
    # widgets render for the first time. This is the supported path.
    app.session_state["expense_draft_snapshot"] = {
        f"expense_employee_name_{TOKEN}": "Dane Example",
        f"expense_employee_number_{TOKEN}": "TEST-4242",
        f"expense_approver_name_{TOKEN}": "Example Approver",
        f"expense_approver_email_{TOKEN}": "approver@example.invalid",
    }
    app.segmented_control[0].set_value("Expense reimbursement").run()

    # The collapsed path must actually be the one under test, or this passes
    # trivially against the expanded layout.
    assert any(_COLLAPSED_MARKER in text for text in _captions(app)), (
        "details block did not collapse; the rest of this test would be vacuous"
    )

    labels = _labels(app)
    for label in _TEXT_FIELDS + _SELECT_FIELDS:
        assert label in labels, (
            f"{label} vanished once the details block collapsed -- disclosure "
            "must relocate fields, never drop them"
        )
    assert "Report date *" in labels

    # Values survived, and the fields are still editable rather than display-only.
    def _field(label):
        return next(f for f in app.text_input if f.label == label)

    assert _field("Employee name *").value == "Dane Example"
    assert _field("Employee number *").value == "TEST-4242"
    assert (
        _field("Contract administrator / approver email *").value
        == "approver@example.invalid"
    )

    _field("Employee name *").set_value("Someone Else").run()
    assert _field("Employee name *").value == "Someone Else"
    assert not app.exception


def test_the_account_selector_is_never_hidden():
    """The account drives job numbers, cost coding and which approvers are
    remembered, and it silently defaults to the first contract because it has no
    placeholder. Collapsing it would repeat the unknown-facility hazard already
    fixed on the purchase-order side, so it stays outside the panel."""
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.session_state["expense_draft_snapshot"] = {
        f"expense_employee_name_{TOKEN}": "Dane Example",
        f"expense_employee_number_{TOKEN}": "TEST-4242",
        f"expense_approver_name_{TOKEN}": "Example Approver",
        f"expense_approver_email_{TOKEN}": "approver@example.invalid",
    }
    app.segmented_control[0].set_value("Expense reimbursement").run()

    assert any(_COLLAPSED_MARKER in text for text in _captions(app))
    assert "Account / contract *" in {field.label for field in app.selectbox}
