"""Shared contact maintenance belongs in the sidebar, not above Org editing."""

from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from test_monthly_report_ui import monthly


def test_shared_directory_editor_is_an_advanced_sidebar_action(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert any(box.label == "Contract and site directory"
               for box in app.sidebar.expander)
    # The primary editable report remains available without opening the
    # shared-directory surface or agreeing to any global contact save.
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Synthetic initial activity.")
    assert not any(b.label == "Save contacts to directory and report" and not b.disabled
                   for b in app.button if "Save contacts to directory and report" in b.label)


def test_sidebar_disclosure_does_not_change_saved_report_or_shared_directory(
        monkeypatch, tmp_path):
    from app.monthly_report_directory import load_directory
    app = monthly(monkeypatch, tmp_path)
    profile = library.list_profiles(RRH_CONTRACT)[0]
    before = library.load_profile(RRH_CONTRACT, profile.key)
    directory_before = load_directory(RRH_CONTRACT)
    app.run()
    assert not app.exception
    assert library.load_profile(RRH_CONTRACT, profile.key) == before
    assert load_directory(RRH_CONTRACT) == directory_before
