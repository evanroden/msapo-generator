"""Synthetic full organization path: shared normalization and uncertain writes."""
from dataclasses import replace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_directory as directory
from app.monthly_report_model import synthetic_profiles

SCRIPT = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_organization_ui import render_organization
from app.monthly_report_ui import _field
from app.monthly_report_directory import CONTACT_SPEC
blocks = st.session_state['blocks']
draft = replace(synthetic_draft(synthetic_profiles()[1], ReportPeriod(2026,9)),
                prepared_by='Synthetic Reviewer', blocks=tuple(blocks.values()))
st.session_state['blocks'] = render_organization(draft, blocks, {'contact_matrix':CONTACT_SPEC},
    'standing_receipt', {}, _field, lambda s,b:b, show_preview=False)
'''


def press(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def field(app, label):
    return next(w for w in app.text_input if w.label == label)


def report(app):
    return app.session_state['blocks']['contact_matrix']


def reopen(block):
    app = AppTest.from_string(SCRIPT)
    app.session_state['blocks'] = {'contact_matrix':block}
    app.run()
    press(app, 'Edit contacts')
    return app


def workspace(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[1]
    sites = tuple(directory.DirectorySite(f.key, f.title, contacts=(
        directory.DirectoryContact('Operator', f'Invented {i}', 'old', ''),))
        for i,f in enumerate(profile.facilities))
    original = directory.save_directory(profile.contract, sites, expected_revision=0,
                                        actor='Synthetic Reviewer', confirmed=True)
    before, missing = directory.contact_block(original, profile.facilities)
    assert not missing
    before = replace(before, source='Library')
    return reopen(before), profile, original, before


def test_multisite_add_keeps_native_field_and_expected_rows_bound_after_shared_grouping(monkeypatch, tmp_path):
    app, profile, original, before = workspace(monkeypatch, tmp_path)
    press(app, 'Add contact')
    identity = field(app, 'Phone').proto.id
    for label,value in [('Facility',profile.facilities[0].title), ('Role','Engineer'),
                        ('Name','New Invented'), ('Phone','new-phone'), ('Email','new@example.invalid')]:
        field(app,label).set_value(value).run()
        assert not app.exception and not app.warning
        assert field(app,'Phone').proto.id == identity
    latest = directory.load_directory(profile.contract)
    assert latest.sites[0].contacts[-1].phone == 'new-phone'
    assert latest.sites[0].contacts[-1].email == 'new@example.invalid'
    assert latest.sites[1] == original.sites[1]
    assert report(app).source == 'Library'
    assert report(app).rows[1][2:4] == ('New Invented','new-phone')
    assert directory.load_directory(profile.contract, original.revision) == original
    press(app,'Close editing')
    assert not app.text_input


@pytest.mark.parametrize('fresh_context', [False, True])
def test_precommit_failure_preserves_pending_intent_until_explicit_retry(monkeypatch, tmp_path, fresh_context):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Edit contact')
    field(app,'Phone').set_value('corrected')
    with patch.object(directory,'automatically_keep_directory_contact_edits',side_effect=OSError('synthetic failure')) as write:
        press(app,'Remove contact')
    assert write.call_count == 1
    assert report(app).rows[0][3] == 'corrected'
    assert len(report(app).rows) == len(before.rows)
    assert any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    assert not app.text_input
    assert directory.load_directory(profile.contract) == original
    if fresh_context:
        app = reopen(report(app))  # No session receipt: reconstruct historical baseline.
    else:
        app.run()
    assert app.warning
    with patch.object(directory,'automatically_keep_directory_contact_edits',wraps=directory.automatically_keep_directory_contact_edits) as write:
        press(app,'Retry shared contact correction')
        app.run()
    assert write.call_count == 1
    latest = directory.load_directory(profile.contract)
    assert latest.revision == original.revision + 1
    assert latest.sites[0].contacts[0].phone == 'corrected'
    assert report(app).source == 'Library'
    assert not any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    press(app,'Edit contact')
    field(app,'Phone').set_value('next correction').run()
    assert directory.load_directory(profile.contract).sites[0].contacts[0].phone == 'next correction'


def test_postcommit_exception_reads_back_exact_revision_without_duplicate_write_or_removal(monkeypatch,tmp_path):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Edit contact')
    field(app,'Phone').set_value('committed correction')
    real = directory.automatically_keep_directory_contact_edits
    def after_commit(*args,**kwargs):
        real(*args,**kwargs)
        raise OSError('synthetic acknowledgement failure')
    with patch.object(directory,'automatically_keep_directory_contact_edits',side_effect=after_commit) as write:
        press(app,'Remove contact')
    assert write.call_count == 1
    latest = directory.load_directory(profile.contract)
    assert latest.revision == original.revision + 1
    expected,missing = directory.contact_block(latest,profile.facilities)
    assert not missing
    assert report(app).references == expected.references
    assert report(app).rows == expected.rows and report(app).source == 'Library'
    assert len(report(app).rows) == len(before.rows)
    app.run()
    assert directory.load_directory(profile.contract).revision == latest.revision


def test_keep_report_only_after_failed_add_retires_future_directory_intent(monkeypatch,tmp_path):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Add contact')
    field(app,'Facility').set_value(profile.facilities[0].title).run()
    field(app,'Role').set_value('Engineer').run()
    with patch.object(directory,'automatically_keep_directory_contact_edits',side_effect=OSError('synthetic failure')):
        field(app,'Name').set_value('New Invented').run()
    press(app,'Keep correction in this report only')
    assert report(app).source == 'This month'
    assert not any(ref.startswith(('directory-add-intent:','directory-pending-correction:')) for ref in report(app).references)
    [b for b in app.button if b.label=='Edit contact'][-1].click().run()
    field(app,'Phone').set_value('report-only phone').run()
    assert directory.load_directory(profile.contract) == original
    assert report(app).rows[-1][3] == 'report-only phone'


@pytest.mark.parametrize('choice', ['Retry shared contact correction', 'Keep correction in this report only'])
def test_stale_shared_recovery_choice_cannot_act_on_newer_pending_correction(monkeypatch,tmp_path,choice):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Edit contact')
    field(app,'Phone').set_value('pending A')
    with patch.object(directory,'automatically_keep_directory_contact_edits',side_effect=OSError('synthetic failure')):
        press(app,'Remove contact')
    old_choice = next(b for b in app.button if b.label == choice)
    current = report(app)
    newer = replace(current, rows=((*current.rows[0][:3], 'pending B', current.rows[0][4]), *current.rows[1:]))
    app.session_state['blocks'] = {'contact_matrix':newer}
    with patch.object(directory,'automatically_keep_directory_contact_edits',wraps=directory.automatically_keep_directory_contact_edits) as write:
        old_choice.click().run()
    assert not app.exception and write.call_count == 0
    assert report(app) == newer
    assert any('changed after this recovery choice' in warning.value for warning in app.warning)
    assert directory.load_directory(profile.contract) == original


def test_incomplete_add_defers_shared_io_and_survives_close_before_completion(monkeypatch,tmp_path):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Add contact')
    with patch.object(directory,'load_directory',side_effect=OSError('synthetic transient read')) as read, \
         patch.object(directory,'automatically_keep_directory_contact_edits',wraps=directory.automatically_keep_directory_contact_edits) as write:
        field(app,'Facility').set_value(profile.facilities[0].title).run()
        assert not app.exception and not app.warning
        assert field(app,'Facility').value == profile.facilities[0].title
        press(app,'Close editing')
        assert not app.text_input
    assert read.call_count == 0 and write.call_count == 0
    assert report(app).rows[-1] == (profile.facilities[0].title,'','','','')
    assert not any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    assert any(ref.startswith('directory-add-intent:') for ref in report(app).references)
    [b for b in app.button if b.label=='Edit contact'][-1].click().run()
    for label,value in [('Name','Incomplete then completed'), ('Role','Engineer'), ('Phone','completed-phone')]:
        field(app,label).set_value(value).run()
        assert not app.exception and not app.warning
    assert report(app).source == 'Library'
    latest = directory.load_directory(profile.contract)
    assert latest.sites[0].contacts[-1].phone == 'completed-phone'
    assert latest.sites[1] == original.sites[1]


@pytest.mark.parametrize('complete', [False, True])
def test_reloaded_add_unavailable_baseline_keeps_visible_recovery_and_add_intent(monkeypatch,tmp_path,complete):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Add contact')
    field(app,'Facility').set_value(profile.facilities[0].title).run()
    press(app,'Close editing')
    app = reopen(report(app))
    [b for b in app.button if b.label=='Edit contact'][-1].click().run()
    with patch.object(directory,'load_directory',side_effect=OSError('synthetic unavailable baseline')), \
         patch.object(directory,'automatically_keep_directory_contact_edits',wraps=directory.automatically_keep_directory_contact_edits) as write:
        if complete:
            # Deliver both required cells together from the native row.
            field(app,'Name').set_value('Reloaded Completed')
        field(app,'Role').set_value('Engineer').run()
    assert write.call_count == 0
    assert any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    assert app.warning
    press(app,'Retry shared contact correction')
    assert not any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    if not complete:
        assert any(ref.startswith('directory-add-intent:') for ref in report(app).references)
        [b for b in app.button if b.label=='Edit contact'][-1].click().run()
        field(app,'Name').set_value('Reloaded Completed').run()
    assert report(app).source == 'Library'
    latest = directory.load_directory(profile.contract)
    assert latest.revision == original.revision + 1
    assert latest.sites[0].contacts[-1].name == 'Reloaded Completed'
    assert latest.sites[1] == original.sites[1]
