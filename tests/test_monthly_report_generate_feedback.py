"""A disabled Generate action must explain why and look disabled."""
import pytest
from app.monthly_report_checks import ReportCheck
from app.monthly_report_guided import generation_block_reason
from test_monthly_report_ui import monthly


@pytest.mark.parametrize(("conflict","checks","ack","expected"), [
    (True, (), True, "Another version was saved"),
    (False, (ReportCheck("required", "Add a required field.", True),), True, "1 required item"),
    (False, (ReportCheck("required", "A", True), ReportCheck("pricing", "B", True)), True, "2 required items"),
    (False, (ReportCheck("period", "Date mismatch.", False),), False, "specific warnings"),
    (False, (ReportCheck("period", "Date mismatch.", False),), True, ""),
    (False, (), True, ""),
])
def test_generation_gate_has_explicit_priority_and_no_extra_blockers(conflict, checks, ack, expected):
    reason = generation_block_reason(conflict=conflict, checks=checks, warnings_ok=ack)
    assert expected in reason
    assert bool(reason) == bool(expected)


def _generate_ui(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided
    recorded = []
    original = guided.st.button

    def button(label, *args, **kwargs):
        if label == "Generate DOCX and PDF":
            recorded.append((kwargs.get("type"), kwargs.get("disabled")))
        return original(label, *args, **kwargs)

    monkeypatch.setattr(guided.st, "button", button)
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    return app, recorded


def _button(app):
    return next(b for b in app.button if b.label == "Generate DOCX and PDF")


def test_required_error_is_grey_and_explained_near_generate(monkeypatch, tmp_path):
    app, seen = _generate_ui(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Insert image here").run()
    assert not app.exception
    assert _button(app).disabled
    assert seen[-1] == ("secondary", True)
    assert any("required item" in c.value and "enable Generate" in c.value for c in app.caption)
    assert any("Monthly Activity Summary" in e.value for e in app.error)


def test_unacknowledged_warning_is_grey_and_ack_enables_generate(monkeypatch, tmp_path):
    app, seen = _generate_ui(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("August 2026 activity.").run()
    assert not app.exception
    assert seen[-1] == ("secondary", True)
    assert _button(app).disabled
    assert any("specific warnings" in c.value and "enable Generate" in c.value for c in app.caption)
    next(w for w in app.checkbox if w.label == "I checked these specific warnings").check().run()
    assert not app.exception
    assert seen[-1] == ("primary", False)
    assert not _button(app).disabled
    next(w for w in app.text_area if w.label == "Activity summary").set_value("July 2026 activity.").run()
    assert not app.exception
    assert seen[-1] == ("secondary", True)
    assert _button(app).disabled


def test_no_warning_needs_no_checkbox_and_remains_single_click(monkeypatch, tmp_path):
    app, seen = _generate_ui(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic current repair.").run()
    assert not app.exception
    assert seen[-1] == ("primary", False)
    assert not _button(app).disabled
    assert not any("I checked these specific warnings" == w.label for w in app.checkbox)
