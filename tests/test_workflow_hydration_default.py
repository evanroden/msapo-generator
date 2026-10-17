"""Fresh native workflow defaults agree with the server-selected route.

The native ButtonGroup uses proto.default when neither widget-manager state
nor an explicit set_value is available at mount/reset. A conflicting Purchase
default must never be advertised by a Monthly or Expense page. AppTest checks
that actual wire contract; CI owns the real first-click/navigation journey.
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.web_ui import MONTHLY_REPORT_WORKFLOW, EXPENSE_WORKFLOW, PURCHASE_WORKFLOW

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = (PURCHASE_WORKFLOW, EXPENSE_WORKFLOW, MONTHLY_REPORT_WORKFLOW)


@pytest.mark.parametrize("route,mode", [
    ("monthly", MONTHLY_REPORT_WORKFLOW),
    ("expense", EXPENSE_WORKFLOW),
    ("purchase", PURCHASE_WORKFLOW),
])
def test_fresh_route_never_advertises_an_unrelated_native_default(monkeypatch, tmp_path, route, mode):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.web_ui.device_token", lambda cookies: "c" * 32)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    app.query_params["workflow"] = route
    app.run()
    assert not app.exception
    control = app.segmented_control[0]
    assert control.value == mode
    assert list(control.proto.default) == [OPTIONS.index(mode)]

    # A deliberate native workflow selection must remain possible, retaining
    # the same widget identity through each display and its ordinary rerun.
    identity = control.id
    for selected in OPTIONS:
        app.segmented_control[0].set_value(selected).run()
        assert not app.exception
        current = app.segmented_control[0]
        assert current.id == identity
        assert current.value == selected
        assert list(current.proto.default) == [OPTIONS.index(selected)]
        app.run()
        assert app.segmented_control[0].value == selected


def test_existing_session_selection_wins_over_a_stale_route_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("app.web_ui.device_token", lambda cookies: "c" * 32)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20)
    app.query_params["workflow"] = "purchase"
    app.session_state["workflow_mode"] = MONTHLY_REPORT_WORKFLOW
    app.run()
    assert not app.exception
    assert app.segmented_control[0].value == MONTHLY_REPORT_WORKFLOW
    assert list(app.segmented_control[0].proto.default) == [2]
