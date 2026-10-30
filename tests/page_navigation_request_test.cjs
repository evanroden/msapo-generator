const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');
function harness() {
    const state={mode:'wide',ownsScroll:false,identity:'report'};
    const rect=(top,height)=>({top,bottom:top+height,height});
    const scrollport={isConnected:true,scrollTop:0,getBoundingClientRect:()=>rect(0,900)};
    const root={isConnected:true,dataset:{},scrollTop:0,getBoundingClientRect:()=>rect(300-scrollport.scrollTop,3500)};
    const field={isConnected:true,disabled:false,parentElement:null,closest:()=>null,getClientRects:()=>[{}],focus(){focus++},scrollIntoView(){}};
    const parent={children:[],querySelector:()=>null,append(value){this.children.push(value)}};
    const marker={id:'report-correction-'+'a'.repeat(64),isConnected:true,dataset:{reportIdentity:'report',fieldKey:'caption',fieldKind:'input'},closest:()=>null,parentElement:parent};
    const link={isConnected:true,dataset:{reportIdentity:'report',token:'first'},getAttribute:()=> '#'+marker.id,closest:()=>null,parentElement:parent};
    let requests=[link],focus=0,schedules=0;
    const pair=(top,inside=false)=>({isConnected:true,contains:node=>inside&&node===marker,querySelector:()=>null,setAttribute(){},focus(){},getBoundingClientRect:()=>rect(top-scrollport.scrollTop,500)});
    const water=pair(1500,true),review=pair(4000),cover=pair(300);
    const sectionMarkers=[['monthly_cover',cover],['monthly_water',water]].map(([id,pair])=>({isConnected:true,dataset:{epcPair:id},closest:selector=>selector==='[data-stale="true"]'?null:pair}));
    root.querySelectorAll=()=>sectionMarkers;root.contains=node=>[cover,water].includes(node);
    const back={isConnected:true,disabled:false},next={isConnected:true,disabled:false,textContent:'Next'},progress={isConnected:true,dataset:{},textContent:''};
    const nav={isConnected:true,getBoundingClientRect:()=>rect(64,52),querySelector:selector=>({'.epc-section-back':back,'.epc-section-next':next,'.epc-section-progress':progress})[selector]||null};
    const handlers={};
    const app={isConnected:true,contains:node=>node.isConnected,querySelector:()=>review,
        querySelectorAll:selector=>selector==='#report-review'?[review]:selector==='.enfra-page-correction-request'?requests:selector==='.enfra-picture-correction'?[marker]:selector==='.st-key-caption input'?[field]:[],
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
function schedulerHarness(width=390, sourceReview=false) {
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
            getClientRects:()=>[{}],focus(){this.focusCount=(this.focusCount||0)+1;document.activeElement=this;},scrollIntoView(){},
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
    const rootClosest=root.closest.bind(root);
    root.closest=selector=>selector==='[data-testid="stMainBlockContainer"]'?app:selector==='[data-testid="stMain"]'?scrollport:rootClosest(selector);
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
    pair('monthly_cover',300);const activity=pair('monthly_activity',1500);pair('monthly_scorecards',2200);
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
    const documentHandlers=new Map();
    document={activeElement:null,hidden:false,documentElement:{clientWidth:width},body:element(),
        createElement:tag=>element(tag.toUpperCase()),
        addEventListener(type,fn){if(!documentHandlers.has(type))documentHandlers.set(type,new Set());documentHandlers.get(type).add(fn)},
        removeEventListener(type,fn){documentHandlers.get(type)?.delete(fn)},
        dispatchEvent(event){for(const fn of documentHandlers.get(event.type)||[])fn(event)},
        querySelectorAll:()=>[],elementFromPoint:()=>null,
        querySelector:selector=>selector.includes('epc_workspace_')?root:selector.includes('monthly_report_navigation')?nav:null};
    class Observer {
        constructor(callback,kind){this.callback=callback;this.kind=kind;this.targets=new Map();observers.push(this);}
        observe(target,options={}){this.targets.set(target,options);}unobserve(target){this.targets.delete(target);}disconnect(){this.targets.clear();}
    }
    const window={innerHeight:900,addEventListener(){},removeEventListener(){},matchMedia:element};
    const context={document,window,navigator:{},CSS:{escape:value=>value},ENFRAWorkspaceGeometry:geometry,Promise,
        ResizeObserver:class extends Observer{constructor(cb){super(cb,'resize');}},MutationObserver:class extends Observer{constructor(cb){super(cb,'mutation');}},
        CustomEvent:class {constructor(type,options){this.type=type;this.detail=options?.detail;}},getComputedStyle:()=>({paddingLeft:'0',paddingRight:'0',fontSize:'16px'}),
        requestAnimationFrame:callback=>{frames.set(++sequence,()=>{measurements++;callback();});return sequence;},cancelAnimationFrame:id=>frames.delete(id)};
    vm.createContext(context);
    for(const file of [...(sourceReview?['monthly_report_source_navigation.js']:[]),'monthly_report_correction_navigation.js','workspace_navigation.js'])vm.runInContext(fs.readFileSync('app/'+file,'utf8'),context);
    const render=vm.runInContext('('+fs.readFileSync('app/workspace_layout.js','utf8').replace('export default function','function')+')',context);
    let renderSequence=1;
    let cleanup=render({data:{workflow:'monthly',identity:'report',navigationKey:'monthly_report_navigation',fullRender:'render-1'}});
    const rerender=(identity='report')=>{const old=cleanup;cleanup=render({data:{workflow:'monthly',identity,navigationKey:'monthly_report_navigation',fullRender:'render-'+(++renderSequence)}});return old;};
    const frame=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());};
    async function drain(){for(let i=0;i<20;i++){if(frames.size)frame();await Promise.resolve();await Promise.resolve();if(!frames.size)return;}assert.fail('self-generated measurement loop');}
    function returnToReview(){
        const back=marker.parentElement.querySelector('.enfra-correction-return');assert.ok(back);
        app.dispatchEvent({type:'click',button:0,target:back,preventDefault(){}});
    }
    const input=event=>document.dispatchEvent({isTrusted:true,...event});
    const command=(button=next)=>{input({type:'keydown',key:'Enter',target:button});app.dispatchEvent({type:'keydown',key:'Enter',target:button});button.onclick?.();};
    return {root,app,scrollport,nav,next,back,link,marker,field,owner,unrelated,element,input,command,cleanup:()=>cleanup(),rerender,frame,drain,returnToReview,deliver,observers,
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
    assert.equal(options.childList,true);assert.equal(options.attributes,true);assert.deepEqual([...options.attributeFilter],['data-token','data-stale','open','inert']);
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


test('one focused Next activation during same-owner full-render handoff reaches the next section before any retry',async()=>{
    const h=schedulerHarness();await h.drain();
    h.next.focus();const handler=h.next.onclick, value=h.field.value, selection=[h.field.selectionStart,h.field.selectionEnd];
    const oldCleanup=h.rerender();
    assert.equal(h.next.onclick,handler);assert.equal(h.active(),h.next);assert.equal(h.next.disabled,false);
    handler();await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');
    const after=h.counts();await h.drain();assert.deepEqual(h.counts(),after);
    assert.equal(h.field.value,value);assert.deepEqual([h.field.selectionStart,h.field.selectionEnd],selection);
    oldCleanup();assert.equal(h.next.onclick,handler);
    h.cleanup();assert.equal(h.next.onclick,null);assert.ok(h.observers.every(observer=>observer.targets.size===0));
});

test('handoff cancels pending exact-field focus without replaying its consumed token',async()=>{
    const h=schedulerHarness();await h.drain();h.link.dataset.token='pending';h.frame();
    assert.equal(h.state.exactPageNavigationTokens.has('pending'),true);
    const oldCleanup=h.rerender();oldCleanup();await h.drain();
    assert.equal(h.counts().focus,0,'the previous owner cannot finish delayed exact-field focus');
    h.link.dataset.token='pending';await h.drain();assert.equal(h.counts().focus,0);
    h.link.dataset.token='fresh';await h.drain();assert.equal(h.counts().focus,1);
    h.cleanup();
});

test('report switch rejects old native callback ownership instead of transferring it',async()=>{
    const h=schedulerHarness();await h.drain();const old=h.next.onclick;
    h.rerender('other');assert.equal(h.next.onclick,null);old();await h.drain();
    assert.equal(h.state.identity,'other');assert.equal(h.state.navigationActive,'monthly_cover');
    assert.equal(h.counts().focus,0);h.cleanup();
});


test('actual SourceReview owner retires exact Return before workspace consumes its one native click after handoff',async()=>{
    const h=schedulerHarness(390,true);await h.drain();
    const legacy=h.element('A','enfra-source-review-return');legacy.dataset.sourceId='prior';h.root.append(legacy);
    h.state.sourceReviewReturn={source:'prior'};
    h.marker.dataset.navigationOwner='exact-manager-page';h.marker.dataset.navigationToken='exact';
    h.link.dataset.token='exact';await h.drain();
    const task=h.state.sourceReviewExactReturn;assert.ok(task);assert.equal(legacy.hidden,true);
    h.rerender();await h.drain();assert.equal(h.state.sourceReviewExactReturn,task);
    const event=extra=>({type:'click',button:0,target:task.back,defaultPrevented:false,
        preventDefault(){this.defaultPrevented=true},...extra});
    for(const guard of [{defaultPrevented:true},{button:1},{metaKey:true},{ctrlKey:true},{altKey:true},{shiftKey:true}]) {
        h.app.dispatchEvent(event(guard));await h.drain();
        assert.equal(h.state.sourceReviewExactReturn,task,'guarded actions cannot retire exact Return');
        assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(legacy.hidden,true);
    }
    const native=event();h.app.dispatchEvent(native);
    assert.equal(h.state.sourceReviewExactReturn,null,'actual SourceReview runs before workspace prevents default');
    assert.equal(legacy.hidden,false,'prior presentation resumes without a second Return activation');
    assert.equal(native.defaultPrevented,true);await h.drain();
    assert.equal(h.state.navigationActive,'report_review');assert.equal(h.counts().focus,1);
    assert.equal(h.field.value,'Replaced 99 seals.');assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,8);
    const after=h.counts();await h.drain();assert.deepEqual(h.counts(),after);
    h.cleanup();
});


async function pendingSequentialIntent() {
    const h=schedulerHarness();await h.drain();h.command();await h.drain();
    assert.equal(h.state.navigationActive,'monthly_activity');
    const markers=h.root.querySelectorAll('[data-epc-pair]');
    const origin=markers.find(node=>node.dataset.epcPair==='monthly_activity');
    const target=markers.find(node=>node.dataset.epcPair==='monthly_scorecards');
    h.field.focus();h.field.value='Caption pending at blur';
    markers.forEach(marker=>marker.dataset.stale='true');
    // The native focus/blur commits a rerender before its one Enter. The
    // actual adapters run here; this offline model is not a browser event.
    h.next.focus();const handler=h.next.onclick;const oldCleanup=h.rerender();
    assert.equal(h.root.dataset.epcFullRender,'render-2');
    assert.equal(h.next.onclick,handler,'same toolbar remains owned while section content streams');
    h.command();await h.drain();
    assert.equal(h.state.navigationRequest,'monthly_scorecards');
    assert.equal(h.state.navigationActive,'monthly_activity');
    assert.equal(h.active(),h.next);assert.equal(h.field.value,'Caption pending at blur');
    return {h,markers,origin,target,oldCleanup};
}

test('blur plus one Enter survives all-stale and partial-fresh content and executes only at fresh destination',async()=>{
    const {h,markers,origin,target,oldCleanup}=await pendingSequentialIntent();
    const before=h.counts(),scroll=h.scrollport.scrollTop;oldCleanup();h.rerender();await h.drain();
    assert.equal(h.state.navigationRequest,'monthly_scorecards');
    origin.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.active(),h.next);
    assert.equal(h.state.navigationRequest,'monthly_scorecards');assert.equal(h.scrollport.scrollTop,scroll);
    const pair=target.closest('.st-key-epc_pair_monthly_scorecards');
    target.dataset.stale='false';const staleChild=h.element();staleChild.dataset.stale='true';pair.append(staleChild);
    await h.drain();assert.equal(h.state.navigationActive,'monthly_activity','fresh marker alone cannot admit stale destination content');
    staleChild.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(h.active(),pair);
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);assert.equal(pair.focusCount,1);
    const after=h.counts();oldCleanup();markers.forEach(marker=>marker.dataset.stale='false');await h.drain();
    assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(h.active(),pair);assert.equal(pair.focusCount,1);
    assert.equal(h.counts().focus,before.focus);assert.equal(h.field.value,'Caption pending at blur');
    assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,8);
    h.cleanup();
});

for(const kind of ['origin-replaced','target-replaced','marker-replaced','order','duplicate','disconnected','report','toolbar','child-control','stale-control','foreign-owner','pointer','key','wheel'])
test(`pending sequential intent cancels ${kind} invalidation without late jump`,async()=>{
    const {h,markers,origin,target}=await pendingSequentialIntent();
    if(kind==='origin-replaced'||kind==='target-replaced') {
        const marker=kind==='origin-replaced'?origin:target;const pair=marker.parentElement;
        pair.isConnected=false;const replacement=h.element('DIV',pair.className);h.root.append(replacement);replacement.append(marker);
    }
    if(kind==='marker-replaced') {const replacement=h.element();replacement.dataset.epcPair=target.dataset.epcPair;target.parentElement.append(replacement);target.remove();}
    if(kind==='order') {const a=h.root.children.indexOf(origin.parentElement),b=h.root.children.indexOf(target.parentElement);[h.root.children[a],h.root.children[b]]=[h.root.children[b],h.root.children[a]];h.deliver({type:'childList',target:h.root});}
    if(kind==='duplicate') {const duplicate=h.element();duplicate.dataset.epcPair=target.dataset.epcPair;target.parentElement.append(duplicate);}
    if(kind==='disconnected')target.parentElement.isConnected=false;
    if(kind==='report')h.rerender('foreign');
    if(kind==='toolbar'){h.next.remove();h.rerender();}
    if(kind==='child-control'){h.next.remove();h.nav.append(h.element('BUTTON','epc-section-next'));}
    if(kind==='stale-control')h.next.dataset.stale='true';
    if(kind==='foreign-owner')h.root.dataset.stale='true';
    if(kind==='pointer')h.input({type:'pointerdown',button:0,target:h.field});
    if(kind==='key')h.input({type:'keydown',key:'Tab',target:h.next});
    if(kind==='wheel')h.input({type:'wheel',deltaY:50,target:h.field});
    markers.forEach(marker=>marker.dataset.stale='false');await h.drain();
    assert.equal(h.state.navigationIntent,null);assert.equal(h.state.navigationRequest,null);
    assert.notEqual(h.state.navigationActive,'monthly_scorecards');assert.notEqual(h.active(),target.parentElement);
    h.cleanup();
});

test('pending same-direction commands coalesce at visible origin; opposite command replaces, never chains',async()=>{
    const {h,markers}=await pendingSequentialIntent();
    h.command();h.command();await h.drain();
    assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.state.navigationRequest,'monthly_scorecards');
    h.command(h.back);await h.drain();assert.equal(h.state.navigationRequest,'monthly_cover');
    markers.forEach(marker=>marker.dataset.stale='false');await h.drain();
    assert.equal(h.state.navigationActive,'monthly_cover');assert.equal(h.state.navigationRequest,null);
    const current=h.active();await h.drain();assert.equal(h.active(),current);h.cleanup();
});


test('fresh destination waits for its still-stale established origin before consuming once',async()=>{
    const {h,origin,target}=await pendingSequentialIntent();
    target.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.state.navigationRequest,'monthly_scorecards');
    origin.dataset.stale='false';await h.drain();
    const pair=target.parentElement;assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(pair.focusCount,1);
    h.rerender();await h.drain();assert.equal(pair.focusCount,1);assert.equal(h.state.navigationRequest,null);h.cleanup();
});


test('a cold controller cannot accept inherited stale sections before establishing this report ownership',async()=>{
    const h=schedulerHarness();const markers=h.root.querySelectorAll('[data-epc-pair]');
    markers.forEach(marker=>marker.dataset.stale='true');await h.drain();
    assert.equal(h.next.disabled,true);h.command();await h.drain();
    assert.equal(h.state.navigationIntent,null);assert.equal(h.state.navigationRequest,null);
    markers.forEach(marker=>marker.dataset.stale='false');await h.drain();assert.equal(h.next.disabled,false);
    h.command();await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');h.cleanup();
});


async function pendingReviewIntent() {
    const h=schedulerHarness();await h.drain();h.command();await h.drain();h.command();await h.drain();
    assert.equal(h.state.navigationActive,'monthly_scorecards');
    const review=h.app.querySelector('#report-review');review.dataset.stale='true';h.command();await h.drain();
    assert.equal(h.state.navigationRequest,'report_review');assert.equal(h.state.navigationActive,'monthly_scorecards');
    return {h,review};
}

for(const location of ['element','ancestor','descendant'])
test(`external Review ${location} stale-only readiness wakes cold controls without resize`,async()=>{
    const h=schedulerHarness(),review=h.app.querySelector('#report-review');let stale=review;
    if(location==='ancestor') {stale=h.element();h.app.append(stale);review.remove();review.isConnected=true;stale.append(review);}
    if(location==='descendant') {stale=h.element();review.append(stale);}
    stale.dataset.stale='true';await h.drain();assert.equal(h.next.disabled,true);
    const before=h.counts().measurements;stale.dataset.stale='false';await h.drain();
    assert.ok(h.counts().measurements>before);assert.equal(h.next.disabled,false);assert.equal(h.counts().pending,0);
    h.cleanup();
});

test('pending final Next executes once on external Review stale-only readiness without incidental resize',async()=>{
    const {h,review}=await pendingReviewIntent();const before=h.counts().measurements;
    review.dataset.stale='false';await h.drain();
    assert.ok(h.counts().measurements>before);assert.equal(h.state.navigationActive,'report_review');
    assert.equal(h.state.navigationRequest,null);assert.equal(review.focusCount,1);assert.equal(h.counts().pending,0);
    await h.drain();assert.equal(review.focusCount,1);h.cleanup();
});

for(const kind of ['duplicate','replacement','disconnection'])
test(`external Review ${kind} cancels old intent and retires old readiness delivery`,async()=>{
    const {h,review}=await pendingReviewIntent();let replacement;
    if(kind!=='disconnection') {replacement=h.element();replacement.id='report-review';replacement.getBoundingClientRect=review.getBoundingClientRect;h.app.append(replacement);}
    if(kind!=='duplicate')review.remove();
    await h.drain();assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);
    assert.notEqual(h.state.navigationActive,'report_review');assert.equal(replacement?.focusCount||0,0);
    if(kind==='duplicate'){replacement.remove();await h.drain();}
    else {const before=h.counts().measurements;review.dataset.stale='false';await h.drain();assert.equal(h.counts().measurements,before);}
    h.cleanup();
});

test('foreign Review and unrelated external app churn do not schedule readiness work',async()=>{
    const h=schedulerHarness();await h.drain();const before=h.counts().measurements;
    const foreign=h.element();foreign.id='report-review';foreign.dataset.stale='true';foreign.dataset.stale='false';
    const other=h.element();h.app.append(other);
    for(let i=0;i<30;i++){const child=h.element();other.append(child);child.dataset.stale='true';child.dataset.stale='false';}
    await h.drain();assert.equal(h.counts().measurements,before);assert.equal(h.counts().pending,0);h.cleanup();
});

test('external Review observer ownership is retired on report switch and terminal cleanup',async()=>{
    const h=schedulerHarness();await h.drain();const old=[...h.observers],review=h.app.querySelector('#report-review');
    h.rerender('other');await h.drain();assert.ok(old.every(observer=>observer.targets.size===0));
    const before=h.counts().measurements;
    for(const observer of old)observer.callback([{type:'attributes',target:review,attributeName:'data-stale'}]);
    await h.drain();assert.equal(h.counts().measurements,before);
    h.cleanup();assert.ok(h.observers.every(observer=>observer.targets.size===0));
    for(const observer of h.observers)observer.callback([{type:'attributes',target:review,attributeName:'data-stale'}]);
    assert.equal(h.counts().pending,0);
});


test('Review ancestor-chain replacement observes only the newly owned stale boundary',async()=>{
    const h=schedulerHarness();await h.drain();const review=h.app.querySelector('#report-review');
    const old=h.element(),current=h.element();h.app.append(old);h.app.append(current);
    review.remove();review.isConnected=true;old.append(review);await h.drain();
    current.dataset.stale='true';review.remove();review.isConnected=true;current.append(review);await h.drain();
    const before=h.counts().measurements;old.dataset.stale='true';old.dataset.stale='false';await h.drain();
    assert.equal(h.counts().measurements,before);
    current.dataset.stale='false';await h.drain();assert.ok(h.counts().measurements>before);assert.equal(h.counts().pending,0);h.cleanup();
});

test('a newly streamed unique external Review is discovered without root churn',async()=>{
    const h=schedulerHarness(),prior=h.app.querySelector('#report-review');prior.remove();await h.drain();
    h.command();await h.drain();h.command();await h.drain();assert.equal(h.next.disabled,true);
    const wrapper=h.element(),review=h.element();review.id='report-review';review.getBoundingClientRect=prior.getBoundingClientRect;
    h.app.append(wrapper);wrapper.append(review);await h.drain();assert.equal(h.next.disabled,false);
    h.command();await h.drain();assert.equal(h.state.navigationActive,'report_review');assert.equal(review.focusCount,1);h.cleanup();
});


function replacementDisclosure(h,section='monthly_activity') {
    const marker=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair===section),pair=marker.parentElement;
    const details=h.element('DETAILS'),summary=h.element('SUMMARY'),body=h.element(),stale=h.element();
    details.open=false;body.dataset.testid='stExpanderDetails';body.inert='';stale.dataset.stale='true';
    details.append(summary);details.append(body);body.append(stale);pair.append(details);
    return {marker,pair,details,summary,body,stale};
}

for(const kind of ['closed-inert','open-inert','closed-not-inert','inert-not-details','stale-summary','stale-marker','stale-pair','stale-focus','hidden-focus'])
test(`native replacement disclosure readiness: ${kind}`,async()=>{
    const h=schedulerHarness(),d=replacementDisclosure(h);
    if(kind==='open-inert')d.details.open=true;
    if(kind==='closed-not-inert')delete d.body.inert;
    if(kind==='inert-not-details')d.details.tagName='DIV';
    if(kind==='stale-summary')d.summary.dataset.stale='true';
    if(kind==='stale-marker')d.marker.dataset.stale='true';
    if(kind==='stale-pair')d.pair.dataset.stale='true';
    if(kind==='stale-focus'||kind==='hidden-focus') {
        const heading=h.element('H3');d.pair.queries.set('h1,h2,h3,h4',heading);
        if(kind==='stale-focus'){heading.dataset.stale='true';d.pair.append(heading);}else d.body.append(heading);
    }
    await h.drain();assert.equal(h.next.disabled,kind!=='closed-inert');
    if(kind==='closed-inert'){h.command();await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(d.pair.focusCount,1);}
    assert.equal(h.field.value,'Replaced 99 seals.');assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,8);h.cleanup();
});

for(const readiness of ['open','inert'])
test(`one pending command leaves visible stale replacement content only after semantic ${readiness} delivery hides it`,async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const d=replacementDisclosure(h);
    if(readiness==='open')d.details.open=true;else delete d.body.inert;
    await h.drain();h.command();await h.drain();assert.equal(h.state.navigationRequest,'monthly_scorecards');
    assert.equal(h.state.navigationActive,'monthly_activity');const before=h.counts().measurements;
    if(readiness==='open')d.details.open=false;else d.body.inert='';
    h.deliver({type:'attributes',target:readiness==='open'?d.details:d.body,attributeName:readiness});await h.drain();
    assert.ok(h.counts().measurements>before);assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(h.state.navigationRequest,null);h.cleanup();
});

test('opening hidden stale content during a pending command prevents execution until visible content is fresh',async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const d=replacementDisclosure(h);
    const target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');target.dataset.stale='true';
    h.command();await h.drain();d.details.open=true;h.deliver({type:'attributes',target:d.details,attributeName:'open'});
    target.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.state.navigationRequest,'monthly_scorecards');
    d.stale.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(target.parentElement.focusCount,1);h.cleanup();
});

test('hidden replacement content never authorizes a foreign report intent or writes source caption',async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();replacementDisclosure(h);
    const target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');target.dataset.stale='true';
    h.command();await h.drain();h.rerender('foreign');target.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationIntent,null);assert.equal(h.state.navigationRequest,null);assert.equal(target.parentElement.focusCount||0,0);
    assert.equal(h.field.value,'Replaced 99 seals.');h.cleanup();
});

function wrapNext(h) {
    const wrapper=h.element();h.nav.append(wrapper);h.next.remove();h.next.isConnected=true;wrapper.append(h.next);return wrapper;
}

for(const accept of ['before-stale','during-stale'])
test(`same established native wrapper retains one ${accept} command across full render but executes only fresh`,async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const wrapper=wrapNext(h);await h.drain();
    const button=h.next,handler=button.onclick,target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');
    target.dataset.stale='true';if(accept==='before-stale')h.command();wrapper.dataset.stale='true';await h.drain();
    assert.equal(button.disabled,false);assert.equal(button.onclick,handler);if(accept==='during-stale')h.command();await h.drain();
    assert.equal(h.state.navigationRequest,'monthly_scorecards');const oldCleanup=h.rerender();oldCleanup();await h.drain();
    assert.equal(button.onclick,handler);assert.equal(h.state.navigationRequest,'monthly_scorecards');
    target.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(target.parentElement.focusCount||0,0);
    wrapper.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(h.state.navigationRequest,null);assert.equal(target.parentElement.focusCount,1);
    h.rerender();await h.drain();assert.equal(target.parentElement.focusCount,1);h.cleanup();
});

for(const kind of ['cold','replacement'])
test(`${kind} stale native button cannot inherit another control's established authorization`,async()=>{
    const h=schedulerHarness();if(kind==='replacement')await h.drain();
    const wrapper=wrapNext(h);let button=h.next;
    if(kind==='replacement'){button.remove();button=h.element('BUTTON','epc-section-next');wrapper.append(button);}
    wrapper.dataset.stale='true';await h.drain();assert.equal(button.disabled,true);button.onclick?.();await h.drain();
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);
    wrapper.dataset.stale='false';await h.drain();assert.equal(button.disabled,false);button.onclick();await h.drain();
    assert.equal(h.state.navigationActive,'monthly_activity');h.cleanup();
});

for(const invalid of ['report','disconnect','replacement','order','foreign-owner','outer-stale-owner','conflicting-input'])
test(`transient wrapper continuity still cancels ${invalid}`,async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const wrapper=wrapNext(h);await h.drain();
    const target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');target.dataset.stale='true';h.command();await h.drain();
    wrapper.dataset.stale='true';await h.drain();
    if(invalid==='report')h.rerender('other');
    if(invalid==='foreign-owner'){h.next.remove();h.next.isConnected=true;h.app.append(h.next);}
    if(invalid==='outer-stale-owner'){const outer=h.element();h.app.append(outer);h.root.remove();h.root.isConnected=true;outer.append(h.root);outer.dataset.stale='true';h.deliver({type:'childList',target:h.root});}
    if(invalid==='disconnect')h.next.remove();
    if(invalid==='replacement'){h.next.remove();wrapper.append(h.element('BUTTON','epc-section-next'));}
    if(invalid==='order'){const p=target.parentElement;h.root.children=h.root.children.filter(n=>n!==p);h.root.children.unshift(p);h.deliver({type:'childList',target:h.root});}
    if(invalid==='conflicting-input')h.input({type:'keydown',key:'Tab',target:h.field});
    wrapper.dataset.stale='false';target.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);assert.equal(target.parentElement.focusCount||0,0);h.cleanup();
});


for(const location of ['origin','target'])
test(`same-wrapper intent still waits for ${location} and fresh required owners`,async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const wrapper=wrapNext(h);await h.drain();
    const sections=h.root.querySelectorAll('[data-epc-pair]'),origin=sections.find(n=>n.dataset.epcPair==='monthly_activity'),target=sections.find(n=>n.dataset.epcPair==='monthly_scorecards');
    const stale=location==='origin'?origin:target;stale.dataset.stale='true';h.command();wrapper.dataset.stale='true';await h.drain();
    wrapper.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');assert.equal(h.state.navigationRequest,'monthly_scorecards');
    stale.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(target.parentElement.focusCount,1);h.cleanup();
});

for(const input of ['repeat','opposite','foreign-pointer','source-return'])
test(`same-wrapper pending command preserves ${input} input semantics`,async()=>{
    const h=schedulerHarness(390,true);await h.drain();h.command();await h.drain();const wrapper=wrapNext(h);await h.drain();
    const target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');target.dataset.stale='true';h.command();wrapper.dataset.stale='true';await h.drain();
    if(input==='repeat'){h.command();h.command();}
    if(input==='opposite')h.command(h.back);
    if(input==='foreign-pointer')h.input({type:'pointerdown',button:0,target:h.field});
    if(input==='source-return')h.link.dataset.token='exact-new';
    await h.drain();wrapper.dataset.stale='false';target.dataset.stale='false';await h.drain();
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);
    if(input==='repeat'){assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(target.parentElement.focusCount,1);}
    if(input==='opposite')assert.equal(h.state.navigationActive,'monthly_cover');
    if(input==='foreign-pointer'||input==='source-return')assert.equal(target.parentElement.focusCount||0,0);
    if(input==='source-return'){assert.equal(h.active(),h.field);assert.deepEqual([...h.state.exactPageNavigationTokens],['exact-new']);}
    h.cleanup();
});

test('terminal cleanup retires same-wrapper pending ownership without late replay',async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();const wrapper=wrapNext(h);await h.drain();
    const target=h.root.querySelectorAll('[data-epc-pair]').find(n=>n.dataset.epcPair==='monthly_scorecards');target.dataset.stale='true';h.command();wrapper.dataset.stale='true';await h.drain();
    const handler=h.next.onclick;h.cleanup();wrapper.dataset.stale='false';target.dataset.stale='false';handler();await h.drain();
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.navigationIntent,null);assert.equal(h.next.onclick,null);assert.equal(target.parentElement.focusCount||0,0);assert.equal(h.counts().pending,0);
});

for(const readiness of ['open','inert'])
test(`external Review native disclosure ${readiness} delivery uses only its owned coalesced observer`,async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();h.command();await h.drain();
    const review=h.app.querySelector('#report-review'),d=replacementDisclosure(h);d.details.remove();d.details.isConnected=true;review.append(d.details);
    if(readiness==='open')d.details.open=true;else delete d.body.inert;
    h.command();await h.drain();assert.equal(h.state.navigationRequest,'report_review');const before=h.counts().measurements;
    if(readiness==='open')d.details.open=false;else d.body.inert='';
    h.deliver({type:'attributes',target:readiness==='open'?d.details:d.body,attributeName:readiness});await h.drain();
    assert.ok(h.counts().measurements>before);assert.equal(h.state.navigationActive,'report_review');assert.equal(review.focusCount,1);assert.equal(h.counts().pending,0);
    const final=h.counts().measurements;h.deliver({type:'attributes',target:h.unrelated,attributeName:'style'});await h.drain();assert.equal(h.counts().measurements,final);h.cleanup();
});


test('one caption-exit Enter survives the shared native toolbar wrapper across all-section streaming',async()=>{
    const h=schedulerHarness();await h.drain();h.command();await h.drain();
    const wrapper=h.element(),controls=[...h.nav.children];h.nav.append(wrapper);
    for(const control of controls){control.remove();control.isConnected=true;wrapper.append(control);}await h.drain();
    const button=h.next,handler=button.onclick,markers=h.root.querySelectorAll('[data-epc-pair]');
    h.field.focus();h.next.focus();markers.forEach(marker=>marker.dataset.stale='true');
    h.rerender();h.command();wrapper.dataset.stale='true';await h.drain();
    assert.equal(h.next,button);assert.equal(button.onclick,handler);assert.equal(button.disabled,false);assert.equal(h.state.navigationRequest,'monthly_scorecards');
    markers.forEach(marker=>marker.dataset.stale='false');await h.drain();assert.equal(h.state.navigationActive,'monthly_activity');
    wrapper.dataset.stale='false';await h.drain();assert.equal(h.state.navigationActive,'monthly_scorecards');assert.equal(h.state.navigationIntent,null);
    const target=markers.find(marker=>marker.dataset.epcPair==='monthly_scorecards').parentElement;assert.equal(target.focusCount,1);
    assert.equal(h.field.value,'Replaced 99 seals.');assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,8);assert.equal(h.counts().pending,0);h.cleanup();
});

}
