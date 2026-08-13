"""Fields the operator still has to fill are highlighted until they are filled.

Both workflows. The highlight is emitted as CSS targeting Streamlit's
``st-key-<key>`` class and is recomputed from the live values every rerun, so it
clears on the run after a field is filled with no state to reset.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.ui_highlight import _class_name, highlight_needed_fields


ROOT = Path(__file__).resolve().parents[1]
RRH = "Rochester Regional Health"
TOKEN = hashlib.sha256(RRH.encode("utf-8")).hexdigest()[:10]


def _emitted_css(app: AppTest) -> str:
    return "\n".join(block.value for block in app.markdown if "<style>" in block.value)


def test_widget_keys_are_normalised_the_way_streamlit_names_the_class():
    """The failure this prevents is SILENT, which is why it is pinned.

    Streamlit rewrites characters outside [A-Za-z0-9_-] into a hyphen when it
    builds the st-key- class, so a key embedding a contract name
    ("requester_<tok>_Rochester Regional Health") becomes
    "requester_<tok>-Rochester-Regional-Health". Emitting the raw key produces a
    selector that matches nothing, with no error and no highlight.
    """
    # Underscores are already class-safe and survive; only the spaces convert.
    assert _class_name("requester_ab12_Rochester Regional Health") == (
        "requester_ab12_Rochester-Regional-Health"
    )
    assert _class_name("LCMC - Children's") == "LCMC---Children-s"
    assert _class_name("plain_key-1") == "plain_key-1"


def test_helper_emits_nothing_for_an_empty_list():
    """No stray rule, and therefore no stray bar, when nothing is outstanding."""
    app = AppTest.from_function(
        lambda: highlight_needed_fields([]), default_timeout=15
    ).run()
    assert not [b for b in app.markdown if "<style>" in b.value]


def test_purchase_order_highlights_the_requester_until_it_is_filled():
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=40).run()
    app.button[0].click().run()          # byline -> synthetic sample

    assert "st-key-po_needs_you" in _emitted_css(app), (
        "the requester is blank and required but nothing was highlighted"
    )

    field = next(
        f
        for f in app.text_input
        if f.label == "Your name (Requester / Asset Manager) *"
    )
    field.set_value("Evan Roden").run()

    assert "st-key-po_needs_you" not in _emitted_css(app), (
        "the highlight survived after the field was filled"
    )


def test_expense_highlights_each_missing_detail_until_it_is_filled():
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=40).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()

    css = _emitted_css(app)
    for field in ("employee_name", "employee_number", "approver_name", "approver_email"):
        assert f"st-key-expense_{field}_{TOKEN}" in css, f"{field} not highlighted"
    # Mail destination defaults to "home", so the satellite office is not
    # required and must not be highlighted.
    assert f"st-key-expense_satellite_office_{TOKEN}" not in css

    name = next(f for f in app.text_input if f.label == "Employee name *")
    name.set_value("Dane Example").run()

    css = _emitted_css(app)
    assert f"st-key-expense_employee_name_{TOKEN}" not in css, (
        "the filled field is still highlighted"
    )
    # The others are untouched.
    for field in ("employee_number", "approver_name", "approver_email"):
        assert f"st-key-expense_{field}_{TOKEN}" in css


def test_fields_with_safe_defaults_are_never_highlighted():
    """Report date, mail destination and service year all carry defaults, so
    they are not things the operator must supply and must not be flagged."""
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=40).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()

    css = _emitted_css(app)
    for field in ("report_date", "mail_destination", "service_year",
                  "employee_home_bu_display"):
        assert f"st-key-expense_{field}_{TOKEN}" not in css, (
            f"{field} has a default and should not be flagged as needing a value"
        )
