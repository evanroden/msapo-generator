"""Passive diagnostics retain first participant loss without editing the form."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def test_form_observation_records_native_removal_identity_and_bounded_private_values():
    script = Path(__file__).parents[1] / "scripts/qa_training_form_observations.js"
    code = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const handlers={}, removed=[]; let mutation,selected=[],input,clock=0;
const container={dataset:{testid:'stMultiSelect'},querySelectorAll(){return selected}};
const date={value:'2026/09/15'};
const form={contains:target=>!target.external,querySelector:()=>date};
let controls='participant-popup';
const makeInput=()=>({isConnected:true,value:'Private filter',getAttribute:name=>name==='aria-controls'?controls:'false',
 closest:s=>s.includes('stForm')?form:container});
const original=input=makeInput();
const document={querySelector:s=>s.startsWith('input')?input:
 s==='.epc-workspace'?{dataset:{epcFullRender:'one'}}:{getAttribute:()=> 'notRunning'},
 addEventListener(type,handler,options){assert.equal(options.capture,true);assert.equal(options.passive,true);handlers[type]=handler},
 removeEventListener(type,handler,capture){assert.equal(handler,handlers[type]);assert.equal(capture,true);removed.push(type)}};
const context={document,window:{},performance:{now:()=>++clock},
 MutationObserver:class {constructor(callback){mutation=callback}observe(target,options){assert.equal(target,form);assert.equal(options.subtree,true)}disconnect(){}}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const observation=context.window.__enfraTrainingFormObservation;
assert.equal(observation.capture().state.selected.length,0);
selected=[{textContent:'Synthetic Person North'}];mutation();
const selectedState=observation.capture();
assert.equal(selectedState.state.selected[0],'expected-participant');
const remove={tagName:'BUTTON',getAttribute:name=>name==='aria-label'?'Remove Synthetic Person North':null,
 closest:s=>s.includes('button')?remove:s.includes('stMultiSelect')?container:null};
handlers.pointerdown({type:'pointerdown',target:remove,isTrusted:true});
selected=[];mutation();
const loss=observation.capture();
assert.equal(loss.events[0].removeExpected,true);assert.equal(loss.events[1].type,'mutation');
assert.equal(loss.events[1].selected.length,0);assert.equal(loss.state.originalConnected,true);
const popup={id:'participant-popup'},otherPopup={id:'unrelated-popup'};
const makeOption=(owner,text)=>{const node={external:true,tagName:'DIV',textContent:text,
 getAttribute:name=>name==='role'?'option':null,
 closest:s=>s==='[role="listbox"]'?owner:s.includes('[role="option"]')?node:null};return node;};
const option=makeOption(popup,'Synthetic Person North');
const otherOption=makeOption(otherPopup,'Private unrelated option');
handlers.pointerdown({type:'pointerdown',target:otherOption,isTrusted:true});
assert.equal(observation.capture().events.length,0);
handlers.pointerdown({type:'pointerdown',target:option,isTrusted:true,pointerType:'mouse',pressure:0.5,
 width:1,height:1,detail:0,button:0,buttons:1,defaultPrevented:false});
controls=null;
handlers.pointerup({type:'pointerup',target:option,isTrusted:true});
handlers.click({type:'click',target:option,isTrusted:true});
const optionEvents=observation.capture().events;
assert.deepEqual(Array.from(optionEvents,event=>event.type),['pointerdown','pointerup','click']);
assert.equal(optionEvents[0].participantOption,'expected-participant');
assert.equal(optionEvents[0].pressure,0.5);assert.equal(optionEvents[0].buttons,1);
assert.equal(optionEvents[0].defaultPreventedAtCapture,false);
handlers.click({type:'click',target:makeOption(popup,'Private unrelated option'),isTrusted:true});
const redactedOption=observation.capture();
assert.equal(redactedOption.events[0].participantOption,'other-participant');
assert.ok(!JSON.stringify(redactedOption).includes('Private'));
const unrelatedField={external:true,closest:s=>s.includes('stForm')?{id:'unrelated-form'}:null};
handlers.input({type:'input',target:unrelatedField,isTrusted:true});
assert.equal(observation.capture().events.length,0);
original.isConnected=false;input=makeInput();mutation();
const replaced=observation.capture().state;
assert.equal(replaced.originalConnected,false);assert.notEqual(replaced.participantNode,selectedState.state.participantNode);
selected=[{textContent:'Private unrelated person'}];mutation();
for(let i=0;i<150;i++)handlers.input({type:'input',target:remove,isTrusted:true});
const bounded=observation.capture();assert.equal(bounded.events.length,120);assert.ok(bounded.dropped>0);
assert.ok(!JSON.stringify(bounded).includes('Private'));assert.equal(bounded.state.selected[0],'other-participant');
observation.dispose();assert.equal(removed.length,8);
'''
    # The fake native nodes expose no focus, input, scroll or dispatch methods.
    # Observation must work with read-only access and passive listeners only.
    result = subprocess.run(["node", "-e", code, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_retention_assertion_keeps_first_loss_and_does_not_retry_or_restore():
    source = Path(__file__).parents[1] / "scripts/qa_monthly_training_date.py"
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "capture_form")
    evidence = {}
    namespace = {"live": SimpleNamespace(EVIDENCE=evidence)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    class Page:
        calls = 0
        def evaluate(self, expression):
            self.calls += 1
            return {"state": {"selected": []}, "events": [{"type": "mutation"}]}
    page = Page()
    with pytest.raises(AssertionError, match="lost at after-typed-date"):
        namespace["capture_form"](page, "after-typed-date", require_participant=True)
    assert page.calls == 1
    assert evidence["form_retention"][0]["observation"]["events"] == [{"type": "mutation"}]
