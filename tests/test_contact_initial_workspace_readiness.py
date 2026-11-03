"""Initial fixture readiness is distinct from the deliberately held recovery gesture."""
import ast
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_compact_contact_journey.py'


def functions():
    return {n.name:n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef)}


def test_idle_fresh_receipt_does_not_admit_unclassified_workspace():
    funcs=functions()
    assert 'await_initial_workspace' in funcs
    expression=next(n.value for n in ast.walk(funcs['await_initial_workspace'])
                    if isinstance(n,ast.Constant) and isinstance(n.value,str) and '=>' in n.value)
    receipt=next(n.value for n in ast.walk(funcs['receipt'])
                if isinstance(n,ast.Constant) and isinstance(n.value,str) and '({after' in n.value)
    script=r'''
const assert=require('node:assert/strict');
const [source,old]=JSON.parse(require('fs').readFileSync(0,'utf8'));
const ready=eval('('+source+')'),receipt=eval('('+old+')');
let mode='',stamp='',classified=false,marker=false,row=false,editor=false,reference=false,pairs=[];
const pair={classList:{contains:()=>classified},querySelector:s=>s==='[data-epc-pair]'?marker:
 s==='.epc-workspace-row'?row:s==='.epc-workspace-editor'?editor:reference};
const root={dataset:{},classList:{contains:()=>classified},querySelectorAll:()=>pairs};
global.document={querySelector:s=>s.includes('stApp')?{getAttribute:()=> 'notRunning'}:
 s.includes('epc_workspace_monthly')?root:null,
 querySelectorAll:()=>[{dataset:{enfraContactReceipt:JSON.stringify({sequence:1,working:{},durable:{}})}}]};
assert.equal(receipt({after:0}),true);assert.equal(ready(),false);
root.dataset.epcMode='wide';root.dataset.epcFullRender='fresh';classified=true;
assert.equal(ready(),false); // An empty shell is not a ready fixture.
pairs=[pair];assert.equal(ready(),false);
marker=true;row=true;editor=true;assert.equal(ready(),false);
reference=true;assert.equal(ready(),true);
pairs.push({classList:{contains:()=>false}});assert.equal(ready(),false);
pairs.pop();root.dataset.epcMode='compact';assert.equal(ready(),false);
root.dataset.epcMode='wide';root.dataset.epcFullRender='';assert.equal(ready(),false);
'''
    subprocess.run(['node','-e',script],input=json.dumps([expression,receipt]),text=True,
                   capture_output=True,check=True,timeout=10)


def test_helper_only_observes_one_bounded_condition():
    node=functions().get('await_initial_workspace')
    assert node is not None
    namespace={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),namespace)
    page=Mock();namespace['await_initial_workspace'](page)
    page.wait_for_function.assert_called_once()
    assert page.wait_for_function.call_args.kwargs == {'timeout':30000}
    assert len(page.method_calls)==1
    text=ast.unparse(node)
    for forbidden in ['click(', 'sleep(', 'wait_for_timeout', 'dispatchEvent', '.focus(', 'scrollTo(']:
        assert forbidden not in text


def test_readiness_occurs_once_after_initial_receipt_before_outputs_only():
    source=SOURCE.read_text()
    assert source.count('await_initial_workspace(page)')==2 # definition + single call
    initial=source.index('baseline = receipt(page)')
    readiness=source.index('await_initial_workspace(page)',initial)
    assert initial<readiness<source.index("outputs('before', baseline)",initial)
    held=ast.unparse(functions()['edit_contact_during_recovery_rerun'])
    assert 'await_initial_workspace' not in held
    assert held.index('page.mouse.down()')<held.index('gate.release()')<held.index('page.mouse.up()')
