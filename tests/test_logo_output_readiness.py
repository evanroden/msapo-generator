"""Synthetic output-oracle readiness, never a waiver of About first-click QA."""
import subprocess
import pytest
from scripts.workspace_logo_click_observations import OUTPUT_READY, click_ready_native_output


def test_observed_pending_hydration_blocks_helper_but_not_hidden_sidebar_controls():
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const wanted={scope:'scope',generation:'generation',sequence:1};
let receipt={...wanted,original_unchanged:true},running='notRunning',visible=true,connected=true,owned=true,disabled=false;
const skeleton={isConnected:true,getClientRects:()=>visible?[{width:400,height:40}]:[]};
const button={textContent:'Render synthetic native logo outputs',get isConnected(){return connected},get disabled(){return disabled},getClientRects:()=>[{width:240,height:40}]};
let pending=[skeleton];
const main={contains:n=>owned&&n===button,querySelectorAll:()=>pending};
const context={location:{origin:'http://127.0.0.1:8546'},getComputedStyle:()=>({visibility:'visible'}),document:{
 querySelectorAll:s=>s==='button'?[button]:[{dataset:{enfraLogoRefresh:JSON.stringify(receipt)}}],
 querySelector:s=>s.includes('stMain')?main:{getAttribute:()=>running}}};
const ready=()=>vm.runInNewContext('('+process.argv[1]+')',context)(wanted);
assert.equal(ready(),false); // visible main-flow 40px loading placeholder in failed traces
visible=false;assert.equal(ready(),true); // collapsed/non-layout placeholder
visible=true;pending=[];assert.equal(ready(),true); // sidebar is deliberately not queried
for(const key of ['scope','generation','sequence']){const old=receipt[key];receipt[key]='stale';assert.equal(ready(),false);receipt[key]=old;}
running='running';assert.equal(ready(),false);running='notRunning';
receipt.original_unchanged=false;assert.equal(ready(),false);receipt.original_unchanged=true;
connected=false;assert.equal(ready(),false);connected=true;
owned=false;assert.equal(ready(),false);owned=true;
disabled=true;assert.equal(ready(),false);disabled=false;
context.location.origin='https://production.example';assert.equal(ready(),false);
'''
    subprocess.run(['node', '-e', script, OUTPUT_READY], check=True, capture_output=True, text=True)


def test_readiness_and_single_native_click_share_existing_deadline(monkeypatch):
    times = iter([100, 112])
    monkeypatch.setattr('time.monotonic', lambda: next(times))
    calls = []
    class Page:
        def wait_for_function(self, predicate, **kwargs): calls.append(('ready', predicate, kwargs))
        def get_by_role(self, *args, **kwargs):
            calls.append(('target', args, kwargs));return self
        def click(self, **kwargs): calls.append(('click', kwargs))
    prior = {'scope':'scope','generation':'generation','sequence':1}
    click_ready_native_output(Page(), prior)
    assert calls[0] == ('ready', OUTPUT_READY, {'arg':prior,'timeout':30000})
    assert calls[1] == ('target', ('button',), {'name':'Render synthetic native logo outputs','exact':True})
    assert calls[2] == ('click', {'timeout':18000})


def test_no_click_after_readiness_budget_expires(monkeypatch):
    times=iter([100,130])
    monkeypatch.setattr('time.monotonic',lambda:next(times))
    class Page:
        def wait_for_function(self,*args,**kwargs): pass
        def get_by_role(self,*args,**kwargs): raise AssertionError('must not click after budget')
    with pytest.raises(TimeoutError,match='deadline'):
        click_ready_native_output(Page(),{'scope':'s','generation':'g','sequence':1})
