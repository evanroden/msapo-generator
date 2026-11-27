"""A pending source is never presented as the current editable report."""
from dataclasses import replace
from io import BytesIO
from streamlit.testing.v1 import AppTest
from app import monthly_report_library as library
from app.monthly_report_guided import complete_guided_sections
from tests.test_monthly_report_start_conflicts import collision, button, manifest, block
from tests.test_monthly_report_start_import import save_start

NOTICE = 'Starting report review is pending.'


def guided(initial):
    app = AppTest.from_string('''
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
working = complete_guided_sections(st.session_state['working'])
state = library.load_profile(working.profile.contract, working.profile.key)
render_section_setup(working.profile.contract, working.period, 'Synthetic Editor', _field,
    state=state, working_draft=working, working_revision=1)
''', default_timeout=30)
    app.session_state['working'] = initial
    return app.run()


def test_pending_notice_covers_keep_and_selected_but_not_success_or_empty(collision):
    initial, first, second, upload, _ = collision
    before = manifest(initial).read_bytes()
    app = guided(initial)
    assert not app.exception
    notice, = [w.value for w in app.warning if NOTICE in w.value]
    assert 'editors still show your current report' in notice
    assert 'source previews may show the pending file' in notice
    button(app, 'Keep current organization chart and return to review').click().run()
    assert any(NOTICE in w.value for w in app.warning)
    assert manifest(initial).read_bytes() == before
    button(app, 'Use incoming organization chart').click().run()
    assert any(NOTICE in w.value for w in app.warning)
    assert manifest(initial).read_bytes() == before
    saved = save_start(app)
    assert block(saved).asset_hashes != block(initial).asset_hashes
    assert not any(NOTICE in w.value for w in app.warning)
    assert library.load_snapshot(initial.profile.contract, initial.profile.key, initial.period).draft == initial


def test_profile_only_review_does_not_claim_there_are_current_editors(collision):
    _, _, _, _, app = collision
    assert not any(NOTICE in w.value for w in app.warning)


def test_full_app_keeps_existing_activity_separate_from_pending_source(monkeypatch, tmp_path):
    from tests.test_monthly_report_ui import monthly
    from tests.test_monthly_report_start_import import report_file
    from app import monthly_report_entry_upload as entry
    app = monthly(monkeypatch, tmp_path)
    source = report_file(tmp_path, contact=False,
        activity=('September 2026 incoming synthetic work awaiting import.',))
    raw = source.read_bytes()
    real = entry.st.file_uploader
    def uploader(label, *args, **kwargs):
        if label != 'Starting report':
            return real(label, *args, **kwargs)
        upload = BytesIO(raw)
        upload.name, upload.size = 'pending-synthetic.docx', len(raw)
        return upload
    monkeypatch.setattr(entry.st, 'file_uploader', uploader)
    app.run()
    assert not app.exception
    assert any(NOTICE in w.value for w in app.warning)
    assert next(w for w in app.text_area if w.label == 'Activity summary').value == 'Synthetic initial activity.'
    assert button(app, 'Continue to this month’s updates').disabled
