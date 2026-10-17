"""Administration routes retain exact namespaces and never replace report drafts."""
from dataclasses import replace
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_admin_ui as admin, monthly_report_designs as designs
from app import monthly_report_designs_ui as design_ui, monthly_report_directory as directory
from app.monthly_report_model import ReportDraft, ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_testing import isolated
from app.monthly_report_ui import shared_fixture_run_token
from test_monthly_report_designs import master_reference
from test_monthly_report_ui import monthly

APP = '''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('a'*32)
'''


def files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('mode', [None, 'isolated', 'fixtures', 'unrecognized'])
def test_urls_preserve_only_supported_public_mode_selectors(mode):
    source = '''
import streamlit as st
from app.monthly_report_admin_ui import admin_url, report_url
st.session_state['admin_url'] = admin_url('directory')
st.session_state['report_url'] = report_url()
'''
    app = AppTest.from_string(source)
    if mode:
        app.query_params['monthly_qa'] = mode
    app.query_params.update({'contract': 'private contract', 'sites': 'private site', 'month': '2026-09',
                             'source': 'private original', 'monthly_admin': 'master'})
    app.run()
    expected = {'workflow': ['monthly'], 'monthly_admin': ['directory']}
    if mode in {'isolated', 'fixtures'}:
        expected['monthly_qa'] = [mode]
    assert parse_qs(urlsplit(app.session_state['admin_url']).query) == expected
    expected.pop('monthly_admin')
    assert parse_qs(urlsplit(app.session_state['report_url']).query) == expected


def test_authoring_has_non_submitting_administration_links_and_no_inline_tools(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    next(field for field in app.text_area if field.label == 'Activity summary').set_value('Acknowledged work stays in this report.').run()
    pending_key = next(key for key, value in app.session_state.filtered_state.items() if key.startswith('report_guided_') and key.endswith('_draft') and isinstance(value, ReportDraft))
    pending = app.session_state[pending_key]
    before = files(tmp_path)
    app.run()
    links = {link.label: link for link in app.sidebar.get('link_button')}
    assert set(links) == {'Contract and site directory', 'Storage maintenance', 'Master design administration'}
    assert all(link.proto.ignore_rerun for link in links.values())
    assert all(parse_qs(urlsplit(link.url).query)['workflow'] == ['monthly'] for link in links.values())
    assert not any(button.key in {'report_storage_check', 'report_storage_consolidate'} for button in app.button)
    assert not any(upload.label == 'New ENFRA master design' for upload in app.get('file_uploader'))
    assert app.session_state[pending_key] == pending
    assert files(tmp_path) == before


@pytest.mark.parametrize('mode', ['live', 'isolated', 'fixtures'])
def test_admin_entry_runs_inside_the_exact_report_namespace(monkeypatch, tmp_path, mode):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    from app.memory import _data_dir
    live_root = _data_dir()
    (live_root / 'unrelated-live-record').write_bytes(b'Keep unchanged')
    seen = []
    monkeypatch.setattr(admin, 'render_storage_maintenance', lambda: seen.append(_data_dir()))
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'storage'
    if mode != 'live':
        app.query_params['monthly_qa'] = mode
    app.run()
    assert not app.exception and not app.error
    if mode == 'live':
        expected = live_root
        assert not app.warning
    else:
        token = shared_fixture_run_token('a' * 32) if mode == 'fixtures' else 'a' * 32
        with isolated(token):
            expected = _data_dir()
        assert any('ISOLATED' in warning.value and 'No live report' in warning.value for warning in app.warning)
        assert expected != live_root
    assert seen == [expected]
    assert (live_root / 'unrelated-live-record').read_bytes() == b'Keep unchanged'
    assert all('source' not in markdown.value for markdown in app.markdown)


def test_unavailable_isolated_storage_never_calls_live_administration(monkeypatch, tmp_path):
    missing = tmp_path / 'missing'
    monkeypatch.setenv('EPC_DATA_DIR', str(missing))
    # A missing provisioned disk is a boundary failure, not a reason to change
    # the requested test mode or create a fallback live storage root.
    seen = []
    monkeypatch.setattr(admin, 'render_storage_maintenance', lambda: seen.append('called'))
    app = AppTest.from_string(APP)
    app.query_params.update({'monthly_admin': 'storage', 'monthly_qa': 'isolated'})
    app.run()
    assert not app.exception
    assert app.error and not seen
    assert not missing.exists()


def test_directory_admin_is_reachable_and_preserves_name_before_read_gate(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError('Saved directory read before attribution')
    monkeypatch.setattr(directory, 'directory_contracts', forbidden)
    monkeypatch.setattr(directory, 'load_directory', forbidden)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'directory'
    app.run()
    assert not app.exception
    assert app.text_input('report_directory_actor').label == 'Directory editor name'
    assert any('Enter your name' in message.value for message in app.info)
    assert not app.get('data_editor') and not app.dataframe
    assert not any(button.key == 'report_directory_back' for button in app.button)
    assert any('target="_self"' in text.value and 'Back to Monthly reports' in text.value for text in app.markdown)


def test_storage_measurement_on_separate_surface_changes_no_report_records(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path)
    pending_key = next(key for key, value in app.session_state.filtered_state.items() if key.startswith('report_guided_') and key.endswith('_draft') and isinstance(value, ReportDraft))
    pending = app.session_state[pending_key]
    before = files(tmp_path)
    app.query_params['monthly_admin'] = 'storage'
    app.run()
    app.button('report_storage_check').click().run()
    assert not app.exception
    assert 'report_storage_summary' in app.session_state.filtered_state
    assert app.session_state[pending_key] == pending
    assert files(tmp_path) == before


def test_master_installation_is_attributed_and_only_changes_future_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    first = designs.install_master(master_reference(tmp_path), actor='Original Editor', expected_revision=0)
    draft = synthetic_draft(designs.pin(synthetic_profiles()[0]), ReportPeriod(2026, 9))
    source = master_reference(tmp_path, 'next', 'Future master').read_bytes()
    monkeypatch.setattr(design_ui.st, 'file_uploader', lambda label, **kwargs: BytesIO(source) if label == 'New ENFRA master design' else None)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'master'
    app.session_state['report_guided_current_draft'] = draft
    app.run()
    assert app.button('report_admin_master_native_design_save').disabled
    app.text_input('report_admin_master_actor').set_value('New Editor').run()
    assert not app.button('report_admin_master_native_design_save').disabled
    app.button('report_admin_master_native_design_save').click().run()
    assert not app.exception and not app.error
    state = designs.master_state()
    assert state['revision'] == 2 and state['default'] != first
    assert state['history'][-1]['actor'] == 'New Editor'
    assert app.session_state['report_guided_current_draft'] == draft
    assert designs.pin(draft.profile) == draft.profile
    assert not any(button.label == 'Apply current master to this report' for button in app.button)
    assert any('Existing drafts' in message.value for message in app.success)


def test_report_uses_new_master_only_after_its_explicit_local_choice(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    designs.install_master(master_reference(tmp_path), actor='Original Editor', expected_revision=0)
    draft = synthetic_draft(designs.pin(synthetic_profiles()[0]), ReportPeriod(2026, 9))
    second = designs.install_master(master_reference(tmp_path, 'next', 'Future master'), actor='Other Editor', expected_revision=1)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_designs_ui import render_apply_master_design
render_apply_master_design(st.session_state['report_guided_current_draft'], 'report_guided_current')
''')
    app.session_state['report_guided_current_draft'] = draft
    before = files(tmp_path / 'runtime')
    app.run()
    assert app.session_state['report_guided_current_draft'] == draft
    assert files(tmp_path / 'runtime') == before
    app.button('report_guided_current_native_design_apply').click().run()
    updated = app.session_state['report_guided_current_draft']
    assert updated.profile.template == designs.MASTER_PREFIX + second
    assert updated.blocks == draft.blocks and updated.sources == draft.sources
    assert files(tmp_path / 'runtime') == before


def test_unknown_admin_route_does_not_render_ordinary_authoring(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError('Unknown admin route must not enter ordinary authoring')
    monkeypatch.setattr('app.monthly_report_guided.render_guided_workflow', forbidden)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'unknown'
    app.run()
    assert not app.exception
    assert any('Choose a Monthly administration page' in error.value for error in app.error)


@pytest.mark.parametrize('mode, active_scope', [('live', True), ('isolated', False), ('fixtures', False)])
def test_admin_rejects_a_mismatched_storage_context_before_any_operation(monkeypatch, mode, active_scope):
    def forbidden(*args, **kwargs):
        raise AssertionError('Mismatched route must not render a storage operation')
    monkeypatch.setattr(admin, 'render_storage_maintenance', forbidden)
    if active_scope:
        with isolated('a' * 32), pytest.raises(ValueError, match='storage context'):
            admin.render_administration('storage', lambda key, value: key, mode=mode)
    else:
        with pytest.raises(ValueError, match='storage context'):
            admin.render_administration('storage', lambda key, value: key, mode=mode)


@pytest.mark.parametrize('mode', ['isolated', 'fixtures'])
def test_master_installation_in_admin_testing_cannot_change_live_master(monkeypatch, tmp_path, mode):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    old = designs.install_master(master_reference(tmp_path), actor='Live Master Editor', expected_revision=0)
    before = files(tmp_path / 'runtime')
    source = master_reference(tmp_path, 'testing', 'Isolated future master').read_bytes()
    monkeypatch.setattr(design_ui.st, 'file_uploader', lambda label, **kwargs: BytesIO(source) if label == 'New ENFRA master design' else None)
    app = AppTest.from_string(APP)
    app.query_params.update({'monthly_admin': 'master', 'monthly_qa': mode})
    app.run()
    app.text_input('report_admin_master_actor').set_value('Isolated Master Editor').run()
    app.button('report_admin_master_native_design_save').click().run()
    assert not app.exception and not app.error
    assert designs.master_state()['revision'] == 1 and designs.master_state()['default'] == old
    token = shared_fixture_run_token('a' * 32) if mode == 'fixtures' else 'a' * 32
    with isolated(token):
        state = designs.master_state()
        assert state['revision'] == 1 and state['default'] != old
        assert state['history'][0]['actor'] == 'Isolated Master Editor'
    after_live = {name: raw for name, raw in files(tmp_path / 'runtime').items()
                  if not name.startswith('_enfra_monthly_report_qa_v1/')}
    assert after_live == before


def test_stale_master_install_requires_explicit_base_choice_and_retains_selected_files(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    designs.install_master(master_reference(tmp_path), actor='Initial Master Editor', expected_revision=0)
    pending = master_reference(tmp_path, 'pending', 'Pending selected design').read_bytes()
    upload = BytesIO(pending)
    monkeypatch.setattr(design_ui.st, 'file_uploader', lambda label, **kwargs: upload if label == 'New ENFRA master design' else None)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'master'
    app.run()
    app.text_input('report_admin_master_actor').set_value('Pending Master Editor').run()
    stale_button = app.button('report_admin_master_native_design_save')
    assert not stale_button.disabled
    other = designs.install_master(master_reference(tmp_path, 'other', 'Concurrent selected design'),
                                   actor='Concurrent Master Editor', expected_revision=1)
    before = files(tmp_path / 'runtime')
    stale_button.click().run()
    assert not app.exception
    assert designs.master_state()['revision'] == 2 and designs.master_state()['default'] == other
    assert app.button('report_admin_master_native_design_save').disabled
    assert any('version 1' in warning.value and 'version 2' in warning.value for warning in app.warning)
    assert any('Concurrent Master Editor' in str(table.value) for table in app.table)
    assert upload.getvalue() == pending and files(tmp_path / 'runtime') == before
    next(button for button in app.button if button.label == 'Continue from master version 2').click().run()
    assert not app.exception and not app.button('report_admin_master_native_design_save').disabled
    assert upload.getvalue() == pending and files(tmp_path / 'runtime') == before
    app.button('report_admin_master_native_design_save').click().run()
    state = designs.master_state()
    assert not app.exception and not app.error
    assert state['revision'] == 3 and state['history'][-1]['actor'] == 'Pending Master Editor'
    assert (designs.library._root() / 'designs' / 'master' / (state['default'] + '.docx')).read_bytes() == pending


def test_current_master_base_accepts_an_idempotent_selected_file(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    path = master_reference(tmp_path)
    digest = designs.install_master(path, actor='Initial Master Editor', expected_revision=0)
    raw = path.read_bytes()
    upload = BytesIO(raw)
    monkeypatch.setattr(design_ui.st, 'file_uploader', lambda label, **kwargs: upload if label == 'New ENFRA master design' else None)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'master'
    app.run()
    app.text_input('report_admin_master_actor').set_value('Current Master Editor').run()
    before = files(tmp_path / 'runtime')
    app.button('report_admin_master_native_design_save').click().run()
    assert not app.exception and not app.error and app.success
    assert designs.master_state()['revision'] == 1 and designs.master_state()['default'] == digest
    assert upload.getvalue() == raw and files(tmp_path / 'runtime') == before


def test_late_master_base_choice_cannot_acknowledge_an_unseen_newer_revision(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    designs.install_master(master_reference(tmp_path), actor='Initial Master Editor', expected_revision=0)
    app = AppTest.from_string(APP)
    app.query_params['monthly_admin'] = 'master'
    app.run()
    app.text_input('report_admin_master_actor').set_value('Pending Master Editor').run()
    uploader_ids = {upload.label: upload.proto.id for upload in app.get('file_uploader')}
    designs.install_master(master_reference(tmp_path, 'second', 'Second master'), actor='Second Editor', expected_revision=1)
    app.run()
    old_choice = next(button for button in app.button if button.label == 'Continue from master version 2')
    designs.install_master(master_reference(tmp_path, 'third', 'Third master'), actor='Third Editor', expected_revision=2)
    before = files(tmp_path / 'runtime')
    old_choice.click().run()
    assert not app.exception and not app.error
    assert app.session_state['report_admin_master_native_design_base_revision'] == 1
    assert any(button.label == 'Continue from master version 3' for button in app.button)
    assert {upload.label: upload.proto.id for upload in app.get('file_uploader')} == uploader_ids
    assert files(tmp_path / 'runtime') == before
