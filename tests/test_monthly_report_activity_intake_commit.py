"""Delivered Activity input survives source mutations and real recovery storage.

AppTest supplies the native widget messages/upload seam. Browser delivery timing
and native caret continuity still require the corresponding browser journey.
"""
from dataclasses import replace
from datetime import date
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active_work
from app.monthly_report_model import Facility, ReportProfile, ReportPeriod, default_sections


TOKEN = '81' * 16
APP = '''
from app.monthly_report_guided import render_guided_workflow
from app.monthly_report_ui import _field, _move
render_guided_workflow('81818181818181818181818181818181', 'UTC', _field, _move)
'''


def editor(app):
    return next(w for w in app.text_area if w.label == 'Activity summary')


def draft(app):
    return next(value for key, value in app.session_state.filtered_state.items()
                if key.startswith('report_guided_') and key.endswith('_draft')
                and hasattr(value, 'blocks'))


def activity(app):
    return next(block for block in draft(app).blocks if block.key == 'activity_summary')


def setup_app(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided, monthly_report_library as library
    from app import monthly_report_start_ui as start, monthly_report_section_preview_ui as preview
    from app import monthly_report_ai as ai
    profile = ReportProfile('Synthetic Activity Contract', 'integrity-west', 'Synthetic West',
        (Facility('integrity-west', 'Synthetic West'),),
        excluded_sections=tuple(s.key for s in default_sections() if s.key != 'activity'))
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(guided, 'operator_today', lambda tz: date(2026, 11, 7))
    monkeypatch.setattr(start, 'choose_contract', lambda *a: profile.contract)
    monkeypatch.setattr(start, 'select_sites', lambda *a, **kw: (profile, profile))
    monkeypatch.setattr(preview, 'render_section_preview', lambda *a, **kw: None)
    monkeypatch.setattr(ai, 'cached', lambda *a, **kw: None)
    def deny_paid(*a, **kw):
        raise AssertionError('Typing/uploading must not call a paid reader')
    monkeypatch.setattr(ai, 'reserve_call', deny_paid)
    library.save_profile(profile, expected_revision=0, actor='Synthetic Reviewer', confirmed=True)
    app = AppTest.from_string(APP, default_timeout=45).run()
    assert not app.exception
    return app, profile


@pytest.mark.parametrize('same_event', [True, False])
@pytest.mark.parametrize('manual', [
    'Original human wording.\n\nManual correction: vibration rechecked on October 9.',
    '',
])
def test_native_upload_merges_delivered_input_and_new_source_then_recovers(
        monkeypatch, tmp_path, same_event, manual):
    import streamlit as st
    app, profile = setup_app(monkeypatch, tmp_path)
    editor(app).set_value('Original human wording.').run()
    assert not app.exception
    initial_id = editor(app).proto.id
    editor(app).set_value(manual)
    if not same_event:
        app.run()
        assert activity(app).text == manual
    original_uploader = st.file_uploader
    def upload(label, *args, **kwargs):
        if label == 'Add activity files (optional)':
            stream = BytesIO(b'Synthetic vendor inspected relief valve RV-27; replacement remains pending.\n')
            stream.name = 'synthetic-intake-service.txt'
            return [stream]
        return original_uploader(label, *args, **kwargs)
    monkeypatch.setattr(st, 'file_uploader', upload)
    app.run()
    assert not app.exception
    assert 'RV-27' in activity(app).text, 'The upload must actually be processed'
    expected = '\n\n'.join(filter(None, (
        manual, 'Synthetic vendor inspected relief valve RV-27; replacement remains pending.')))
    assert activity(app).text == expected
    assert editor(app).value == expected
    assert editor(app).proto.id == initial_id
    journal = active_work.load(TOKEN, profile.contract, profile.key, ReportPeriod(2026, 10))
    assert journal and next(b.text for b in journal.draft.blocks if b.key == 'activity_summary') == expected
    monkeypatch.setattr(st, 'file_uploader', original_uploader)
    app.run()
    assert not app.exception and activity(app).text == expected
    resumed = AppTest.from_string(APP, default_timeout=45).run()
    assert not resumed.exception and activity(resumed).text == expected
    assert editor(resumed).value == expected


@pytest.mark.parametrize('change_references', [True, False])
def test_interrupted_receipt_stays_recoverable_after_source_reference_change(change_references):
    from test_monthly_report_rich_text_hydration import _interrupted_edit
    pending = 'A delivered human correction which was not committed.'
    app = _interrupted_edit(pending)
    before = app.session_state['canonical_block']
    app.session_state['canonical_block'] = replace(before,
        text=before.text + '\n\nA separately accepted source finding.',
        references=('new-source:1:revision',) if change_references else before.references)
    app.run()
    assert not app.exception
    assert pending not in app.session_state['canonical_block'].text
    assert any(w.label == 'Apply interrupted edit' for w in app.button)
    assert any(pending in item.value for item in app.get('code'))
