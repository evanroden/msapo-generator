from concurrent.futures import Future
from io import BytesIO
import hashlib

from app import monthly_report_upload_ui as ui, receipt_jobs
from test_monthly_report_ui import monthly


def activity_upload(monkeypatch, raw):
    stream = BytesIO(raw)
    stream.name = 'activity.txt'
    original = ui.st.file_uploader
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label, *args, **kwargs:
                        [stream] if label == 'Upload activity reports and supporting files' else original(label, *args, **kwargs))


def test_first_pass_is_automatic_and_manual_edits_survive_reader(monkeypatch, tmp_path):
    future = Future()
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
