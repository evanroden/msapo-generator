"""Server/protobuf contracts, not native-browser acceptance evidence."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_mbcx_financial_pages import financial_page_allowed
from test_monthly_report_financial_warning_navigation import fixture
from test_monthly_report_mbcx_financial_pages import setup, sources


OPEN = 'Review client-facing ENFRA financial pages'
PREFIX = 'financial_disclosure_fixture'
LOCAL = PREFIX + '_evidence_section_mbcx_report'
SCRIPT = '''
import streamlit as st
from app.monthly_report_ui import preserve_report_draft_state, restore_report_draft_state
from app.monthly_report_mbcx_financial_pages import render_reviewed_batch
preserve_report_draft_state()
restore_report_draft_state()
draft = st.session_state['fixture_draft']
contents = st.session_state['fixture_contents']
selected = st.selectbox('Fixture owner', [c.source.id for c in contents], key='fixture_owner')
shown = st.checkbox('Fixture visible', value=True, key='fixture_visible')
if shown:
    content = next(c for c in contents if c.source.id == selected)
    handled, revised, batch = render_reviewed_batch(
        draft.profile, content, {b.key: b for b in draft.blocks}, {},
        'financial_disclosure_fixture_evidence_section_mbcx_report',
        period=draft.period, editor_scope='fixture-scope', sections=draft.sections)
    assert revised == content and not batch
preserve_report_draft_state()
'''


def app_fixture(monkeypatch, tmp_path):
    draft, target, _ = fixture(monkeypatch, tmp_path)
    _, old, _ = setup(monkeypatch, tmp_path, text='Synthetic ordinary pump inspection.')
    contents = (old, target)
    draft = replace(draft, sources=tuple(c.source for c in contents))
    originals = {c.source.id: sources.source_bytes(draft.profile, c.source) for c in contents}
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state['fixture_draft'] = draft
    app.session_state['fixture_contents'] = contents
    return app, draft, contents, originals


def open_control(app):
    return next(w for w in app.checkbox if w.label == OPEN)


def assert_unchanged(app, draft, contents, originals):
    assert not app.exception
    assert app.session_state['fixture_draft'] == draft
    assert app.session_state['fixture_draft'].fingerprint == draft.fingerprint
    assert app.session_state['fixture_contents'] == contents
    for content in contents:
        source = content.source
        assert sources.source_bytes(draft.profile, source) == originals[source.id]
        assert not financial_page_allowed(source, 1, draft.profile, 'mbcx_report')
    for label in ('This is an ENFRA report intended for the client',
                  'I reviewed these pages: their amounts are client-facing ENFRA content, with no vendor-invoice totals'):
        assert not any(w.value for w in app.checkbox if w.label == label)
    assert all(b.disabled for b in app.button if b.label == 'Include reviewed financial pages')


@pytest.mark.parametrize('hide', ['source', 'disclosure'])
@pytest.mark.parametrize('closed', [False, True])
def test_exact_owner_open_default_survives_late_remount_without_grants(monkeypatch, tmp_path, hide, closed):
    app, draft, contents, originals = app_fixture(monkeypatch, tmp_path)
    old, target = contents
    old_key = LOCAL + '_financial_' + old.source.id
    app.run()
    assert open_control(app).value is False and open_control(app).proto.default is False
    open_control(app).check().run()
    app.multiselect[0].set_value([1]).run()
    if closed:
        open_control(app).uncheck().run()
        assert app.session_state[old_key + '_open'] is False
    assert_unchanged(app, draft, contents, originals)
    if hide == 'source':
        app.selectbox[0].set_value(target.source.id).run()
        # A fresh source does not inherit the old source's open choice/pages.
        assert open_control(app).value is False and open_control(app).proto.default is False
        assert not app.multiselect
        app.selectbox[0].set_value(old.source.id).run()
    else:
        next(w for w in app.checkbox if w.label == 'Fixture visible').uncheck().run()
        assert not any(w.label == OPEN for w in app.checkbox)
        next(w for w in app.checkbox if w.label == 'Fixture visible').check().run()
    # Consume any one-shot state packet. A native remount must now agree with
    # the retained exact-owner Boolean without relying on set_value again.
    app.run()
    control = open_control(app)
    assert control.key == old_key + '_open'
    assert control.value is (not closed)
    assert control.proto.set_value is False
    assert control.proto.default is control.value
    assert app.session_state[old_key + '_pages'] == [1]
    assert_unchanged(app, draft, contents, originals)
    if closed:
        assert not app.multiselect
        # Only another explicit user opening may reveal the remembered pages.
        open_control(app).check().run()
    assert app.multiselect[0].value == [1]
    assert [int(app.multiselect[0].proto.options[i].split()[1])
            for i in app.multiselect[0].proto.default] == [1]
    assert_unchanged(app, draft, contents, originals)


@pytest.mark.parametrize('foreign_owner', ['source', 'report'])
def test_foreign_open_key_never_opens_fresh_owner(monkeypatch, tmp_path, foreign_owner):
    app, draft, contents, originals = app_fixture(monkeypatch, tmp_path)
    old, target = contents
    foreign = (LOCAL + '_financial_' + target.source.id + '_open'
               if foreign_owner == 'source' else
               'different_report_evidence_section_mbcx_report_financial_' + old.source.id + '_open')
    # These are explicit retained UI choices of a different owner, not grants.
    app.session_state['report_draft_mirror'] = {foreign: True}
    app.run()
    app.run()
    assert open_control(app).value is False
    assert open_control(app).proto.default is False
    assert open_control(app).proto.set_value is False
    assert not app.multiselect
    assert_unchanged(app, draft, contents, originals)
