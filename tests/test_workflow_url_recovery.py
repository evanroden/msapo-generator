"""Only the public workflow choice may survive an ordinary URL reload."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.web_ui import (
    MONTHLY_REPORT_WORKFLOW,
    EXPENSE_WORKFLOW,
    PURCHASE_WORKFLOW,
    _workflow_from_query,
    _workflow_query_name,
)

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_url_route_is_strict_and_contains_no_identity():
    assert _workflow_from_query("monthly") == MONTHLY_REPORT_WORKFLOW
    assert _workflow_from_query("expense") == EXPENSE_WORKFLOW
    assert _workflow_from_query("purchase") == PURCHASE_WORKFLOW
    assert _workflow_from_query("other") is None
    assert _workflow_from_query(["monthly", "purchase"]) is None
    assert _workflow_query_name(MONTHLY_REPORT_WORKFLOW) == "monthly"
    assert _workflow_query_name("invalid") == "purchase"


def test_existing_url_opens_monthly_on_a_fresh_streamlit_session():
    at = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    at.query_params["workflow"] = "monthly"
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == MONTHLY_REPORT_WORKFLOW
    assert at.session_state["workflow_mode"] == MONTHLY_REPORT_WORKFLOW
    assert at.query_params["workflow"] == "monthly"


def test_switching_workflow_updates_url_and_preserves_unrelated_url_values():
    at = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    at.query_params["workflow"] = "monthly"
    at.query_params["example"] = "not-private"
    at.run()
    at.segmented_control[0].set_value(EXPENSE_WORKFLOW).run()
    assert not at.exception
    assert at.query_params["workflow"] == "expense"
    assert at.query_params["example"] == "not-private"
    at.segmented_control[0].set_value(MONTHLY_REPORT_WORKFLOW).run()
    assert not at.exception
    assert at.query_params["workflow"] == "monthly"


def test_unknown_query_starts_in_purchase_order_without_changing_session_identity():
    at = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    at.query_params["workflow"] = "invalid-mode"
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == PURCHASE_WORKFLOW
    assert at.query_params["workflow"] == "purchase"


def test_existing_session_widget_selection_overrides_outdated_query():
    at = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    at.query_params["workflow"] = "expense"
    at.session_state["workflow_mode"] = MONTHLY_REPORT_WORKFLOW
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == MONTHLY_REPORT_WORKFLOW
    assert at.query_params["workflow"] == "monthly"
