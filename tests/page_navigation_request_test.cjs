const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');
function harness() {
    const state={mode:'wide',ownsScroll:false,identity:'report'};
    const rect=(top,height)=>({top,bottom:top+height,height});
    const scrollport={scrollTop:0,getBoundingClientRect:()=>rect(0,900)};
    const root={dataset:{},scrollTop:0,getBoundingClientRect:()=>rect(300-scrollport.scrollTop,3500)};
    const field={isConnected:true,disabled:false,parentElement:null,closest:()=>null,getClientRects:()=>[{}],focus(){focus++},scrollIntoView(){}};
    const parent={children:[],querySelector:()=>null,append(value){this.children.push(value)}};
    const marker={id:'report-correction-'+'a'.repeat(64),isConnected:true,dataset:{reportIdentity:'report',fieldKey:'caption',fieldKind:'input'},closest:()=>null,parentElement:parent};
    const link={isConnected:true,dataset:{reportIdentity:'report',token:'first'},getAttribute:()=> '#'+marker.id,closest:()=>null,parentElement:parent};
    let requests=[link],focus=0,schedules=0;
    const pair=(top,inside=false)=>({isConnected:true,contains:node=>inside&&node===marker,querySelector:()=>null,setAttribute(){},focus(){},getBoundingClientRect:()=>rect(top-scrollport.scrollTop,500)});
    const water=pair(1500,true),review=pair(4000),cover=pair(300);
    const back={disabled:false},next={disabled:false,textContent:'Next'},progress={dataset:{},textContent:''};
    const nav={getBoundingClientRect:()=>rect(64,52),querySelector:selector=>({'.epc-section-back':back,'.epc-section-next':next,'.epc-section-progress':progress})[selector]||null};
    const handlers={};
    const app={contains:node=>node.isConnected,querySelector:()=>review,
        querySelectorAll:selector=>selector==='.enfra-page-correction-request'?requests:selector==='.enfra-picture-correction'?[marker]:selector==='.st-key-caption input'?[field]:[],
        addEventListener(type,fn){handlers[type]=fn},removeEventListener(type){delete handlers[type]}};
    const context={document:{activeElement:null,createElement:()=>({})},CSS:{escape:x=>x},Promise};
    vm.createContext(context);
    for(const file of ['monthly_report_correction_navigation.js','workspace_navigation.js'])vm.runInContext(fs.readFileSync('app/'+file,'utf8'),context);
    const controller=context.ENFRAWorkspaceNavigation.create({root,app,scrollport,nav,state,geometry,schedule(){schedules++}});
    function measure(){const resolved=controller.prepare({mode:'wide',reason:'normal'},
        {chromeBottom:64,scrollport:{y:0},visual:{y:0}},[
        {id:'monthly_cover',title:'Cover',pair:cover},{id:'monthly_water',title:'Water',pair:water}]);
        controller.update(resolved,{chromeBottom:64,scrollport:{y:0},visual:{y:0}})}
    return {measure,state,link,marker,requests:value=>requests=value,counts:()=>({focus,schedules}),handlers};
}
const settled=async()=>{await Promise.resolve();await Promise.resolve();};
test('a committed exact page request navigates and focuses once across passive rerenders',async()=>{
    const h=harness();h.measure();await settled();assert.equal(h.state.navigationActive,'monthly_water');assert.equal(h.counts().focus,1);
    const before=h.counts();h.measure();h.measure();await settled();assert.deepEqual(h.counts(),before);
});
test('duplicate current request signals cannot choose an arbitrary owner',async()=>{
    const h=harness();h.requests([h.link,{...h.link}]);h.measure();await settled();assert.equal(h.counts().focus,0);assert.equal(h.counts().schedules,0);
});
test('a previously consumed nonce never regains focus after a newer request',async()=>{
    const h=harness();h.measure();await settled();h.link.dataset.token='second';h.measure();await settled();assert.equal(h.counts().focus,2);
    h.link.dataset.token='first';h.measure();await settled();assert.equal(h.counts().focus,2);
});
test('a newer native action cancels the queued display focus',async()=>{
    const h=harness();h.measure();h.handlers.pointerdown();await settled();assert.equal(h.counts().focus,0);
});

// Integrated scheduler delivery regressions run in the existing hosted Node contract.
{
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');

// An offline DOM/observer protocol double. Run the actual layout, navigation
// controller and exact-field resolver, including their RAF and cleanup paths.
// Delivery honors the options registered by production, never calls measure
// directly, and records the adapter's own attribute/child-list writes too.
function schedulerHarness(width=390) {
    const observers=[],frames=new Map();let sequence=0,measurements=0,focus=0;
    function deliver(record) {
        for(const observer of [...observers]) {
            if(observer.kind!=='mutation')continue;
            for(const [target,options] of observer.targets) {
                if(target!==record.target && !(options.subtree&&target.contains(record.target)))continue;
                const admitted=record.type==='childList'?options.childList:options.attributes&&
                    (!options.attributeFilter||options.attributeFilter.includes(record.attributeName));
                if(admitted){observer.callback([record]);break;}
            }
        }
    }
    const dataName=key=>'data-'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase());
    let document;
    function element(tag='DIV',className='') {
        const values=new Set(className.split(' ').filter(Boolean)),queries=new Map();let content='';
        const node={tagName:tag,isConnected:true,parentElement:null,children:[],scrollTop:0,
            handlers:new Map(),queries,
            append(child){child.parentElement=this;this.children.push(child);deliver({type:'childList',target:this});},
            prepend(child){child.parentElement=this;this.children.unshift(child);deliver({type:'childList',target:this});},
            insertBefore(child,before){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(x=>x!==child);child.parentElement=this;this.children.splice(this.children.indexOf(before),0,child);deliver({type:'childList',target:this});},
            remove(){this.isConnected=false;if(this.parentElement){this.parentElement.children=this.parentElement.children.filter(x=>x!==this);deliver({type:'childList',target:this.parentElement});}},
            contains(child){for(let n=child;n;n=n.parentElement)if(n===this)return true;return false;},
            setAttribute(name,value){this[name]=String(value);deliver({type:'attributes',target:this,attributeName:name});},
            getAttribute(name){return this[name]??null;},hasAttribute(name){return this[name]!==undefined;},
            matches(selector){return selector[0]==='.'?values.has(selector.slice(1)):selector[0]==='#'?this.id===selector.slice(1):
                selector==='[data-stale="true"]'?this.dataset.stale==='true':selector==='[inert]'?Boolean(this.inert):
                selector==='[data-epc-pair]'?Boolean(this.dataset.epcPair):this.tagName.toLowerCase()===selector;},
            closest(selector){for(let n=this;n;n=n.parentElement)if(n.matches?.(selector))return n;return null;},
            querySelectorAll(selector){
                const parts=selector.split(' '),last=parts.pop(),found=[];
                const visit=n=>{for(const child of n.children){
                    if(child.matches(last)&&(!parts.length||child.parentElement?.closest(parts.join(' '))))found.push(child);visit(child);
                }};visit(this);return found;
            },
            querySelector(selector){return queries.has(selector)?queries.get(selector):this.querySelectorAll(selector)[0]||null;},
            addEventListener(type,fn){if(!this.handlers.has(type))this.handlers.set(type,new Set());this.handlers.get(type).add(fn);},
            removeEventListener(type,fn){this.handlers.get(type)?.delete(fn);},
            dispatchEvent(event){for(const fn of [...(this.handlers.get(event.type)||[])])fn(event);},
            getBoundingClientRect:()=>({x:0,y:0,left:0,top:0,right:width,bottom:900,width,height:900}),
            getClientRects:()=>[{}],focus(){document.activeElement=this;},scrollIntoView(){},
        };
        const changed=name=>deliver({type:'attributes',target:node,attributeName:name});
        Object.defineProperty(node,'nextElementSibling',{get:()=>node.parentElement?.children[node.parentElement.children.indexOf(node)+1]||null});
        node.dataset=new Proxy({}, {set(target,key,value){target[key]=String(value);changed(dataName(key));return true;},
            deleteProperty(target,key){delete target[key];changed(dataName(key));return true;}});
        node.classList={add(value){values.add(value);changed('class');},remove(value){values.delete(value);changed('class');},
            contains:value=>values.has(value),toggle(value,on){on?values.add(value):values.delete(value);changed('class');}};
        Object.defineProperty(node,'className',{get:()=>[...values].join(' '),set(value){values.clear();value.split(' ').forEach(x=>values.add(x));changed('class');}});
        Object.defineProperty(node,'disabled',{get:()=>Boolean(node._disabled),set(value){node._disabled=value;changed('disabled');}});
        Object.defineProperty(node,'textContent',{get:()=>content,set(value){content=value;deliver({type:'childList',target:node});}});
        node.style={setProperty(){changed('style');}};
        return node;
    }
    const scrollport=element(),app=element(),root=element(),nav=element(),review=element();
    scrollport.append(app);app.append(root);app.append(review);root.append(nav);
    review.id='report-review';
    const rect=(top,height)=>({x:0,y:top,left:0,top,right:width,bottom:top+height,width,height});
    root.getBoundingClientRect=()=>rect(300-scrollport.scrollTop,3500);
    review.getBoundingClientRect=()=>rect(4000-scrollport.scrollTop,60);
    root.closest=selector=>selector.includes('stMainBlockContainer')?app:scrollport;
    nav.getBoundingClientRect=()=>rect(0,52);
    const back=element('BUTTON','epc-section-back'),next=element('BUTTON','epc-section-next'),progress=element('SPAN','epc-section-progress');
    nav.append(back);nav.append(next);nav.append(progress);
    function pair(id,top) {
        const pair=element('DIV','st-key-epc_pair_'+id),marker=element(),editor=element('DIV','st-key-epc_edit_'+id),reference=element('DIV','st-key-epc_reference_'+id);
        const row=element(),editColumn=element(),refColumn=element();row.dataset.testid='stHorizontalBlock';
        root.append(pair);pair.append(marker);pair.append(row);row.append(editColumn);row.append(refColumn);editColumn.append(editor);refColumn.append(reference);
        marker.dataset.epcPair=id;marker.dataset.epcTitle=id;
        editor.closest=()=>editColumn;reference.closest=()=>refColumn;
        pair.getBoundingClientRect=()=>rect(top-scrollport.scrollTop,500);
        return {pair,editor};
    }
    pair('monthly_cover',300);const activity=pair('monthly_activity',1500);
    const owner=element('DIV','st-key-caption'),field=element('TEXTAREA');
    field.value='Replaced 99 seals.';field.selectionStart=3;field.selectionEnd=8;
    field.focus=()=>{focus++;document.activeElement=field;};
    activity.editor.append(owner);owner.append(field);
    const marker=element('SPAN','enfra-picture-correction');
    marker.id='report-correction-'+'a'.repeat(64);
    Object.assign(marker.dataset,{reportIdentity:'report',fieldKey:'caption',fieldKind:'textarea'});
    activity.editor.append(marker);
    const link=element('A','enfra-page-correction-request');link.href='#'+marker.id;link.dataset.reportIdentity='report';
    activity.editor.append(link);
    const unrelated=element();root.append(unrelated);
    document={activeElement:null,hidden:false,documentElement:{clientWidth:width},body:element(),
        createElement:tag=>element(tag.toUpperCase()),addEventListener(){},removeEventListener(){},querySelectorAll:()=>[],elementFromPoint:()=>null,
        querySelector:selector=>selector.includes('epc_workspace_')?root:selector.includes('monthly_report_navigation')?nav:null};
    class Observer {
        constructor(callback,kind){this.callback=callback;this.kind=kind;this.targets=new Map();observers.push(this);}
        observe(target,options={}){this.targets.set(target,options);}unobserve(target){this.targets.delete(target);}disconnect(){this.targets.clear();}
    }
    const window={innerHeight:900,addEventListener(){},removeEventListener(){},matchMedia:element};
    const context={document,window,navigator:{},CSS:{escape:value=>value},ENFRAWorkspaceGeometry:geometry,Promise,
        ResizeObserver:class extends Observer{constructor(cb){super(cb,'resize');}},MutationObserver:class extends Observer{constructor(cb){super(cb,'mutation');}},
        CustomEvent:class {constructor(type){this.type=type;}},getComputedStyle:()=>({paddingLeft:'0',paddingRight:'0',fontSize:'16px'}),
        requestAnimationFrame:callback=>{frames.set(++sequence,()=>{measurements++;callback();});return sequence;},cancelAnimationFrame:id=>frames.delete(id)};
    vm.createContext(context);
    for(const file of ['monthly_report_correction_navigation.js','workspace_navigation.js'])vm.runInContext(fs.readFileSync('app/'+file,'utf8'),context);
    const render=vm.runInContext('('+fs.readFileSync('app/workspace_layout.js','utf8').replace('export default function','function')+')',context);
    const cleanup=render({data:{workflow:'monthly',identity:'report',navigationKey:'monthly_report_navigation'}});
    const frame=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());};
    async function drain(){for(let i=0;i<20;i++){if(frames.size)frame();await Promise.resolve();await Promise.resolve();if(!frames.size)return;}assert.fail('self-generated measurement loop');}
    function returnToReview(){
        const back=marker.parentElement.querySelector('.enfra-correction-return');assert.ok(back);
        app.dispatchEvent({type:'click',button:0,target:back,preventDefault(){}});
    }
    return {root,app,nav,link,marker,field,owner,unrelated,cleanup,frame,drain,returnToReview,deliver,observers,
        state:root._epcWorkspace,counts:()=>({focus,measurements,pending:frames.size}),active:()=>document.activeElement};
}

for(const width of [390,1180])test(`${width}px mounted first request, Return and fresh repeated attribute-only request focus exactly once`,async()=>{
    const h=schedulerHarness(width);await h.drain();assert.equal(h.counts().focus,0);
    h.link.dataset.token='first';h.deliver({type:'childList',target:h.link.parentElement});await h.drain();assert.equal(h.counts().focus,1);assert.equal(h.active(),h.field);
    h.returnToReview();await h.drain();assert.equal(h.state.navigationActive,'report_review');
    h.link.dataset.token='second';await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.counts().focus,2);
    assert.equal(h.active(),h.field);assert.equal(h.field.value,'Replaced 99 seals.');assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,8);
    assert.deepEqual([...h.state.exactPageNavigationTokens],['first','second']);assert.equal(h.counts().pending,0);h.cleanup();
});

test('a first request delivered solely as a token attribute also reaches the exact field',async()=>{
    const h=schedulerHarness();await h.drain();h.link.dataset.token='first';await h.drain();
    assert.equal(h.counts().focus,1);assert.equal(h.active(),h.field);h.cleanup();
});

for(const owner of ['link','marker','field','owner'])test(`request waits for exact ${owner} stale owner to become ready`,async()=>{
    const h=schedulerHarness();await h.drain();h[owner].dataset.stale='true';h.link.dataset.token='waiting';await h.drain();
    assert.equal(h.counts().focus,0);assert.equal(h.state.exactPageNavigationTokens.has('waiting'),false);
    h[owner].dataset.stale='false';await h.drain();assert.equal(h.counts().focus,1);assert.equal(h.state.navigationActive,'monthly_activity');
    h[owner].dataset.stale='false';await h.drain();assert.equal(h.counts().focus,1);h.cleanup();
});

for(const kind of ['foreign-request','foreign-marker','disabled-field','duplicate-request','duplicate-marker','duplicate-field','disconnected-field'])test(`${kind} remains refused on observed delivery`,async()=>{
    const h=schedulerHarness();await h.drain();
    if(kind==='foreign-request')h.link.dataset.reportIdentity='other';
    if(kind==='foreign-marker')h.marker.dataset.reportIdentity='other';
    if(kind==='disabled-field')h.field.disabled=true;
    if(kind==='disconnected-field')h.field.isConnected=false;
    if(kind==='duplicate-request')h.link.parentElement.append({...h.link});
    if(kind==='duplicate-marker')h.marker.parentElement.append({...h.marker});
    if(kind==='duplicate-field')h.owner.append({...h.field});
    h.link.dataset.token='rejected';await h.drain();assert.equal(h.counts().focus,0);
    assert.equal(h.state.exactPageNavigationTokens.has('rejected'),false);h.cleanup();
});

test('consumed tokens and unrelated attribute churn never reopen an exact field after Return',async()=>{
    const h=schedulerHarness();await h.drain();h.link.dataset.token='first';await h.drain();h.returnToReview();await h.drain();
    for(let i=0;i<40;i++){h.unrelated.dataset.token='foreign-'+i;h.unrelated.dataset.stale=String(i%2===0);h.link.dataset.token='first';}
    assert.equal(h.counts().pending,1,'the native delivery burst shares the existing RAF');await h.drain();
    assert.equal(h.state.navigationActive,'report_review');assert.equal(h.counts().focus,1);assert.equal(h.counts().pending,0);h.cleanup();
});

test('a burst delivers only its latest exact fresh nonce and coalesces into the existing scheduler',async()=>{
    const h=schedulerHarness();await h.drain();const before=h.counts();
    for(let i=0;i<40;i++)h.link.dataset.token='burst-'+i;
    assert.equal(h.counts().pending,1);h.frame();assert.equal(h.counts().measurements,before.measurements+1);
    await h.drain();assert.equal(h.counts().focus,1);assert.deepEqual([...h.state.exactPageNavigationTokens],['burst-39']);
    assert.equal(h.counts().pending,0);h.cleanup();
});

for(const action of ['pointerdown','keydown','dispose'])test(`${action} cancels queued focus and cannot replay its consumed nonce`,async()=>{
    const h=schedulerHarness();await h.drain();h.link.dataset.token='cancelled';h.frame();
    if(action==='dispose')h.cleanup();else h.app.dispatchEvent({type:action});
    await h.drain();assert.equal(h.counts().focus,0);assert.equal(h.state.exactPageNavigationTokens.has('cancelled'),true);
    h.link.dataset.token='cancelled';h.owner.dataset.stale='false';await h.drain();assert.equal(h.counts().focus,0);h.cleanup();
});

test('only token/readiness attributes are observed; layout writes do not loop and disposed callbacks are inert',async()=>{
    const h=schedulerHarness();await h.drain();
    const observer=h.observers.find(o=>o.kind==='mutation'&&o.targets.get(h.root)?.subtree),options=observer.targets.get(h.root);
    assert.equal(options.childList,true);assert.equal(options.attributes,true);assert.deepEqual([...options.attributeFilter],['data-token','data-stale']);
    for(const attributeName of ['disabled','style','data-epc-mode','data-section','aria-expanded'])h.deliver({type:'attributes',target:h.root,attributeName});
    assert.equal(h.counts().pending,0);const before=h.counts().measurements;h.cleanup();
    observer.callback([{type:'attributes',target:h.link,attributeName:'data-token'}]);
    await h.drain();assert.equal(h.counts().measurements,before);assert.equal(h.counts().pending,0);
    assert.ok(h.observers.every(o=>o.targets.size===0));
});

test('existing child-list discovery still admits a mounted exact request without an attribute event',async()=>{
    const h=schedulerHarness();await h.drain();h.link.isConnected=false;h.link.dataset.token='mounted';await h.drain();assert.equal(h.counts().focus,0);
    h.link.isConnected=true;h.deliver({type:'childList',target:h.link.parentElement});await h.drain();assert.equal(h.counts().focus,1);h.cleanup();
});

}
