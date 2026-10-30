"""Pinned native queue repair and row preservation; not browser input proof.

Compile the installer's exact repaired bytes in memory. Never mutate the
installed dependency or real report data to test its native queue behavior.
"""
from copy import deepcopy
import json

import pytest
from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.runtime.scriptrunner_utils import script_requests as requests
from test_work_order_imported_rows import current, launch, native_rows
from test_work_order_row_insertion import ABOVE, BLANK, COMPACT, wire


@pytest.fixture(autouse=True)
def candidate_in_memory_only(monkeypatch):
    from scripts.streamlit_string_trigger_coalescing import repaired_source
    from pathlib import Path
    original = Path(requests.__file__).read_bytes()
    namespace = dict(requests.__dict__)
    exec(compile(repaired_source(original, installed_version="1.61.1"),
                 "<local-owner-handoff-candidate>", "exec"), namespace)
    monkeypatch.setattr(requests, '_coalesce_widget_states', namespace['_coalesce_widget_states'])


def states(*widgets):
    result = WidgetStates()
    for widget in widgets:
        result.widgets.add(**widget)
    return result


def trigger(payload='{"row":0,"label":"Insert blank above"}', ident='current-row-action'):
    return {'id': ident, 'string_trigger_value': {'data': payload}}


def queued(*messages, fragments=None):
    queue = requests.ScriptRequests()
    for index, message in enumerate(messages):
        assert queue.request_rerun(requests.RerunData(widget_states=message,
            fragment_id=fragments[index] if fragments else None))
    return queue.on_scriptrunner_yield(), queue


def by_id(message):
    return {widget.id: widget for widget in message.widgets}


def test_real_request_queue_retains_row_trigger_before_separate_grid_edit():
    action = states({'id':'visible', 'bool_value':True}, trigger())
    edit = states({'id':'visible', 'bool_value':True},
                  {'id':'grid','string_value':'{"edited_rows":{"0":{"Work orders":"Received edited before insertion"}},"added_rows":[],"deleted_rows":[]}'})
    original_action, original_edit = deepcopy(action), deepcopy(edit)
    request, _ = queued(action, edit)
    output = by_id(request.rerun_data.widget_states)
    assert output['current-row-action'].string_trigger_value.data == trigger()['string_trigger_value']['data']
    assert output['grid'].string_value == edit.widgets[1].string_value
    assert output['visible'].bool_value
    assert action == original_action and edit == original_edit


def test_unset_new_string_trigger_does_not_erase_unconsumed_native_action():
    request, _ = queued(states(trigger()), states(trigger(None)))
    assert by_id(request.rerun_data.widget_states)['current-row-action'].string_trigger_value.data == trigger()['string_trigger_value']['data']


def test_newer_action_for_same_widget_wins_without_replaying_old_payload():
    newer='{"row":3,"label":"Insert blank below"}'
    request, _ = queued(states(trigger()), states(trigger(newer)))
    assert by_id(request.rerun_data.widget_states)['current-row-action'].string_trigger_value.data == newer


def test_changed_widget_type_never_resurrects_old_trigger():
    request, _ = queued(states(trigger()), states({'id':'current-row-action','string_value':'replacement field'}))
    assert by_id(request.rerun_data.widget_states)['current-row-action'].string_value == 'replacement field'


def test_empty_old_string_trigger_is_not_added_to_new_snapshot():
    request, _ = queued(states(trigger(None)), states({'id':'grid','string_value':'newest'}))
    assert set(by_id(request.rerun_data.widget_states)) == {'grid'}


@pytest.mark.parametrize('family,payload', [('trigger_value',True),('chat_input_value',{'data':'chat'})])
def test_existing_trigger_families_and_latest_nontrigger_values_remain(family,payload):
    old=states({'id':'button',family:payload}, {'id':'grid','string_value':'older'})
    new=states({'id':'grid','string_value':'newest'})
    request, _=queued(old,new)
    output=by_id(request.rerun_data.widget_states)
    assert output['button']==old.widgets[0]
    assert output['grid']==new.widgets[0]


def test_consumed_request_does_not_leak_trigger_to_a_later_rerun():
    first, queue=queued(states(trigger()),states({'id':'grid','string_value':'edit'}))
    assert 'current-row-action' in by_id(first.rerun_data.widget_states)
    assert queue.on_scriptrunner_yield() is None
    assert queue.request_rerun(requests.RerunData(widget_states=states({'id':'grid','string_value':'later'})))
    later=queue.on_scriptrunner_yield()
    assert set(by_id(later.rerun_data.widget_states))=={'grid'}


def test_full_run_and_scope_metadata_are_not_replaced_by_fragment_queue():
    old=states(trigger())
    new=states({'id':'grid','string_value':'newest'})
    request, _=queued(old,new,fragments=['preview',None])
    assert request.rerun_data.fragment_id_queue==[]
    assert 'current-row-action' in by_id(request.rerun_data.widget_states)


def test_real_row_callback_gets_coalesced_action_and_edit_once_without_source_loss():
    app=launch(COMPACT)
    original=app.session_state['block']
    proto=app.dataframe[0].proto
    action=states(trigger(ident=next(iter(proto.button_click_widgets.values()))))
    edit=states({'id':proto.id,'string_value':json.dumps({'edited_rows':{'0':{'Work orders':'Received edited before insertion'}},'added_rows':[],'deleted_rows':[]})})
    request,_=queued(action,edit,action,edit)
    app._run(request.rerun_data.widget_states)
    assert not app.exception
    expected=(BLANK,('Received edited before insertion',*COMPACT.rows[0][1:]),*COMPACT.rows[1:])
    assert current(app).rows==expected
    assert current(app).columns==COMPACT.columns
    assert current(app).reference==COMPACT.reference
    assert native_rows(current(app))==(COMPACT.columns,*expected)
    assert app.session_state['block'].extra_tables[1:]==original.extra_tables[1:]
    wire(app) # Canonical acknowledgement must not replay the consumed action.
    assert current(app).rows==expected
    app._run(action) # The retired callback cannot insert into a rebased occurrence.
    assert not app.exception and current(app).rows==expected


def runtime_source():
    """Use a verified pristine fixture even after the real installer has run."""
    from hashlib import sha256
    from pathlib import Path
    from scripts import streamlit_string_trigger_coalescing as repair
    raw = Path(requests.__file__).read_bytes()
    if sha256(raw).hexdigest() == repair.REPAIRED_SHA256:
        raw = raw.replace(repair.ADDED_IMPORT, b'', 1).replace(repair.ADDED_TRIGGER, b'', 1)
    assert sha256(raw).hexdigest() == repair.SOURCE_SHA256
    return raw


def test_runtime_only_changes_trigger_complete_adaptive_browser_workflow():
    from pathlib import Path
    import re

    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    sections = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    for event in ('push', 'pull_request'):
        assert {'scripts/streamlit_string_trigger_coalescing.py',
                'tests/test_streamlit_string_trigger_coalescing.py'} <= set(
            re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))


@pytest.mark.parametrize('already_installed', [False, True])
def test_installer_changes_only_two_pinned_lines_and_is_idempotent(tmp_path, already_installed):
    import stat
    from scripts import streamlit_string_trigger_coalescing as repair
    path=tmp_path/repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original=runtime_source()
    expected=original.replace(repair.IMPORT,repair.IMPORT+repair.ADDED_IMPORT,1).replace(repair.TRIGGER,repair.TRIGGER+repair.ADDED_TRIGGER,1)
    path.write_bytes(expected if already_installed else original)
    path.chmod(0o644)
    receipt=repair.patch_script_requests(tmp_path, installed_version='1.61.1')
    assert receipt['string_trigger_coalescing'] and receipt['already_patched'] == already_installed
    assert path.read_bytes()==expected
    assert stat.S_IMODE(path.stat().st_mode)==0o644
    assert repair.patch_script_requests(tmp_path,installed_version='1.61.1')['already_patched']
    assert path.read_bytes()==expected
    assert not list(path.parent.glob('.pending-enfra-trigger-*'))


@pytest.mark.parametrize('version,corruption',[('1.61.2',b''),('1.61.1',b'\n# different dependency\n')])
def test_unexpected_runtime_is_rejected_without_changing_bytes(tmp_path,version,corruption):
    from scripts import streamlit_string_trigger_coalescing as repair
    path=tmp_path/repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original=runtime_source()+corruption
    path.write_bytes(original)
    with pytest.raises(RuntimeError):repair.patch_script_requests(tmp_path,installed_version=version)
    assert path.read_bytes()==original
    assert not list(path.parent.glob('.pending-enfra-trigger-*'))


def test_changed_source_before_publish_is_not_overwritten(tmp_path,monkeypatch):
    from pathlib import Path
    from scripts import streamlit_string_trigger_coalescing as repair
    path=tmp_path/repair.RELATIVE_PATH
    path.parent.mkdir(parents=True)
    original=runtime_source()
    path.write_bytes(original)
    real_read=Path.read_bytes
    reads=0
    concurrent=original+b'\n# concurrent owner\n'
    def read(p):
        nonlocal reads
        if p==path:
            reads+=1
            if reads==2:path.write_bytes(concurrent)
        return real_read(p)
    monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises(RuntimeError,match='changed during installation'):
        repair.patch_script_requests(tmp_path,installed_version='1.61.1')
    assert path.read_bytes()==concurrent
    assert not list(path.parent.glob('.pending-enfra-trigger-*'))


@pytest.mark.parametrize('explicit_static',[False,True])
def test_existing_cli_installs_runtime_for_native_jobs_but_keeps_explicit_static_fixture_isolated(monkeypatch,tmp_path,capsys,explicit_static):
    from pathlib import Path
    import streamlit
    from scripts import patch_streamlit_frontend as frontend
    from scripts import streamlit_string_trigger_coalescing as repair
    import sys
    calls=[]
    monkeypatch.setattr(frontend,'version',lambda _:'1.61.1')
    monkeypatch.setattr(repair,'patch_script_requests',lambda root,**kw:calls.append(('runtime',root,kw)) or {'string_trigger_coalescing':True})
    monkeypatch.setattr(frontend,'patch_bundle',lambda root,**kw:calls.append(('frontend',root,kw)) or {'entry':'unchanged-entry'})
    monkeypatch.setattr(sys,'argv',['patch_streamlit_frontend.py']+(['--static-dir',str(tmp_path)] if explicit_static else []))
    frontend.main()
    receipt=json.loads(capsys.readouterr().out)
    assert receipt['entry']=='unchanged-entry'
    if explicit_static:
        assert [c[0] for c in calls]==['frontend']
        assert 'native_trigger_runtime' not in receipt
    else:
        assert [c[0] for c in calls]==['runtime','frontend']
        assert calls[0][1]==Path(streamlit.__file__).parent
        assert receipt['native_trigger_runtime']['string_trigger_coalescing']


def test_explicit_empty_string_is_newer_event_not_absent_trigger():
    # Optional proto data='' is present and distinct from data=None/unset.
    # Preserve a newer explicit clear; never resurrect the older row payload.
    request, queue = queued(states(trigger()), states(trigger('')),
                            states({'id': 'grid', 'string_value': 'latest edit'}))
    output = by_id(request.rerun_data.widget_states)
    assert output['current-row-action'].string_trigger_value.HasField('data')
    assert output['current-row-action'].string_trigger_value.data == ''
    assert output['grid'].string_value == 'latest edit'
    assert queue.on_scriptrunner_yield() is None


def test_consumed_boolean_and_string_triggers_do_not_replay_after_explicit_clear():
    first, queue = queued(states(trigger(), {'id': 'button', 'trigger_value': True}),
                          states({'id': 'grid', 'string_value': 'first edit'}))
    assert by_id(first.rerun_data.widget_states)['button'].trigger_value
    cleared = states(trigger(None), {'id': 'button', 'trigger_value': False})
    assert queue.request_rerun(requests.RerunData(widget_states=cleared))
    assert queue.request_rerun(requests.RerunData(widget_states=states({'id': 'grid', 'string_value': 'later edit'})))
    later = queue.on_scriptrunner_yield()
    assert set(by_id(later.rerun_data.widget_states)) == {'grid'}
    assert queue.on_scriptrunner_yield() is None
