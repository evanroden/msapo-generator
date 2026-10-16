"""The fresh-month probe observes one native action without repairing it."""
import ast
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


SOURCE = Path(__file__).parents[1] / "scripts/qa_water_fresh_page_journey.py"


def select_function(monkeypatch, calls):
    tree = ast.parse(SOURCE.read_text())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "select")
    sync = ModuleType("playwright.sync_api")

    class Expect:
        def to_have_value(self, value):
            calls.append(("expect value", value))

    sync.expect = lambda _: Expect()
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["select"]


class Page:
    def __init__(self, calls, *, fail_at=None, cleanup_failure=False):
        self.calls, self.fail_at, self.cleanup_failure = calls, fail_at, cleanup_failure

    def get_by_role(self, role, *, name, exact):
        assert exact
        self.calls.append(("locate", role, name))
        page = self

        class Control:
            def evaluate(self, script):
                assert role == "combobox" and "new MutationObserver" in script
                page.calls.append(("install passive probe", name))
                return {"id": "original", "connected": True, "expanded": "false"}

            def click(self):
                page.calls.append(("click", role, name))
                if page.fail_at == role:
                    raise RuntimeError("Original native action failed")

        return Control()

    def evaluate(self, script):
        if "finish" in script:
            self.calls.append(("finish passive probe",))
            if self.cleanup_failure:
                raise ValueError("Diagnostic cleanup failed")
        else:
            assert "snapshot" in script
            self.calls.append(("read passive probe",))
        return {"id": "original", "connected": True, "expanded": "false"}


def test_probe_preserves_one_original_input_click_exact_option_and_value_assertion(monkeypatch):
    calls, record = [], {}
    select_function(monkeypatch, calls)(Page(calls), "Reporting month", "September", record=record)
    assert calls == [
        ("locate", "combobox", "Reporting month"), ("install passive probe", "Reporting month"),
        ("click", "combobox", "Reporting month"), ("read passive probe",),
        ("locate", "option", "September"), ("click", "option", "September"),
        ("expect value", "September"), ("finish passive probe",),
    ]
    assert set(record["month_activation"][0]) == {"requested_month", "before", "after_click", "final"}


@pytest.mark.parametrize("fail_at", ["combobox", "option"])
def test_primary_native_failure_survives_diagnostic_cleanup_failure(monkeypatch, fail_at):
    calls, record = [], {}
    with pytest.raises(RuntimeError, match="Original native action failed"):
        select_function(monkeypatch, calls)(Page(calls, fail_at=fail_at, cleanup_failure=True),
                                           "Reporting month", "September", record=record)
    assert calls[-1] == ("finish passive probe",)
    assert calls.count(("click", "combobox", "Reporting month")) == 1
    assert record["month_activation"][0]["cleanup_error"] == "Diagnostic cleanup failed"


def test_other_select_controls_keep_the_existing_action_sequence_without_probe(monkeypatch):
    calls, record = [], {}
    select_function(monkeypatch, calls)(Page(calls), "Reporting year", "2026", record=record)
    assert calls == [("locate", "combobox", "Reporting year"), ("click", "combobox", "Reporting year"),
                     ("locate", "option", "2026"), ("click", "option", "2026"), ("expect value", "2026")]
    assert record == {}


def test_actual_passive_javascript_retains_batched_open_close_and_bounds_without_native_writes():
    import json
    tree = ast.parse(SOURCE.read_text())
    install = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and "const events=[], mutations=[]" in node.value)
    # A DOM/observer contract model executes the actual probe source. It does
    # not launch a browser or claim to reproduce the native dropdown failure.
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const install=JSON.parse(fs.readFileSync(0,'utf8'));
const listeners=new Map();let observer,rectReads=0,clock=0;
const document={activeElement:null,querySelector:selector=>selector==='.epc-workspace'
  ?{dataset:{epcFullRender:'full-1'}}:{getAttribute:()=> 'notRunning'}};
const node={id:'native-1',isConnected:true,expanded:'false',getAttribute:name=>{
  assert.equal(name,'aria-expanded');return node.expanded;},getBoundingClientRect:()=>{
  rectReads++;return{x:1,y:2,width:300,height:40};},
  addEventListener:(kind,callback,options)=>{assert.deepEqual({...options},{capture:true,passive:true});listeners.set(kind,callback);},
  removeEventListener:(kind,callback,capture)=>{assert.equal(capture,true);assert.equal(listeners.get(kind),callback);listeners.delete(kind);},
  focus:()=>{throw Error('Probe moved focus');},dispatchEvent:()=>{throw Error('Probe injected event');}};
Object.defineProperty(node,'value',{get:()=> 'October',set:()=>{throw Error('Probe wrote input value');}});
class Observer{constructor(callback){this.callback=callback;this.pending=[];observer=this;}
  observe(target,options){assert.equal(target,node);assert.deepEqual(JSON.parse(JSON.stringify(options)),
    {attributes:true,attributeFilter:['aria-expanded'],attributeOldValue:true});}
  takeRecords(){const pending=this.pending;this.pending=[];return pending;}
  disconnect(){this.disconnected=true;}}
const window={};
const attach=vm.runInNewContext('('+install+')',{window,document,MutationObserver:Observer,performance:{now:()=>++clock}});
const before=attach(node);assert.equal(before.id,'native-1');assert.equal(before.fullRender,'full-1');
assert.equal(before.scriptState,'notRunning');assert.equal(before.connected,true);assert.equal(rectReads,1);
listeners.get('pointerdown')({type:'pointerdown',isTrusted:false});
listeners.get('pointerdown')({type:'pointerdown',isTrusted:true});
document.activeElement=node;listeners.get('focus')({type:'focus',isTrusted:true});
assert.equal(rectReads,1,'Native-event listeners must not read layout');
// Both mutations can be delivered after the final value is already false.
observer.callback([{target:node,attributeName:'aria-expanded',oldValue:'false'},
                   {target:node,attributeName:'aria-expanded',oldValue:'true'}]);
let state=window.__enfraFreshMonthActivation.snapshot();
assert.deepEqual(Array.from(state.mutations,m=>[m.before,m.after]),[['false','true'],['true','false']]);
assert.deepEqual(Array.from(state.events,e=>e.type),['pointerdown','focus']);
for(let i=0;i<60;i++)listeners.get('mousedown')({type:'mousedown',isTrusted:true});
observer.pending=Array.from({length:60},()=>({target:node,attributeName:'aria-expanded',oldValue:'false'}));
node.isConnected=false;
const final=window.__enfraFreshMonthActivation.finish();
assert.equal(final.connected,false);assert.equal(final.events.length,24);assert.equal(final.droppedEvents,38);
assert.equal(final.mutations.length,24);assert.equal(final.droppedMutations,38);
assert.equal(observer.disconnected,true);assert.equal(listeners.size,0);
assert.equal(window.__enfraFreshMonthActivation,undefined);assert.equal(node.value,'October');
console.log('PASS actual passive probe, intermediate state, bounds, cleanup, and no native writes');
'''
    run = subprocess.run(["node", "-e", script], input=json.dumps(install), capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS actual passive probe" in run.stdout
