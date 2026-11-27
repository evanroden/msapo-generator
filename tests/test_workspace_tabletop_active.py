"""Execute the actual tabletop selector against hosted failure geometry."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_tabletop_preview_uses_the_same_active_section_as_navigation():
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const geometry = require('./app/workspace_geometry.js');
const source = fs.readFileSync('app/workspace_layout.js', 'utf8');
const start = source.indexOf('    function updateActive(context) {');
const end = source.indexOf('    let waitingForGesture', start);
assert.ok(start >= 0 && end > start);
assert.ok(source.includes('navigation?.update(context,sample);\n        updateActive(context);'),
    'the coordinator must resolve the current reading line before preview visibility');
function run({activityTop, organizationBottom, navigationActive, previous = null, navigation = {}, mode = 'tabletop'}) {
    const pairs = [
        {id:'monthly_organization', pair:{dataset:{}, box:{y:-38.8125,height:organizationBottom + 38.8125}}},
        {id:'monthly_activity', pair:{dataset:{}, box:{y:activityTop,height:1243.34375}}},
        {id:'monthly_scorecards', pair:{dataset:{}, box:{y:1740.6875,height:798.53125}}},
    ];
    const state = {active:previous, navigationActive};
    const context = {mode, editor:{y:416}};
    vm.runInNewContext(source.slice(start, end) + '\nupdateActive(context);', {
        geometry, state, pairs, navigation, context, rect:pair=>pair.box,
    });
    return {state,pairs,active:pairs.filter(({pair})=>pair.dataset.epcActive === 'true').map(({id})=>id)};
}
// Exact failure rectangles from both hosted engines: the old y+32 line
// lies within Organization even though Back/Next has landed on Activity.
for (const [activityTop,organizationBottom] of [[481.34375,465.34375],[481.375,465.375]]) {
    let result = run({activityTop,organizationBottom,navigationActive:'monthly_activity'});
    assert.equal(result.state.active,'monthly_activity');
    assert.deepEqual(result.active,['monthly_activity'],'only the current editor preview is exposed');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',previous:'monthly_organization'});
    assert.deepEqual(result.active,['monthly_activity'],'a stale prior tabletop preview cannot override navigation');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_scorecards',previous:'monthly_activity'});
    assert.deepEqual(result.active,['monthly_scorecards'],'forward navigation uses the same coordinator');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',previous:'monthly_scorecards'});
    assert.deepEqual(result.active,['monthly_activity'],'reverse navigation uses the same coordinator');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',navigation:null});
    assert.deepEqual(result.active,['monthly_organization'],'other tools retain their existing geometric reading line');
    result = run({activityTop,organizationBottom,navigationActive:null});
    assert.deepEqual(result.active,['monthly_organization'],'uninitialized navigation retains geometric fallback');
    result = run({activityTop,organizationBottom,navigationActive:'not_a_present_section'});
    assert.deepEqual(result.active,['monthly_organization'],'missing navigation target does not blank every preview');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',mode:'wide'});
    assert.deepEqual(result.active,[],'ordinary wide previews remain unconfined');
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)


def test_mode_transition_hands_anchor_to_coordinator_after_scroll_owner_changes():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/workspace_layout.js','utf8');
const start=source.indexOf('        if (previous !== context.mode && activeBefore) {');
const end=source.indexOf('        globalThis.ENFRAWorkspaceNavigation?.focusEntries',start);
assert.ok(start>=0&&end>start);
for(const [previous,mode,ownsScroll,ownedScrollBefore,hasAnchor] of [
    ['book','tabletop',true,false,true], ['tabletop','compact',false,true,true],
    ['compact','tabletop',true,false,true], ['tabletop','book',false,true,true],
    ['tabletop','tabletop',true,true,true], ['book','tabletop',true,false,false],
]) {
    const events=[],state={mode:previous,ownsScroll:ownedScrollBefore,outerScroll:123};
    let rootScroll=0,outerScroll=0;
    const root={get scrollTop(){return rootScroll},set scrollTop(value){rootScroll=value;events.push('root-scroll')}};
    const scrollport={get scrollTop(){return outerScroll},set scrollTop(value){outerScroll=value;events.push('outer-scroll')}};
    const context={mode,editor:{y:416}};
    const activeBefore=hasAnchor?{id:'monthly_activity',pair:{getBoundingClientRect:()=>({top:481.375})}}:null;
    const navigation={height:()=>53,reanchor(id){assert.equal(state.ownsScroll,true);assert.equal(id,'monthly_activity');events.push('anchor')},
        update(){events.push('update')}};
    vm.runInNewContext(source.slice(start,end),{state,root,scrollport,context,previous,ownsScroll,ownedScrollBefore,activeBefore,navigation,
        anchor:null,sample:{},updateActive(){events.push('preview')}});
    const enters=previous!==mode&&ownsScroll&&hasAnchor;
    assert.equal(events.filter(x=>x==='anchor').length,enters?1:0);
    if(enters){assert.deepEqual(events,['root-scroll','anchor','update','preview']);assert.equal(rootScroll,.375);}
    else assert.deepEqual(events.slice(-2),['update','preview']);
    assert.equal(events.filter(x=>x==='root-scroll').length,enters?1:0,'no additional corrective scrolling');
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)


def test_clearance_uses_the_owned_roots_measured_navigation_and_skips_ordinary_scroll():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/workspace_layout.js','utf8');
const start=source.indexOf('        const viewportSignature =');
const end=source.indexOf('        const signature =',start);
assert.ok(start>=0 && end>start);
for(const ownsScroll of [true,false]) for(const changed of [true,false]) {
 const sample={visual:{width:669,height:250,scale:1},layout:{width:669,height:250},textScale:1};
 const context={mode:ownsScroll?'tabletop':'compact'};
 const current=JSON.stringify([669,250,1,sample.layout,1,context.mode]);
 const state={focusViewport:changed?'previous':current,focusTextScale:1};
 const root={getBoundingClientRect:()=>({top:416,bottom:900})};
 const scrollport={getBoundingClientRect:()=>({top:0,bottom:900})};
 const calls=[];
 const env={state,sample,context,root,scrollport,ownsScroll,top:122,bottom:900,focusClearUntil:0,schedule:()=>{},navigation:{height:()=>50},
  ENFRAWorkspaceNavigation:{keepFocusedClear:value=>calls.push(value)}};
 vm.runInNewContext(source.slice(start,end),env);
 assert.equal(calls.length,changed?1:0,'ordinary scroll never invokes corrective scrolling');
 if(changed){assert.equal(calls[0].top,ownsScroll?478:122);assert.equal(calls[0].scrollport,ownsScroll?root:scrollport);}
 assert.equal(state.focusViewport,current);
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)


def test_mode_transition_prefers_the_current_native_editor_over_stale_preview():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/workspace_layout.js','utf8');
const start=source.indexOf('        const focusedPair =');
const end=source.indexOf('        if (!ownedScrollBefore',start);
assert.ok(start>=0&&end>start);
for(const [focused,previous,mode,wanted] of [
 ['activity','book','tabletop','activity'],
 ['activity','wide','tabletop','activity'],
 ['reference','book','tabletop','organization'],
 ['none','book','tabletop','organization'],
 ['activity','tabletop','tabletop',null],
]) {
 const document={activeElement:focused};
 const pairs=['organization','activity'].map(id=>({id,pair:{
  querySelector:()=>({contains:n=>n===id}),
  getBoundingClientRect:()=>({bottom:500}),
 }}));
 const result=vm.runInNewContext(source.slice(start,end)+'\nactiveBefore?.id ?? null',{
  pairs,document,previous,context:{mode},state:{active:'organization'},sample:{scrollport:{y:0}},
 });
 assert.equal(result,wanted,'focus owns the transition only inside a native editor');
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)


def test_viewport_reflow_rechecks_only_its_bounded_window_and_honors_user_cancel():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/workspace_layout.js','utf8');
const start=source.indexOf('        const viewportSignature =');
const end=source.indexOf('        const signature =',start);
const calls=[];let now=1000,scheduled=0;
const sample={visual:{width:669,height:885,scale:1},layout:{width:669,height:885},textScale:2};
const context={mode:'compact'},root={getBoundingClientRect:()=>({top:0,bottom:885})};
const env={sample,context,root,scrollport:root,ownsScroll:false,top:122,bottom:885,
 state:{focusViewport:'old',focusTextScale:2},focusClearUntil:0,Date:{now:()=>now},
 schedule:()=>scheduled++,navigation:null,ENFRAWorkspaceNavigation:{keepFocusedClear:x=>calls.push(x)}};
const evaluate=()=>vm.runInNewContext('{'+source.slice(start,end)+'}',env);
evaluate();assert.equal(calls.length,1);assert.equal(env.focusClearUntil,1600);
now=1400;evaluate();assert.equal(calls.length,2,'late native reflow stays covered');
now=1601;evaluate();assert.equal(calls.length,2,'ordinary later scrolling stays untouched');
// All deliberate input gestures cancel the settling window synchronously.
const a=source.indexOf('    const cancelFocusClear ='),b=source.indexOf('    const controlsOwner =',a);
const listeners={},cleanups=[];env.focusClearUntil=2000;
vm.runInNewContext(source.slice(a,b),Object.assign(env,{subscriptions:cleanups,
 document:{addEventListener:(type,fn)=>listeners[type]=fn,removeEventListener(){}}}));
for(const type of ['pointerdown','keydown','wheel','touchstart']){env.focusClearUntil=2000;listeners[type]();assert.equal(env.focusClearUntil,0);}
assert.equal(cleanups.length,4);
// Switching into a confined owner must cancel any page-flow settle window.
env.state.focusViewport='old';env.state.focusTextScale=2;
env.focusClearUntil=2200;env.ownsScroll=true;now=1700;
evaluate();assert.equal(env.focusClearUntil,0);
const after=calls.length;now=1750;evaluate();
assert.equal(calls.length,after,'a stale page-flow window must not undo confined reading');
'''
    subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True,text=True)
