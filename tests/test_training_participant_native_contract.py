"""Execute the locked React Aria multiselect callbacks, not a menu substitute."""
from pathlib import Path
import json
import subprocess

import pytest
import streamlit


def test_native_filter_can_open_when_controller_is_ready_and_pointer_opens_first():
    source = (Path(streamlit.__file__).parent / "static" / "static" / "js" /
              "Multiselect.Bh_0JsCR.js").read_text()

    def callback(name, suffix):
        start = source.index(name + "=(0,w.useCallback)(") + len(name + "=(0,w.useCallback)(")
        return source[start:source.index(suffix, start)]

    start = source.index("e.current=(e=null)=>n.open(e,`manual`)") + len("e.current=")
    opening = source[start:source.index("),()=>{e.current=null}", start)]
    code = r'''
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
function model(ready){
 const state={filter:'',open:false,focused:0,opens:[]};
 const O={current:''},k={current:false},z={current:null},input={current:{focus(){state.focused++}}};
 const T=value=>{state.filter=value};
 const build=new Function('O','T','k','z','_','Y',
   'return {input:'+source.input+',opened:'+source.opened+',pointer:'+source.pointer+'};');
 const handlers=build(O,T,k,z,input,false);
 const install=()=>{z.current=new Function('n','return ('+source.opening+')')({
   open(position,trigger){state.opens.push([position,trigger]);state.open=true;handlers.opened(true);}});};
 if(ready)install();
 return {state,handlers,install,render(){O.current=state.filter}};
}
// Fill is a supported source path once the controller effect has installed.
const ready=model(true);ready.handlers.input('Synthetic Person North');
assert.equal(ready.state.filter,'Synthetic Person North');assert.equal(ready.state.open,true);
assert.deepEqual(ready.state.opens,[[null,'manual']]);
// An absent effect-installed ref explains no menu, but not an empty filter.
const early=model(false);early.handlers.input('Synthetic Person North');early.render();early.install();
assert.equal(early.state.open,false);assert.equal(early.state.filter,'Synthetic Person North');
// Normal pointer entry establishes the menu before one filter operation.
const pointer=model(true);pointer.handlers.pointer({target:{closest(){return null}}});
assert.equal(pointer.state.focused,1);assert.equal(pointer.state.open,true);
pointer.handlers.input('Synthetic Person North');
assert.equal(pointer.state.filter,'Synthetic Person North');assert.equal(pointer.state.opens.length,1);
// A close transition really does clear filter text; its occurrence in the
// failed browser remains unrecorded and cannot be inferred from this model.
pointer.handlers.opened(false);assert.equal(pointer.state.filter,'');
'''
    subprocess.run(["node", "-e", code, json.dumps({
        "input": callback("Ne", ",[]),Pe="),
        "opened": callback("Pe", ",[]),X="),
        "pointer": callback("Le", ",[Y]),Re="),
        "opening": opening,
    })], check=True, capture_output=True, text=True)


@pytest.mark.parametrize("scenario", ["selection", "closed", "null-close"])
def test_native_scroll_uses_committed_selection_before_passive_cleanup(tmp_path, scenario):
    from scripts.streamlit_overlay_resize import OVERLAY_BUNDLE, repair_overlay

    assets = Path(streamlit.__file__).parent / "static/static/js"
    multiselect = (assets / "Multiselect.Bh_0JsCR.js").read_text()
    combo = (assets / "fuzzyFilterSelectOptions.Bf8rcmtM.js").read_text()
    widget = (assets / "useBasicWidgetState.CCuiA4s6.js").read_text()
    overlay = (assets / OVERLAY_BUNDLE).read_text()

    def between(source, start, end):
        offset = source.index(start)
        return source[offset:source.index(end, offset)]

    def callback(name, end):
        prefix = name + "=(0,w.useCallback)("
        return between(multiselect, prefix, end)[len(prefix):]

    source = tmp_path / "native.json"
    source.write_text(json.dumps({
        "widget": between(widget, "function o(", "function s("),
        "latest": between(overlay, "function Ze(", "var Qe="),
        "change": callback("Me", ",[t.maxSelections,S,x]),Ne="),
        "opened": callback("Pe", ",[]),X="),
        "close": "let " + between(combo, "G=()=>{if(o===`multiple`)", ",q=()=>"),
    }))
    before, after = tmp_path / "before.js", tmp_path / "after.js"
    before.write_bytes(repair_overlay((assets / OVERLAY_BUNDLE).read_bytes(), latest_scroll_close=False))
    after.write_bytes(repair_overlay((assets / OVERLAY_BUNDLE).read_bytes()))
    result = subprocess.run(["node", str(Path(__file__).with_name("training_scroll_commit_test.cjs")),
                             str(source), str(before), str(after), scenario], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
