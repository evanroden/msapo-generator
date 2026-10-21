"""One explicit group review retains both unchanged receipt obligations."""
import pytest
from streamlit.testing.v1 import AppTest
from test_monthly_report_native_art_review import sample


def review_app(sample, before=''):
    path, *_ = sample
    return AppTest.from_string(f'''
from pathlib import Path
import streamlit as st
from test_monthly_report_native_art_review import setup
from app.monthly_report_section_ui import _native_art_preservation_review
from app.monthly_report_ui import _field
path, view, profile, period, inventory, saved = setup(Path({str(path)!r}))
{before}
actor = st.text_input('Reviewer', value='Synthetic Operator')
st.session_state['receipt'] = _native_art_preservation_review(path, view, profile, period,
    actor, 'synthetic', _field, saved=st.session_state.get('saved_review'))
''', default_timeout=30).run()


@pytest.mark.parametrize('keep,review', [(True, False), (False, True), (True, True)])
def test_old_separate_checks_cannot_silently_grant_combined_consent(sample, keep, review):
    app = review_app(sample, f'''
for occurrence in inventory.occurrences:
    key = 'synthetic_native_art_' + inventory.sha256[:20] + '_' + occurrence.preview_group_key[:16]
    st.session_state[key + '_keep'] = {keep!r}
    st.session_state[key + '_review'] = {review!r}
''')
    assert not app.exception
    assert len(app.checkbox) == 2 and not any(c.value for c in app.checkbox)
    assert app.session_state['receipt'] is None


def test_single_group_ack_requires_every_group_and_actor_then_exact_receipt(sample):
    *_, receipt = sample
    app = review_app(sample)
    assert len(app.checkbox) == 2
    assert all('keep it unchanged' in c.label for c in app.checkbox)
    assert sum('no visible pricing or inappropriate private information' in c.value for c in app.caption) == 2
    app.checkbox[0].check().run()
    assert app.session_state['receipt'] is None
    app.checkbox[1].check().run()
    assert app.session_state['receipt'] == receipt
    app.text_input[0].set_value('').run()
    assert app.session_state['receipt'] is None
    app.text_input[0].set_value('Synthetic Operator').run()
    assert app.session_state['receipt'] == receipt
    app.checkbox[0].uncheck().run()
    assert app.session_state['receipt'] is None
    app.checkbox[0].check().run()
    assert app.session_state['receipt'] == receipt
    assert not app.exception


def test_verified_saved_receipt_reuses_review_without_new_checkbox(sample):
    *_, receipt = sample
    app = review_app(sample, "st.session_state['saved_review'] = saved")
    assert not app.exception and len(app.checkbox) == 0
    assert app.session_state['receipt'] == receipt


def test_combined_check_is_invalidated_by_new_report_month(sample):
    app = review_app(sample, '''
if st.session_state.get('next_month'):
    from dataclasses import replace
    period = replace(period, month=period.month % 12 + 1)
''')
    for checkbox in app.checkbox:
        checkbox.check()
    app.run()
    assert app.session_state['receipt'] is not None
    app.session_state['next_month'] = True
    app.run()
    assert not app.exception
    assert len(app.checkbox) == 2 and not any(c.value for c in app.checkbox)
    assert app.session_state['receipt'] is None


def test_prior_check_cannot_approve_unavailable_image(sample, monkeypatch):
    from app import monthly_report_import as imports
    app = review_app(sample)
    for checkbox in app.checkbox:
        checkbox.check()
    app.run()
    assert app.session_state['receipt'] is not None
    def unavailable(*args, **kwargs):
        raise ValueError('Synthetic unavailable image')
    monkeypatch.setattr(imports, '_read_import_image', unavailable)
    app.run()
    assert not app.exception and app.error
    assert app.session_state['receipt'] is None
