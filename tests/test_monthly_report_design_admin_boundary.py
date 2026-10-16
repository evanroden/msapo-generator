"""Global master design writes must be separate from report content entry."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_designs as designs
from app.monthly_report_designs_ui import design_summary
from app.monthly_report_model import synthetic_profiles
from test_monthly_report_ui import monthly


def test_status_is_read_only_and_pinned_design_is_not_current_global_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = replace(synthetic_profiles()[0], template=designs.MASTER_PREFIX + "a" * 64)
    identity, latest = design_summary(type("Draft", (), {"profile": profile})())
    assert identity == "ENFRA master · " + "a" * 12
    assert latest == 0
    assert designs.master_state()["revision"] == 0


def test_monthly_cover_has_read_only_design_and_sidebar_admin(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    labels = [e.label for e in app.expander]
    assert "About this report" in labels
    assert "Master design administration — all contracts" in [e.label for e in app.sidebar.expander]
    assert any("This report uses:" in c.value for c in app.caption)
    assert any("separate administrative sidebar" in c.value for c in app.caption)
