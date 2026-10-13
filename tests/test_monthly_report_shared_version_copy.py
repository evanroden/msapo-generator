"""Shared historical versions are distinct from browser draft recovery."""

from test_monthly_report_ui import monthly


def test_manual_report_save_has_unambiguous_shared_scope(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    assert not app.exception
    assert any(item.label == "Shared report history" for item in app.expander)
    labels = [item.label for item in app.button]
    assert labels.count("Save shared version") == 1
    assert "Save progress" not in labels
    assert any("Browser draft recovery is separate" in item.value
               for item in app.get("caption"))

    before = next(w for w in app.text_area
                  if w.label == "Activity summary").value
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area
                if w.label == "Activity summary").value == before
