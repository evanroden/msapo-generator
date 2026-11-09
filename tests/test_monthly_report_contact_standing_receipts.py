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
    def field_path(node, path=()):
        if getattr(node, 'type', '') == 'text_input' and node.proto.id == identity:
            return path
        for index, child in getattr(node, 'children', {}).items():
            found = field_path(child, path + (index,))
            if found is not None:
                return found
    path = field_path(app._tree)
    assert path is not None
    for label,value in [('Facility',profile.facilities[0].title), ('Role','Engineer'),
                        ('Name','New Invented'), ('Phone','new-phone'), ('Email','new@example.invalid')]:
        field(app,label).set_value(value).run()
        assert not app.exception and not app.warning
        assert field(app,'Phone').proto.id == identity
        assert field_path(app._tree) == path, 'The active editor must not move parents during directory regrouping.'
        assert len([b for b in app.button if b.label == 'Edit contact']) == len(report(app).rows) - 1
        assert len(app.text_input) == 5
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

def test_parent_reentry_rehydrates_phone_from_committed_directory_without_a_new_write(monkeypatch, tmp_path):
    app, profile, original, before = workspace(monkeypatch, tmp_path)
    press(app, 'Add contact')
    for label, value in [('Facility', profile.facilities[0].title), ('Role', 'Engineer'),
                         ('Name', 'Synthetic New Person'), ('Phone', '202-555-0174')]:
        field(app, label).set_value(value).run()
        assert not app.exception
    assert any(row[3] == '202-555-0174' for row in report(app).rows)
    old_key = field(app, 'Phone').key
    saved_revision = directory.load_directory(profile.contract).revision
    press(app, 'Done')
    assert not app.text_input
    press(app, 'Edit contacts')
    assert field(app, 'Phone').value == '202-555-0174'
    assert field(app, 'Phone').key != old_key
    assert any(row[3] == '202-555-0174' for row in report(app).rows)
    assert directory.load_directory(profile.contract).revision == saved_revision

def test_parent_done_consumes_unblurred_native_phone_before_save_or_reload(monkeypatch, tmp_path):
    app, profile, original, before = workspace(monkeypatch, tmp_path)
    press(app, 'Edit contact')
    field(app, 'Phone').set_value('delivered-with-done')  # No preliminary .run() / blur.
    press(app, 'Done')
    assert not app.text_input and not app.exception and not app.warning
    assert report(app).rows[0][3] == 'delivered-with-done'
    latest = directory.load_directory(profile.contract)
    assert latest.revision == original.revision + 1
    assert latest.sites[0].contacts[0].phone == 'delivered-with-done'
    assert not any(ref.startswith('directory-pending-correction:') for ref in report(app).references)
    assert directory.load_directory(profile.contract, original.revision) == original


CHART_SCRIPT = SCRIPT.replace("{'contact_matrix':CONTACT_SPEC}",
    "{'org_chart':next(s for sec in default_sections() for s in sec.blocks if s.key=='org_chart'),"
    "'contact_matrix':CONTACT_SPEC}").replace(
    "from app.monthly_report_model import ReportPeriod,",
    "from app.monthly_report_model import default_sections, ReportPeriod,")


def test_edit_chart_after_an_unblurred_contact_field_opens_the_chart_in_one_action(monkeypatch, tmp_path):
    """The team chart renders before contacts; the deferred switch must still open it."""
    from app.monthly_report_model import ResolvedBlock
    _, profile, original, before = workspace(monkeypatch, tmp_path)
    app = AppTest.from_string(CHART_SCRIPT)
    app.session_state['blocks'] = {'org_chart': ResolvedBlock('org_chart', 'This month'), 'contact_matrix': before}
    app.run()
    press(app, 'Edit contacts')
    press(app, 'Edit contact')
    field(app, 'Phone').set_value('delivered-with-chart')  # No preliminary .run() / blur.
    press(app, 'Edit chart')
    assert not app.warning
    assert any(b.key == 'standing_receipt_organization_close_org_chart' for b in app.button), \
        'one Edit chart action opens the chart editor'
    assert not any(b.label == 'Edit chart' for b in app.button)
    assert not app.text_input, 'the contact editor closed after its field was kept'
    assert report(app).rows[0][3] == 'delivered-with-chart'
    assert directory.load_directory(profile.contract).sites[0].contacts[0].phone == 'delivered-with-chart'


@pytest.mark.parametrize('choice', ['Retry shared contact correction', 'Keep correction in this report only'])
def test_resolved_recovery_does_not_move_next_native_edit_on_passive_rerun(monkeypatch,tmp_path,choice):
    app, profile, original, before = workspace(monkeypatch,tmp_path)
    press(app,'Edit contact')
    field(app,'Phone').set_value('stable correction')
    with patch.object(directory,'automatically_keep_directory_contact_edits',side_effect=OSError('synthetic failure')):
        press(app,'Remove contact')
    with patch.object(directory,'automatically_keep_directory_contact_edits',wraps=directory.automatically_keep_directory_contact_edits) as write:
        press(app,choice)
        assert not any('still pending' in warning.value for warning in app.warning)
        assert not any(button.label in ('Retry shared contact correction','Keep correction in this report only') for button in app.button)
        button=next(button for button in app.button if button.label=='Edit contact')
        identity=button.proto.id
        def path(node,parents=()):
            if getattr(node,'type','')=='button' and node.proto.id==identity:return parents
            for index,child in getattr(node,'children',{}).items():
                found=path(child,(*parents,index))
                if found is not None:return found
        previous_path=path(app._tree)
        previous_report=report(app)
        previous_directory=directory.load_directory(profile.contract)
        app.run()
        assert not app.exception
        assert path(app._tree)==previous_path
        assert report(app)==previous_report
        assert directory.load_directory(profile.contract)==previous_directory
        assert write.call_count==(1 if choice.startswith('Retry') else 0)
    press(app,'Edit contact')
    assert field(app,'Phone').value=='stable correction'


def test_contact_native_default_is_present_on_first_mount_without_state_hydration(monkeypatch, tmp_path):
    from streamlit.elements.lib import policies
    app, profile, original, before = workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    with patch.object(policies._LOGGER, 'warning') as warning:
        press(app, 'Edit contact')
    assert not warning.called
    phone = field(app, 'Phone')
    identity = phone.proto.id
    assert phone.proto.default == 'old'
    assert phone.proto.set_value is False
    assert phone.value == 'old'
    assert phone.key in app.session_state['report_widget_keys']
    app.run()
    assert field(app, 'Phone').proto.id == identity
    assert field(app, 'Phone').value == 'old'
    field(app, 'Phone').set_value('new-native-phone').run()
    assert field(app, 'Phone').proto.id == identity
    assert field(app, 'Phone').proto.default == 'new-native-phone'
    assert report(app).rows[0][3] == 'new-native-phone'
    field(app, 'Phone').set_value('').run()
    assert field(app, 'Phone').proto.id == identity
    assert field(app, 'Phone').proto.default == ''
    assert field(app, 'Phone').value == ''
    assert report(app).rows[0][3] == ''
    app.run()
    assert field(app, 'Phone').value == ''
    press(app, 'Done')
    press(app, 'Edit contacts')
    assert field(app, 'Phone').proto.default == ''
    assert field(app, 'Phone').value == ''


def test_after_commit_recovery_reentry_starts_with_saved_native_phone(monkeypatch, tmp_path):
    app, profile, original, before = workspace(monkeypatch, tmp_path)
    press(app, 'Edit contact')
    field(app, 'Phone').set_value('after-commit-native')
    real = directory.automatically_keep_directory_contact_edits
    def after_commit(*args, **kwargs):
        real(*args, **kwargs)
        raise OSError('synthetic acknowledgement failure')
    with patch.object(directory, 'automatically_keep_directory_contact_edits', side_effect=after_commit):
        press(app, 'Remove contact')
    press(app, 'Edit contact')
    phone = field(app, 'Phone')
    assert phone.proto.default == 'after-commit-native'
    assert phone.proto.set_value is False
    identity = phone.proto.id
    field(app, 'Phone').set_value('immediate-replacement')
    press(app, 'Done')
    assert not app.text_input
    assert report(app).rows[0][3] == 'immediate-replacement'
    assert directory.load_directory(profile.contract).sites[0].contacts[0].phone == 'immediate-replacement'


def test_native_contact_default_keeps_existing_transformed_registration_key(monkeypatch):
    from types import SimpleNamespace
    from app import monthly_report_contact_cards_ui as cards
    state = {'actual-key': 'delivered dirty edit'}
    rendered = []
    fake = SimpleNamespace(session_state=state,
        text_input=lambda label, **kwargs: rendered.append((dict(state), kwargs)),
        button=lambda *args, **kwargs: None)
    monkeypatch.setattr(cards, 'st', fake)
    cards._fields(SimpleNamespace(columns=('Phone',)), (('logical-key', 'old'),),
                  lambda key, original: 'actual-key', ('record', 'epoch', (), None, ()), False)
    assert state == {'actual-key': 'delivered dirty edit'}
    assert rendered[0][1]['key'] == 'actual-key'
    assert rendered[0][1]['value'] == 'delivered dirty edit'


def test_native_contact_default_retires_only_a_fresh_registration_seed(monkeypatch):
    from types import SimpleNamespace
    from app import monthly_report_contact_cards_ui as cards
    state = {'unrelated-key': 'retain'}
    rendered = []
    def register(key, original):
        state.setdefault('actual-key', original)
        return 'actual-key'
    fake = SimpleNamespace(session_state=state,
        text_input=lambda label, **kwargs: rendered.append((dict(state), kwargs)),
        button=lambda *args, **kwargs: None)
    monkeypatch.setattr(cards, 'st', fake)
    cards._fields(SimpleNamespace(columns=('Phone',)), (('logical-key', 'saved-phone'),),
                  register, ('record', 'epoch', (), None, ()), False)
    assert rendered[0][0] == {'unrelated-key': 'retain'}
    assert rendered[0][1]['value'] == 'saved-phone'
