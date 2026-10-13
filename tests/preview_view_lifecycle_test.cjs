// Model repeated Streamlit v2 render invocations on one mounted shadow root.
// This deliberately queues an old observer after the new two-page DOM exists.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag='div') {Object.assign(this,{tag,children:[],dataset:{},style:{},listeners:new Map(),clientHeight:500,clientWidth:400,scrollTop:0,offsetTop:0});}
    append(...children) {this.children.push(...children);}
    replaceChildren(...children) {this.children=children;}
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
    panel.append(new Element('select'));
    for(const action of ['previous','next','enlarge']) {const e=new Element('button');e.dataset.action=action;panel.append(e);}
    return {root,panel};
}

test('new page data disposes prior observers and late callbacks cannot size or request old data',()=>{
    const {root,panel}=dom(), timers=new Map(), sent=[], observers=[];
    let sequence=0;
    class Observer {constructor(callback){this.callback=callback;this.active=true;observers.push(this);}observe(){}disconnect(){this.active=false;}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:callback=>{timers.set(++sequence,callback);return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const invoke=data=>render({parentElement:root,data:{viewScope:'draft-a|activity',pages:[],...data},setStateValue:(name,value)=>sent.push(value)});
    const oldCleanup=invoke({generation:'preparing',sizes:[],ready:false});
    const oldIntersection=observers[0],oldResize=observers[1];
    oldIntersection.callback([{isIntersecting:true}]);
    const newCleanup=invoke({generation:'current',sizes:[[612,792],[612,792]],ready:true});
    assert.equal(panel.querySelectorAll('figure').length,2);
    assert.equal(observers.filter(observer=>observer.active).length,3);
    assert.equal(document.listeners.get('keydown').size,1);
    // Already queued work can run even after disconnect. It must be a no-op.
    assert.doesNotThrow(()=>oldResize.callback());
    oldIntersection.callback([{isIntersecting:false}]);
    oldCleanup(); // A delayed framework unmount cannot cancel this render.
    assert.equal(timers.size,1);
    for(const callback of timers.values())callback();timers.clear();
    assert.equal(sent.length,1);
    assert.equal(sent[0].generation,'current');
    assert.equal(sent[0].visible,true);
    assert.deepEqual(Array.from(sent[0].pages),[0,1]);
    const figures=panel.querySelectorAll('figure');
    figures[0].getBoundingClientRect=()=>({top:-480,bottom:20});
    figures[1].getBoundingClientRect=()=>({top:20,bottom:480});
    observers[4].callback();
    for(const callback of timers.values())callback();timers.clear();
    assert.equal(panel._previewState.page,1,'a preceding caption sliver cannot select the wrong page');
    assert.equal(panel.querySelector('.report-preview-position').textContent,'2 / 2');
    newCleanup();newCleanup();
    assert.equal(observers.filter(observer=>observer.active).length,0);
    assert.equal(document.listeners.get('keydown').size,0);
});

test('delayed workspace cleanup cannot release a newer tabletop scroll owner',()=>{
    const root=new Element(),scrollport=new Element(),app=new Element(),document=new Element();
    const classes=element=>{const values=new Set();element.classList={add:value=>values.add(value),remove:value=>values.delete(value),contains:value=>values.has(value)};};
    [root,scrollport,app].forEach(classes);
    root.closest=selector=>selector.includes('stMainBlockContainer')?app:scrollport;
    const create=document.createElement=tag=>{const element=new Element(tag);element.remove=()=>{};return element;};
    document.querySelector=()=>root;
    const window=new Element();window.matchMedia=()=>new Element();
    const observers=[],frames=new Map();let sequence=0;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const context={window,document,navigator:{},CSS:{escape:value=>value},globalThis:{ENFRAWorkspaceGeometry:{}},ResizeObserver:Observer,MutationObserver:Observer,
        requestAnimationFrame:callback=>{frames.set(++sequence,callback);return sequence;},cancelAnimationFrame:id=>frames.delete(id)};
    const source=fs.readFileSync('app/workspace_layout.js','utf8');
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const previous=render({data:{workflow:'monthly',identity:'same-draft'}});
    const current=render({data:{workflow:'monthly',identity:'same-draft'}});
    // A newer measurement now owns the outer scroller. Delayed old cleanup
    // must not clear this class or cancel the current measurement request.
    scrollport.classList.add('epc-workspace-scroll-owner');
    previous();
    assert.equal(scrollport.classList.contains('epc-workspace-scroll-owner'),true);
    assert.equal(frames.size,1);
    current();current();
    assert.equal(scrollport.classList.contains('epc-workspace-scroll-owner'),false);
    assert.equal(frames.size,0);
});

test('only visible pending preview polls at two seconds and stale invocation cannot poll a new generation',()=>{
    const {root,panel}=dom(),timers=new Map(),sent=[],observers=[];let sequence=0;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:(callback,delay)=>{timers.set(++sequence,{callback,delay});return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const invoke=(generation,pending)=>render({parentElement:root,data:{generation,pending,viewScope:'one|activity',pages:[],sizes:[],ready:false},setStateValue:(name,value)=>sent.push({name,value})});
    const fire=delay=>{const entry=[...timers].find(([,value])=>value.delay===delay);assert.ok(entry,'expected timer '+delay);timers.delete(entry[0]);entry[1].callback();};
    const cleanup=invoke('old',true);
    fire(120);
    assert.equal([...timers.values()].filter(t=>t.delay===2000).length,0,'offscreen pending work does not poll');
    observers[0].callback([{isIntersecting:true}]);fire(120);fire(2000);
    assert.equal(sent.filter(item=>item.name==='poll').length,1);
    assert.equal(sent.at(-1).value.generation,'old');
    assert.equal(sent.at(-1).value.sequence,1);
    const stalePoll=[...timers.values()].find(t=>t.delay===2000).callback;
    const newCleanup=invoke('current',false);cleanup();stalePoll();fire(120);
    assert.equal(sent.filter(item=>item.name==='poll').length,1,'disposed generation cannot send a late poll');
    assert.equal([...timers.values()].filter(t=>t.delay===2000).length,0,'current complete preview does not poll');
    newCleanup();invoke('new-pending',true);fire(120);
    document.hidden=true;document.listeners.get('visibilitychange').forEach(fn=>fn());fire(120);
    assert.equal([...timers.values()].filter(t=>t.delay===2000).length,0,'hidden document suspends pending polls');
    panel._previewCleanup();
    assert.equal(timers.size,0);
});
