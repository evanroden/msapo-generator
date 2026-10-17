"""The compact preview probe observes the original native action without fixing it."""
import ast
import json
from pathlib import Path
import subprocess

import pytest


SOURCE = Path(__file__).parents[1] / "scripts/qa_water_page_journey.py"


def original_function(calls):
    tree = ast.parse(SOURCE.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "open_water_preview")

    def current(page, qa, *, inset):
        assert inset == 90
        calls.append("original bounded current preview")
        if page.fail_at == "current":
            raise RuntimeError("Original current preview failed")

    namespace = {"WATER": ".st-key-epc_pair_monthly_water", "current_water_preview": current}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["open_water_preview"]


class Page:
    def __init__(self, calls, *, fail_at=None, cleanup_failure=False, setup_failure=False):
        self.calls, self.fail_at = calls, fail_at
        self.cleanup_failure, self.setup_failure = cleanup_failure, setup_failure

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ("button", "View preview", True)
        self.calls.append("original exact button")
        return self

    def evaluate(self, script, *args):
        if "new MutationObserver" in script:
            self.calls.append("install passive probe")
            assert args == (".st-key-epc_pair_monthly_water",)
            if self.setup_failure:
                raise ValueError("Probe setup failed")
        elif "finish" in script:
            self.calls.append("finish passive probe")
            if self.cleanup_failure:
                raise ValueError("Probe cleanup failed")
        else:
            assert "snapshot" in script
            self.calls.append("read passive probe")
        return {"currentButtonIsOriginal": True, "onclickType": "function"}

    def click(self):
        self.calls.append("one original native click")
        if self.fail_at == "click":
            raise RuntimeError("Original native click failed")


def test_one_original_click_and_bounded_current_assertion_remain_authoritative():
    calls, observations = [], {}
    page = Page(calls)
    original_function(calls)(page, page, object(), observations)
    assert calls == ["original exact button", "install passive probe", "one original native click",
                     "read passive probe", "original bounded current preview", "finish passive probe"]
    assert set(observations["compact_preview_activation"]) == {"before", "after_click", "final"}


@pytest.mark.parametrize("fail_at", ["click", "current"])
def test_primary_native_failure_is_not_masked_by_diagnostic_cleanup(fail_at):
    calls, observations = [], {}
    page = Page(calls, fail_at=fail_at, cleanup_failure=True)
    with pytest.raises(RuntimeError, match="Original"):
        original_function(calls)(page, page, object(), observations)
    assert calls.count("one original native click") == 1
    assert calls[-1] == "finish passive probe"
    assert observations["compact_preview_activation"]["cleanup_error"] == "Probe cleanup failed"


def test_diagnostic_setup_failure_does_not_add_an_action_or_skip_current_assertion():
    calls, observations = [], {}
    page = Page(calls, setup_failure=True)
    original_function(calls)(page, page, object(), observations)
    assert calls == ["original exact button", "install passive probe", "one original native click",
                     "original bounded current preview", "finish passive probe"]
    assert observations["compact_preview_activation"]["setup_error"] == "Probe setup failed"


def test_actual_probe_javascript_tracks_original_binding_after_handler_and_batched_changes_passively():
    tree = ast.parse(SOURCE.read_text())
    install = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                   and isinstance(n.value, str) and "const events=[],mutations=[]" in n.value)
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const install=JSON.parse(fs.readFileSync(0,'utf8')),listeners=new Map();
let clock=0,rectReads=0,observer,currentPair,currentButton,currentReference;
const root={dataset:{epcFullRender:'full-1',epcMode:'compact'}};
const reference={isConnected:true},attrs=new Map(),expanded=new Map([['aria-expanded','false']]);
const pair={isConnected:true,closest:selector=>{assert.equal(selector,'.epc-workspace');return root;},
 getAttribute:name=>attrs.get(name)??null,querySelector:selector=>selector==='.epc-compact-open'?node:reference};
const handler=()=>{};
const node={isConnected:true,tagName:'BUTTON',getAttribute:name=>expanded.get(name)??null,
 closest:selector=>{assert.equal(selector,'.st-key-epc_pair_monthly_water');return pair;},
 contains:target=>target===node,getBoundingClientRect:()=>{rectReads++;return{x:16,y:90,width:100,height:44};}};
for(const forbidden of ['value','textContent','innerText'])Object.defineProperty(node,forbidden,
 {get:()=>{throw Error('Probe read report text');},set:()=>{throw Error('Probe wrote report text');}});
Object.defineProperty(node,'onclick',{get:()=>handler,set:()=>{throw Error('Probe replaced handler');}});
node.focus=node.click=node.dispatchEvent=()=>{throw Error('Probe injected native action');};
const document={activeElement:null,querySelector:selector=>{
 if(selector==='.st-key-epc_pair_monthly_water')return currentPair;
 if(selector==='[data-testid="stApp"]')return{getAttribute:()=> 'notRunning'};
 throw Error('Unexpected selector '+selector);},
 addEventListener:(kind,callback,options)=>{assert.equal(options.passive,true);
   const key=kind+options.capture;assert(!listeners.has(key));listeners.set(key,callback);},
 removeEventListener:(kind,callback,capture)=>{const key=kind+capture;assert.equal(listeners.get(key),callback);listeners.delete(key);}};
pair.querySelector=selector=>selector==='.epc-compact-open'?currentButton:currentReference;
currentPair=pair;currentButton=node;currentReference=reference;
class Observer{constructor(callback){observer=this;this.callback=callback;this.pending=[];}
 observe(target,options){assert.equal(target,pair);assert.deepEqual(JSON.parse(JSON.stringify(options)),
  {attributes:true,subtree:true,attributeFilter:['aria-expanded','data-epc-preview-open'],attributeOldValue:true});}
 takeRecords(){const pending=this.pending;this.pending=[];return pending;}
 disconnect(){this.disconnected=true;}}
const window={};const attach=vm.runInNewContext('('+install+')',
 {window,document,MutationObserver:Observer,performance:{now:()=>++clock}});
const before=attach(node,'.st-key-epc_pair_monthly_water');
assert.equal(before.onclickType,'function');assert.equal(before.currentButtonIsOriginal,true);
assert.equal(before.currentReferenceIsOriginal,true);assert.equal(before.fullRender,'full-1');
assert.equal(before.mode,'compact');assert.equal(before.pairOpen,null);assert.equal(rectReads,1);
const fire=(kind,capture,trusted=true)=>listeners.get(kind+capture)
 ({type:kind,isTrusted:trusted,eventPhase:capture?1:3,target:node});
fire('pointerdown',true,false);fire('pointerdown',true);fire('click',true);
// A normal external handler changes state between capture and bubble; probe
// records the actual state and never invokes or replaces that handler itself.
attrs.set('data-epc-preview-open','true');expanded.set('aria-expanded','true');fire('click',false);
assert.equal(rectReads,1,'Event observers cannot introduce layout reads');
let state=window.__enfraWaterPreviewActivation.snapshot();
assert.deepEqual(Array.from(state.events,e=>[e.type,e.phase,e.pairOpen]),
 [['pointerdown',1,null],['click',1,null],['click',3,'true']]);
// Preserve intermediate values when both attributes open then close in one batch.
attrs.delete('data-epc-preview-open');expanded.set('aria-expanded','false');
observer.callback([{target:pair,attributeName:'data-epc-preview-open',oldValue:null},
 {target:node,attributeName:'aria-expanded',oldValue:'false'},
 {target:pair,attributeName:'data-epc-preview-open',oldValue:'true'},
 {target:node,attributeName:'aria-expanded',oldValue:'true'}]);
state=window.__enfraWaterPreviewActivation.snapshot();
assert.deepEqual(Array.from(state.mutations,m=>[m.target,m.before,m.after]),
 [['original-pair',null,'true'],['original-button','false','true'],
  ['original-pair','true',null],['original-button','true','false']]);
for(let i=0;i<60;i++)fire('mousedown',true);
observer.pending=Array.from({length:60},()=>({target:node,attributeName:'aria-expanded',oldValue:'false'}));
node.isConnected=false;pair.isConnected=false;reference.isConnected=false;
currentPair={querySelector:()=>null,getAttribute:()=>null,closest:()=>null};currentButton=null;currentReference=null;
const final=window.__enfraWaterPreviewActivation.finish();
assert.equal(final.currentPairIsOriginal,false);assert.equal(final.currentButtonIsOriginal,false);
assert.equal(final.currentReferenceIsOriginal,false);assert.equal(final.buttonConnected,false);
assert.equal(final.events.length,24);assert.equal(final.droppedEvents,39);
assert.equal(final.mutations.length,24);assert.equal(final.droppedMutations,40);
assert.equal(observer.disconnected,true);assert.equal(listeners.size,0);
assert.equal(window.__enfraWaterPreviewActivation,undefined);assert.equal(node.onclick,handler);
console.log('PASS actual passive original-button/binding/mutation contract; not a browser cause reproduction');
'''
    run = subprocess.run(["node", "-e", script], input=json.dumps(install), capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS actual passive" in run.stdout
