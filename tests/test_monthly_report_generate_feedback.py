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
        if label == "Create Word and PDF":
            recorded.append((kwargs.get("type"), kwargs.get("disabled")))
        return original(label, *args, **kwargs)

    monkeypatch.setattr(guided.st, "button", button)
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    return app, recorded


def _button(app):
    return next(b for b in app.button if b.label == "Create Word and PDF")


def test_required_error_is_grey_and_explained_near_generate(monkeypatch, tmp_path):
    app, seen = _generate_ui(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Insert image here").run()
    assert not app.exception
    assert _button(app).disabled
    assert seen[-1] == ("secondary", True)
    assert any("required item" in c.value and "enable Create Word and PDF" in c.value for c in app.caption)
    assert any("Monthly Activity Summary" in e.value for e in app.error)


def test_unacknowledged_warning_is_grey_and_ack_enables_generate(monkeypatch, tmp_path):
    app, seen = _generate_ui(monkeypatch, tmp_path)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("August 2026 activity.").run()
    assert not app.exception
    assert seen[-1] == ("secondary", True)
    assert _button(app).disabled
    assert any("specific warnings" in c.value and "enable Create Word and PDF" in c.value for c in app.caption)
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


@pytest.mark.parametrize(("code", "message", "block_key", "expected", "target"), [
    ("client_pages", "New cover photograph needs review.", "cover_photo", "Review the new or changed pictures", "#report-review"),
    ("pricing", "Remove pricing from Activity.", "activity_summary", "Remove pricing from Activity.", "#report-section-activity"),
    ("required", "Add required Activity details.", "activity_summary", "Add ", "#report-section-activity"),
    ("required", "Include the missing section.", "organization", "Add ", "#report-section-organization"),
    ("unavailable_source", "Restore a missing source before export.", "", "Restore a missing source", "#report-review"),
])
def test_each_preflight_gate_explains_the_fix_above_generation(
        monkeypatch, tmp_path, code, message, block_key, expected, target):
    from app import monthly_report_guided as guided
    from app.monthly_report_checks import ReportCheck
    app, recorded = _generate_ui(monkeypatch, tmp_path)
    monkeypatch.setattr(guided, "preflight", lambda *_: (
        ReportCheck(code, message, True, block_key),))
    app.run()
    assert not app.exception
    assert _button(app).disabled and recorded[-1] == ("secondary", True)
    # Streamlit captions retain the real user-visible link directly above
    # the action, not just the separate preflight error elsewhere.
    messages = [c.value for c in app.caption if c.value.startswith("Before generating:")]
    assert messages
    assert any(expected in caption and target in caption for caption in messages)


def test_unacknowledged_warning_has_action_link_next_to_generation(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided
    from app.monthly_report_checks import ReportCheck
    app, _ = _generate_ui(monkeypatch, tmp_path)
    monkeypatch.setattr(guided, "preflight", lambda *_: (
        ReportCheck("period", "Review the report month.", False, "activity_summary"),))
    app.run()
    assert not app.exception and _button(app).disabled
    assert any("Before generating:" in c.value and "I checked these specific warnings" in c.value
               and "#report-review" in c.value for c in app.caption)


def test_production_monthly_editor_exposes_no_qa_caption_or_full_digest(monkeypatch, tmp_path):
    import re
    app, _ = _generate_ui(monkeypatch, tmp_path)
    assert not app.exception
    # Do not treat internal hidden navigation attributes as rendered copy:
    # only user-facing captions and alerts are subject to this QA-leak check.
    visible = [str(node.value) for collection in (app.caption, app.info,
               app.error, app.warning, app.success) for node in collection]
    assert not [text for text in visible if text.startswith("QA ")]
    assert not [text for text in visible if re.search(r"(?<![a-f0-9])[a-f0-9]{64}(?![a-f0-9])", text, re.I)]


def test_newer_shared_revision_has_navigation_at_generation_action(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided, monthly_report_library as library
    app, _ = _generate_ui(monkeypatch, tmp_path)
    from app.contracts import RRH_CONTRACT
    from app.monthly_report_model import ReportPeriod
    prefix = "report_guided_" + guided._signature((
        RRH_CONTRACT, "synthetic-guided", ReportPeriod(2026, 9).key))
    library.save_snapshot(app.session_state[prefix + "_draft"], expected_revision=0,
                          entered_editor="Synthetic Editor")
    app.run()
    assert not app.exception and _button(app).disabled
    assert any("Before generating: Compare the newer saved version" in c.value
               and "#monthly-conflict-review" in c.value for c in app.caption)
