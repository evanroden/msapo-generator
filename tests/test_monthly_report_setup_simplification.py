"""Regression checks for the first read-only monthly report copy simplification."""

from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from test_monthly_report_ui import monthly


def test_short_help_and_admin_storage_remain_accessible(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception

    labels = {expander.label for expander in app.expander}
    assert "How to use this page" in labels
    assert "Saving and recovery" in labels
    assert "First time here? How to finish a monthly report" not in labels
    assert "What will be remembered?" not in labels

    # Backend storage tools are not routine authoring questions. They remain
    # discoverable in the administrative sidebar and preserve their widget keys.
    sidebar_labels = {expander.label for expander in app.sidebar.expander}
    assert "Storage maintenance — all contracts" in sidebar_labels
    sidebar_buttons = {button.key for button in app.sidebar.button}
    assert {"report_storage_check", "report_storage_consolidate"} <= sidebar_buttons
    assert not any("Suggested month: previous month" in item.value for item in app.get("caption"))


def test_administrative_storage_check_does_not_modify_report_records(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    selected = library.list_profiles(RRH_CONTRACT)[0]
    original = library.load_profile(RRH_CONTRACT, selected.key)
    assert original is not None

    next(button for button in app.sidebar.button
         if button.key == "report_storage_check").click().run()

    assert not app.exception
    assert "report_storage_summary" in app.session_state.filtered_state
    after = library.load_profile(RRH_CONTRACT, selected.key)
    assert after.revision == original.revision
    assert after.profile == original.profile
    # The operator's editable content, historical snapshots and directory
    # are covered separately by the existing monthly UI regression suite.
