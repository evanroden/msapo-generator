"""The starting DOCX is optional after saved monthly work has loaded."""

from test_monthly_report_ui import monthly


def test_resumed_report_has_secondary_import_but_keeps_authoritative_activity(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert any(expander.label == "Use a different starting report"
               for expander in app.expander)
    assert any(widget.label == "Starting report"
               for widget in app.get("file_uploader"))
    assert next(widget for widget in app.text_area
                if widget.label == "Activity summary").value == "Synthetic initial activity."
    assert not any("Word DOCX, up to 128 MB. Your original file is retained."
                   in item.value for item in app.get("caption"))


def test_first_report_still_shows_primary_source_uploader(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(widget for widget in app.checkbox
         if widget.key.startswith("report_sites_")).check().run()
    assert not app.exception
    assert any(widget.label == "Starting report"
               for widget in app.get("file_uploader"))
    assert not any(expander.label == "Use a different starting report"
                   for expander in app.expander)
