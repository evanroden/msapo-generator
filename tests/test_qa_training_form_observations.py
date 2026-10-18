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
const form={contains:()=>true,querySelector:()=>date};
const makeInput=()=>({isConnected:true,value:'Private filter',getAttribute:()=> 'false',
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
 closest:s=>s.includes('button')?remove:container};
handlers.pointerdown({type:'pointerdown',target:remove,isTrusted:true});
selected=[];mutation();
const loss=observation.capture();
assert.equal(loss.events[0].removeExpected,true);assert.equal(loss.events[1].type,'mutation');
assert.equal(loss.events[1].selected.length,0);assert.equal(loss.state.originalConnected,true);
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
    subprocess.run(["node", "-e", code, str(script)], check=True, capture_output=True, text=True)


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
