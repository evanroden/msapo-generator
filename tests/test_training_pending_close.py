"""Exact shipped pending-state boundary; no timers, DOM writes or fake input."""
import json
from pathlib import Path
import subprocess

import pytest
import streamlit

from scripts.streamlit_combobox_close import COMBOBOX_BUNDLE, repair_combobox_close
from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, repair_overlay


def between(source, start, end):
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


@pytest.fixture
def native_sources():
    assets = Path(streamlit.__file__).parent / "static/static/js"
    multiselect = (assets / "Multiselect.Bh_0JsCR.js").read_text()
    combo = (assets / COMBOBOX_BUNDLE).read_bytes()
    repaired = repair_combobox_close(combo).decode()
    widget = (assets / "useBasicWidgetState.CCuiA4s6.js").read_text()
    overlay = (assets / OVERLAY_BUNDLE).read_bytes()
    def callback(name, end):
        prefix = name + "=(0,w.useCallback)("
        return between(multiselect, prefix, end)[len(prefix):]
    return {
        "widget": between(widget, "function o(", "function s("),
        "latest": between(overlay.decode(), "function Ze(", "var Qe="),
        "change": callback("Me", ",[t.maxSelections,S,x]),Ne="),
        "opened": callback("Pe", ",[]),X="),
        "close": "let " + between(combo.decode(), "G=()=>{if(o===`multiple`)", ",q=()=>"),
        "repairedClose": "let " + between(repaired, "G=()=>{if(o===`multiple`)", ",q=()=>"),
        "commitKey": between(combo.decode(), "q=()=>{F.isOpen", ",ae=")[2:],
        "focus": between(combo.decode(), "oe=t=>", ",se=")[3:],
        "remove": callback("X", ",[S]),Fe="),
        "clear": callback("Z", ",[S]),Le="),
        "keyboard": callback("ze", ",[Y,t.acceptNewOptions,t.maxSelections,t.options,J,S,x]),Q="),
    }, overlay


@pytest.mark.parametrize("scenario", ["before-effect", "precommit", "precommit-existing", "precommit-custom", "after-commit"])
def test_close_retains_pending_selection_and_real_scroll_dismissal(tmp_path, native_sources, scenario):
    native, overlay = native_sources
    source, overlay_path = tmp_path / "native.json", tmp_path / "overlay.js"
    source.write_text(json.dumps(native))
    overlay_path.write_bytes(repair_overlay(overlay))
    result = subprocess.run(["node", str(Path(__file__).with_name("training_pending_close_test.cjs")),
        str(source), str(overlay_path), str(overlay_path), scenario], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_close_does_not_change_multiple_selection_but_single_commit_is_unchanged(native_sources):
    native, _ = native_sources
    code = r'''
const assert=require('node:assert/strict');
const native=JSON.parse(process.argv[1]);
for (const kind of ['multiple','single']) for (const custom of [false,true])
for (const input of ['', 'typed custom']) for (const force of [false,true]) {
 function run(source) {
  const result={changes:[],selectionChanges:[],closes:0,inputs:[],normalizes:0};
  const value=kind==='multiple'?['north','south']:'north';
  const close=new Function('o','i','h','e','C','b','T','v','V','z','H','y','ne',
   source+';return {close:K,commit:ie,revert:G}')(kind,custom,value,
   {inputValue:input,onChange:v=>result.changes.push(v),onSelectionChange:v=>result.selectionChanges.push(v)},
   kind==='multiple'?null:'north',{getItem:()=>({textValue:'North'})},input,value,
   v=>result.inputs.push(v),()=>result.closes++,{current:value},v=>result.selectionChanges.push(v),
   ()=>result.normalizes++);
  close.commit(force);return result;
 }
 const before=run(native.close),after=run(native.repairedClose);
 if(kind==='single') assert.deepEqual(after,before);
 else {
  assert.equal(after.closes,1);assert.deepEqual(after.changes,[]);
  assert.deepEqual(after.selectionChanges,[]);assert.deepEqual(after.inputs,before.inputs);
 }
}
// Intentional native removal/clear remains a real selection write.
const writes=[],q={current:['North','South']},y={current:false},g={current:null},v={current:0};
const S=value=>writes.push(value.value);
const remove=new Function('q','y','g','v','S','return '+native.remove)(q,y,g,v,S);
remove(new Set(['South']));assert.deepEqual(q.current,['North']);
assert.deepEqual(writes.at(-1),['North']);
remove(new Set(['North']));assert.deepEqual(writes.at(-1),[]);
const clear=new Function('S','return '+native.clear)(S);clear();assert.deepEqual(writes.at(-1),[]);
'''
    result = subprocess.run(["node", "-e", code, json.dumps(native)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_selection_bulk_custom_keyboard_escape_and_backspace(native_sources):
    native, _ = native_sources
    code = r'''
const assert=require('node:assert/strict');
const n=JSON.parse(process.argv[1]);
function model(x,filter='',max=0){
 const state={writes:[],filter,opened:0,prevented:0,stopped:0};
 const k={current:true},K={current:[{id:'0',value:'North'},{id:'1',value:'South'}]},O={current:filter};
 const q={current:x},y={current:false},g={current:null},v={current:0},B={current:null},D={current:!!filter};
 const S=p=>state.writes.push(p.value),T=v=>state.filter=v,t={maxSelections:max,acceptNewOptions:true,options:['North','South']};
 const change=new Function('k','K','O','t','x','S','T','return '+n.change)(k,K,O,t,x,S,T);
 const keyboard=new Function('Y','J','x','k','z','D','T','t','O','B','l','S','y','g','v','q','return '+n.keyboard)
  (false,false,x,k,{current:()=>state.opened++},D,T,t,O,B,v=>v!=null,S,y,g,v,q);
 return {state,change,key(key){keyboard({key,currentTarget:{value:state.filter},nativeEvent:{isComposing:false},
  preventDefault(){state.prevented++},stopPropagation(){state.stopped++}})}};
}
let h=model([]);h.change(['0','1']);assert.deepEqual(h.state.writes.at(-1),['North','South']);
h=model(['Existing']);h.change(['0']);assert.deepEqual(h.state.writes.at(-1),['Existing','North']);
h=model([]);h.change(['__select_all__']);assert.deepEqual(h.state.writes.at(-1),['North','South']);
h=model([], 'Custom');h.change(['__creatable__']);assert.deepEqual(h.state.writes.at(-1),['Custom']);
h=model(['North'],'Custom',1);h.change(['__creatable__']);assert.deepEqual(h.state.writes,[]);
h=model(['North'],'Custom');h.key('Enter');assert.deepEqual(h.state.writes.at(-1),['North','Custom']);
h=model(['North','South']);h.key('Backspace');assert.deepEqual(h.state.writes.at(-1),['North']);
h=model(['North'],'pending');h.key('Escape');assert.equal(h.state.filter,'');assert.deepEqual(h.state.writes,[]);
'''
    result = subprocess.run(["node", "-e", code, json.dumps(native)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_pinned_close_and_resize_repairs_compose_without_accepting_modified_inputs():
    from scripts.streamlit_combobox_close import CLOSE_REPAIRED
    from scripts.streamlit_virtualizer_resize import VIRTUALIZER_REPAIRED
    raw = (Path(streamlit.__file__).parent / "static/static/js" / COMBOBOX_BUNDLE).read_bytes()
    repaired = repair_combobox_close(raw, virtualizer_resize=True)
    assert repaired.count(CLOSE_REPAIRED) == 1
    assert repaired.count(VIRTUALIZER_REPAIRED) == 1
    for changed in (raw + b" ", repaired):
        with pytest.raises(RuntimeError, match="Unexpected locked ComboBox"):
            repair_combobox_close(changed, virtualizer_resize=True)


def test_native_keyboard_commit_and_focus_validation_remain_owned_by_native_callbacks(native_sources):
    native, _ = native_sources
    code = r'''
const assert=require('node:assert/strict');const n=JSON.parse(process.argv[1]);
for(const mode of ['single','multiple'])for(const open of [false,true])
for(const focused of [null,'north'])for(const selected of [false,true]){
 const calls=[];
 const commit=new Function('F','x','o','ie','K','return '+n.commitKey)(
  {isOpen:open},{focusedKey:focused,isSelected:()=>selected,select:key=>calls.push(['select',key])},
  mode,forced=>calls.push(['commit',forced]),()=>calls.push(['close']));
 commit();
 assert.deepEqual(calls,open&&focused!==null ? selected&&mode==='single' ? [['commit',true]] : [['select','north']] : [['close']]);
}
for(const focused of [true,false])for(const shouldClose of [true,false]){
 const calls=[],ae={current:['old',[]]},value=['north'];
 const focus=new Function('ae','T','v','n','e','I','a','K','W','u','return '+n.focus)(
  ae,'typed',value,'focus',{isReadOnly:false},(...args)=>calls.push(['open',...args]),shouldClose,
  ()=>calls.push(['close']),{commitValidation:()=>calls.push(['validate'])},value=>calls.push(['focus',value]));
 focus(focused);
 assert.deepEqual(calls,focused ? [['open',null,'focus'],['focus',true]] :
  [...(shouldClose?[['close']]:[]),['validate'],['focus',false]]);
}
'''
    result = subprocess.run(["node", "-e", code, json.dumps(native)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
