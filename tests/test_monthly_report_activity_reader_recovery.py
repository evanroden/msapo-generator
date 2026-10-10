"""F11: uploaded activity must remain editable if automatic reading fails or finishes instantly."""
from concurrent.futures import Future
from io import BytesIO
from types import SimpleNamespace

import pytest

from app import monthly_report_ai as ai, monthly_report_upload_ui as ui
from app import monthly_report_library as library


def network_response(monkeypatch, raw):
    class Client:
        def __init__(self, **kwargs):
            self.messages = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=raw)])
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', 'synthetic-test-token')
    monkeypatch.setattr(ai.anthropic, 'Anthropic', Client)


@pytest.mark.parametrize('response', [
    '```json\n{"items":[]}\n```',
    'Analysis follows:\n{"items":[]}\nAll source material remains editable.',
])
def test_reader_accepts_single_json_object_with_fence_or_trailing_remark(monkeypatch, response):
    network_response(monkeypatch, response)
    assert ai.request_json([{'type':'text','text':'synthetic source'}]) == {'items': []}


@pytest.mark.parametrize('response', ['', 'No usable JSON returned', '```json\n{\"items\":\n```'])
def test_reader_empty_or_malformed_reply_has_actionable_message_not_parser_exception(monkeypatch, response):
    network_response(monkeypatch, response)
    with pytest.raises(ValueError, match='document reader|reader.*response') as exc:
        ai.request_json([{'type':'text','text':'synthetic source'}])
    assert 'line 1 column 1' not in str(exc.value)
    assert 'JSONDecodeError' not in str(exc.value)


def app_for_text(monkeypatch, tmp_path, *, ai_key, cache=None):
    from test_monthly_report_ui import monthly
    from app import monthly_report_section_preview_ui
    original_uploader = ui.st.file_uploader
    text = (b'2026-09-03 | WO-TEST-1001 | PUMP-TEST-02\n'
            b'Completed strainer cleaning and leak inspection. Result: no leakage found.\n')
    uploaded = SimpleNamespace(name='activity.txt', getvalue=lambda: text)
    monkeypatch.setattr(ui.st, 'file_uploader', lambda label, *args, **kwargs:
                        [uploaded] if label=='Upload activity reports and supporting files'
                        else original_uploader(label, *args, **kwargs))
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', ai_key)
    if cache is not None:
        monkeypatch.setattr(ai, 'cached', lambda profile, kind, key: cache if kind=='section_upload' else None)
    return monthly(monkeypatch, tmp_path)


def activity(app):
    return next(w for w in app.text_area if w.label == 'Activity summary').value


def test_without_configured_reader_native_first_pass_is_kept_and_costs_nothing(monkeypatch, tmp_path):
    from app import receipt_jobs
    monkeypatch.setattr(receipt_jobs, 'start_receipt', lambda *args: pytest.fail('no reader should start without API key'))
    app = app_for_text(monkeypatch, tmp_path, ai_key='')
    app.run()
    assert not app.exception
    assert 'Completed strainer cleaning' in activity(app)
    assert not any('Retry reading uploaded files' == button.label for button in app.button)
    app.run()
    assert 'Completed strainer cleaning' in activity(app)
    assert not list(tmp_path.rglob('budgets/*.json'))


def test_immediate_cached_completion_never_aborts_initial_editor_run(monkeypatch, tmp_path):
    app = app_for_text(monkeypatch, tmp_path, ai_key='synthetic-test-token', cache={'items': []})
    assert not app.exception
    app.run()
    assert not app.exception
    assert 'Completed strainer cleaning' in activity(app)
    assert not any('Your edits were kept' in w.value for w in app.warning)
    assert not any('Retry reading uploaded files' == b.label for b in app.button)
    app.run()
    assert not app.exception and 'Completed strainer cleaning' in activity(app)


def test_immediately_failed_reader_keeps_native_text_and_no_parser_trace(monkeypatch, tmp_path):
    from app import receipt_jobs
    def immediate_failure(prepare, worker):
        future=Future()
        future.set_exception(ValueError('The document reader returned an incomplete response. Edit the extracted text or retry reading.'))
        return future
    monkeypatch.setattr(receipt_jobs, 'start_receipt', immediate_failure)
    app = app_for_text(monkeypatch, tmp_path, ai_key='synthetic-test-token')
    app.run()
    assert not app.exception
    assert 'Completed strainer cleaning' in activity(app)
    assert any('incomplete response' in w.value for w in app.warning)
    app.run()
    assert 'Completed strainer cleaning' in activity(app)
    assert not any('New source suggestions are ready' in w.value for w in app.warning)


def test_cached_exact_suggestion_is_applied_once_and_keeps_native_evidence(monkeypatch, tmp_path):
    from app import monthly_report_sources
    def cached(profile, kind, digest):
        if kind != 'section_upload':
            return None
        contents = next(value for key, value in ui.st.session_state.items()
                        if key.endswith('_evidence') and isinstance(value, tuple) and value)
        src=contents[0].source
        assert src.page_texts and 'Completed strainer cleaning' in src.page_texts[0]
        return {'items': [{'source':src.id, 'page':1,
                           'text':'Completed strainer cleaning and leak inspection. Result: no leakage found.',
                           'row':[], 'include_page':False}]}
    monkeypatch.setattr(ai,'cached',cached)
    app=app_for_text(monkeypatch,tmp_path,ai_key='synthetic-test-token')
    for _ in range(3):
        app.run()
        assert not app.exception
    assert activity(app).count('Completed strainer cleaning and leak inspection.')==1
    assert not any('Your edits were kept' in w.value for w in app.warning)


def test_invalid_cached_suggestion_is_not_saved_and_retry_bypasses_cache(monkeypatch, tmp_path):
    from app import receipt_jobs
    counts={'cache':0,'network':0,'save':0}
    def invalid_cache(profile, kind, key):
        if kind=='section_upload':
            counts['cache']+=1
            return {'items':'malformed'}
        return None
    def valid_receipt(prepare, worker):
        counts['network']+=1
        f=Future();f.set_result({'items':[]});return f
    def save_cache(*args):
        counts['save']+=1
    monkeypatch.setattr(ai,'cached',invalid_cache)
    monkeypatch.setattr(ai,'save_cache',save_cache)
    monkeypatch.setattr(receipt_jobs,'start_receipt',valid_receipt)
    app=app_for_text(monkeypatch,tmp_path,ai_key='synthetic-test-token')
    app.run()
    assert not app.exception and 'Completed strainer cleaning' in activity(app)
    assert counts['cache']==1 and counts['save']==0
    assert any('invalid section details' in w.value for w in app.warning)
    next(b for b in app.button if b.label=='Retry reading uploaded files').click().run()
    assert not app.exception
    assert counts['network']==1 and counts['save']==1
    assert counts['cache']==1, 'retry must ignore a poison cached response'
    app.run()
    assert 'Completed strainer cleaning' in activity(app)
    assert not any('invalid section details' in w.value for w in app.warning)
