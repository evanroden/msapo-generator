"""The optional production sample observer cannot alter input or collect text."""
import json
from pathlib import Path
import subprocess

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_logo_recovery_sample as sample


def test_observer_registration_rejects_non_sample_context():
    with pytest.raises(ValueError, match="separate test area"):
        sample._input_observer()


def test_observer_can_be_enabled_and_rerendered_without_creating_records(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    app = AppTest.from_string('''
from app import monthly_report_logo_recovery_sample as sample
with sample.sample_scope('a'*32):
    sample.render_sample()
''').run()
    app.button('report_logo_sample_observe').click().run()
    assert not app.exception
    app.run()
    assert not app.exception
    assert not list(tmp_path.rglob('*.json'))


def test_observer_receipts_are_bounded_passive_and_disposed():
    source = Path('app/monthly_report_input_observation.js').read_text()
    code = r'''
const assert = require('node:assert/strict');
const source = JSON.parse(process.argv[1]);
class Element {constructor(tagName) {this.tagName=tagName;} closest() {return null;}}
const label = new Element('LABEL'), input = new Element('INPUT'), unrelated = new Element('INPUT');
label.contains = node => node === label || node === input;
input.closest = selector => selector === 'label' ? label : null;
Object.defineProperties(input, {
 checked:{get:()=>false, set(){throw Error('control write');}},
 disabled:{get:()=>false}, isConnected:{get:()=>true},
 value:{get(){throw Error('private value read');}},
});
Object.freeze(input);
let registrations = [], tasks = [], frames = new Map(), nextFrame = 1;
const panel = {textContent:''};
const document = {
 activeElement: input,
 querySelector(selector) {assert.match(selector,/Restore this collection/); return input;},
 addEventListener(type, handler, options) {
  assert.deepEqual(options,{capture:true,passive:true}); registrations.push({type,handler,options});
 },
 removeEventListener(type, handler, options) {
  registrations = registrations.filter(item => item.type !== type || item.handler !== handler || item.options !== options);
 },
};
const mount = new Function('document','Element','queueMicrotask','requestAnimationFrame','cancelAnimationFrame',
 'return ('+source.replace('export default ','')+');')(
 document,Element,fn=>tasks.push(fn),fn=>{let id=nextFrame++;frames.set(id,fn);return id;},id=>frames.delete(id));
const dispose = mount({parentElement:{querySelector(){return panel;}}});
const handler = registrations.find(item=>item.type==='click').handler;
const event = {type:'click',target:label,isTrusted:true,pointerType:'mouse',button:0,buttons:0,
 detail:1,width:1,height:1,pressure:0.5,defaultPrevented:false,
 get key(){throw Error('private key read');},
 preventDefault(){throw Error('input interference');},stopPropagation(){throw Error('input interference');}};
const first = panel.textContent;
const unrelatedEvent = Object.create(event); unrelatedEvent.target=unrelated;
handler(unrelatedEvent); assert.equal(panel.textContent,first);
handler(event);
event.defaultPrevented = true;
tasks.splice(0).forEach(fn=>fn());
let receipts = JSON.parse(panel.textContent);
assert.equal(receipts[1].defaultPrevented,false);
assert.equal(receipts[1].pressure,0.5);
assert.equal(receipts[2].defaultPrevented,true);
assert.equal(receipts[2].state.checked,false);
assert.equal(receipts[2].state.focusedControl,'restore-confirmation');
const pendingFrames = Array.from(frames.values()); frames.clear(); pendingFrames.forEach(fn=>fn());
assert.equal(JSON.parse(panel.textContent).at(-1).defaultPrevented,true);
for(let i=0;i<100;i++)handler(event);
receipts = JSON.parse(panel.textContent);
assert.equal(receipts.length,80);
assert.ok(receipts[0].sequence>1);
const before = panel.textContent;
dispose(); tasks.splice(0).forEach(fn=>fn());
assert.equal(panel.textContent,before);
assert.equal(registrations.length,0); assert.equal(frames.size,0);
'''
    result = subprocess.run(['node', '-e', code, json.dumps(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
