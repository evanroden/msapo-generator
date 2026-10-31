"""Actual QA helper control-flow contracts; not browser/hydration acceptance."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_text_hydration.py'


def helper(*, current='', pending='Saved issue', continued=True):
    calls = []
    class Field:
        value = current
        def input_value(self):
            calls.append('read'); return self.value
        def get_attribute(self, name):
            assert name == 'id'; calls.append('id'); return 'native-1'
        def fill(self, value):
            calls.append(('fill', value)); self.value = value
        def press(self, key):
            calls.append(('key', key))
        def evaluate(self, _):
            calls.append('continuity')
            return {'inputObserved':True,'sameNode':continued,'inputNodeConnected':continued}
    field = Field()
    class Page:
        def get_by_role(self, role, **kwargs):
            assert role=='textbox' and kwargs=={'name':'Issue description','exact':True}
            calls.append('locator'); return field
        def evaluate(self, script, *args):
            calls.append('cleanup' if script=='window.__enfraTextEditCleanup?.()' else 'observe')
    def expect(locator):
        assert locator is field
        def to_have_value(expected):
            calls.append(('expected', expected))
            # Simulate the browser's later controlled-value delivery; never a
            # helper action. A mismatch must stop the helper before any input.
            field.value = pending
            assert field.value == expected
        return SimpleNamespace(to_have_value=to_have_value)
    def acknowledged(page,label,value):
        calls.append('acknowledged'); assert page is target and field.value==value
    target = Page()
    live = SimpleNamespace(EVIDENCE={'phase':'Issue clear'}, event=lambda *a,**kw:calls.append('request'))
    node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='commit_text')
    ns={'expect':expect,'sha256':sha256,'live':live,'await_text':acknowledged,
        'TEXT_EDIT_OBSERVER':observer_script()}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),ns)
    return lambda text,expected:ns['commit_text'](target,'Issue description',text,expected_before=expected),calls


def test_pending_existing_value_is_established_before_any_native_edit_on_one_locator():
    run,calls=helper()
    run('', 'Saved issue')
    assert calls[:5]==['locator',('expected','Saved issue'),'read','request','id']
    assert calls.count('locator')==1
    assert [c for c in calls if isinstance(c,tuple)and c[0]in{'fill','key'}]==[('fill',''),('key','Tab')]
    assert calls[-3:]==['acknowledged','continuity','cleanup']


def test_missing_expected_value_stops_before_observer_and_native_action():
    run,calls=helper(pending='')
    with pytest.raises(AssertionError):run('', 'Saved issue')
    assert calls==['locator',('expected','Saved issue')]


def test_genuine_no_op_still_fails_before_native_input():
    run,calls=helper(pending='')
    with pytest.raises(AssertionError,match='must change'):run('', '')
    assert 'observe'not in calls
    assert not any(isinstance(c,tuple)and c[0]=='fill'for c in calls)


def test_replaced_input_event_node_still_fails_after_acknowledgment():
    run,calls=helper(continued=False)
    with pytest.raises(AssertionError,match='node was replaced'):run('', 'Saved issue')
    assert 'continuity'in calls and 'acknowledged'in calls


def native_edit_journey(*, fail_phase=None, reentry_focus=True, reentry_value=''):
    """Check the real harness sequence, not the app's callback correctness.

    Product AppTests cover consecutive callbacks and browser CI must provide
    native input, receipt, visible-value and original-node acceptance.
    """
    calls = []
    expected = {'Training notes': 'Saved training', 'Issue description': 'Saved issue'}
    values = dict(expected)
    current_phase = ''

    def phase(name):
        nonlocal current_phase
        current_phase = name

    def commit_text(page, label, text, *, expected_before):
        assert page is target
        assert values[label] == expected_before
        calls.append(('edit', label, expected_before, text))
        if current_phase == fail_phase:
            raise AssertionError('The exact requested edit was not acknowledged.')
        values[label] = text

    def await_text(page, label, text):
        assert page is target and values[label] == text
        calls.append(('reload acknowledgment', label, text))

    def checkpoint(name, passed):
        assert passed is True
        calls.append(('check', name))

    class Field:
        def click(self):
            calls.append(('native reentry click',))

    field = Field()

    class Page:
        def reload(self, **kwargs):
            calls.append(('reload', kwargs))

        def get_by_role(self, role, *, name, exact):
            assert role == 'textbox' and name == 'Issue description' and exact is True
            calls.append(('reentry locator', name))
            return field

        def set_viewport_size(self, size):
            calls.append(('viewport', size))

    def expect(locator):
        assert locator is field

        def to_be_focused():
            calls.append(('reentry focused',))
            assert reentry_focus, 'The native reentry click did not focus the editor.'

        def to_have_value(value):
            calls.append(('reentry value', value))
            assert value == '' and values['Issue description'] == value
            assert reentry_value == value, 'The reloaded native editor lost its empty value.'

        return SimpleNamespace(to_be_focused=to_be_focused, to_have_value=to_have_value)

    def correct_issue_warning(page, *, keyboard=False):
        assert page is target and values['Issue description'] == ''
        calls.append(('exact warning and Return', 'keyboard' if keyboard else 'pointer'))

    target = Page()
    nodes = [node for node in ast.parse(SOURCE.read_text()).body
             if isinstance(node, ast.FunctionDef) and node.name == 'exercise_text_edits']
    assert len(nodes) == 1, 'The native edit journey must expose its exact action sequence.'
    ns = {'EXPECTED': expected, 'phase': phase, 'commit_text': commit_text,
          'await_text': await_text, 'live': SimpleNamespace(checkpoint=checkpoint),
          'expect': expect, 'correct_issue_warning': correct_issue_warning}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return lambda: ns['exercise_text_edits'](target), calls


def test_native_edit_journey_retains_reload_checks_and_adds_consecutive_issue_edits():
    run, calls = native_edit_journey()
    run()
    reload = ('reload', {'wait_until': 'domcontentloaded'})
    assert calls == [
        ('edit', 'Training notes', 'Saved training', ''),
        reload,
        ('reload acknowledgment', 'Training notes', ''),
        ('check', 'Training notes deliberate clear survives reload'),
        ('edit', 'Training notes', '', 'Saved training'),
        reload,
        ('reload acknowledgment', 'Training notes', 'Saved training'),
        ('check', 'Training notes reentry survives reload'),
        ('edit', 'Issue description', 'Saved issue', ''),
        reload,
        ('reload acknowledgment', 'Issue description', ''),
        ('check', 'Issue description deliberate clear survives reload'),
        ('reentry locator', 'Issue description'),
        ('native reentry click',),
        ('reentry focused',),
        ('reentry value', ''),
        ('check', 'Issue description first native focus after reload preserves empty value'),
        ('exact warning and Return', 'pointer'),
        ('edit', 'Issue description', '', 'Saved issue'),
        ('edit', 'Issue description', 'Saved issue', ''),
        ('viewport', {'width': 390, 'height': 844}),
        ('exact warning and Return', 'keyboard'),
        ('viewport', {'width': 1365, 'height': 900}),
        ('edit', 'Issue description', '', 'Saved issue'),
        ('check', 'Issue description consecutive clear and reentry without reload'),
        reload,
        ('reload acknowledgment', 'Issue description', 'Saved issue'),
        ('check', 'Issue description reentry survives reload'),
    ]


@pytest.mark.parametrize('failure', ['focus', 'value'])
def test_native_reload_reentry_failure_stops_before_warning_or_further_edit(failure):
    run, calls = native_edit_journey(
        reentry_focus=failure != 'focus', reentry_value='Stale issue' if failure == 'value' else '')
    with pytest.raises(AssertionError, match='did not focus|lost its empty value'):
        run()
    assert calls.count(('native reentry click',)) == 1
    assert not any(call[0] == 'exact warning and Return' for call in calls)
    assert sum(call[0] == 'reload' for call in calls) == 3
    assert sum(call[0] == 'edit' for call in calls) == 3


def test_unacknowledged_consecutive_edit_stops_without_retry_or_reload():
    run, calls = native_edit_journey(fail_phase='Issue description consecutive clear and save')
    with pytest.raises(AssertionError, match='not acknowledged'):
        run()
    assert calls[-2:] == [
        ('edit', 'Issue description', '', 'Saved issue'),
        ('edit', 'Issue description', 'Saved issue', ''),
    ]
    assert sum(call[0] == 'reload' for call in calls) == 3
    assert sum(call[0] == 'edit' for call in calls) == 5


def observer_script():
    for node in ast.parse(SOURCE.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == 'TEXT_EDIT_OBSERVER'
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    pytest.fail('The native edit observer must retain passive acknowledgment timing.')


def observe_timing(scenario):
    """Execute the actual observer against deterministic DOM/event observations.

    This tests evidence ordering and cleanup, not native-browser acceptance.
    The fake targets reject any attempted value/focus mutation.
    """
    observer = observer_script()
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the passive observer contract tests.')
    setup = r"""
const assert = require('node:assert/strict');
let now = 0, scriptState = 'notRunning', receipt = null, invalidReceipt = null;
const listeners = new Map();
let observer;
const input = {id:'native-1', tagName:'TEXTAREA', isConnected:true,
    getAttribute:name => name==='aria-label' ? 'Issue description' : null,
    focus:() => {throw new Error('The observer must never change focus.');}};
Object.defineProperty(input, 'value', {get:() => '', set:() => {
    throw new Error('The observer must never write a field value.');
}});
globalThis.window = globalThis;
Object.defineProperty(globalThis, 'performance', {value:{now:() => now, timeOrigin:1000}});
globalThis.document = {
    documentElement:{}, activeElement:input,
    querySelector:selector => selector==='[data-testid="stApp"]'
        ? {getAttribute:() => scriptState} : {dataset:{epcFullRender:'fixture-1'}},
    querySelectorAll:() => receipt || invalidReceipt !== null
        ? [{dataset:{enfraTextReceipt:invalidReceipt ?? JSON.stringify(receipt)}}] : [],
    addEventListener:(kind, callback) => listeners.set(kind, callback),
    removeEventListener:(kind, callback) => {
        assert.equal(listeners.get(kind), callback); listeners.delete(kind);
    }
};
globalThis.MutationObserver = class {
    constructor(callback) {this.callback=callback; this.disconnected=false; observer=this;}
    observe(target, options) {assert.equal(target, document.documentElement); this.options=options;}
    disconnect() {this.disconnected=true;}
};
const emit = (kind, target=input) => listeners.get(kind)?.({type:kind, target, isTrusted:true});
const mutate = (records=[]) => {if(!observer.disconnected) observer.callback(records);};
const matching = () => ({working:{issues:['wanted']}, durable:{issues:['wanted']},
    working_fingerprint:'same', durable_fingerprint:'same', durable_revision:5});
const result = () => window.__enfraTextEdit.snapshot();
"""
    script = setup + '\n(' + observer + ")({label:'Issue description',sha:'wanted'});\n" + scenario
    completed = subprocess.run([node, '-'], input=script, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize('detach_first', [True, False])
def test_passive_observer_distinguishes_observed_detachment_and_exact_ack_order(detach_first):
    detach = 'input.isConnected=false; mutate();'
    ack = 'receipt=matching(); mutate();'
    first, second = (detach, ack) if detach_first else (ack, detach)
    result = observe_timing(
        "now=10; emit('input'); emit('change'); emit('blur');\n"
        + 'now=20; ' + first + '\nnow=30; ' + second
        + '\nconsole.log(JSON.stringify(result()));'
    )
    assert result['clock'] == 'performance.now'
    assert result['time_origin_ms'] == 1000
    assert result['first_input']['at_ms'] == 10
    assert result['first_detachment']['at_ms'] == (20 if detach_first else 30)
    assert result['first_matching_ack']['at_ms'] == (30 if detach_first else 20)
    assert result['first_matching_ack']['durable_revision'] == 5
    assert result['ordering'] == (
        'detachment_observed_before_ack' if detach_first else 'ack_observed_before_detachment'
    )


def test_same_observation_does_not_invent_detachment_ack_order():
    result = observe_timing("""
now=10; emit('input');
now=20; input.isConnected=false; receipt=matching(); mutate();
console.log(JSON.stringify(result()));
""")
    assert result['ordering'] == 'same_observation'
    assert result['first_detachment']['observation'] == result['first_matching_ack']['observation']


def test_ack_requires_first_input_both_hashes_fingerprint_and_settled_app():
    result = observe_timing("""
receipt=matching(); mutate(); assert.equal(result().first_matching_ack, null);
receipt=null; now=10; emit('input');
now=20; receipt=matching(); receipt.durable.issues=['wrong']; mutate();
assert.equal(result().first_matching_ack, null);
now=30; receipt=matching(); receipt.durable_fingerprint='different'; mutate();
assert.equal(result().first_matching_ack, null);
now=40; receipt=matching(); scriptState='running'; mutate();
assert.equal(result().first_matching_ack, null);
now=50; scriptState='notRunning'; mutate();
console.log(JSON.stringify(result()));
""")
    assert result['first_matching_ack']['at_ms'] == 50
    assert result['first_matching_ack']['script_state'] == 'notRunning'
    assert result['first_matching_ack']['working_sha'] == 'wanted'
    assert result['first_matching_ack']['durable_sha'] == 'wanted'


def test_observer_keeps_first_native_target_and_bounds_evidence_then_cleans_up():
    result = observe_timing("""
now=10; emit('input');
const later={...input,id:'native-2'};
for(let i=0;i<100;i++) {
    now=20+i; scriptState=i%2 ? 'running' : 'notRunning'; emit('input', later); mutate();
}
assert.equal(window.__enfraTextEdit.node, input);
assert.equal(window.__enfraTextEdit.events.length, 16);
now=130; input.isConnected=false; scriptState='notRunning'; receipt=matching(); mutate();
const captured=result();
window.__enfraTextEditCleanup();
assert.equal(listeners.size, 0); assert.equal(observer.disconnected, true);
console.log(JSON.stringify(captured));
""")
    assert result['first_input']['input_node_id'] == 'native-1'
    assert len(result['transitions']) <= 32
    assert result['transitions_truncated'] is True
    assert result['first_detachment']['at_ms'] == 130
    assert result['first_matching_ack']['at_ms'] == 130


def test_invalid_receipt_does_not_interrupt_observation_or_create_ack():
    result = observe_timing("""
now=10; emit('input'); now=20; invalidReceipt='{'; mutate();
assert.equal(result().first_matching_ack, null);
now=30; invalidReceipt=null; receipt=matching(); mutate();
console.log(JSON.stringify(result()));
""")
    assert result['receipt_parse_errors'] >= 1
    assert result['first_matching_ack']['at_ms'] == 30
