"""Execute the actual QA predicate; no browser, generated image or product mutation."""
import ast
import json
from pathlib import Path
import subprocess

SOURCE = Path(__file__).parents[1] / 'scripts/qa_expense_adaptive.py'


def test_current_image_readiness_atomic_negative_controls():
    tree = ast.parse(SOURCE.read_text())
    predicate = next(ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == '_LOADED_PAGE_READY' for t in n.targets))
    program = r'''
const assert=require('node:assert/strict');
const ready=eval('('+PREDICATE+')');
const expected={owner:'expense_packet',scope:'current-generation',index:1};
let markers,panels,figures,images,shadow=true;
const shadowRoot={querySelectorAll:s=>s==='.report-preview'?panels:[]};
const host={shadowRoot};
const pair={isConnected:true,querySelectorAll:s=>s==='*'&&shadow?[host]:s==='.report-preview'&&!shadow?panels:[]};
const marker={dataset:{epcPair:expected.owner},closest:()=>pair};
const panel={_previewState:{scope:expected.scope},querySelectorAll:s=>s==='figure[data-index="1"]'?figures:[]};
const figure={querySelectorAll:s=>s==='img'?images:[]};
const jpeg='data:image/jpeg;base64,NEW';
function image(){return {isConnected:true,src:jpeg,currentSrc:jpeg,complete:true,naturalWidth:1275,naturalHeight:1650,
 getAttribute(n){return this.src},getClientRects:()=>[{}],getBoundingClientRect:()=>({width:500,height:650}),
 style:{visibility:'visible',display:'block'}}}
global.document={querySelectorAll:()=>markers};global.getComputedStyle=n=>n.style;
function reset(){markers=[marker];panels=[panel];figures=[figure];images=[image()];pair.isConnected=true;panel._previewState.scope=expected.scope;}
reset();assert.equal(ready(expected),true); // actual component's open shadow root
shadow=false;assert.equal(ready(expected),true);shadow=true;
const nested={querySelectorAll:s=>s==='*'?[{shadowRoot}]:[]};
host.shadowRoot=nested;assert.equal(ready(expected),true);host.shadowRoot=shadowRoot;
// Pending decode never authorizes, then the SAME current image can become ready.
images[0].complete=false;images[0].naturalWidth=0;assert.equal(ready(expected),false);
images[0].complete=true;assert.equal(ready(expected),false);images[0].naturalWidth=1275;assert.equal(ready(expected),true);
reset();images[0].currentSrc='data:image/jpeg;base64,OLD';assert.equal(ready(expected),false);
reset();images[0].src='';assert.equal(ready(expected),false);
reset();images[0].src=images[0].currentSrc='data:image/png;base64,OTHER';assert.equal(ready(expected),false);
reset();images[0].naturalHeight=0;assert.equal(ready(expected),false);
reset();images[0].naturalWidth=0;assert.equal(ready(expected),false); // complete broken image
reset();const old=images[0];old.isConnected=false;assert.equal(ready(expected),false);
images=[image()];assert.equal(ready(expected),true); // reacquire replacement, never retained old handle
reset();markers=[marker,marker];assert.equal(ready(expected),false);
reset();panels=[panel,panel];assert.equal(ready(expected),false);
reset();figures=[figure,figure];assert.equal(ready(expected),false);
reset();images.push(image());assert.equal(ready(expected),false);
reset();panel._previewState.scope='old-generation';assert.equal(ready(expected),false);
reset();markers=[];assert.equal(ready(expected),false);
reset();images=[];assert.equal(ready(expected),false);
reset();pair.isConnected=false;assert.equal(ready(expected),false);
reset();images[0].getClientRects=()=>[];assert.equal(ready(expected),false);
reset();images[0].getBoundingClientRect=()=>({width:0,height:1});assert.equal(ready(expected),false);
for(const visibility of ['hidden','collapse']){reset();images[0].style.visibility=visibility;assert.equal(ready(expected),false);}
reset();images[0].style.display='none';assert.equal(ready(expected),false);
reset();host.shadowRoot={querySelectorAll:s=>s==='*'?Array(8193).fill({}):panels};assert.equal(ready(expected),false);
reset();host.shadowRoot={querySelectorAll:s=>s==='*'?Array(65).fill({shadowRoot}):[]};assert.equal(ready(expected),false);
host.shadowRoot=shadowRoot;reset();assert.equal(ready(expected),true);
console.log('atomic image controls passed');
'''.replace('PREDICATE', json.dumps(predicate))
    result = subprocess.run(['node', '-e', program], text=True, capture_output=True, check=True)
    assert result.stdout.strip() == 'atomic image controls passed'


def test_helper_uses_one_existing_five_second_wait_without_retry_or_dom_write():
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'loaded_page')
    waits = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'wait_for_function']
    assert len(waits) == 1
    assert next(k.value.id for k in waits[0].keywords if k.arg == 'timeout') == 'remaining'
    assert 'deadline=time.monotonic()+5' in ast.get_source_segment(SOURCE.read_text(), fn)
    assert 'remaining=(deadline-time.monotonic())*1000' in ast.get_source_segment(SOURCE.read_text(), fn)
    assert 'if remaining<=0:' in ast.get_source_segment(SOURCE.read_text(), fn)
    assert not any(isinstance(n, (ast.For, ast.While, ast.Try)) for n in ast.walk(fn))
    text = ast.get_source_segment(SOURCE.read_text(), fn)
    assert 'sleep' not in text and 'setAttribute' not in text and 'dispatchEvent' not in text
    assert "expected['index']=index" in text
