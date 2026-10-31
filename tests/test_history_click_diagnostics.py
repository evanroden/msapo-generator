"""Diagnostics observe one native action, never retry or change its outcome."""
import ast
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_passive_probe_targets_geometry_caps_and_cleanup():
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let frames=new Map(),listeners=new Map(),serial=0,clock=0,top=449,removed=0;
const owner={classList:['st-key-private_customer_history_open']};
const summary={isConnected:true,getBoundingClientRect:()=>({x:380,y:top,width:899,height:40}),
 contains:target=>target===summary,
 closest:selector=>selector.includes('stApp')?app:owner};
const pair={isConnected:true,getBoundingClientRect:()=>({x:380,y:100,width:899,height:700}),
 querySelectorAll:()=>Array(2).fill({})};
const port={scrollTop:14955};
const app={querySelector:selector=>selector.includes('stMain')?port:summary,
 querySelectorAll:()=>[pair]};
const document={addEventListener:(type,fn,opts)=>{
 assert.deepEqual(Object.keys(opts).sort(),['capture','passive']);
 assert.equal(opts.capture,true);assert.equal(opts.passive,true);listeners.set(type,fn);},
 removeEventListener:(type,fn,capture)=>{assert.equal(capture,true);assert.equal(listeners.get(type),fn);listeners.delete(type);removed++;}};
const window={};
vm.runInNewContext(source,{window,document,CSS:{escape:x=>x},performance:{now:()=>clock++},
 requestAnimationFrame:fn=>{frames.set(++serial,fn);return serial;},cancelAnimationFrame:id=>frames.delete(id)});
const probe=window.__enfraHistoryClickProbe,observation={};probe.start(summary,observation);
assert.equal(observation.diagnostic.samples[0].rect[1],449);
listeners.get('pointerdown')({type:'pointerdown',isTrusted:false,target:summary,clientX:829,clientY:449});
assert.equal(observation.diagnostic.events.length,0);
listeners.get('pointerdown')({type:'pointerdown',isTrusted:true,target:summary,clientX:829,clientY:449});
top=477;
const other={closest:()=>null};
listeners.get('pointerup')({type:'pointerup',isTrusted:true,target:other,clientX:829,clientY:449});
let [id,fn]=frames.entries().next().value;frames.delete(id);fn();
assert.equal(observation.diagnostic.samples.at(-1).rect[1],477);
assert.equal(observation.diagnostic.samples.at(-1).scrollTop,14955);
assert.equal(observation.diagnostic.events[0].category,'history');
assert.equal(observation.diagnostic.events[1].category,'other');
assert.notEqual(observation.diagnostic.events[0].target,observation.diagnostic.events[1].target);
const ended=probe.stop();assert.equal(ended.stopped,true);assert.equal(frames.size,0);assert.equal(listeners.size,0);
assert.equal(probe.stop(),ended);assert.equal(removed,4);
assert.ok(!JSON.stringify(ended).includes('private_customer'));
// Unfinished action has hard memory/scheduling bounds, even without stop().
probe.start(summary,{});let calls=0;
while(frames.size){const [id,fn]=frames.entries().next().value;frames.delete(id);fn();assert.ok(++calls<200);}
assert.equal(probe.last().truncated,true);assert.ok(probe.last().samples.length<=128);
assert.ok(JSON.stringify(probe.last()).length<66000);assert.equal(listeners.size,0);
// Replacing an active probe cancels its old work/listeners before collecting.
probe.start(summary,{});probe.start(summary,{});assert.equal(listeners.size,4);probe.stop();
assert.equal(frames.size,0);assert.equal(listeners.size,0);
'''
    subprocess.run(['node', '-e', script], input=json.dumps(
        (ROOT / 'scripts/history_click_diagnostics.js').read_text()), text=True,
        check=True, capture_output=True, timeout=10)


def test_cleanup_failure_does_not_mask_or_retry_original_click_failure():
    tree = ast.parse((ROOT / 'scripts/qa_monthly_history.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_history')
    page, panel, summary = Mock(), Mock(), Mock()
    panel.evaluate.return_value = False
    panel.locator.return_value.first = summary
    summary.click.side_effect = RuntimeError('original native action failed')
    page.evaluate.side_effect = RuntimeError('diagnostic collection failed')
    namespace = {'history': lambda _:panel, 'receipt': lambda _:{'sequence':1}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'actual-driver', 'exec'),namespace)
    with pytest.raises(RuntimeError, match='original native action failed'):
        namespace['set_history'](page,True,'synthetic',[])
    assert summary.click.call_count == 1
    page.evaluate.assert_called_once_with('window.__enfraHistoryClickProbe?.stop()')


def test_probe_has_no_input_or_layout_side_effect_apis():
    source = (ROOT / 'scripts/history_click_diagnostics.js').read_text()
    for prohibited in ('preventDefault', 'stopPropagation', 'dispatchEvent', 'scrollTo(', '.focus(',
                       '.value', '.textContent', '.innerHTML', 'location.', 'fetch(', 'setTimeout('):
        assert prohibited not in source
