"""Execute the locked React Aria multiselect callbacks, not a menu substitute."""
from pathlib import Path
import json
import subprocess

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
