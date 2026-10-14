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

test('viewer presents a scroll-only document without page, fit, zoom or enlarge controls',()=>{
    const file=fs.readFileSync('app/monthly_report_preview_view.py','utf8');
    const html=file.split('\n').find(line=>line.startsWith('HTML = '));
    assert.ok(html && html.includes('report-preview-scroll'));
    assert.ok(html.includes('tabindex="0"'),'native keyboard scrolling remains available');
    assert.ok(html.includes('retry-request') && html.includes(' hidden>'),'only failure retry is present');
    assert.ok(!/<select|data-action="(?:previous|next|enlarge)"|Fit width|Fit page|125%|150%/.test(html),
        'no disabled, hidden, or focusable legacy navigation/zoom widgets remain');
});

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
    assert.equal(document.listeners.has('keydown'),false,'preview has no enlargement Escape handler');
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
    // Explicit source inspection can unmount before the scroll debounce fires.
    // Persist that exact latest offset rather than the previous acknowledgment.
    panel.querySelector('.report-preview-scroll').scrollTop=137;
    newCleanup();newCleanup();
    assert.equal(context.window.__enfraPreviewViews.get('draft-a|activity').offset,137);
    assert.equal(observers.filter(observer=>observer.active).length,0);
    assert.equal(document.listeners.has('keydown'),false);
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

test('hidden remount and cache reload preserve a page anchor until real pagination returns',()=>{
    const {root,panel}=dom(),timers=new Map(),observers=[];let sequence=0;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:callback=>{timers.set(++sequence,callback);return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const invoke=sizes=>render({parentElement:root,data:{generation:'same-content',viewScope:'one|activity',pages:[],sizes,ready:Boolean(sizes.length)},setStateValue:()=>{}});
    const sizes=[[612,792],[612,792],[612,792]];
    invoke(sizes);
    const scroll=panel.querySelector('.report-preview-scroll');
    const figures=scroll.querySelectorAll('figure');
    // A normal scrolling action moves the third page into view. No internal
    // navigation controls or direct preview-state injection are involved.
    figures.forEach((figure,index)=>{
        figure.offsetTop=index*600;
        figure.getBoundingClientRect=()=>({
            top:index*600-scroll.scrollTop,bottom:(index+1)*600-scroll.scrollTop
        });
    });
    assert.equal(figures[0].style.width,'376px','native pages fit the available 400px pane');
    scroll.scrollTop=1273;
    for(const listener of scroll.listeners.get('scroll'))listener();
    for(const callback of [...timers.values()])callback();timers.clear();
    assert.equal(panel._previewState.page,2,'scrolling selects page three');
    // Hide before cleanup, as compact/tabletop may do before a fragment update.
    panel._previewCleanup();
    scroll.clientWidth=0;scroll.clientHeight=0;scroll.scrollTop=0;
    invoke([]);
    assert.equal(panel._previewState.page,2,'unknown pagination cannot clamp to placeholder page one');
    assert.equal(context.window.__enfraPreviewViews.get('one|activity').offset,73);
    assert.equal(panel.querySelector('.report-preview-position').textContent,'—');
    invoke(sizes);
    assert.equal(panel._previewState.page,2);
    const figure=scroll.querySelector('figure[data-index="2"]');
    Object.defineProperty(figure,'offsetTop',{get:()=>scroll.clientWidth*2});
    scroll.clientWidth=600;scroll.clientHeight=400;
    observers.at(-2).callback();
    assert.equal(scroll.scrollTop,1273,'becoming measurable restores exact page and offset');
    assert.equal(panel.querySelector('.report-preview-position').textContent,'3 / 3');
    scroll.clientWidth=450;
    observers.at(-2).callback();
    assert.equal(scroll.scrollTop,973,'resize preserves the same page anchor');
    invoke([[612,792]]);
    assert.equal(panel._previewState.page,0,'known changed pagination uses nearest surviving page');
    panel._previewCleanup();
});

test('tabletop active reference uses its measured upper bounds when observer clips lower ancestor',()=>{
    const {root,panel}=dom(),timers=new Map(),observers=[],sent=[];let sequence=0;
    const workspace=new Element(),pair=new Element();
    workspace.dataset.epcMode='tabletop';pair.dataset.epcActive='true';
    // Only the server-rendered keyed containers exist at first mount. The
    // async layout adapter has not added either presentation class yet.
    root.closest=selector=>selector==='[class*="st-key-epc_workspace_"]'?workspace:
        selector==='[class*="st-key-epc_pair_"]'?pair:null;
    panel.getBoundingClientRect=()=>({left:80,right:1360,top:56,bottom:380,width:1280,height:324});
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1,innerWidth:1440,innerHeight:900},document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:callback=>{timers.set(++sequence,callback);return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const cleanup=render({parentElement:root,data:{generation:'one',viewScope:'expense|receipt2',pages:[],sizes:[],ready:false},setStateValue:(name,value)=>sent.push(value)});
    const fire=()=>{for(const callback of timers.values())callback();timers.clear();};
    observers[0].callback([{isIntersecting:false}]);fire();
    assert.equal(sent.at(-1).visible,true,'visible active upper preview must be admitted');
    pair.dataset.epcActive='false';observers[2].callback();fire();
    assert.equal(sent.at(-1).visible,false,'outgoing receipt cannot continue requesting pages');
    pair.dataset.epcActive='true';document.hidden=true;observers[2].callback();fire();
    assert.equal(sent.at(-1).visible,false,'background pages remain suspended');
    cleanup();
});

test('interrupted viewport delivery reconciles applied server state without repeating acknowledged work',()=>{
    const {root,panel}=dom(),timers=new Map(),observers=[],sent=[];let sequence=0;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:(callback,delay)=>{timers.set(++sequence,{callback,delay});return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const invoke=ack=>render({parentElement:root,data:{generation:'receipt-a',viewScope:'expense|receipt-a',pages:[],sizes:[],ready:false,
        acknowledgedViewport:{visible:ack,pages:[0],dpi:96,generation:'receipt-a'}},setStateValue:(name,value)=>sent.push(value)});
    const fire=(delay=120)=>{for(const [id,item] of [...timers])if(item.delay===delay){timers.delete(id);item.callback();}};
    invoke(false);observers[0].callback([{isIntersecting:true}]);fire();
    assert.equal(sent.length,1);assert.equal(sent[0].visible,true);
    // A competing rerun stored the browser value but did not apply its callback.
    // The canonical server acknowledgment remains false on the next invocation.
    invoke(false);fire();
    assert.equal(sent.length,2,'a send alone cannot leave a visible pane stuck forever');
    assert.ok(sent[1].requestId>sent[0].requestId,'retry must remain a distinct Streamlit state update');
    invoke(true);fire();
    assert.equal(sent.length,2,'acknowledged viewport causes no redundant Python event');
    assert.equal(timers.size,0,'acknowledgment cancels its retry timer');
    invoke(false);fire();
    const start=sent.length;
    fire(2000);fire(2000);fire(2000);
    assert.equal(sent.length,start+2,'no-response delivery retries at most twice');
    assert.equal(timers.size,0,'a disconnected request cannot poll forever');
    assert.equal(panel.querySelector('[data-action="retry-request"]').hidden,false);
    for(let repeat=0;repeat<5;repeat++) {invoke(false);fire();fire(2000);}
    assert.equal(sent.length,start+2,'stale rerenders cannot bypass the transmission budget');
    assert.equal(timers.size,0,'exhausted rerenders cannot restart acknowledgment polling');
    assert.equal(panel.querySelector('[data-action="retry-request"]').hidden,false,'recovery remains available after rerender');
    assert.equal(panel.querySelector('.report-preview-status').textContent,'Preview request interrupted — retry.');
    panel.querySelector('[data-action="retry-request"]').onclick();
    assert.equal(sent.length,start+3,'explicit retry delivers only this bounded view request');
    assert.equal(panel.querySelector('[data-action="retry-request"]').hidden,true);
    fire(2000);fire(2000);fire(2000);
    assert.equal(panel.querySelector('[data-action="retry-request"]').hidden,false);
    // A different desired request receives its own budget and clears the old
    // failure while pending; no click is required to navigate away from it.
    context.window.devicePixelRatio=3;
    panel.querySelector('.report-preview-scroll').clientWidth=600;
    observers.at(-2).callback();fire();
    assert.equal(sent.at(-1).dpi,150);
    assert.equal(panel._previewState.requestAttempts,1);
    assert.equal(panel.querySelector('[data-action="retry-request"]').hidden,true);
    assert.equal(panel.querySelector('.report-preview-status').textContent,'');
    panel._previewCleanup();
    assert.equal(timers.size,0,'unmount cancels pending acknowledgment recovery');
});

test('preview requests and pending polls yield to full editing reruns until framework idle',()=>{
    const {root,panel}=dom(),app=new Element(),timers=new Map(),observers=[],sent=[];let sequence=0;
    app.setAttribute('data-test-script-state','rerunRequested');
    root.closest=selector=>selector==='[data-testid="stApp"]'?app:null;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:(callback,delay)=>{timers.set(++sequence,{callback,delay});return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const fire=delay=>{for(const [id,item] of [...timers])if(item.delay===delay){timers.delete(id);item.callback();}};
    render({parentElement:root,data:{generation:'edit',viewScope:'monthly|activity',pages:[],sizes:[],ready:false,pending:true},
        setStateValue:(name,value)=>sent.push({name,value})});
    observers[0].callback([{isIntersecting:true}]);fire(120);
    assert.equal(sent.length,0,'viewport cannot supersede a queued business edit');
    app.setAttribute('data-test-script-state','running');observers[3].callback();fire(120);
    assert.equal(sent.length,0,'full rerun remains undisturbed');
    app.setAttribute('data-test-script-state','notRunning');observers[3].callback();fire(120);
    assert.equal(sent.length,1);assert.equal(sent[0].name,'viewport');
    app.setAttribute('data-test-script-state','rerunRequested');fire(2000);
    assert.equal(sent.length,1,'an already scheduled pending poll also yields');
    app.setAttribute('data-test-script-state','notRunning');observers[3].callback();fire(120);fire(2000);
    assert.equal(sent.length,2);assert.equal(sent[1].name,'poll');
    panel._previewCleanup();assert.equal(timers.size,0);
});

test('late hidden response retains only the current decoded page during a visible layout return',()=>{
    const {root,panel}=dom(),timers=new Map(),observers=[];let sequence=0;
    class Observer {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const context={window:{devicePixelRatio:1},document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Observer,ResizeObserver:Observer,MutationObserver:Observer,
        setTimeout:callback=>{timers.set(++sequence,callback);return sequence;},clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8').split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const invoke=(pages,generation='current')=>render({parentElement:root,data:{generation,viewScope:'one|activity',
        pages,sizes:[[612,792],[612,792],[612,792]],ready:true},setStateValue:()=>{}});
    invoke([{index:0,image:'first'},{index:1,image:'second'}]);
    panel._previewState.page=1;panel._previewState.visible=true;
    const selected=panel.querySelector('figure[data-index="1"]').querySelector('img');
    invoke([]); // Server applied the outgoing compact/hidden request.
    assert.equal(panel.querySelectorAll('img').length,1);
    assert.equal(panel.querySelector('img'),selected,'same decoded page survives the late empty response');
    invoke([{index:2,image:'next'}]);
    assert.equal(panel.querySelectorAll('img').length,2,'one retained selected page fits the two-image bound');
    invoke([{index:0,image:'new-first'},{index:2,image:'new-next'}]);
    assert.equal(panel.querySelectorAll('img').length,2,'two supplied pages evict any third retained page');
    invoke([{index:1,image:'second'}]);panel._previewState.visible=false;invoke([]);
    assert.equal(panel.querySelectorAll('img').length,0,'an actually hidden surface still releases its images');
    panel._previewState.visible=true;invoke([{index:1,image:'second'}]);invoke([],'new-content');
    assert.equal(panel.querySelectorAll('img').length,0,'new report content cannot inherit old imagery');
    panel._previewCleanup();
});


test('native editing event withholds preview fragments until matching full-render receipt is idle',()=>{
    const {root,panel}=dom(),app=new Element(),workspace=new Element();
    const editPair=new Element(),scorecardPair=new Element();
    const timers=new Map(),sent=[],observers={intersection:[],resize:[],mutation:[]};
    let sequence=0;
    app.setAttribute('data-test-script-state','notRunning');
    workspace.dataset.epcFullRender='full-before-native-edit';
    workspace.dataset.epcMode='wide';
    root.closest=selector=>selector==='[data-testid="stApp"]'?app:
        selector==='[class*="st-key-epc_workspace_"]'?workspace:
        selector==='[class*="st-key-epc_pair_"]'?editPair:null;
    class Intersection {constructor(callback){this.callback=callback;observers.intersection.push(this);}
        observe(){}disconnect(){}}
    class Resize {constructor(callback){this.callback=callback;observers.resize.push(this);}
        observe(){}disconnect(){}}
    class Mutation {constructor(callback){this.callback=callback;observers.mutation.push(this);}
        observe(){}disconnect(){}}
    const document=new Element();document.createElement=tag=>new Element(tag);
    const window={devicePixelRatio:1};
    const context={window,document,Map,JSON,Array,Number,Math,String,Boolean,
        IntersectionObserver:Intersection,ResizeObserver:Resize,MutationObserver:Mutation,
        setTimeout:(callback,delay)=>{timers.set(++sequence,{callback,delay});return sequence;},
        clearTimeout:id=>timers.delete(id)};
    const source=fs.readFileSync('app/monthly_report_preview_view.py','utf8')
        .split('JS = r"""\n')[1].split('\n"""')[0];
    const render=vm.runInNewContext('('+source.replace('export default function','function')+')',context);
    const cleanup=render({parentElement:root,data:{generation:'same',viewScope:'expense|receipt',
        pages:[],sizes:[[612,792]],ready:true},setStateValue:(name,value)=>sent.push({name,value})});
    const fire=delay=>{
        for(const [id,item] of [...timers])if(item.delay===delay){timers.delete(id);item.callback();}
    };
    observers.intersection[0].callback([{isIntersecting:true}]);fire(120);
    assert.equal(sent.length,1);
    const gate=window.__enfraPreviewNativeEditGates.get(app);
    assert.ok(gate && !gate.pending);
    app.listeners.get('change').forEach(fn=>fn({target:{
        matches:selector=>selector.includes('input'),closest:()=>null
    }}));
    assert.equal(gate.pending,true,'the native event queues a whole report rerun');
    panel.querySelector('.report-preview-scroll').clientWidth=1200;
    observers.resize[0].callback();fire(120);
    assert.equal(sent.length,1,'no fragment may overtake pending business input');
    workspace.dataset.epcFullRender='full-after-native-edit';
    app.setAttribute('data-test-script-state','running');
    observers.mutation[0].callback();fire(120);
    assert.equal(gate.pending,true,'a new stamp without script completion is not an acknowledgment');
    assert.equal(sent.length,1,'preview remains deferred during the full run');
    app.setAttribute('data-test-script-state','notRunning');
    observers.mutation[0].callback();fire(120);
    assert.equal(gate.pending,false,'only a distinct completed full-run stamp releases it');
    assert.equal(sent.length,2,'deferred viewport request is sent after canonical editing');
    assert.equal(sent[1].value.dpi,150);
    // Ordinary labels/focus and viewer-native Retry never imply a business
    // rerun; WebKit checkbox labels do, even before their native change event.
    const activate=target=>app.listeners.get('click').forEach(fn=>fn({target}));
    const textLabel={querySelector:()=>null};
    activate({closest:selector=>selector==='label'?textLabel:null});
    assert.equal(gate.pending,false,'text-label focus cannot stall an output preview');
    activate({closest:selector=>selector==='.report-preview'?panel:null});
    assert.equal(gate.pending,false,'preview-owned actions cannot stall themselves');
    const choiceLabel={querySelector:selector=>selector.includes('checkbox')?{}:null};
    activate({closest:selector=>selector==='label'?choiceLabel:null});
    assert.equal(gate.pending,true,'checkbox click guards before a change event bubbles');
    panel.querySelector('.report-preview-scroll').clientWidth=360;
    observers.resize[0].callback();fire(120);
    assert.equal(sent.length,2,'WebKit click must not interleave a fragment with editor rerun');
    workspace.dataset.epcFullRender='full-after-checkbox';
    app.setAttribute('data-test-script-state','running');
    observers.mutation[0].callback();fire(120);
    assert.equal(sent.length,2,'a running full script is not finished');
    app.setAttribute('data-test-script-state','notRunning');
    observers.mutation[0].callback();fire(120);
    assert.equal(gate.pending,false,'click gate releases only on a completed full render');
    assert.equal(sent.length,3,'latest coalesced viewport follows the full editor');
    // WebKit can send view fragments while a long Activity text area is still
    // unblurred through book/tabletop/wide transitions. Its first input event
    // must guard those fragments BEFORE the native change/full-editor rerun.
    const typeInto=target=>app.listeners.get('input').forEach(fn=>fn({target}));
    typeInto({matches:selector=>selector==='input',closest:()=>null});
    assert.equal(gate.pending,false,'ordinary unrelated controls do not stall previews');
    typeInto({matches:selector=>selector==='textarea',
        closest:selector=>selector==='.report-preview'?panel:null});
    assert.equal(gate.pending,false,'typing inside preview is not a report edit');
    typeInto({matches:selector=>selector==='textarea',
        closest:selector=>selector.includes('st-key-epc_edit_')?{}:
            selector.includes('st-key-epc_pair_')?editPair:null});
    assert.equal(gate.pending,true,'unblurred Activity input must guard before blur');
    assert.equal(gate.blockAll,false,'typing does not claim a whole editor rerun');
    assert.equal(gate.scopePair,editPair,'only the edited section is held');
    // A user may scroll the lower tabletop editor to an unrelated section
    // *without blurring* Activity. Its initially unseen preview must still
    // request its first useful page rather than saying loads when visible.
    const {root:siblingRoot}=dom(),siblingSent=[];
    siblingRoot.closest=selector=>selector==='[data-testid="stApp"]'?app:
        selector==='[class*="st-key-epc_workspace_"]'?workspace:
        selector==='[class*="st-key-epc_pair_"]'?scorecardPair:null;
    const siblingCleanup=render({parentElement:siblingRoot,data:{generation:'same',
        viewScope:'expense|scorecards',pages:[],sizes:[[612,792]],ready:true},
        setStateValue:(name,value)=>siblingSent.push({name,value})});
    observers.intersection.at(-1).callback([{isIntersecting:true}]);fire(120);
    assert.equal(siblingSent.length,1,
        'another newly visible section requests content while Activity is still unblurred');
    panel.querySelector('.report-preview-scroll').clientWidth=1200;
    observers.resize[0].callback();fire(120);
    assert.equal(sent.length,3,'the actively edited section withholds its preview while unblurred');
    // Native blur/change now actually starts a full Streamlit render; protect
    // all panes during this short race, then release on the canonical receipt.
    app.listeners.get('change').forEach(fn=>fn({target:{
        matches:selector=>selector.includes('textarea'),closest:()=>null
    }}));
    assert.equal(gate.blockAll,true,'committing native edit protects all sections');
    workspace.dataset.epcFullRender='full-after-unblurred-activity';
    app.setAttribute('data-test-script-state','running');
    observers.mutation[0].callback();fire(120);
    assert.equal(gate.pending,true,'new full-render stamp needs completed editor run');
    app.setAttribute('data-test-script-state','notRunning');
    observers.mutation[0].callback();fire(120);
    assert.equal(gate.pending,false,'acknowledged edited report releases only deferred view requests');
    assert.equal(sent.length,4,'one bounded latest preview request follows full Activity commit');
    assert.equal(Object.hasOwn(gate,'text'),false,'no input or receipt text is copied');
    siblingCleanup();
    cleanup();
    assert.equal(app.listeners.get('input').size,0,'multiline capture listener cleans up');
    assert.equal(app.listeners.get('change').size,0,'all native listeners clean up');
    assert.equal(app.listeners.get('click').size,0,'the label capture listener cleans up');
    assert.equal(window.__enfraPreviewNativeEditGates.get(app),undefined);
});
