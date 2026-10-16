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

function pendingEditorWithSibling() {
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
            pages:[],sizes:[],ready:false},setStateValue:(name,value)=>sent.push({name,value})});};
    const first=mount(editPair),second=mount(otherPair);
    const fire=()=>{for(const [id,item] of [...timers])if(item.delay===120){timers.delete(id);item.callback();}};
    const target={matches:s=>s==='textarea',closest:s=>s.includes('st-key-epc_edit_')?{}:
        s.includes('st-key-epc_pair_')?editPair:null};
    const dispatch=(name,event)=>{for(const fn of app.listeners.get(name)||[])fn(event);};
    dispatch('input',{target});
    const gate=window.__enfraPreviewNativeEditGates.get(app);
    assert.equal(gate.blockAll,false,'unsubmitted typing remains section-scoped');
    return {app,workspace,target,dispatch,fire,gate,sent,intersections,mutations,
        cleanup:()=>{second();first();}};
}

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

test('ordinary Enter, composition, focus, disabled buttons and file pickers do not claim a full rerun',()=>{
    const h=pendingEditorWithSibling();
    for(const event of [{key:'Enter'},{key:'Enter',ctrlKey:true,isComposing:true},{key:'Tab'},{key:'a',ctrlKey:true}])
        h.dispatch('keydown',{target:h.target,...event});
    h.dispatch('click',{target:{closest:s=>'[data-testid="stButton"] button'===s?{disabled:true}:null}});
    h.dispatch('click',{target:{closest:s=>s==='input[type="file"]'?{}:null}});
    h.intersections[1].callback([{isIntersecting:true}]);h.fire();
    assert.equal(h.gate.blockAll,false);assert.equal(h.sent.length,1);
    h.cleanup();
});
