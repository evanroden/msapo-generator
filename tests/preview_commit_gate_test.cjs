// Model repeated Streamlit v2 render invocations on one mounted shadow root.
// This deliberately queues an old observer after the new two-page DOM exists.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag='div') {Object.assign(this,{tag,children:[],dataset:{},style:{},listeners:new Map(),clientHeight:500,clientWidth:400,scrollTop:0,offsetTop:0});}
    append(...children) {for(const child of children)child.parent=this;this.children.push(...children);}
    replaceChildren(...children) {this.children=children;}
    remove() {if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);}
    querySelectorAll(selector) {
        const matches = element => selector.startsWith('.') ? element.className===selector.slice(1) :
            selector.startsWith('[data-action=') ? element.dataset.action===selector.match(/"(.*?)"/)[1] :
            selector.startsWith('figure[data-index=') ? element.tag==='figure' && element.dataset.index===selector.match(/"(.*?)"/)[1] : element.tag===selector;
        return this.children.flatMap(child=>[...(matches(child)?[child]:[]),...child.querySelectorAll(selector)]);
    }
    querySelector(selector) {return this.querySelectorAll(selector)[0] || null;}
    addEventListener(type,callback) {if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(callback);}
    removeEventListener(type,callback) {this.listeners.get(type)?.delete(callback);}
    closest() {return null;}
    getBoundingClientRect() {return {top:0,bottom:500};}
    setAttribute(key,value) {this[key]=value;}
    getAttribute(key) {return this[key];}
}
function dom() {
    const root=new Element(), panel=new Element();panel.className='report-preview';root.append(panel);
    for(const name of ['status','scroll','position']) {const e=new Element();e.className='report-preview-'+name;panel.append(e);}
    const retry=new Element('button');retry.dataset.action='retry-request';panel.append(retry);
    return {root,panel};
}

function pendingEditorWithSibling({preparer=false,onPreview=null}={}) {
    const app=new Element(),workspace=new Element(),editPair=new Element(),otherPair=new Element();
    const document=new Element(),window={devicePixelRatio:1},timers=new Map(),sent=[];
    const intersections=[],mutations=[];let sequence=0;
    app.setAttribute('data-test-script-state','notRunning');
    workspace.dataset.epcFullRender='before-submit';workspace.dataset.epcMode='wide';
    document.createElement=tag=>new Element(tag);
    class Intersection {constructor(cb){this.callback=cb;intersections.push(this);}observe(){}disconnect(){}}
    class Mutation {constructor(cb){this.callback=cb;mutations.push(this);}observe(){}disconnect(){}}
    class Resize {constructor(cb){this.callback=cb;}observe(){}disconnect(){}}
    const context={window,document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Intersection,MutationObserver:Mutation,ResizeObserver:Resize,
        setTimeout:(callback,delay)=>{timers.set(++sequence,{callback,delay});return sequence;},
        clearTimeout:id=>timers.delete(id)};
    const code=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+code.replace('export default function','function')+')',context);
    const mount=pair=>{const {root,panel}=dom();
        root.closest=selector=>selector==='[data-testid="stApp"]'?app:
            selector==='[class*="st-key-epc_workspace_"]'?workspace:
            selector==='[class*="st-key-epc_pair_"]'?pair:null;
        return render({parentElement:root,data:{generation:'same',viewScope:pair===editPair?'one|activity':'one|other',
            pages:[],sizes:[],ready:false},setStateValue:(name,value)=>{
                sent.push({name,value});onPreview?.(pair===editPair?'preview-one':'preview-two');
            }});};
    const first=mount(editPair),second=mount(otherPair);
    const fire=()=>{for(const [id,item] of [...timers])if(item.delay===120){timers.delete(id);item.callback();}};
    const target={matches:s=>s==='input,textarea,select' ||
        (preparer?s==='input[aria-label="Prepared by"]':s==='textarea'),
        closest:s=>preparer?null:s.includes('st-key-epc_edit_')?{}:
            s.includes('st-key-epc_pair_')?editPair:null};
    const dispatch=(name,event)=>{for(const fn of app.listeners.get(name)||[])fn(event);};
    dispatch('input',{target});
    const gate=window.__enfraPreviewNativeEditGates.get(app);
    if(!preparer)assert.equal(gate.blockAll,false,'unsubmitted textarea typing remains section-scoped');
    return {app,workspace,target,dispatch,fire,gate,sent,intersections,mutations,
        cleanup:()=>{second();first();}};
}

// Streamlit 1.61.1 WidgetStateManager.scheduleFlush (requirements.lock): the
// first queued fragment survives a later undefined/full request in the same
// zero-ms batch. TextInput's blur commit reaches it through a deferred effect.
// This models that upstream scheduler, independently of the app's preview gate.
class LockedWidgetBatch {
    constructor(){this.scheduledFragmentId=undefined;this.flushScheduled=false;this.hasPreparer=false;}
    schedule(fragmentId,{preparer=false}={}){
        if(this.scheduledFragmentId===undefined)this.scheduledFragmentId=fragmentId;
        this.flushScheduled=true;this.hasPreparer ||= preparer;
    }
    flush(){return {fragment:this.scheduledFragmentId,hasPreparer:this.hasPreparer};}
}

test('locked upstream scheduler can carry a native commit only in an earlier preview fragment',()=>{
    const batch=new LockedWidgetBatch();
    batch.schedule('preview-one');
    batch.schedule(undefined,{preparer:true});
    assert.deepEqual(batch.flush(),{fragment:'preview-one',hasPreparer:true});
});

test('Prepared-by typing holds all identity-dependent previews before deferred native Tab commit',()=>{
    const batch=new LockedWidgetBatch();
    const h=pendingEditorWithSibling({preparer:true,onPreview:fragment=>batch.schedule(fragment)});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    // Native change capture happens before React's deferred onBlur effect.
    // It cannot retract a fragment that the viewer already queued while typing.
    h.dispatch('change',{target:h.target});
    batch.schedule(undefined,{preparer:true});
    assert.deepEqual(batch.flush(),{fragment:undefined,hasPreparer:true},
        'corrected attribution must request a full editor run, not ride only in a preview fragment');
    assert.equal(h.gate.blockAll,true);
    h.workspace.dataset.epcFullRender='after-preparer';
    h.mutations[0].callback();h.fire();
    assert.equal(h.sent.length,2,'distinct completed full receipt releases both reference viewers');
    h.cleanup();
});

for(const shiftKey of [false,true])
test((shiftKey?'Shift+Tab':'Tab')+' promotes a pending native textarea edit before focus geometry can queue a fragment',()=>{
    const batch=new LockedWidgetBatch();
    const h=pendingEditorWithSibling({onPreview:fragment=>batch.schedule(fragment)});
    // A browser moves focus/scroll after this keydown and before its native
    // change/blur handlers. An adjacent preview must not claim that batch.
    h.dispatch('keydown',{target:h.target,key:'Tab',shiftKey,isComposing:false});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    h.dispatch('change',{target:h.target});
    batch.schedule(undefined,{preparer:true});
    assert.deepEqual(batch.flush(),{fragment:undefined,hasPreparer:true},
        'the native textarea commit needs a full editor run even when Tab changes preview geometry');
    h.cleanup();
});

test('Tab without a pending native edit does not claim a full editor rerun',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('keydown',{target:h.target,key:'Tab',isComposing:false});
    assert.equal(h.gate.pending,false);assert.equal(h.gate.blockAll,false);
    h.cleanup();
});

for(const modifier of ['ctrlKey','metaKey'])test(modifier+' Enter commits cannot coalesce with another preview fragment',()=>{
    const h=pendingEditorWithSibling();
    h.dispatch('keydown',{target:h.target,key:'Enter',[modifier]:true,isComposing:false});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.sent.length,0,'the committing keyboard event must hold every preview before React batches it');
    assert.equal(h.gate.blockAll,true);
    h.workspace.dataset.epcFullRender='after-submit';
    h.app.setAttribute('data-test-script-state','running');
    h.mutations[0].callback();h.fire();assert.equal(h.sent.length,0);
    h.app.setAttribute('data-test-script-state','notRunning');
    h.mutations[0].callback();h.fire();assert.equal(h.sent.length,2);
    h.cleanup();assert.equal(h.app.listeners.get('keydown').size,0);
});

test('native Streamlit action click holds adjacent previews before the full rerun',()=>{
    const h=pendingEditorWithSibling();
    const button={disabled:false};
    h.dispatch('click',{target:{closest:s=>s==='[data-testid="stButton"] button'?button:null}});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.sent.length,0,'a source-manager/Include button cannot be overtaken by a preview request');
    assert.equal(h.gate.blockAll,true);h.cleanup();
});

test('shared-history disclosure holds queued preview work until its native full-render acknowledgment',()=>{
    const h=pendingEditorWithSibling();
    h.gate.pending=false;h.gate.scopePair=null;
    // The production keyed disclosure has on_change="rerun". Its normal
    // summary click is neither an input change nor an stButton activation.
    const disclosure={classList:['stExpander','st-key-report_history_open']};
    const summary={closest:s=>s==='[class*="_history_open"]'?disclosure:null};
    h.intersections[1].callback([{isIntersecting:true}]);
    h.dispatch('click',{target:{closest:s=>s==='summary'?summary:null}});
    assert.equal(h.gate.pending,true,'opening history must claim its actual full editor rerun');
    assert.equal(h.gate.blockAll,true);
    h.fire();assert.equal(h.sent.length,0,'queued disposable previews cannot overtake opening history');
    h.workspace.dataset.epcFullRender='history-opened';
    h.app.setAttribute('data-test-script-state','running');
    h.mutations[0].callback();h.fire();assert.equal(h.sent.length,0);
    h.app.setAttribute('data-test-script-state','notRunning');
    h.mutations[0].callback();h.fire();assert.equal(h.sent.length,2);
    h.cleanup();
});

for(const name of ['st-key-report_help','st-key-report_history_open_notes'])
test('ordinary disclosure does not strand previews awaiting a nonexistent full render: '+name,()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const summary={closest:s=>s==='[class*="_history_open"]'?{classList:[name]}:null};
    h.dispatch('click',{target:{closest:s=>s==='summary'?summary:null}});
    assert.equal(h.gate.pending,false);assert.equal(h.gate.blockAll,false);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,2);
    h.cleanup();
});

for(const referenceSelector of ['[class*="st-key-epc_reference_"]','.epc-workspace-reference'])
test('fragment Retry preview does not await an impossible full rerun: '+referenceSelector,()=>{
    const h=pendingEditorWithSibling();
    h.gate.pending=false;h.gate.scopePair=null;
    const button={disabled:false},reference={};
    h.dispatch('click',{target:{closest:s=>s===referenceSelector?reference:
        s==='[data-testid="stButton"] button'?button:null}});
    assert.equal(h.gate.pending,false,'reference-only fragment controls cannot open a full-editor hold');
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.sent.length,2,'both eligible previews remain able to send after a fragment Retry action');
    h.cleanup();
});

test('ordinary Enter, composition, focus, disabled buttons and file pickers do not claim a full rerun',()=>{
    const h=pendingEditorWithSibling();
    for(const event of [{key:'Enter'},{key:'Enter',ctrlKey:true,isComposing:true},
        {key:'Tab',isComposing:true},{key:'Tab',ctrlKey:true},{key:'Tab',altKey:true},
        {key:'Tab',metaKey:true},{key:'a',ctrlKey:true}])
        h.dispatch('keydown',{target:h.target,...event});
    h.dispatch('click',{target:{closest:s=>'[data-testid="stButton"] button'===s?{disabled:true}:null}});
    h.dispatch('click',{target:{closest:s=>s==='input[type="file"]'?{}:null}});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.gate.blockAll,false);assert.equal(h.sent.length,1);
    h.cleanup();
});

// #293 (R6-9): a gesture that submits nothing never receives a full-render
// receipt, so it must not open a hold that would strand every preview.
const labelClick=choice=>({target:{closest:s=>s==='label'?{querySelector:()=>choice}:null}});
const choice=(type,{checked=false,disabled=false,ariaDisabled=null}={})=>
    ({type,checked,disabled,getAttribute:name=>name==='aria-disabled'?ariaDisabled:null});

for(const [name,control] of [
    ['an already-selected radio',choice('radio',{checked:true})],
    ['a disabled checkbox',choice('checkbox',{disabled:true})],
    ['an aria-disabled radio',choice('radio',{ariaDisabled:'true'})]])
test('clicking the label of '+name+' does not open the preview hold',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('click',labelClick(control));
    assert.equal(h.gate.pending,false,'no editor run follows, so no receipt could release it');
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.sent.length,2,'both previews stay able to load');
    h.cleanup();
});

for(const control of [choice('radio'),choice('checkbox'),choice('checkbox',{checked:true})])
test('a real '+control.type+(control.checked?' uncheck':' choice')+' still holds previews until its full render',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('click',labelClick(control));
    assert.equal(h.gate.pending,true);assert.equal(h.gate.blockAll,true);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,0);
    h.workspace.dataset.epcFullRender='after-choice';h.mutations[0].callback();h.fire();
    assert.equal(h.sent.length,2);h.cleanup();
});

const fileInput=(files,accept='.pdf,.docx,image/*')=>({type:'file',files,
    matches:s=>s==='input,textarea,select',closest:()=>null,
    getAttribute:name=>name==='accept'?accept:null});

for(const [name,files] of [
    ['a file type the uploader rejects',[{name:'synthetic-notes.txt',type:'text/plain'}]],
    ['only rejected files',[{name:'synthetic.exe',type:''},{name:'synthetic.txt',type:'text/plain'}]],
    ['an emptied file picker',[]]])
test(name+' does not open the preview hold',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('change',{target:fileInput(files)});
    assert.equal(h.gate.pending,false);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,2);
    h.cleanup();
});

for(const [name,files,accept] of [
    ['an accepted extension',[{name:'Synthetic Report.DOCX',type:''}],'.pdf,.docx'],
    ['an accepted media type',[{name:'synthetic-photo',type:'image/png'}],'image/*'],
    ['an uploader without a type list',[{name:'synthetic.bin',type:''}],null],
    // The uploader judges each file; one accepted file still starts a run.
    ['a mix with one accepted file',[{name:'synthetic.exe',type:''},{name:'synthetic.pdf',type:'application/pdf'}],'.pdf']])
test(name+' still holds previews until the upload run renders',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('change',{target:fileInput(files,accept)});
    assert.equal(h.gate.pending,true);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,0);
    h.workspace.dataset.epcFullRender='after-upload';h.mutations[0].callback();h.fire();
    assert.equal(h.sent.length,2);h.cleanup();
});


// A radio activated directly is checked before its click is dispatched.
const radioInput=(checked,group=null)=>{const radio={type:'radio',checked,disabled:false,getAttribute:()=>null,
    matches:s=>s==='input[type="radio"]'||s==='input,textarea,select'};
    radio.closest=s=>s==='label'?{querySelector:()=>radio}:s==='[role="radiogroup"]'?group:null;return radio;};

for(const gesture of ['keydown','pointerdown'])
test('a new radio choice activated directly ('+gesture+') still holds previews',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const radio=radioInput(false);
    h.dispatch(gesture,{target:radio,key:' ',isComposing:false});
    radio.checked=true;  // the browser checks it before dispatching the click
    h.dispatch('click',{target:radio});
    assert.equal(h.gate.pending,true);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,0);
    h.cleanup();
});

test('Space on the radio that is already selected does not open the hold',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const radio=radioInput(true);
    h.dispatch('keydown',{target:radio,key:' ',isComposing:false});
    h.dispatch('click',{target:radio});
    assert.equal(h.gate.pending,false);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,2);
    h.cleanup();
});

test('an arrow-key selection within a radio group holds previews',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const members=[];const group={querySelectorAll:()=>members};
    const old=radioInput(true,group),next=radioInput(false,group);members.push(old,next);
    h.dispatch('keydown',{target:old,key:'ArrowDown',isComposing:false});
    old.checked=false;next.checked=true;  // the browser moves the selection
    h.dispatch('click',{target:next});
    assert.equal(h.gate.pending,true,'the newly selected radio was recorded unselected at keydown');
    h.cleanup();
});

test('a scripted click on the selected radio with no gesture does not open the hold',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    h.dispatch('click',{target:radioInput(true)});
    assert.equal(h.gate.pending,false,'no change event follows, so no run could release a hold');
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,2);
    h.cleanup();
});

test('a scripted click that does change a radio is held by its change event',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const radio=radioInput(true);
    h.dispatch('click',{target:radio});
    h.dispatch('change',{target:radio});  // fired in the same task after the activation
    assert.equal(h.gate.pending,true);
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();assert.equal(h.sent.length,0);
    h.cleanup();
});


for(const selected of [true,false])
test('a label click and its forwarded input click agree ('+(selected?'already selected':'new choice')+')',()=>{
    const h=pendingEditorWithSibling();h.gate.pending=false;h.gate.scopePair=null;
    const radio=radioInput(selected),text={closest:s=>s==='label'?{querySelector:()=>radio}:null};
    h.dispatch('pointerdown',{target:text});
    h.dispatch('click',{target:text});
    radio.checked=true;  // the browser then forwards a click to the input
    h.dispatch('click',{target:radio});
    assert.equal(h.gate.pending,!selected,selected?'re-clicking the selected option starts no run':'a new choice holds');
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.sent.length,selected?2:0);
    h.cleanup();
});


test('old workspace cleanup cannot evict a newer live native editor gate',()=>{
    // During a site/report switch Streamlit may mount a new keyed workspace
    // before disposing the old preview. Both editors share the same stApp,
    // but their gate ownership and full-render receipts are independent.
    const app=new Element(),oldWorkspace=new Element(),nextWorkspace=new Element();
    const oldPair=new Element(),nextPair=new Element();
    app.setAttribute('data-test-script-state','notRunning');
    oldWorkspace.dataset.epcFullRender='old-before';
    nextWorkspace.dataset.epcFullRender='new-before';
    const document=new Element(),window={devicePixelRatio:1},timers=new Map(),sent=[];
    const intersections=[],mutations=[];let seq=0;
    document.createElement=tag=>new Element(tag);
    class Intersection {constructor(callback){this.callback=callback;intersections.push(this);}observe(){}disconnect(){}}
    class Mutation {constructor(callback){this.callback=callback;mutations.push(this);}observe(){}disconnect(){}}
    class Resize {constructor(callback){this.callback=callback;}observe(){}disconnect(){}}
    const context={window,document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Intersection,MutationObserver:Mutation,ResizeObserver:Resize,
        setTimeout:(callback,delay)=>{timers.set(++seq,{callback,delay});return seq;},
        clearTimeout:id=>timers.delete(id)};
    const code=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+code.replace('export default function','function')+')',context);
    const mount=(workspace,pair,where)=>{
        const {root,panel}=dom();
        root.closest=selector=>selector==='[data-testid="stApp"]'?app:
            selector==='[class*="st-key-epc_workspace_"]'?workspace:
            selector==='[class*="st-key-epc_pair_"]'?pair:null;
        const cleanup=render({parentElement:root,data:{generation:'one',
            viewScope:where,pages:[],sizes:[],ready:false},
            setStateValue:(name,value)=>sent.push({where,name,value})});
        return {cleanup,panel};
    };
    const fire=()=>{
        for(const [id,item] of [...timers]){
            if(item.delay===120){timers.delete(id);item.callback();}
        }
    };
    const old=mount(oldWorkspace,oldPair,'old|activity');
    const map=window.__enfraPreviewNativeEditGates,oldGate=map.get(app);
    assert.ok(oldGate);assert.equal(oldGate.refs,1);
    const first=mount(nextWorkspace,nextPair,'new|activity');
    const current=map.get(app);
    assert.ok(current&&current!==oldGate);
    assert.equal(current.refs,1);
    assert.equal(app.listeners.get('change').size,2,
        'old gate exists briefly until its old preview is disposed');

    old.cleanup(); // old mounted preview unmounts AFTER the new gate exists
    assert.equal(map.get(app),current,
        'retiring an older gate must not delete the new workspace ownership');
    assert.equal(app.listeners.get('change').size,1);
    const second=mount(nextWorkspace,nextPair,'new|evidence');
    assert.equal(map.get(app),current,
        'a new sibling preview must reuse the existing new-workspace gate');
    assert.equal(current.refs,2);
    assert.equal(app.listeners.get('change').size,1,
        'gate must not create a second native editor input/change listener');

    // The new gate still blocks view traffic during an actual native edit.
    const target={type:'text',matches:s=>s==='input,textarea,select',closest:()=>null};
    for(const listener of app.listeners.get('change'))listener({target});
    assert.equal(current.pending,true);assert.equal(current.blockAll,true);
    // Select each newly visible reference and drain only normal viewport timers.
    intersections[1].callback([{isIntersecting:true}]);
    intersections[2].callback([{isIntersecting:true}]);
    fire();
    assert.equal(sent.filter(x=>x.name==='viewport'&&x.value.visible).length,0,
        'no visible reference may overtake the full editor commit');

    nextWorkspace.dataset.epcFullRender='new-after-native-edit';
    for(const observer of mutations)observer.callback();
    assert.equal(current.pending,false,'only the new workspace receipt releases its hold');
    fire();
    assert.equal(sent.filter(x=>x.name==='viewport'&&x.value.visible).length,2,
        'both new-workspace previews may resume only after that receipt');

    first.cleanup();
    assert.equal(map.get(app),current);
    assert.equal(current.refs,1);
    second.cleanup();
    assert.equal(map.get(app),undefined);
    assert.equal(app.listeners.get('change').size,0);
    assert.equal(timers.size,0);
});
