from types import SimpleNamespace
import importlib
import json
from pathlib import Path
import pytest
from scripts import qa_simplicity_delivery as diagnostic

def broken(*args):
    raise RuntimeError('broken diagnostic')

def test_wrapper_preserves_arguments_result_exception_and_broken_sink():
    calls=[]; value=object()
    def native(*args,**kwargs):
        calls.append((args,kwargs)); return value
    wrapped=diagnostic.trace(native,lambda:{},broken,'test')
    assert wrapped(1, test=2) is value
    assert calls==[((1,),{'test':2})]
    error=ValueError('native')
    def fail(): raise error
    with pytest.raises(ValueError) as caught:
        diagnostic.trace(fail,lambda:{},broken,'test')()
    assert caught.value is error

def test_import_and_unflagged_install_do_not_patch_product(monkeypatch):
    import streamlit as st
    from app import monthly_report_guided as guided
    button,render=st.button,guided._render_ordered_section
    importlib.reload(diagnostic)
    monkeypatch.delenv('EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS',raising=False)
    diagnostic.install(st,guided)
    assert (st.button,guided._render_ordered_section)==(button,render)
    fresh=Path('tests/fixtures/workspaces/monthly_fresh_app.py').read_text()
    assert 'qa_simplicity_delivery' not in fresh

def test_flag_without_synthetic_marker_refuses_install(monkeypatch,tmp_path):
    for key in ('EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS','EPC_MONTHLY_DOM_FIXTURE','EPC_MONTHLY_FRESH_TASK','EPC_MONTHLY_SIMPLICITY_TASK'):
        monkeypatch.setenv(key,'1')
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    st=SimpleNamespace(button=lambda:None)
    guided=SimpleNamespace(_render_ordered_section=lambda:None)
    original=st.button
    with pytest.raises((ValueError,AssertionError)):
        diagnostic.install(st,guided)
    assert st.button is original

def test_install_targeted_idempotent_and_native_callback_once(monkeypatch):
    monkeypatch.setattr(diagnostic,'allowed',lambda:True)
    registrations=[]; calls=[]; rows=[]
    def native_button(*args,**kwargs): registrations.append((args,kwargs));return 'unchanged'
    def render(*args,**kwargs): calls.append(('render',args,kwargs)); return 7
    st=SimpleNamespace(button=native_button,session_state={})
    guided=SimpleNamespace(_render_ordered_section=render)
    diagnostic.install(st,guided,rows.append)
    installed=st.button; diagnostic.install(st,guided,broken)
    assert st.button is installed
    def accept_workorders(*args,**kwargs): calls.append(('callback',args,kwargs));return 9
    accept_workorders.__module__='app.monthly_report_upload_ui'
    assert st.button('Add totals to summary',on_click=accept_workorders,key='secret',args=(3,))=='unchanged'
    assert registrations[-1][1]['args']==(3,)
    assert registrations[-1][1]['on_click'](3,x=4)==9
    assert calls==[('callback',(3,),{'x':4})]
    assert [r['phase'] for r in rows]==['before','after']
    st.button('Other action',on_click=accept_workorders)
    assert registrations[-1][1]['on_click'] is accept_workorders
    assert guided._render_ordered_section(None,SimpleNamespace(key='training'),x=2)==7
    assert len(rows)==2

def test_hashed_wire_keeps_false_and_true_distinct_without_payloads():
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    observer=diagnostic.Wire()
    msg=ForwardMsg();msg.delta.new_element.button.id='secret-button';msg.delta.new_element.button.label='Add totals to summary'
    observer.message('received',msg.SerializeToString())
    for pressed in (False,True):
        msg=BackMsg();msg.rerun_script.widget_states.widgets.add(id='secret-button').trigger_value=pressed
        msg.rerun_script.widget_states.widgets.add(id='secret-editor').string_value='secret report words'
        observer.message('sent',msg.SerializeToString())
    assert [r['actions'][0]['pressed'] for r in observer.rows[1:]]==[False,True]
    assert 'secret' not in json.dumps(observer.rows)
    for _ in range(300): observer.message('sent',msg.SerializeToString())
    assert len(observer.rows)==diagnostic.LIMIT

def test_snapshot_hashes_pending_report_values():
    draft=SimpleNamespace(fingerprint='secret report',profile=SimpleNamespace(key='secret profile'),period=SimpleNamespace(key='secret month'),blocks=(),sources=())
    state={'report_guided_secret_draft':draft,'report_guided_secret_pending_accepted_workorders':{'text':'secret words','scope':'secret key'}}
    result=diagnostic.snapshot(state)
    assert result[0]['pending'] is True
    assert 'secret' not in json.dumps(result)

def test_harness_keeps_exact_native_click_and_strict_expectation():
    source=Path('scripts/qa_monthly_simplicity.py').read_text()
    assert 'page.get_by_role("button", name="Add totals to summary", exact=True).click()\n        expect(page.locator(PANEL)).not_to_be_visible()' in source
    assert 'force=True' not in source
    assert 'context.tracing.start(screenshots=False, snapshots=False, sources=False)' in source

def test_trace_allowlist_removes_upload_bytes_widget_keys_and_raw_archive(tmp_path):
    from zipfile import ZipFile
    path=tmp_path/'trace.zip'
    with ZipFile(path,'w') as archive:
        archive.writestr('test.trace',json.dumps({'type':'before','callId':'secret-call','startTime':1,'method':'setInputFiles','params':{'buffer':'secret-bytes','selector':'secret-widget-key'}})+'\n'+json.dumps({'type':'after','callId':'secret-call','endTime':2,'result':'secret-result'}))
        archive.writestr('resources/secret','secret body')
    rows=diagnostic.safe_trace(path)
    assert len(rows['pairs'])==1 and rows['pairs'][0]['method']=='setInputFiles'
    assert rows['pairs'][0]['before']=={'startTime':1}
    assert rows['pairs'][0]['after']=={'endTime':2}
    assert rows['truncated'] is False
    assert 'secret' not in json.dumps(rows)
    assert not path.exists()


def test_trace_nonactions_do_not_spend_budget_and_overflow_is_explicit(tmp_path):
    from zipfile import ZipFile
    path=tmp_path/'trace.zip'
    events=[]
    for i in range(250):
        events.extend([{'type':'before','callId':f'noise-{i}','method':'expect'},
                       {'type':'after','callId':f'noise-{i}'}])
    for i in range(100):
        events.extend([{'type':'before','callId':f'action-{i}','method':'click','startTime':i},
                       {'type':'after','callId':f'action-{i}','endTime':i+1}])
    with ZipFile(path,'w') as archive:
        archive.writestr('test.trace','\n'.join(map(json.dumps,events)))
    result=diagnostic.safe_trace(path)
    assert len(result['pairs'])==96
    assert result['pairs'][0]['call']==diagnostic.digest('action-0')
    assert result['overflow_calls']==4 and result['truncated'] is True
    assert result['unpaired_calls']==0
    assert all(p['method']=='click' and 'before' in p and 'after' in p for p in result['pairs'])


def test_diagnostic_workflow_optin_is_only_on_existing_native_step():
    from hashlib import sha256
    source=Path('.github/workflows/monthly-simplicity.yml').read_text()
    addition="        env:\n          EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS: '1'\n"
    anchor='      - name: First intake and repeated Training without hidden disclosure clicks\n'
    assert source.count('EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS')==1
    assert anchor+addition+'        timeout-minutes: 11' in source
    # Removing exactly this step-local opt-in restores the entire base workflow,
    # including commands, permissions, triggers, budgets and artifact settings.
    assert sha256(source.replace(addition,'',1).encode()).hexdigest()=='bd0bd3522b1ba5f7a8eb21fa65623453bbf6cefa116e47e831273ec56d0cae69'
    assert not any('qa_simplicity_delivery' in p.read_text() for p in Path('app').glob('*.py'))
    assert 'EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS' not in Path('tests/fixtures/workspaces/monthly_fresh_app.py').read_text()
