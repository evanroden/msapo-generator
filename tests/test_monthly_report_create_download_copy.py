"""Download action labels keep save scope and revision-bound readiness honest."""

from app.monthly_report_checks import ReportCheck
from app.monthly_report_guided import generation_block_reason
from test_monthly_report_ui import monthly


def test_working_report_offers_one_clear_creation_action_without_ready_claim(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    labels = [button.label for button in app.button]
    assert labels.count("Create Word and PDF") == 1
    assert "Generate DOCX and PDF" not in labels
    assert "Generate anyway" not in labels
    assert any("Creating files also attempts to save a shared version." == node.value
               for node in app.get("caption"))
    assert not any("Ready to download" in node.value for node in app.success)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Synthetic initial activity.")
    # Creation is a real action, not a self-running effect on initial mount.


def test_renamed_creation_still_preserves_required_and_warning_gates():
    blocking = (ReportCheck("required", "An actual field is missing", True),)
    assert "Create Word and PDF" in generation_block_reason(
        conflict=False, checks=blocking, warnings_ok=True)
    warning = (ReportCheck("source_date_unknown", "A source needs its date checked", False),)
    assert "Create Word and PDF" in generation_block_reason(
        conflict=False, checks=warning, warnings_ok=False)
    assert generation_block_reason(conflict=False, checks=(), warnings_ok=True) == ""
    assert "Another version" in generation_block_reason(
        conflict=True, checks=(), warnings_ok=True)
