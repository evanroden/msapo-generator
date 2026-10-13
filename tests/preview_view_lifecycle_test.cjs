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
    newCleanup();newCleanup();
    assert.equal(observers.filter(observer=>observer.active).length,0);
    assert.equal(document.listeners.get('keydown').size,0);
});
