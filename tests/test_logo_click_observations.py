"""Read-only diagnostic contracts, not a substitute for hosted native evidence."""
import json
import subprocess

import pytest

from scripts.workspace_logo_click_observations import INSTALL, FINISH, native_click_geometry


@pytest.mark.parametrize('large', [False, True])
def test_actual_observer_reads_geometry_caps_events_and_removes_listeners(large):
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const callbacks={},observers=[];
let clock=0,failRects=false;
const nodes={};
function node(tag,testid,key){
 const n={nodeType:1,tagName:tag,classList:key?[key]:[],dataset:{},scrollTop:13349,scrollHeight:14249,clientHeight:900,
 getAttribute:k=>k==='data-testid'?testid:k==='data-test-script-state'?'notRunning':null,
 getBoundingClientRect:()=>{if(failRects)throw Error('detached diagnostic');return {toJSON:()=>({x:380,y:684.625,width:240.5,height:38})}},
 closest:()=>null,querySelector:selector=>nodes[selector]||null,
 querySelectorAll:()=>Array(process.argv[3]==='large'?40:1).fill(nodes.skeleton),textContent:tag==='BUTTON'?'Render synthetic native logo outputs':''};
 Object.defineProperty(n,'value',{get(){throw Error('Input values must not be read')}});
 return new Proxy(n,{set(){throw Error('DOM writes forbidden')}});
}
nodes.skeleton=node('DIV','stSkeleton','st-key-synthetic-grid');
for(const selector of ['[data-testid="stMain"]','.st-key-epc_workspace_monthly','[data-enfra-logo-refresh]',
 '.st-key-epc_pair_monthly_rfi','.epc-workspace-reference','[class*="st-key-epc_preview_slot_"]',
 '[data-testid="stMainBlockContainer"]','[data-testid="stApp"]'])nodes[selector]=node('DIV','test','st-key-synthetic');
const button=node('BUTTON','stBaseButton-secondary');
const document={activeElement:null,querySelector:s=>nodes[s],querySelectorAll:()=>[button],
 addEventListener(type,fn){callbacks[type]=fn},removeEventListener(type){delete callbacks[type]}};
class Observer{constructor(fn){this.fn=fn;this.disconnected=false;observers.push(this)}observe(){}disconnect(){this.disconnected=true}}
const window={};
const context={window,document,location:{origin:'http://127.0.0.1:8546'},innerWidth:1365,innerHeight:900,
 TextEncoder,performance:{now:()=>++clock},ResizeObserver:Observer,MutationObserver:Observer,getComputedStyle:()=>({getPropertyValue:()=> '681.03125px'})};
vm.runInNewContext('('+process.argv[1]+')()',context);
for(let i=0;i<150;i++)callbacks.scroll({type:'scroll',isTrusted:true,target:nodes['[data-testid="stMain"]']});
const result=vm.runInNewContext('('+process.argv[2]+')()',context);
if(process.argv[3]==='large'){assert.ok(result.events.length<96);assert.ok(result.dropped>55)}
else{assert.equal(result.events.length,96);assert.equal(result.dropped,55)}
assert.ok(result.bytes<=result.byteLimit);
assert.equal(result.events[0].kind,'installed');assert.equal(result.final.kind,'final');
assert.equal(result.events[1].main.scrollTop,13349);assert.equal(result.events[1].main.scrollHeight,14249);
assert.equal(result.events[1].skeletonCount,process.argv[3]==='large'?40:1);assert.equal(result.events[1].button.rect.y,684.625);
assert.equal(Object.keys(callbacks).length,0);assert.ok(observers.every(o=>o.disconnected));
assert.equal(window.__enfraLogoClickGeometry,undefined);
vm.runInNewContext('('+process.argv[1]+')()',context);failRects=true;
assert.throws(()=>vm.runInNewContext('('+process.argv[2]+')()',context),/detached diagnostic/);
assert.equal(window.__enfraLogoClickGeometry,undefined);assert.equal(Object.keys(callbacks).length,0);
assert.ok(observers.every(o=>o.disconnected));
context.location.origin='https://production.example';
assert.throws(()=>vm.runInNewContext('('+process.argv[1]+')()',context),/isolated logo fixture/);
'''
    subprocess.run(['node', '-e', script, INSTALL, FINISH, 'large' if large else 'small'], check=True, capture_output=True, text=True)


def test_first_action_failure_is_preserved_and_evidence_saved(tmp_path):
    class Page:
        calls = []
        def evaluate(self, script):
            self.calls.append(script)
            return {'events': [{'kind': 'installed'}, {'kind': 'pointerdown'}]}
    page = Page()
    with pytest.raises(RuntimeError, match='original first click'):
        with native_click_geometry(page, tmp_path):
            raise RuntimeError('original first click')
    assert page.calls == [INSTALL, FINISH]
    assert len(json.loads((tmp_path / 'native-click-geometry.json').read_text())['events']) == 2


def test_observer_collection_error_does_not_replace_native_failure(tmp_path):
    class Page:
        def evaluate(self, script):
            if script == FINISH:
                raise ValueError('disconnected page')
    with pytest.raises(RuntimeError, match='native failure'):
        with native_click_geometry(Page(), tmp_path):
            raise RuntimeError('native failure')
    assert json.loads((tmp_path / 'native-click-geometry.json').read_text()) == {'diagnostic_error': 'ValueError'}


def test_diagnostic_does_not_change_native_click_or_wait_predicate():
    import inspect
    from scripts.qa_about_logo_refresh import native_outputs
    source = inspect.getsource(native_outputs)
    assert source.count('.click()') == 2  # one Render, one download-loop action
    assert source.count("name='Render synthetic native logo outputs', exact=True).click()") == 1
    assert "wait_state(page, after=sequence, scope=prior['scope'], generation=prior['generation'])" in source
    for forbidden in ('force=', 'wait_for_timeout', 'scroll_into_view', '.focus(', 'setTimeout', 'requestAnimationFrame'):
        assert forbidden not in source + INSTALL


@pytest.mark.parametrize('failure', ['write', 'serialize'])
@pytest.mark.parametrize('native_fails', [False, True])
def test_artifact_failure_preserves_native_error_but_is_explicit_after_success(tmp_path, monkeypatch, failure, native_fails):
    from pathlib import Path
    class Page:
        def evaluate(self, script):
            return {'events': []} if failure == 'write' else {'unserializable': object()}
    if failure == 'write':
        def broken_write(*args, **kwargs):
            raise OSError('diagnostic write failed')
        monkeypatch.setattr(Path, 'write_text', broken_write)
    expected = RuntimeError if native_fails else OSError if failure == 'write' else TypeError
    with pytest.raises(expected) as caught:
        with native_click_geometry(Page(), tmp_path):
            if native_fails:
                raise RuntimeError('original native failure')
    if native_fails:
        assert str(caught.value) == 'original native failure'
