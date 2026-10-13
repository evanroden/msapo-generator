from concurrent.futures import Future
from io import BytesIO
import hashlib
import pytest

from app import monthly_report_upload_ui as ui, receipt_jobs
from test_monthly_report_ui import monthly


def activity_upload(monkeypatch, raw):
    stream = BytesIO(raw)
    stream.name = 'activity.txt'
    original = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label, *args, **kwargs:
                        [stream] if label == 'Add activity files (optional)' else original(label, *args, **kwargs))


def test_first_pass_is_automatic_and_manual_edits_survive_reader(monkeypatch, tmp_path):
    from app import monthly_report_ai as ai
    future = Future()
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', 'synthetic-test-token')
    monkeypatch.setattr(ai, 'cached', lambda *args: None)
    monkeypatch.setattr(receipt_jobs, 'start_receipt', lambda prepare, read: future)
    app = monthly(monkeypatch, tmp_path)
    raw = b'Inspected the motor.\nReplacement is scheduled for next month.'
    activity_upload(monkeypatch, raw)
    app.run()
    assert not app.exception
    editor = next(w for w in app.text_area if w.label == 'Activity summary')
    assert 'Inspected the motor.' in editor.value
    assert 'Replacement is scheduled for next month.' in editor.value
    editor.set_value('AM edited the activity summary.').run()
    identity = hashlib.sha256(raw).hexdigest()
    future.set_result({'items': [{'source': identity, 'page': 1, 'text': 'Inspected the motor.', 'row': []}]})
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == 'AM edited the activity summary.'
    next(w for w in app.button if w.label == 'Add new source suggestions to my edits').click().run()
    app.run()
    assert not app.exception
    text = next(w for w in app.text_area if w.label == 'Activity summary').value
    assert 'AM edited the activity summary.' in text and text.count('Inspected the motor.') == 1
    app.run()
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == text


@pytest.mark.parametrize('manual', ['A manual correction entered as reading completes.', ''])
def test_reader_completion_and_activity_callback_in_same_rerun_preserve_manual_input(
        monkeypatch, tmp_path, manual):
    from app import monthly_report_ai as ai
    future = Future()
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', 'synthetic-test-token')
    monkeypatch.setattr(ai, 'cached', lambda *args: None)
    monkeypatch.setattr(receipt_jobs, 'start_receipt', lambda prepare, read: future)
    app = monthly(monkeypatch, tmp_path)
    raw = b'Inspected the motor.\nReplacement is scheduled for next month.'
    activity_upload(monkeypatch, raw)
    app.run()
    assert not app.exception
    editor = next(w for w in app.text_area if w.label == 'Activity summary')
    assert 'Inspected the motor.' in editor.value
    identity = hashlib.sha256(raw).hexdigest()
    # Complete the old-baseline reader BEFORE the textarea change triggers a
    # full rerun. The callback is newer input even though guided.py has not
    # reached its final canonical-draft assignment yet.
    future.set_result({'items': [{'source': identity, 'page': 1,
                                 'text': 'Inspected the motor.', 'row': []}]})
    editor.set_value(manual).run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == manual
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value, 'blocks'))
    assert next(b.text for b in draft.blocks if b.key == 'activity_summary') == manual
    assert any('Your edits were kept' in w.value for w in app.warning)
    assert any(b.label == 'Add new source suggestions to my edits' for b in app.button)
    app.run()
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == manual
