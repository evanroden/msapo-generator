"""Passive receipts distinguish native change, wire delivery and server replay."""
from hashlib import sha256
import json
import subprocess
from types import SimpleNamespace

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.qa_monthly_site_pointer import FIRST, SECOND, SiteTailEvidence, TAIL_CLIENT


class Page:
    def __init__(self):
        self.listeners, self.evaluations = {}, []

    def on(self, kind, callback):
        self.listeners[kind] = callback

    def evaluate(self, expression):
        self.evaluations.append(expression)


class Context:
    def __init__(self):
        self.calls = []
        self.tracing = SimpleNamespace(start=lambda **kw: self.calls.append(('start', kw)),
                                       stop=lambda **kw: self.calls.append(('stop', kw)))

    def add_init_script(self, script):
        self.script = script


def observer(tmp_path):
    context, page, record = Context(), Page(), {}
    return SiteTailEvidence(context, page, tmp_path / 'webkit-keyboard', record), context, page, record


def checkbox(identifier='real-native-site', label=FIRST, *, value=False, assigned=False, cached=''):
    msg = ForwardMsg(hash=cached)
    widget = msg.delta.new_element.checkbox
    widget.id, widget.label = identifier, label
    widget.default, widget.value, widget.set_value = False, value, assigned
    msg.metadata.delta_path.extend([1, 2])
    return msg.SerializeToString()


def test_native_bool_delivery_is_bound_to_known_site_without_other_values(tmp_path):
    obs, _, _, _ = observer(tmp_path)
    obs.message('received', ForwardMsg(new_session={'script_run_id': 'server-run-before-tail'}).SerializeToString(), 1)
    obs.message('received', checkbox(cached='server-checkbox'), 1)
    assert obs.rows == []  # Learn IDs quietly; native initial activation is unchanged.
    obs.start()
    msg = BackMsg()
    msg.rerun_script.fragment_id = 'actual-fragment'
    msg.rerun_script.widget_states.widgets.add(id='real-native-site', bool_value=False)
    msg.rerun_script.widget_states.widgets.add(id='other-checkbox', bool_value=True)
    msg.rerun_script.widget_states.widgets.add(id='private-text', string_value='unrelated human text')
    obs.message('sent', msg.SerializeToString(), 1)
    row = obs.rows[-1]['detail']
    assert row['fragment'] == 'actual-fragment'
    assert row['widgets'] == [{'label': FIRST, 'id_hash': sha256(b'real-native-site').hexdigest(), 'checked': False}]
    assert obs.known['real-native-site']['run'] == 'server-run-before-tail'
    retained = json.dumps(obs.rows)
    for private in ('real-native-site', 'other-checkbox', 'private-text', 'unrelated human text'):
        assert private not in retained


def test_server_assignment_cached_reference_and_completed_run_remain_distinct(tmp_path):
    obs, _, _, _ = observer(tmp_path)
    obs.active = True
    obs.message('received', checkbox(value=True, assigned=True, cached='cached-checkbox'), 2)
    obs.message('received', ForwardMsg(ref_hash='cached-checkbox').SerializeToString(), 2)
    obs.message('received', ForwardMsg(new_session={'script_run_id': 'later-full-run'}).SerializeToString(), 2)
    obs.message('received', ForwardMsg(script_finished=ForwardMsg.FINISHED_SUCCESSFULLY).SerializeToString(), 2)
    rows = [r['detail'] for r in obs.rows]
    assert rows[0]['value'] is True and rows[0]['set_value'] is True
    assert rows[1]['reference'] == rows[0]
    assert rows[2]['run'] == 'later-full-run' and rows[2]['fragments'] == []
    assert rows[3]['kind'] == 'script_finished'


def test_port_matches_only_first_site_fixture_and_keeps_both_frame_listeners(tmp_path):
    obs, _, page, _ = observer(tmp_path)
    calls = []
    page.listeners['websocket'](SimpleNamespace(url='ws://127.0.0.1:8526/_stcore/stream',
                                               on=lambda *args: calls.append(args)))
    assert [kind for kind, _ in calls] == ['framereceived', 'framesent']
    for address in ('ws://127.0.0.1:8542/_stcore/stream', 'ws://127.0.0.1:8520/_stcore/stream',
                    'wss://msapo-generator.onrender.com/_stcore/stream', 'ws://localhost:8526/_stcore/stream'):
        with pytest.raises(ValueError, match='synthetic localhost fixture'):
            page.listeners['websocket'](SimpleNamespace(url=address))


def test_malformed_unrelated_and_oversized_frames_do_not_pollute_tail(tmp_path):
    obs, _, _, _ = observer(tmp_path)
    obs.active = True
    for raw in ('not binary', b'\xff', b'x' * (4 * 1024 * 1024 + 1),
                checkbox(label='Unrelated site'), ForwardMsg(ref_hash='unseen').SerializeToString()):
        obs.message('received', raw, 1)
    assert obs.rows == [] and not obs.known
    for index in range(40):
        obs.message('received', checkbox(identifier=str(index), cached=str(index)), 1)
    assert len(obs.known) == len(obs.cache) == 32


def test_native_and_playwright_errors_are_unfiltered_even_before_tail(tmp_path):
    obs, _, page, record = observer(tmp_path)
    native = 'ResizeObserver loop completed with undelivered notifications.'
    message = {'kind': 'window-error', 'at': 42, 'detail': {'message': native, 'stack': ''}}
    page.listeners['console'](SimpleNamespace(text='ENFRA_SITE_TAIL ' + json.dumps(message)))
    page.listeners['pageerror'](RuntimeError('EncodingError: observed native failure'))
    assert record['browser_error_count'] == 2
    assert [row['kind'] for row in record['browser_errors']] == ['window-error', 'pageerror']
    assert record['browser_errors'][0]['message'] == native
    assert obs.active is False
    for _ in range(2100):
        obs._record('pageerror', {'message': native})
    assert len(obs.rows) == 2000 and len(obs.errors) == 200
    assert record['browser_error_count'] == 2102  # Count is not silently capped with payloads.


@pytest.mark.parametrize('stage', ['start', 'stop'])
def test_optional_trace_failure_cannot_mask_primary_assertion(tmp_path, stage):
    obs, context, page, record = observer(tmp_path)
    def unavailable(**kwargs):
        raise RuntimeError('Trace unavailable')
    setattr(context.tracing, stage, unavailable)
    with pytest.raises(AssertionError, match='first native assertion'):
        try:
            obs.start()
            raise AssertionError('first native assertion')
        finally:
            obs.finish()
    assert [d['stage'] for d in record['diagnostic_errors']] == ['trace-' + stage]
    assert page.evaluations == ['window.__enfraSiteTail.arm()', 'window.__enfraSiteTail.stop()']
    events = tmp_path / 'webkit-keyboard-events.jsonl'
    assert events.exists() and all(json.loads(line) for line in events.read_text().splitlines())
    if stage == 'start':
        assert context.calls == []


def test_client_observes_trusted_delivery_same_node_and_replacement_without_mutating():
    # A deterministic DOM double executes the actual passive listener. No browser,
    # server, framework event, synthetic report input or runtime patch is used.
    program = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
function setup(port){
 const listeners={},events=[],inputs=[];
 const document={activeElement:null,addEventListener:(k,fn,options)=>{
   assert.equal(options.capture,true);assert.equal(options.passive,true);listeners[k]=fn},
   querySelector:s=>s.includes('stApp')?{getAttribute:()=> 'notRunning'}:
      s.includes('identity_sites')?{textContent:'Combined report: two sites'}:null,
   querySelectorAll:()=>inputs};
 const window={};const context={location:{hostname:'127.0.0.1',port},document,window,
   performance:{timeOrigin:900,now:()=>42},console:{debug:text=>events.push(JSON.parse(text.slice(16)))},
   addEventListener:(k,fn,options)=>{assert.equal(options.passive,true);listeners[k]=fn}};
 vm.runInNewContext(source,context);
 function input(name){
   const node={tagName:'INPUT',id:'native-dom',isConnected:true,checked:true,disabled:false,
     getAttribute:()=>name,matches:()=>true};
   node.closest=()=>({querySelector:()=>node});return node;
 }
 return {listeners,events,inputs,window,document,input};
}
assert.equal(setup('8542').window.__enfraSiteTail,undefined);
const env=setup('8526'),node=env.input('United Memorial Medical Center');env.inputs.push(node);
const event={target:node,isTrusted:true,preventDefault:()=>{throw Error('prevented')},
 stopPropagation:()=>{throw Error('stopped')}};
env.listeners.change(event);assert.equal(env.events.length,0);
env.window.__enfraSiteTail.arm();env.listeners.pointerdown(event);node.checked=false;
env.listeners.change(event);env.listeners.input(event);
const native=env.events.filter(x=>x.kind==='native-event');
assert.equal(native.length,3);assert.equal(native[0].detail.trusted,true);
assert.equal(native[0].detail.input.node,native[1].detail.input.node);
assert.equal(native[0].detail.input.checked,true);assert.equal(native[1].detail.input.checked,false);
assert.equal(native[1].detail.fullRender,null);assert.equal(native[1].detail.running,'notRunning');
node.isConnected=false;const replacement=env.input('United Memorial Medical Center');
env.inputs[0]=replacement;env.listeners.click({...event,target:replacement});
assert.notEqual(env.events.at(-1).detail.input.node,native[0].detail.input.node);
assert.equal(node.checked,false);assert.equal(replacement.checked,true);
env.window.__enfraSiteTail.stop();const n=env.events.length;env.listeners.change(event);
assert.equal(env.events.length,n);
env.listeners.error({message:'ResizeObserver loop completed with undelivered notifications.'});
assert.equal(env.events.at(-1).kind,'window-error');
assert.match(env.events.at(-1).detail.message,/ResizeObserver/);
"""
    result = subprocess.run(['node', '-e', program], input=json.dumps(TAIL_CLIENT),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
