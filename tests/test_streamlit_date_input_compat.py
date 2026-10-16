"""Exact locked-asset boundary and real BaseWeb announcement-branch regression."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess

import pytest
import streamlit

from scripts import patch_streamlit_date_input as compat


@pytest.fixture
def bundle(tmp_path):
    installed = Path(streamlit.__file__).parent / "static"
    target = tmp_path / "static" / "js" / compat.BUNDLE_NAME
    target.parent.mkdir(parents=True)
    raw = (installed / "static" / "js" / compat.BUNDLE_NAME).read_bytes()
    # The shared runtime may already have received the same idempotent patch.
    target.write_bytes(raw)
    (target.parent / compat.INDEX_BUNDLE).write_bytes((installed / "static" / "js" / compat.INDEX_BUNDLE).read_bytes())
    (tmp_path / "index.html").write_bytes(b'<script src="./static/js/' + compat.INDEX_BUNDLE.encode() + b'"></script>')
    return tmp_path, target


def test_exact_patch_changes_only_scalar_boundary_and_is_idempotent(bundle):
    root, target = bundle
    before = target.read_bytes()
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    assert receipt["original_sha256"] == sha256(before).hexdigest()
    assert not receipt["already_patched"]
    assert target.read_bytes() == before
    repaired = target.parent / receipt["bundle"]
    assert repaired.read_bytes() == before.replace(compat.ORIGINAL, compat.REPAIRED, 1)
    entry = target.parent / receipt["entry"]
    assert compat.BUNDLE_NAME.encode() not in entry.read_bytes()
    assert entry.read_bytes().count(receipt["bundle"].encode()) == 2
    assert receipt["entry"].encode() in (root / "index.html").read_bytes()
    assert compat.INDEX_BUNDLE.encode() not in (root / "index.html").read_bytes()
    snapshot = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == snapshot


@pytest.mark.parametrize("mutation", ["version", "content", "missing", "duplicate", "entry", "html", "destination"])
def test_unknown_asset_fails_without_changes(bundle, mutation):
    root, target = bundle
    installed_version = "1.61.2" if mutation == "version" else "1.61.1"
    if mutation == "content":
        target.write_bytes(target.read_bytes() + b" ")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "duplicate":
        target.write_bytes(target.read_bytes() + compat.ORIGINAL)
    elif mutation == "entry":
        path = target.parent / compat.INDEX_BUNDLE
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "html":
        (root / "index.html").write_bytes(b"Unknown entry")
    elif mutation == "destination":
        repaired = target.read_bytes().replace(compat.ORIGINAL, compat.REPAIRED, 1)
        name = "DateInput.enfra-scalar-" + sha256(repaired).hexdigest()[:12] + ".js"
        (target.parent / name).write_bytes(b"Unexpected existing content")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises((RuntimeError, FileNotFoundError)):
        compat.patch_bundle(root, installed_version=installed_version)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_real_baseweb_announcement_distinguishes_scalar_and_unfinished_range(bundle):
    root, target = bundle
    installed = Path(streamlit.__file__).parent / "static" / "static" / "js"
    candidates = [path for path in installed.glob("*.js")
                  if b"t.datepicker.selectSecondDatePrompt" in path.read_bytes()]
    assert len(candidates) == 1
    baseweb = candidates[0].read_text()
    start = baseweb.index("!e.props.value||Array.isArray(e.props.value)")
    end_token = ':Jv(t.datepicker.selectedDate,{date:e.state.inputValue||``})'
    end = baseweb.index(end_token, start) + len(end_token)
    expression = baseweb[start:end]
    original_boundary = compat.ORIGINAL.decode().split(",minDate:")[0].split("value:")[1]
    compat.patch_bundle(root, installed_version="1.61.1")
    repaired_boundary = compat.REPAIRED.decode().split(",minDate:")[0].split("value:")[1]
    code = r'''
const {expression,original,repaired}=JSON.parse(process.argv[1]);
const assert=require('node:assert/strict');
const boundary=code=>new Function('t','x','return '+code);
const before=boundary(original),after=boundary(repaired);
const announce=new Function('e','t','Jv','return '+expression);
const locale={datepicker:{selectedDate:'Selected date is ${date}.',
 selectedDateRange:'Selected range is ${startDate} to ${endDate}.',
 selectSecondDatePrompt:'Select the second date.'}};
const interpolate=(text,args)=>text.replace(/\$\{(\w+)\}/g,(_,key)=>args[key]);
const message=value=>announce({props:{value},state:{inputValue:'2026/09/15'},
 formatDisplayValue:date=>date.toISOString().slice(0,10)},locale,interpolate);
const a=new Date(2026,8,15),b=new Date(2026,8,16),one=[a],two=[a,b];
assert.match(message(before({isRange:false},one)),/Select the second date/);
assert.equal(after({isRange:false},one),a);
assert.doesNotMatch(message(after({isRange:false},one)),/second date/);
assert.match(message(after({isRange:false},one)),/Selected date is/);
assert.equal(after({isRange:false},[]),null);
assert.equal(message(after({isRange:false},[])),'');
assert.equal(after({isRange:true},one),one);
assert.match(message(after({isRange:true},one)),/Select the second date/);
assert.equal(after({isRange:true},two),two);
assert.match(message(after({isRange:true},two)),/Selected range is/);
console.log(JSON.stringify({unpatched:message(before({isRange:false},one)),
 scalar:message(after({isRange:false},one)),range:message(after({isRange:true},one))}));
'''
    result = subprocess.run(["node", "-e", code, json.dumps({"expression": expression,
                            "original": original_boundary, "repaired": repaired_boundary})],
                            check=True, capture_output=True, text=True)
    observed = json.loads(result.stdout)
    assert "second date" in observed["unpatched"]
    assert "second date" not in observed["scalar"]
    assert "second date" in observed["range"]


def test_real_metadata_then_date_install_sequence_preserves_entry_and_branding(bundle):
    from scripts import patch_streamlit_metadata as metadata
    root, target = bundle
    installed_html = Path(streamlit.__file__).parent / "static" / "index.html"
    (root / "index.html").write_bytes(installed_html.read_bytes())
    branding = Path(__file__).resolve().parents[1] / "branding"
    before_entry = (target.parent / compat.INDEX_BUNDLE).read_bytes()
    metadata.install_branding(root, branding_dir=branding)
    receipt = compat.patch_bundle(root, installed_version="1.61.1")
    assert (target.parent / compat.INDEX_BUNDLE).read_bytes() == before_entry
    assert sha256(before_entry).hexdigest() == compat.INDEX_SHA256
    assert b"<title>Process Control</title>" in (root / "index.html").read_bytes()
    assert receipt["entry"].encode() in (root / "index.html").read_bytes()
    snapshot = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    metadata.install_branding(root, branding_dir=branding)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == snapshot


def test_locked_native_clear_keeps_its_accessible_button_and_keyboard_contract():
    """The native selector is valid; do not bypass it with a hidden SVG click.

    Execute the actual locked BaseWeb render method, rather than constructing
    a substitute clear control. This covers emitted props/handlers only; the
    CI browser journey separately observes the mounted accessibility tree.
    """
    installed = Path(streamlit.__file__).parent / "static" / "static" / "js"
    candidates = [path for path in installed.glob("*.js")
                  if b"t.datepicker.selectSecondDatePrompt" in path.read_bytes()]
    assert len(candidates) == 1
    source = candidates[0].read_text()
    start = source.index("value:function(){var e,t=this,n=this.props,r=n.clearable") + len("value:")
    end = source.index("}},{key:`render`,", start) + 1
    method = source[start:end]
    code = r'''
const assert=require('node:assert/strict');
const method=JSON.parse(process.argv[1]);
const k={createElement:(component,props,...children)=>({component,props,children})};
const values={mini:'mini',compact:'compact',default:'default',large:'large'};
const render=new Function('Fr','m','qn','Jn','Hn','j','Zr','k','Pr','ae','d','zn',
  'return ('+method+')')(v=>v,(_override,component)=>[component,{}],
    'container','svg',()=>({}),values,(obj,key,value)=>(obj[key]=value,obj),k,
    Object.assign,(_props,handler)=>handler,(_props,handler)=>handler,{textarea:'textarea'});
let cleared=0,prevented=0;
const instance={props:{clearable:true,value:'2026/09/16',size:'default',type:'text'},
 state:{isFocusVisibleForClear:false},onClearIconClick:()=>{cleared++}};
const clear=render.call(instance).children[0];
assert.equal(clear.component,'svg');
assert.equal(clear.props.role,'button');
assert.equal(clear.props['aria-label'],'Clear value');
assert.equal(clear.props.title,'Clear value');
assert.equal(clear.props.tabIndex,0);
clear.props.onClick();
for(const key of ['Enter',' '])clear.props.onKeyDown({key,preventDefault:()=>{prevented++}});
clear.props.onKeyDown({key:'Escape',preventDefault:()=>{prevented++}});
assert.equal(cleared,3);assert.equal(prevented,2);
for(const changed of [{value:''},{value:null},{clearable:false},{disabled:true},{readOnly:true}])
 assert.equal(render.call({...instance,props:{...instance.props,...changed}}),null);
'''
    subprocess.run(["node", "-e", code, json.dumps(method)], check=True,
                   capture_output=True, text=True)


def test_native_partial_date_mask_requires_focus_before_replacement_selection():
    """Reproduce the historical wrong date under a focus-order precondition.

    Playwright 1.58 selects an input before focusing it for ``fill``. The locked
    mask's native focus handler moves a partial date's cursor to its end. This
    executes that handler and the vendor's actual mask transform; it is not a
    browser event-timing claim. The CI journey captures the actual input/caret.
    """
    installed = Path(streamlit.__file__).parent / "static" / "static" / "js"
    candidates = [path for path in installed.glob("*.js")
                  if b"t.datepicker.selectSecondDatePrompt" in path.read_bytes()]
    assert len(candidates) == 1
    source = candidates[0].read_text()
    start = source.index('var h={9:`[0-9]`')
    end = source.index('function ne(){var e=RegExp(`windows`', start)
    helpers = source[start:end]
    start = source.index("n.onFocus=function(e){", end) + len("n.onFocus=")
    on_focus = source[start:source.index("},n.onBlur=function(e){", start) + 1]
    start = source.index("n.setCursorToEnd=function(){", end) + len("n.setCursorToEnd=")
    cursor_to_end = source[start:source.index("},n.setSelection=function", start) + 1]
    start = source.index("function re(e){", end)
    is_function = source[start:source.index("function ie(){", start)]
    code = r'''
const assert=require('node:assert/strict');
const {helpers,onFocus,cursorToEnd,isFunction}=JSON.parse(process.argv[1]);
const build=new Function('n',helpers+isFunction+
 ';n.onFocus='+onFocus+';n.setCursorToEnd='+cursorToEnd+';return {parseMask:_,apply:te};');
function replaceDate(focusFirst){
 const n={props:{},value:'2026/09/',selection:{start:0,end:0,length:0},
   runSaveSelectionLoop:()=>{},
   setCursorPosition(position){this.selection={start:position,end:position,length:0};}};
 const {parseMask,apply}=build(n);n.maskOptions=parseMask('9999/99/99',null);
 const selectAll=()=>{n.selection={start:0,end:n.value.length,length:n.value.length};};
 if(focusFirst){n.onFocus({});selectAll();}else{selectAll();n.onFocus({});}
 const before={...n.selection},entered='2026/08/31';
 const raw=n.value.slice(0,before.start)+entered+n.value.slice(before.end);
 const end=before.start+entered.length;
 return {before,raw,result:apply(n.maskOptions,raw,{start:end,end,length:0},n.value,before)};
}
const selectedBeforeFocus=replaceDate(false),focusedBeforeSelect=replaceDate(true);
assert.deepEqual(selectedBeforeFocus.before,{start:8,end:8,length:0});
assert.equal(selectedBeforeFocus.raw,'2026/09/2026/08/31');
assert.equal(selectedBeforeFocus.result.value,'2026/09/20');
assert.deepEqual(focusedBeforeSelect.before,{start:0,end:8,length:8});
assert.equal(focusedBeforeSelect.result.value,'2026/08/31');
'''
    subprocess.run(["node", "-e", code, json.dumps({"helpers": helpers,
                    "onFocus": on_focus, "cursorToEnd": cursor_to_end,
                    "isFunction": is_function})], check=True, capture_output=True, text=True)


def test_native_date_change_uses_cached_selection_and_keyboard_clear_refreshes_it():
    """The actual mask can change correct raw replacement input after capture.

    The mounted CI input received August 31 with the correct selection, then
    displayed September 31. Execute the vendor's actual onChange/onPaste paths
    to distinguish its cached selection from the current native input range.
    This models the internal precondition; it does not inspect browser internals.
    """
    installed = Path(streamlit.__file__).parent / "static" / "static" / "js"
    candidates = [path for path in installed.glob("*.js")
                  if b"t.datepicker.selectSecondDatePrompt" in path.read_bytes()]
    assert len(candidates) == 1
    source = candidates[0].read_text()
    start = source.index('var h={9:`[0-9]`')
    end = source.index('function ne(){var e=RegExp(`windows`', start)
    # Include actual native selection helpers, not a test implementation of
    # the vendor's synchronous cached-selection update.
    native_start = source.index('function p(e,t,n){', source.index('var Ei=t('))
    helpers = source[native_start:end]

    def method(name, next_name):
        start = source.index("n." + name + "=function(", end) + len("n." + name + "=")
        return source[start:source.index("},n." + next_name + "=function", start) + 1]

    start = source.index("function re(e){", end)
    is_function = source[start:source.index("function ie(){", start)]
    start = source.index("function d(e){", source.index("var Ei=t("))
    identity = source[start:source.index("var f=function(", start)]
    code = r'''
const assert=require('node:assert/strict');
const x=JSON.parse(process.argv[1]);
const build=new Function('n','oe','se','document',x.helpers+x.isFunction+x.identity+
 ';n.getInputValue='+x.getInputValue+';n.setInputValue='+x.setInputValue+
 ';n.getSelection='+x.getSelection+';n.setSelection='+x.setSelection+';n.isFocused='+x.isFocused+
 ';n.isInputAutofilled='+x.autofilled+';n.onChange='+x.onChange+';n.onPaste='+x.onPaste+
 ';n.saveSelectionLoop='+x.saveSelectionLoop+';n.runSaveSelectionLoop='+x.runSaveSelectionLoop+
 ';n.setCursorToEnd='+x.setCursorToEnd+';n.setCursorPosition='+x.setCursorPosition+
 ';n.onFocus='+x.onFocus+';n.onMouseDown='+x.onMouseDown+';return _;');
function state(cached,initial='2026/09/'){
 const input={value:initial,selectionStart:0,selectionEnd:initial.length,matches:()=>false};
 // Only native DOM and the animation-frame clock are test adapters. The real
 // setSelection method performs both the DOM write and previousSelection update.
 const frames=new Map(),listeners=new Map();let frameId=0;
 const document={addEventListener:(name,fn)=>listeners.set(name,fn),
  removeEventListener:name=>listeners.delete(name)};
 const n={props:{},value:input.value,focused:true,previousSelection:{...cached},
  mounted:true,selectionDeferId:null,saveSelectionLoopDeferId:null,getInputDOMNode:()=>input};
 const parseMask=build(n,callback=>{frames.set(++frameId,callback);return frameId;},
  id=>frames.delete(id),document);
 n.maskOptions=parseMask('9999/99/99',null);n.input=input;n.frames=frames;n.listeners=listeners;
 n.flushFrame=()=>{for(const[id,fn]of [...frames.entries()])if(frames.has(id)){frames.delete(id);fn();}};
 return n;
}
function deliver(n,raw,selection){
 n.input.value=raw;n.input.selectionStart=selection.start;n.input.selectionEnd=selection.end;
 n.onChange({});assert.equal(n.frames.size,1);return n.value;
}
const stale={start:8,end:8,length:0},current={start:0,end:8,length:8};
assert.equal(deliver(state(stale),'2026/08/31',{start:10,end:10,length:0}),'2026/09/31');
assert.equal(deliver(state(current),'2026/08/31',{start:10,end:10,length:0}),'2026/08/31');
const pasted=state(stale);pasted.onPaste({defaultPrevented:false});
assert.equal(deliver(pasted,'2026/08/31',{start:10,end:10,length:0}),'2026/08/31');
for(const entered of ['2026/08/31','2026/10/01','2026/09/','2026/09/15']){
 const n=state(stale);
 assert.equal(deliver(n,'',{start:0,end:0,length:0}),'');
 assert.deepEqual(n.previousSelection,{start:0,end:0,length:0});
 for(const character of entered){
  const s=n.getSelection(),raw=n.input.value.slice(0,s.start)+character+n.input.value.slice(s.end),end=s.start+1;
  deliver(n,raw,{start:end,end,length:0});
 }
 assert.equal(n.value,entered);
}
// Reproduce the WebKit capture using actual focus/mouse/cache handlers. The
// native input and frame clock are adapters; internal callback order is a model.
function focusAndDelete(settleBeforeSelection,initial='2026/09/'){
 const n=state(stale,initial);n.focused=false;n.previousSelection=null;
 n.input.selectionStart=n.input.selectionEnd=0;
 n.onMouseDown({clientX:0,clientY:0});n.onFocus({});
 n.listeners.get('mouseup')({clientX:0,clientY:0});
 if(settleBeforeSelection){n.flushFrame();n.flushFrame();}
 n.input.selectionStart=0;n.input.selectionEnd=n.input.value.length;
 const selected=n.getSelection();
 if(!settleBeforeSelection)n.flushFrame();
 const beforeDelete=n.getSelection(),cached={...n.previousSelection};
 const start=beforeDelete.start===beforeDelete.end?Math.max(0,beforeDelete.start-1):beforeDelete.start;
 const before=n.input.value;
 n.input.value=n.input.value.slice(0,start)+n.input.value.slice(beforeDelete.end);
 n.input.selectionStart=n.input.selectionEnd=start;
 const raw={value:n.input.value,selection:n.getSelection()};
 // Backspace in an empty input has no native input/change delivery.
 if(n.input.value!==before)n.onChange({});
 return{selected,beforeDelete,cached,raw,value:n.input.value,selection:n.getSelection(),native:n};
}
const lateFrame=focusAndDelete(false),settled=focusAndDelete(true);
assert.deepEqual(lateFrame.selected,{start:0,end:8,length:8});
assert.deepEqual(lateFrame.beforeDelete,{start:8,end:8,length:0});
assert.deepEqual(lateFrame.cached,{start:0,end:8,length:8});
assert.deepEqual(lateFrame.raw,{value:'2026/09',selection:{start:7,end:7,length:0}});
assert.equal(lateFrame.value,'2026/09/');
assert.deepEqual(lateFrame.selection,{start:8,end:8,length:0});
assert.deepEqual(settled.beforeDelete,{start:0,end:8,length:8});
assert.equal(settled.raw.value,'');assert.equal(settled.value,'');
// Empty focus can defer only cursor0; it cannot invalidate its0..0 selection.
// Full dates do not queue an end-cursor move. The partial negative above stays.
// Exercise actual focus/cache/delete/type handlers with and without interleaved
// frames. No empty-input change event is invented to make the model succeed.
for(const initial of ['', '2026/09/14', '2026/09/'])
 for(const settle of [false,true])
  for(const framesWhileTyping of [false,true])
   for(const entered of ['2026/09/14','2026/08/31','2026/10/01','2026/09/']){
    if(initial==='2026/09/'&&!settle)continue; // Proved unsafe above, guard retained.
    const result=focusAndDelete(settle,initial),n=result.native;
    assert.equal(result.value,'');
    if(initial==='')assert.deepEqual(result.beforeDelete,{start:0,end:0,length:0});
    for(const character of entered){
     if(framesWhileTyping)n.flushFrame();
     const selection=n.getSelection(),end=selection.start+1;
     n.input.value=n.input.value.slice(0,selection.start)+character+n.input.value.slice(selection.end);
     n.input.selectionStart=n.input.selectionEnd=end;n.onChange({});
    }
    assert.equal(n.input.value,entered);
   }
'''
    subprocess.run(["node", "-e", code, json.dumps({"helpers": helpers,
                    "isFunction": is_function, "identity": identity,
                    "getInputValue": method("getInputValue", "setInputValue"),
                    "setInputValue": method("setInputValue", "setCursorToEnd"),
                    "getSelection": method("getSelection", "getCursorPosition"),
                    "setSelection": method("setSelection", "getSelection"),
                    "isFocused": method("isFocused", "getBeforeMaskedValueChangeConfig"),
                    "autofilled": method("isInputAutofilled", "onChange"),
                    "onChange": method("onChange", "onFocus"),
                    "onPaste": method("onPaste", "handleRef"),
                    "saveSelectionLoop": method("saveSelectionLoop", "runSaveSelectionLoop"),
                    "runSaveSelectionLoop": method("runSaveSelectionLoop", "stopSaveSelectionLoop"),
                    "setCursorToEnd": method("setCursorToEnd", "setSelection"),
                    "setCursorPosition": method("setCursorPosition", "isFocused"),
                    "onFocus": method("onFocus", "onBlur"),
                    "onMouseDown": method("onMouseDown", "onPaste")})],
                   check=True, capture_output=True, text=True)
