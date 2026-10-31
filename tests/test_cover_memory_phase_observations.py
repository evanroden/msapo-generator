from types import SimpleNamespace
import pytest
from scripts import workspace_cover_memory_phases as phases
from scripts import workspace_cover_service_observations as service


def test_no_context_wrapper_is_transparent(monkeypatch):
    owner=SimpleNamespace(call=lambda value:value)
    monkeypatch.setattr(phases,'_record',lambda label:pytest.fail('inactive trace'))
    phases._wrap(owner,'call','example')
    value=object();assert owner.call(value) is value


def test_marked_context_records_boundaries_and_preserves_original_exception(monkeypatch):
    labels=[];monkeypatch.setattr(phases,'_record',labels.append)
    error=RuntimeError('original')
    def fail():raise error
    owner=SimpleNamespace(call=fail);phases._wrap(owner,'call','example')
    marker=phases._ACTIVE.set(('base','token'))
    try:
        with pytest.raises(RuntimeError) as caught:owner.call()
        assert caught.value is error
    finally:phases._ACTIVE.reset(marker)
    assert labels==['example:before','example:after']


def test_unmarked_fixture_cannot_install(monkeypatch):
    def denied(*args):raise ValueError('unmarked')
    monkeypatch.setattr(service,'require',denied)
    monkeypatch.setattr(phases,'_install',lambda:pytest.fail('must not install'))
    with pytest.raises(ValueError,match='unmarked'):
        with phases.observe('base','token'):pass


def test_counter_limit_and_no_binary_content(monkeypatch,capsys):
    monkeypatch.setattr(service,'require',lambda *args:None)
    monkeypatch.setattr(phases,'_COUNT',255)
    marker=phases._ACTIVE.set(('base','token'))
    try:
        phases._record('native-registration:before')
        phases._record('native-registration:after')
    finally:phases._ACTIVE.reset(marker)
    output=capsys.readouterr().err
    assert output.count('COVER_MEMORY_PHASE ')==1 and len(output)<2048
    assert 'token' not in output and 'base' not in output


def test_initial_missing_namespace_skips_trace_install_then_context_resets(monkeypatch):
    def absent(*args):raise ValueError('History observations require an existing isolated namespace.')
    monkeypatch.setattr(service,'require',absent)
    monkeypatch.setattr(phases,'_install',lambda:pytest.fail('must wait for namespace'))
    with phases.observe('base','token'):
        assert phases._ACTIVE.get() is None
    assert phases._ACTIVE.get() is None


def test_valid_context_restores_after_error(monkeypatch):
    monkeypatch.setattr(service,'require',lambda *args:None)
    monkeypatch.setattr(phases,'_install',lambda:None)
    with pytest.raises(RuntimeError):
        with phases.observe('base','token'):
            assert phases._ACTIVE.get()==('base','token')
            raise RuntimeError('original')
    assert phases._ACTIVE.get() is None


@pytest.mark.parametrize('diagnostic_error',[ValueError('namespace reset'),OSError('output closed')])
def test_diagnostic_error_does_not_mask_action_error(monkeypatch,diagnostic_error):
    error=RuntimeError('action')
    def fail():raise error
    def unavailable(label):raise diagnostic_error
    monkeypatch.setattr(phases,'_record',unavailable)
    owner=SimpleNamespace(call=fail);phases._wrap(owner,'call','example')
    marker=phases._ACTIVE.set(('base','token'))
    try:
        with pytest.raises(RuntimeError) as caught:owner.call()
        assert caught.value is error
    finally:phases._ACTIVE.reset(marker)


@pytest.mark.parametrize('scope,generation,allowed',[
    ('current',None,True),('other',None,False),('current','stale',False)])
def test_prerender_lease_setup_only_current_scope_without_bound_generation(monkeypatch,scope,generation,allowed):
    from app import monthly_report_testing as testing
    from scripts import workspace_history_observations as history
    def mismatch(*args):raise ValueError('Cover service QA namespace mismatch')
    monkeypatch.setattr(service,'require',mismatch)
    monkeypatch.setattr(history,'namespace',lambda *args:('target','current','valid'))
    monkeypatch.setattr(testing,'scope',lambda:scope)
    monkeypatch.setattr(testing,'generation',lambda:generation)
    installed=[];monkeypatch.setattr(phases,'_install',lambda:installed.append(True))
    if allowed:
        with phases.observe('base','token'):assert phases._ACTIVE.get()==('base','token')
        assert installed==[True]
    else:
        with pytest.raises(ValueError,match='namespace mismatch'):
            with phases.observe('base','token'):pytest.fail('unauthorized context')
        assert not installed
    assert phases._ACTIVE.get() is None
