"""Explicit contact recovery survives rerun yields without replaying failed saves."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

from app import monthly_report_directory as directory
from app import monthly_report_visual_ui as ui
from app.monthly_report_model import synthetic_profiles


def interrupt():
    raise RerunException(RerunData())


class State(dict):
    stop = None
    reads = 0
    def get(self, key, default=None):
        self.reads += 1
        if self.stop == ('get', self.reads):
            self.stop = None
            interrupt()
        return super().get(key, default)
    def __setitem__(self, key, value):
        if self.stop == ('set', key):
            self.stop = None
            interrupt()
        super().__setitem__(key, value)
    def pop(self, key, default=None):
        if self.stop == ('pop', key):
            self.stop = None
            interrupt()
        return super().pop(key, default)


@pytest.fixture
def case(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[1]
    sites = tuple(directory.DirectorySite(f.key, f.title, contacts=(
        directory.DirectoryContact('Operator', f'Invented {i}', 'old', ''),))
        for i, f in enumerate(profile.facilities))
    original = directory.save_directory(profile.contract, sites, expected_revision=0,
                                        actor='Synthetic Reviewer', confirmed=True)
    before, missing = directory.contact_block(original, profile.facilities)
    assert not missing
    before = replace(before, source='Library')
    after = replace(before, source='This month', rows=(
        (*before.rows[0][:3], '202-555-0175', before.rows[0][4]), *before.rows[1:]))
    draft = SimpleNamespace(profile=profile, prepared_by='Synthetic Reviewer')
    block = replace(after, references=(*after.references, ui._contact_pending_marker(draft)))
    state = State(p_standing_recovery={'before': before, 'after': after})
    messages = []
    def warning(message):
        if state.stop == ('warning',):
            state.stop = None
            interrupt()
        messages.append(message)
    monkeypatch.setattr(ui, 'st', SimpleNamespace(session_state=state, warning=warning,
                         info=warning, button=lambda *a, **k: None))
    def render():
        return ui._recover_contact_correction(draft, block, 'p')
    assert render() == (block, True)
    control = state['p_standing_action']
    def queue(action='retry', owner=None):
        ui._queue_contact_recovery('p', block, action, owner or control)
    return SimpleNamespace(**locals())


@pytest.mark.parametrize('boundary', [1, 2])
def test_prewrite_state_interruption_retains_one_double_click_intent(case, monkeypatch, boundary):
    c = case
    c.queue(); c.queue()
    real = directory.automatically_keep_directory_contact_edits
    calls = []
    def writer(*a, **k):
        calls.append(1)
        return real(*a, **k)
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', writer)
    c.state.reads = 0; c.state.stop = ('get', boundary)
    with pytest.raises(RerunException):
        c.render()
    assert c.control['phase'] == 'queued' and not calls
    result, pending = c.render()
    assert not pending and result.rows[0][3] == '202-555-0175'
    assert calls == [1]
    assert directory.load_directory(c.profile.contract).revision == c.original.revision + 1
    c.queue()  # same displayed generation cannot re-arm a consumed action
    c.render()
    assert calls == [1]


def test_fixture_like_prewrite_pop_interruption_resumes_only_proven_unchanged_baseline(case, monkeypatch):
    c = case; c.queue()
    real = directory.automatically_keep_directory_contact_edits
    attempts = []
    def writer(*a, **k):
        c.state.pop('_contact_fault_once', '')
        attempts.append(1)
        return real(*a, **k)
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', writer)
    c.state.stop = ('pop', '_contact_fault_once')
    with pytest.raises(RerunException): c.render()
    assert c.control['phase'] == 'interrupted' and attempts == []
    assert not c.render()[1]
    assert attempts == [1]


@pytest.mark.parametrize('boundary', [('set', 'p_standing_recovery'), ('warning',)])
def test_definite_failure_ack_precedes_every_pending_ui_yield_and_new_retry_is_explicit(case, monkeypatch, boundary):
    c = case; c.queue()
    attempts = []
    def fail(*a, **k):
        attempts.append(1)
        raise OSError('definite precommit failure')
    real = directory.automatically_keep_directory_contact_edits
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', fail)
    c.state.stop = boundary
    with pytest.raises(RerunException): c.render()
    assert c.control['phase'] == 'terminal'
    assert c.render() == (c.block, True)
    assert attempts == [1]
    fresh = c.state['p_standing_action']
    assert fresh is not c.control
    c.queue(owner=c.control)
    assert fresh['phase'] == 'offered'
    c.queue(owner=fresh)
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', real)
    assert not c.render()[1]
    assert directory.load_directory(c.profile.contract).revision == c.original.revision + 1


def test_commit_before_ack_interruption_reads_back_without_second_save(case, monkeypatch):
    c = case; c.queue(); attempts = []
    real = directory.automatically_keep_directory_contact_edits
    def writer(*a, **k):
        attempts.append(1)
        real(*a, **k)
        interrupt()
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', writer)
    with pytest.raises(RerunException): c.render()
    result, pending = c.render()
    assert not pending and result.rows[0][3] == '202-555-0175'
    assert attempts == [1]
    assert directory.load_directory(c.profile.contract).revision == c.original.revision + 1


@pytest.mark.parametrize('storage', ['unavailable', 'changed', 'archived'])
def test_interrupted_unknown_or_changed_storage_never_retries(case, monkeypatch, storage):
    c = case; c.queue()
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', lambda *a, **k: interrupt())
    with pytest.raises(RerunException): c.render()
    real_load = directory.load_directory
    def load(contract, revision=None, **kwargs):
        if storage == 'unavailable': raise OSError('unavailable')
        original = real_load(contract, revision, **kwargs)
        if revision is None:
            return replace(original, revision=original.revision + 1,
                           archived=storage == 'archived')
        return original
    monkeypatch.setattr(directory, 'load_directory', load)
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits',
                        lambda *a, **k: pytest.fail('Unproven storage must not write'))
    assert c.render() == (c.block, True)
    assert c.control['phase'] == 'terminal'


def test_report_only_ack_survives_pop_and_old_control_cannot_replace_new_intent(case, monkeypatch):
    c = case; c.queue('report_only')
    c.state.stop = ('pop', 'p_standing_recovery')
    with pytest.raises(RerunException): c.render()
    assert c.control['phase'] == 'terminal'
    result, pending = c.render()
    assert not pending and ui._contact_pending_marker(c.draft) not in result.references
    assert directory.load_directory(c.profile.contract).revision == c.original.revision
    newer = dict(c.control, generation='new', phase='queued', action='retry')
    c.state['p_standing_action'] = newer
    c.queue('report_only', owner=c.control)
    assert newer['action'] == 'retry' and newer['phase'] == 'queued'


def test_concurrent_changed_contact_after_resume_proof_remains_cas_guarded(case, monkeypatch):
    c = case; c.queue()
    real = directory.automatically_keep_directory_contact_edits
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', lambda *a, **k: interrupt())
    with pytest.raises(RerunException): c.render()
    def racing_writer(*a, **k):
        current = directory.load_directory(c.profile.contract)
        changed = replace(current.sites[0], contacts=(replace(current.sites[0].contacts[0], phone='other actor'),))
        directory.save_directory(c.profile.contract, (changed, *current.sites[1:]),
            expected_revision=current.revision, actor='Other synthetic actor', confirmed=True)
        return real(*a, **k)
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits', racing_writer)
    result, pending = c.render()
    assert pending and result.rows[0][3] == '202-555-0175'
    assert directory.load_directory(c.profile.contract).sites[0].contacts[0].phone == 'other actor'
    assert directory.load_directory(c.profile.contract).revision == c.original.revision + 1
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits',
                        lambda *a, **k: pytest.fail('Failed CAS must not auto-retry'))
    assert c.render()[1]


def test_interrupted_baseline_requires_matching_directory_identity(case):
    c = case
    altered = replace(c.before, references=tuple(
        ref.replace('directory:', 'directory:wrong-', 1) if ref.startswith('directory:') else ref
        for ref in c.before.references))
    assert not ui._contact_retry_baseline_unchanged(c.draft, altered)


def test_queued_retry_with_unavailable_baseline_reoffers_usable_report_only(case, monkeypatch):
    c = case; c.queue()
    c.state.pop('p_standing_recovery')
    monkeypatch.setattr(directory, 'load_directory', lambda *a, **k: (_ for _ in ()).throw(OSError('unavailable')))
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits',
                        lambda *a, **k: pytest.fail('Unavailable baseline must not write'))
    assert c.render() == (c.block, True)
    assert c.control['phase'] == 'terminal'
    fresh = c.state['p_standing_action']
    assert fresh['phase'] == 'offered' and fresh is not c.control
    c.queue('report_only', owner=fresh)
    result, pending = c.render()
    assert not pending and result.rows == c.block.rows


def test_success_ack_before_cleanup_survives_later_unavailable_readback(case, monkeypatch):
    c = case; c.queue()
    c.state.stop = ('pop', 'p_standing_recovery')
    with pytest.raises(RerunException): c.render()
    assert c.control['phase'] == 'terminal' and not c.control['result'][1]
    monkeypatch.setattr(directory, 'load_directory', lambda *a, **k: (_ for _ in ()).throw(OSError('unavailable')))
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits',
                        lambda *a, **k: pytest.fail('Acknowledged success must not write twice'))
    result, pending = c.render()
    assert not pending and result.source == 'Library' and result.rows[0][3] == '202-555-0175'


def test_queued_action_cannot_edit_newer_expected_block(case, monkeypatch):
    c = case; c.queue()
    newer = replace(c.block, rows=((*c.block.rows[0][:3], 'newer pending', c.block.rows[0][4]), *c.block.rows[1:]))
    monkeypatch.setattr(directory, 'automatically_keep_directory_contact_edits',
                        lambda *a, **k: pytest.fail('Stale expected block must not write'))
    result, pending = ui._recover_contact_correction(c.draft, newer, 'p')
    assert pending and result == newer
    assert any('changed after this recovery choice' in text for text in c.messages)
    assert c.state['p_standing_action']['expected'] == newer
    c.queue(owner=c.control)
    assert c.state['p_standing_action']['phase'] == 'offered'
