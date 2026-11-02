const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture() {
    const frames=new Map(),timers=new Map(),observers=new Set();let seq=0;
    const state={identity:'current-report'},workspace={dataset:{epcMode:'wide'},closest(){return this.stale?this:null;}};workspace._epcWorkspace=state;
    const scroll={scrollTop:800,scrollHeight:5000,clientHeight:750,parentElement:null};
    const review={parentElement:scroll,top:80,isConnected:true,focuses:0,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(o){assert.equal(o.preventScroll,true);this.focuses++;}};
    const entries={};
    for(const id of ['first','second']) {
        // Streamlit's native summary owns both its expanded state and the
        // inert body. Assigning details.open alone leaves controls inactive.
        function disclosure(parentElement) {
            const node={tagName:'DETAILS',open:false,expanded:false,inert:true,clicks:0,parentElement};
            node.summary={click(){node.clicks++;node.expanded=!node.expanded;node.open=node.expanded;node.inert=!node.expanded;}};
            node.querySelector=selector=>selector===':scope > summary'?node.summary:selector.includes('stExpanderDetails')?{hasAttribute:()=>node.inert}:null;
            return node;
        }
        const outer=disclosure(scroll),details=disclosure(outer);
        const field={disabled:false,isConnected:true,stale:false,focuses:0,scrolls:0,closest(selector){return selector==='[inert]'?(outer.inert||details.inert?details:null):this.stale?this:null;},focus(o){assert.equal(o.preventScroll,true);if(!outer.inert&&!details.inert)this.focuses++;},scrollIntoView(){this.scrolls++;}};
        Object.defineProperty(field,'value',{get(){throw Error('navigation cannot read business values');},set(){throw Error('navigation cannot write business values');}});
        const dateWidget={querySelector:s=>s==='label'?{textContent:'Source date'}:s==='input'?field:null};
        const owner={isConnected:true,dataset:{reportIdentity:state.identity},closest(){return this.stale?this:null;}};
        const group={owners:[owner],querySelectorAll(){return this.owners;}};
        const boundary={parentElement:outer,isConnected:true,ready:true,workspace,group,
            closest(selector){return selector.includes('epc_workspace_monthly')?this.workspace:selector.includes('_source_metadata_corrections')?this.group:this.stale?this:null;},
            querySelector:s=>boundary.ready&&id==='first'&&s.includes('Source sites')?field:null,
            querySelectorAll:s=>s==='details'?[details]:boundary.ready&&s==='[data-testid="stDateInput"]'&&id==='second'?[dateWidget]:[],getAnimations:()=>[]};
        const marker={id:'source-details-'+id,isConnected:true,closest:s=>s==='[data-stale="true"]'?(marker.stale?marker:null):boundary};
        const link={isConnected:true,parentElement:scroll,top:400,classList:{contains:()=>false},closest(s){if(s==='a')return this;return s.includes('epc_workspace_monthly')?(this.alert?.marker.workspace ?? (this.alert ? null : workspace)):s==='[data-stale="true"]'?(this.stale?this:null):this.alert?.container || this;},getAttribute:()=>`#source-details-${id}--${id==='first'?'site':'date'}`,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(){this.focused=true;}};
        const back={dataset:{sourceId:id},hidden:true,classList:{contains:()=>true},closest(){return this;}};
        entries[id]={outer,details,field,boundary,marker,link,back,owner,group};
    }
    const correctionMarkers=[];
    function inline(tag) {
        const attrs={};
        return {tagName:tag.toUpperCase(),isConnected:true,parentElement:scroll,
            textContent:'',getAttribute:key=>attrs[key],setAttribute:(key,value)=>{attrs[key]=value;},
            classList:{contains:()=>false},closest(s){if(s==='a')return this;return s.includes('epc_workspace_monthly')?(this.alert?.marker.workspace ?? (this.alert ? null : workspace)):s==='[data-stale="true"]'?(this.stale?this:null):this.alert?.container || this;},
            getBoundingClientRect:()=>({top:400}),focus(){this.focused=true;},
            after(replacement){this.alert.link=replacement;replacement.alert=this.alert;},
            remove(){if(this.alert.link===this)this.alert.link=null;}};
    }
    const app={request:null,listeners:new Map(),workspaces:[workspace],extraMarkers:[],contains:node=>node.insideApp!==false,querySelector:s=>s.startsWith('#')?review:s==='.enfra-source-review-target'?app.request:null,
        querySelectorAll:s=>s.includes('epc_workspace_monthly')?app.workspaces:s==='.enfra-source-correction'?correctionMarkers:s==='[id^="source-details-"]'?[...Object.values(entries).map(v=>v.marker),...app.extraMarkers]:Object.values(entries).map(v=>v.back),
        addEventListener(k,fn){this.listeners.set(k,fn);},removeEventListener(k,fn){if(this.listeners.get(k)===fn)this.listeners.delete(k);}};
    const addCorrection=id=>{
        const alert={querySelector:s=>s==='a[data-enfra-correction-link]'?alert.link:null,
            querySelectorAll:s=>s==='strong'?[alert.status]:[]};
        alert.status=inline('strong');alert.status.textContent='Loading correction controls…';alert.status.alert=alert;
        Object.defineProperty(alert,'control',{get:()=>alert.link||alert.status});
        const container={isConnected:true,querySelector:()=>alert,querySelectorAll:()=>container.markers,closest:s=>container.stale?container:null};alert.container=container;
        const marker={isConnected:true,workspace,dataset:{reportIdentity:state.identity,sourceId:id,kind:id==='first'?'site':'date',label:id==='first'?'Correct site':'Correct date'},
            closest:s=>s.includes('epc_workspace_monthly')?marker.workspace:s==='[data-stale="true"]'?(marker.stale?marker:null):container};
        alert.marker=marker;container.markers=[marker];correctionMarkers.push(marker);return alert;
    };
    class Observer {
        constructor(callback){this.callback=callback;}
        observe(target){this.target=target;observers.add(this);}
        disconnect(){observers.delete(this);}
    }
    const context={document:{getElementById:id=>entries[id.replace('source-details-','')]?.marker,scrollingElement:scroll,createElement:inline},getComputedStyle:()=>({overflowY:'auto'}),Promise,MutationObserver:Observer,
        setTimeout:(fn,ms)=>{assert.ok(ms>0&&ms<=5000);timers.set(++seq,fn);return seq;},clearTimeout:id=>timers.delete(id),
        requestAnimationFrame:fn=>{frames.set(++seq,fn);return seq;},cancelAnimationFrame:id=>frames.delete(id)};
    vm.runInNewContext(fs.readFileSync('app/monthly_report_source_navigation.js','utf8'),context);
    const install=()=>context.ENFRASourceReviewNavigation.install(app,state);
    const click=(target,other={})=>{const e={button:0,target,prevented:false,preventDefault(){this.prevented=true;},...other};app.listeners.get('click')(e);return e;};
    const flush=async()=>{await Promise.resolve();await Promise.resolve();for(const [id,fn]of [...frames]){frames.delete(id);fn();}};
    const changed=boundary=>{for(const observer of [...observers])if(observer.target===boundary||observer.target===app)observer.callback([]);};
    const expire=()=>{for(const [id,fn]of [...timers]){timers.delete(id);fn();}};
    const pendingObservers=()=>[...observers].filter(observer=>observer.target!==app);
    return{entries,app,state,workspace,review,scroll,install,click,flush,changed,expire,observers,timers,pendingObservers,addCorrection,context};
}

test('one correction opens its outer and exact source disclosure and focuses its native field',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first,b=h.entries.second;
    assert.equal(h.click(a.link).prevented,true);await h.flush();
    assert.equal(a.outer.open,true);assert.equal(a.details.open,true);assert.equal(a.field.focuses,1);assert.equal(a.field.scrolls,1);
    assert.equal(a.outer.inert,false);assert.equal(a.details.inert,false);
    assert.equal(a.outer.clicks,1);assert.equal(a.details.clicks,1);
    assert.equal(b.details.open,false);assert.equal(b.field.focuses,0);
    assert.equal(a.back.hidden,false);assert.equal(b.back.hidden,true);
    h.click(b.link);await h.flush();
    assert.equal(b.field.focuses,1);assert.equal(a.back.hidden,true);assert.equal(b.back.hidden,false);
    cleanup();assert.equal(h.app.listeners.size,0);
});

test('date correction resolves the native widget label without reading or changing its value',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.second;
    assert.equal(h.click(a.link).prevented,true);await h.flush();
    assert.equal(a.field.focuses,1);assert.equal(a.field.scrolls,1);
    assert.equal(a.details.inert,false);assert.equal(h.entries.first.details.open,false);
    cleanup();
});

test('a first correction opens a cold native panel and focuses its field when it loads',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.second;a.boundary.ready=false;
    assert.equal(h.click(a.link).prevented,true);await h.flush();
    assert.equal(a.details.open,true);assert.equal(a.field.focuses,0);
    a.boundary.ready=true;h.changed(a.boundary);await h.flush();
    assert.equal(a.field.focuses,1);assert.equal(a.field.scrolls,1);
    assert.equal(h.pendingObservers().length,0);assert.equal(h.timers.size,0);
    cleanup();
});

test('return and timeout cancel lazy focus without a later jump or retained observer',async()=>{
    for(const action of ['return','timeout','dispose','new input']) {
        const h=fixture(),cleanup=h.install(),a=h.entries.first;a.boundary.ready=false;
        h.click(a.link);await h.flush();
        if(action==='return')h.click(a.back);
        else if(action==='timeout')h.expire();
        else if(action==='new input')h.app.listeners.get('keydown')({key:'Tab'});
        else cleanup();
        a.boundary.ready=true;h.changed(a.boundary);await h.flush();
        assert.equal(a.field.focuses,0);assert.equal(a.field.scrolls,0);
        assert.equal(h.pendingObservers().length,0);assert.equal(h.timers.size,0);
        cleanup();
        assert.equal(h.observers.size,0);
    }
});

test('an unrelated endless loading animation cannot strand a ready correction field',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first;
    a.boundary.getAnimations=()=>[{playState:'running',effect:{getComputedTiming:()=>({endTime:Infinity})},finished:new Promise(()=>{})}];
    h.click(a.link);await h.flush();assert.equal(a.field.focuses,1);
    cleanup();
});

test('Return restores the same warning and accepts already-open disclosures',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first;a.outer.summary.click();a.details.summary.click();
    h.click(a.link);await h.flush();a.link.top=100;
    h.click(a.back);assert.equal(h.scroll.scrollTop,500);assert.equal(a.link.focused,true);assert.equal(a.back.hidden,true);
    assert.equal(a.outer.clicks,1);assert.equal(a.details.clicks,1);
    cleanup();
});

test('Return measures its warning after hiding its own return affordance',async()=>{
    for(const keepWarning of [true,false]) {
        const h=fixture(),cleanup=h.install(),a=h.entries.first;
        h.click(a.link);await h.flush();
        const target=keepWarning?a.link:h.review;
        if(!keepWarning)a.link.isConnected=false;
        target.top=100;
        let hidden=false;
        Object.defineProperty(a.back,'hidden',{get(){return hidden;},set(value){
            if(value&&!hidden)target.top-=24;
            hidden=value;
        }});
        h.click(a.back);
        assert.equal(h.scroll.scrollTop,800+76-(keepWarning?400:80));
        assert.equal(a.back.hidden,true);
        assert.equal(h.state.sourceReviewReturn,null);
        cleanup();
    }
});

test('corrected warning/form may disappear across rerun without losing Return to review',async()=>{
    const h=fixture(),a=h.entries.first;let cleanup=h.install();
    h.click(a.link);await h.flush();cleanup();a.link.isConnected=false;a.field.isConnected=false;
    cleanup=h.install();assert.equal(a.back.hidden,false);
    h.review.top=220;h.click(a.back);
    assert.equal(h.scroll.scrollTop,940);assert.equal(h.review.focuses,1);assert.equal(h.state.sourceReviewReturn,null);
    cleanup();
});

test('modifier clicks and stale navigation callbacks do not disturb the editor',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first;
    assert.equal(h.click(a.link,{ctrlKey:true}).prevented,false);assert.equal(a.details.open,false);
    h.click(a.link);cleanup();await h.flush();assert.equal(a.field.focuses,0);
});

test('cold warnings remain plain until their owned handler, layout and native field are ready',async()=>{
    const h=fixture(),notice=h.addCorrection('second');
    const nativeStatus=notice.status;
    h.entries.second.boundary.ready=false;delete h.workspace.dataset.epcMode;
    assert.equal(notice.control.tagName,'STRONG');assert.equal(notice.control.getAttribute('href'),undefined);
    const cleanup=h.install();await h.flush();assert.equal(notice.control.tagName,'STRONG');
    h.entries.second.boundary.ready=true;h.changed(h.entries.second.boundary);await h.flush();
    assert.equal(notice.control.tagName,'STRONG');
    h.workspace.dataset.epcMode='wide';h.changed(h.app);await h.flush();
    assert.equal(notice.control.tagName,'A');assert.equal(notice.control.textContent,'Correct date');
    assert.equal(notice.status,nativeStatus);assert.equal(nativeStatus.hidden,true);
    assert.equal(notice.control.getAttribute('href'),'#source-details-second--date');
    h.click(notice.control);await h.flush();assert.equal(h.entries.second.field.focuses,1);
    cleanup();assert.equal(notice.control,nativeStatus);assert.equal(nativeStatus.hidden,false);assert.equal(h.observers.size,0);
});

test('one ready source is usable without waiting for another source or an offscreen preview',async()=>{
    const h=fixture(),first=h.addCorrection('first'),second=h.addCorrection('second');
    h.entries.second.boundary.ready=false;
    const cleanup=h.install();await h.flush();
    assert.equal(first.control.tagName,'A');assert.equal(second.control.tagName,'STRONG');
    assert.equal(h.click(first.control,{ctrlKey:true}).prevented,false);
    assert.equal(h.entries.first.details.open,false);
    h.click(first.control);await h.flush();assert.equal(h.entries.first.field.focuses,1);
    assert.equal(h.entries.second.field.focuses,0);cleanup();
});

test('disabled, stale and foreign native targets never activate a correction',async()=>{
    for(const reason of ['disabled','stale','different report']) {
        const h=fixture(),notice=h.addCorrection('first'),a=h.entries.first;
        if(reason==='disabled')a.field.disabled=true;
        if(reason==='stale')a.field.stale=true;
        if(reason==='different report')a.boundary.workspace={};
        const cleanup=h.install();await h.flush();assert.equal(notice.control.tagName,'STRONG',reason);
        a.field.disabled=false;a.field.stale=false;a.boundary.workspace=h.workspace;
        h.changed(a.boundary);await h.flush();assert.equal(notice.control.tagName,'A',reason);
        a.field.disabled=true;h.changed(a.boundary);await h.flush();assert.equal(notice.control.tagName,'STRONG',reason);
        cleanup();assert.equal(h.observers.size,0);
    }
});

test('late warnings activate once and disposal restores a truthful unavailable state',async()=>{
    const h=fixture(),cleanup=h.install();await h.flush();
    const notice=h.addCorrection('first');h.changed(h.app);await h.flush();
    const link=notice.control;assert.equal(link.tagName,'A');
    h.changed(h.app);await h.flush();assert.equal(notice.control,link);
    cleanup();assert.equal(notice.control.tagName,'STRONG');assert.equal(h.observers.size,0);
    h.changed(h.app);await h.flush();assert.equal(notice.control.tagName,'STRONG');
    const again=h.install();await h.flush();assert.equal(notice.control.tagName,'A');again();
});

test('the actual sibling source form activates only for its explicit report owner',async()=>{
    const h=fixture(),a=h.entries.first,notice=h.addCorrection('first');
    a.boundary.workspace=null; // guided renders this form before workspace()
    const cleanup=h.install();await h.flush();
    assert.equal(notice.control.tagName,'A');
    h.click(notice.control);await h.flush();
    assert.equal(a.field.focuses,1);assert.equal(a.details.inert,false);
    assert.equal(h.entries.second.details.open,false);
    cleanup();
});

test('sibling forms with missing, foreign, stale or duplicate ownership stay inactive',async()=>{
    for(const reason of ['missing owner','foreign owner','stale owner','stale form','stale marker','duplicate marker','detached marker','outside app']) {
        const h=fixture(),a=h.entries.first,notice=h.addCorrection('first');a.boundary.workspace=null;
        if(reason==='missing owner')a.group.owners=[];
        if(reason==='foreign owner')a.owner.dataset.reportIdentity='another-report';
        if(reason==='stale owner')a.owner.stale=true;
        if(reason==='stale form')a.boundary.stale=true;
        if(reason==='stale marker')a.marker.stale=true;
        if(reason==='duplicate marker')h.app.extraMarkers.push({...a.marker});
        if(reason==='detached marker')a.marker.isConnected=false;
        if(reason==='outside app')a.boundary.insideApp=false;
        const cleanup=h.install();await h.flush();
        assert.equal(notice.control.tagName,'STRONG',reason);
        h.click(a.link);await h.flush();
        assert.equal(a.field.focuses,0,reason);assert.equal(a.details.clicks,0,reason);
        cleanup();assert.equal(h.observers.size,0);
    }
});

test('a displayed link cannot focus a field that becomes stale before the readiness frame',async()=>{
    const h=fixture(),a=h.entries.first,notice=h.addCorrection('first');
    const cleanup=h.install();await h.flush();const link=notice.control;
    a.field.stale=true; // no controlsChanged frame has run yet
    h.click(link);await h.flush();
    assert.equal(a.field.focuses,0);assert.equal(a.details.clicks,0);
    cleanup();
});

test('deferred focus revalidates exact source and captured report ownership',async()=>{
    for(const reason of ['owner changed','report changed','source duplicated','field stale']) {
        const h=fixture(),a=h.entries.first;a.boundary.workspace=null;
        const cleanup=h.install();a.boundary.ready=false;h.click(a.link);await h.flush();
        if(reason==='owner changed')a.owner.dataset.reportIdentity='another-report';
        if(reason==='report changed')h.state.identity='another-report';
        if(reason==='source duplicated')h.app.extraMarkers.push({...a.marker});
        if(reason==='field stale')a.field.stale=true;
        a.boundary.ready=true;h.changed(a.boundary);await h.flush();
        assert.equal(a.field.focuses,0,reason);assert.equal(a.field.scrolls,0,reason);
        assert.equal(h.pendingObservers().length,0,reason);
        cleanup();assert.equal(h.observers.size,0);
    }
});

test('a correction reopens a native disclosure during its inert closing transition',async()=>{
    const h=fixture(),a=h.entries.first,cleanup=h.install();
    a.outer.summary.click();a.details.summary.click();
    a.details.open=true;a.details.expanded=false;a.details.inert=true;
    h.click(a.link);await h.flush();
    assert.equal(a.details.expanded,true);assert.equal(a.details.open,true);
    assert.equal(a.details.inert,false);assert.equal(a.field.focuses,1);
    assert.equal(h.entries.second.details.open,false);
    cleanup();
});


test('actual sibling review warning reaches its same-report sibling source form',async()=>{
    const h=fixture(),a=h.entries.second,notice=h.addCorrection('second');
    notice.marker.workspace=null;a.boundary.workspace=null;
    const cleanup=h.install();await h.flush();assert.equal(notice.control.tagName,'A');
    h.click(notice.control);await h.flush();assert.equal(a.field.focuses,1);assert.equal(a.details.inert,false);
    cleanup();
});

test('sibling warnings cannot borrow foreign, stale, duplicate or missing ownership',async()=>{
    for(const reason of ['missing identity','foreign identity','stale marker','detached marker','duplicate marker','duplicate workspace','foreign workspace','foreign containing workspace','stale warning','outside app','unknown kind','wrong source','duplicate warning']) {
        const h=fixture(),a=h.entries.second,notice=h.addCorrection('second');
        notice.marker.workspace=null;a.boundary.workspace=null;
        if(reason==='missing identity')delete notice.marker.dataset.reportIdentity;
        if(reason==='foreign identity')notice.marker.dataset.reportIdentity='foreign';
        if(reason==='stale marker')notice.marker.stale=true;
        if(reason==='detached marker')notice.marker.isConnected=false;
        if(reason==='duplicate marker')notice.container.markers.push({...notice.marker});
        if(reason==='duplicate workspace')h.app.workspaces.push({...h.workspace});
        if(reason==='foreign workspace')h.workspace._epcWorkspace={identity:'foreign'};
        if(reason==='stale warning')notice.container.stale=true;
        if(reason==='foreign containing workspace')notice.marker.workspace={};
        if(reason==='outside app')notice.marker.insideApp=false;
        if(reason==='unknown kind')notice.marker.dataset.kind='unknown';
        if(reason==='wrong source')notice.marker.dataset.sourceId='missing';
        if(reason==='duplicate warning'){const duplicate=h.addCorrection('second');duplicate.marker.workspace=null;}
        const cleanup=h.install();await h.flush();assert.equal(notice.control.tagName,'STRONG',reason);
        cleanup();
    }
});

test('sibling warning ownership is checked again at click and deferred focus',async()=>{
    for(const phase of ['click','focus']) {
        const h=fixture(),a=h.entries.second,notice=h.addCorrection('second');
        notice.marker.workspace=null;a.boundary.workspace=null;
        const cleanup=h.install();await h.flush();const link=notice.control;assert.equal(link.tagName,'A');
        if(phase==='click')notice.marker.dataset.reportIdentity='foreign';
        else a.boundary.ready=false;
        h.click(link);await h.flush();
        notice.marker.dataset.reportIdentity='foreign';a.boundary.ready=true;h.changed(a.boundary);await h.flush();
        assert.equal(a.field.focuses,0,phase);assert.equal(a.field.scrolls,0,phase);cleanup();
    }
});

test('native warning action retains its callback and a new target focuses once after rerun',async()=>{
    const h=fixture(),a=h.entries.first;let cleanup=h.install();
    const warning={dataset:{sourceId:'first'}};
    const wrapper={querySelector:()=>warning};
    const button={isConnected:true,parentElement:h.scroll,getBoundingClientRect:()=>({top:420}),closest:()=>wrapper,setAttribute(){},focus(){this.focused=true;}};
    const target={closest:s=>s==='button'?button:null};
    assert.equal(h.click(target).prevented,false,'the native selection/open callback must still run');
    assert.equal(a.field.focuses,0);assert.equal(h.state.sourceReviewReturn.source,'first');
    cleanup();h.app.request={isConnected:true,closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,dataset:{sourceId:'first',field:'site',token:'new-native-action'}};
    cleanup=h.install();await h.flush();
    assert.equal(a.field.focuses,1);assert.equal(a.details.open,true);assert.equal(a.back.hidden,false);
    cleanup();cleanup=h.install();await h.flush();
    assert.equal(a.field.focuses,1,'an ordinary rerender cannot repeatedly steal editor focus');
    h.click(a.back);assert.equal(button.focused,true);assert.equal(h.state.sourceReviewReturn,null);
    cleanup();
});

function exactManager(h) {
    const parent={children:[],querySelector:s=>parent.children.find(n=>'.'+n.className===s)||null,append:n=>parent.children.push(n)};
    const marker={id:'report-correction-'+'a'.repeat(64),isConnected:true,
        dataset:{reportIdentity:h.state.identity,fieldKey:'exact',fieldKind:'combobox',navigationOwner:'exact-manager-page',navigationToken:'accepted-token'},
        closest:()=>null,parentElement:parent};
    const link={isConnected:true,dataset:{reportIdentity:h.state.identity,token:'accepted-token'},
        classList:{contains:s=>s==='enfra-page-correction-request'},getAttribute:()=>'#'+marker.id,closest:()=>null,parentElement:parent};
    const field=h.entries.second.field;field.parentElement=h.entries.second.details;field.getClientRects=()=>[{}];
    const original=h.app.querySelectorAll;
    h.app.querySelectorAll=s=>s==='.enfra-picture-correction'?[marker]:s==='.st-key-exact [role="combobox"]'?[field]:original(s);
    h.app.dispatchEvent=e=>h.app.listeners.get(e.type)?.(e);
    h.context.CustomEvent=class {constructor(type,options){this.type=type;this.detail=options.detail;}};
    h.context.CSS={escape:x=>x};
    vm.runInNewContext(fs.readFileSync('app/monthly_report_correction_navigation.js','utf8'),h.context);
    return {parent,marker,link,field,reveal:current=>h.context.ENFRAPictureCorrections.reveal(h.app,link,h.state.identity,current||(()=>true))};
}
function clickExactManager(h) {
    const warning={isConnected:true,dataset:{sourceId:'second',reportIdentity:h.state.identity,navigationOwner:'exact-manager-page'},closest:()=>null};
    const wrapper={querySelector:s=>s==='.enfra-source-warning'?warning:null};
    const button={closest:s=>s.includes('monthly_source_warning_')?wrapper:null,getBoundingClientRect:()=>({top:420})};
    return h.click({closest:s=>s==='button'?button:null});
}
for (const prior of [false,true]) test(`accepted exact manager-page Return has sole ownership, prior legacy=${prior}`,async()=>{
    const h=fixture(),cleanup=h.install();
    if(prior){h.click(h.entries.first.link);await h.flush();assert.equal(h.entries.first.back.hidden,false);}
    const previous=h.state.sourceReviewReturn, before=h.scroll.scrollTop;
    assert.equal(clickExactManager(h).prevented,false,'the real exact-owner callback must run');
    assert.equal(h.state.sourceReviewReturn,previous,'click is not acceptance');
    assert.equal(h.entries.first.back.hidden,!prior);
    const exact=exactManager(h);exact.reveal();await h.flush();
    assert.equal(h.state.sourceReviewReturn,previous,'accepted display ownership must retain the prior task');
    assert.equal(exact.parent.children.filter(n=>n.className==='enfra-correction-return').length,1);
    assert.ok(Object.values(h.entries).every(entry=>entry.back.hidden));
    assert.equal(h.scroll.scrollTop,before,'ownership transfer performs no scroll');
    // A completed old receipt cannot erase a later ordinary source task.
    h.click(h.entries.first.link);await h.flush();const next=h.state.sourceReviewReturn;
    h.app.dispatchEvent({type:'enfra-exact-correction-ready',detail:{...exact,back:exact.parent.children[0]}});
    assert.equal(h.state.sourceReviewReturn,next);assert.equal(h.entries.first.back.hidden,false);
    cleanup();
});

for(const retirement of ['return','marker-removed','field-disabled','field-inert','request-retired','owner-changed','token-changed','new-legacy-task'])
    test(`exact manager presentation retirement restores valid earlier legacy Return: ${retirement}`,async()=>{
        const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
        const prior=h.state.sourceReviewReturn,exact=exactManager(h);exact.reveal();await h.flush();
        const back=exact.parent.children.find(n=>n.className==='enfra-correction-return');
        assert.equal(h.entries.first.back.hidden,true);assert.equal(h.state.sourceReviewReturn,prior);
        if(retirement==='return') {
            back.closest=s=>s==='a'?back:null;
            assert.equal(h.click(back).prevented,false,'ordinary workspace handler still owns navigation');
        } else if(retirement==='new-legacy-task') h.click(h.entries.first.link);
        else {
            if(retirement==='marker-removed')exact.marker.isConnected=false;
            if(retirement==='field-disabled')exact.field.disabled=true;
            if(retirement==='field-inert')exact.field.closest=s=>s==='[inert]'?{}:null;
            if(retirement==='request-retired')exact.link.isConnected=false;
            if(retirement==='owner-changed')exact.marker.dataset.navigationOwner='foreign-owner';
            if(retirement==='token-changed')exact.link.dataset.token='foreign-token';
            h.changed(h.app);await h.flush();
        }
        assert.equal(back.hidden,true);assert.equal(h.entries.first.back.hidden,false);
        if(retirement!=='new-legacy-task')assert.equal(h.state.sourceReviewReturn,prior);
        cleanup();
    });

for(const action of ['Water','source-warning'])test(`native ${action} takeover replaces only exact presentation with the existing native legacy task`,async()=>{
    const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const exact=exactManager(h);exact.reveal();await h.flush();
    const back=exact.parent.children.find(n=>n.className==='enfra-correction-return');
    const marker={dataset:{sourceId:'second',...(action==='Water'?{returnTarget:'report-section-water'}:{})}};
    const wrapper={querySelector:()=>marker};
    const button={closest:s=>s.includes(action==='Water'?'monthly_source_page_correction_':'monthly_source_warning_')?wrapper:null,
        getBoundingClientRect:()=>({top:400})};
    assert.equal(h.click({closest:s=>s==='button'?button:null}).prevented,false);
    assert.equal(h.state.sourceReviewReturn.source,'second');assert.equal(back.hidden,true);
    assert.equal(h.entries.first.back.hidden,true);assert.equal(h.entries.second.back.hidden,false);
    assert.equal(h.state.sourceReviewReturn.target,action==='Water'?'report-section-water':undefined);
    cleanup();
});

test('consumed manager token cannot re-reveal a second Return after explicit legacy takeover',async()=>{
    const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const exact=exactManager(h);exact.reveal();await h.flush();
    h.click(h.entries.first.link);await h.flush();const prior=h.state.sourceReviewReturn;
    exact.reveal();await h.flush();
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);
    assert.equal(exact.parent.children.find(n=>n.className==='enfra-correction-return').hidden,true);
    cleanup();
});

test('same-report adapter reinstall retains the current exact presentation without losing prior task',async()=>{
    const h=fixture();let cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const prior=h.state.sourceReviewReturn,exact=exactManager(h);exact.reveal();await h.flush();
    cleanup();cleanup=h.install();await h.flush();
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,true);
    exact.link.isConnected=false;h.changed(h.app);await h.flush();
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);
    cleanup();assert.equal(h.app.listeners.size,0);
});

test('unchanged Return presentation does not trigger another observed text mutation',async()=>{
    const h=fixture(),cleanup=h.install();await h.flush();
    for(const entry of Object.values(h.entries)) {
        const text=entry.back.textContent;
        Object.defineProperty(entry.back,'textContent',{get:()=>text,set:()=>{throw Error('unchanged display must not mutate');}});
    }
    h.changed(h.app);await h.flush();cleanup();
});

test('accepted manager presentation never restores legacy Return into a foreign report',async()=>{
    const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const exact=exactManager(h);exact.reveal();await h.flush();
    h.state.identity='replacement-report';h.changed(h.app);await h.flush();
    assert.ok(Object.values(h.entries).every(entry=>entry.back.hidden));
    cleanup();
});

test('rejected native callback without accepted exact destination retains earlier Return',async()=>{
    const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const prior=h.state.sourceReviewReturn;
    assert.equal(clickExactManager(h).prevented,false);await h.flush();
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);
    cleanup();
});
for(const invalid of ['foreign','stale','retired','outside','duplicate','disabled','hidden','inert','cancelled','wrong-token','ordinary-link','ordinary-marker'])
    test(`unaccepted exact manager landing retains prior Return: ${invalid}`,async()=>{
        const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
        const prior=h.state.sourceReviewReturn,exact=exactManager(h);
        if(invalid==='foreign')exact.marker.dataset.reportIdentity='foreign';
        if(invalid==='stale')exact.marker.closest=()=>({});
        if(invalid==='retired')exact.marker.isConnected=false;
        if(invalid==='outside')exact.marker.insideApp=false;
        if(invalid==='duplicate'){const original=h.app.querySelectorAll;h.app.querySelectorAll=s=>s==='.enfra-picture-correction'?[exact.marker,exact.marker]:original(s);}
        if(invalid==='disabled')exact.field.disabled=true;
        if(invalid==='hidden')exact.field.getClientRects=()=>[];
        if(invalid==='inert')exact.field.closest=s=>s==='[inert]'?{}:null;
        if(invalid==='wrong-token')exact.link.dataset.token='different-token';
        if(invalid==='ordinary-link')exact.link.classList.contains=()=>false;
        if(invalid==='ordinary-marker')delete exact.marker.dataset.navigationOwner;
        clickExactManager(h);exact.reveal(()=>invalid!=='cancelled');await h.flush();
        assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);
        cleanup();
    });

for(const invalid of ['foreign','stale','retired','outside'])test(`invalid exact manager-page owner cannot retire or redirect legacy context: ${invalid}`,async()=>{
    const h=fixture(),cleanup=h.install();h.click(h.entries.first.link);await h.flush();
    const prior=h.state.sourceReviewReturn;
    const warning={isConnected:invalid!=='retired',insideApp:invalid!=='outside',
        dataset:{sourceId:'second',reportIdentity:invalid==='foreign'?'foreign':h.state.identity,navigationOwner:'exact-manager-page'},
        closest:()=>invalid==='stale'?{}:null};
    const wrapper={querySelector:()=>warning};
    const button={closest:s=>s.includes('monthly_source_warning_')?wrapper:null};
    assert.equal(h.click({closest:s=>s==='button'?button:null}).prevented,false);
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);assert.equal(h.entries.second.back.hidden,true);
    cleanup();
});

test('page correction keeps its native callback and returns to the same page task',async()=>{
    const h=fixture(),a=h.entries.first;let cleanup=h.install();
    const context={dataset:{sourceId:'first',returnTarget:'report-section-water'}};
    const wrapper={querySelector:s=>s==='.enfra-source-page-correction'?context:null};
    const button={isConnected:true,parentElement:h.scroll,top:420,getBoundingClientRect(){return{top:this.top};},
        closest:s=>s.includes('monthly_source_page_correction_')?wrapper:null,setAttribute(){},focus(){this.focused=true;}};
    const originalQuery=h.app.querySelector;
    h.app.querySelector=s=>s==='#report-section-water'?h.review:originalQuery(s);
    const target={closest:s=>s==='button'?button:null};
    assert.equal(h.click(target).prevented,false);
    assert.equal(h.state.sourceReviewReturn.target,'report-section-water');
    assert.equal(a.back.textContent,'Return to report pages');
    cleanup();h.app.request={isConnected:true,closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,dataset:{sourceId:'first',field:'site',token:'page-context-action'}};
    cleanup=h.install();await h.flush();
    assert.equal(a.field.focuses,1);button.top=120;
    h.click(a.back);assert.equal(h.scroll.scrollTop,500);assert.equal(button.focused,true);
    assert.equal(h.state.sourceReviewReturn,null);cleanup();
});


test('opening the single page owner scrolls its exact source once without reading input',async()=>{
    const h=fixture();
    const page={isConnected:true,parentElement:{getAnimations:()=>[]},focuses:0,scrolls:0,
        closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,
        setAttribute(){},focus(o){assert.equal(o.preventScroll,true);this.focuses++;},scrollIntoView(){this.scrolls++;}};
    const originalId=h.context.document.getElementById;
    h.context.document.getElementById=id=>id==='source-page-context-first'?page:originalId(id);
    const originalQuery=h.app.querySelector;
    h.app.querySelector=s=>s==='.enfra-report-page-target'?{isConnected:true,closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,dataset:{sourceId:'first',token:'one-open'}}:originalQuery(s);
    let cleanup=h.install();await h.flush();assert.equal(page.focuses,1);assert.equal(page.scrolls,1);
    cleanup();cleanup=h.install();await h.flush();assert.equal(page.focuses,1);cleanup();
});

test('native correction waits for its cold date input and cancels stale ownership',async()=>{
    for(const change of [false,true]) {
        const h=fixture(),a=h.entries.second;
        h.app.request={isConnected:true,closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,
            dataset:{sourceId:'second',field:'date',token:'native-cold-date'}};
        a.boundary.ready=false;
        const cleanup=h.install();await h.flush();assert.equal(a.field.focuses,0);
        if(change)h.state.identity='different-report';
        a.boundary.ready=true;h.changed(a.boundary);await h.flush();
        assert.equal(a.field.focuses,change?0:1);
        assert.equal(h.state.sourceReviewFocusToken,change?undefined:'native-cold-date');
        cleanup();assert.equal(h.observers.size,0);assert.equal(h.timers.size,0);
    }
});

test('a native source target in the no-Activity sibling manager requires its exact report owner',async()=>{
    for(const foreign of [false,true]) {
        const h=fixture(),a=h.entries.second;
        a.boundary.workspace=null;
        if(foreign)a.owner.dataset.reportIdentity='foreign-report';
        h.app.request={isConnected:true,closest:s=>s.includes('_source_manager_panel')?a.group:null,
            dataset:{sourceId:'second',field:'date',token:'native-sibling-date'}};
        const cleanup=h.install();await h.flush();
        assert.equal(a.field.focuses,foreign?0:1);
        cleanup();assert.equal(h.observers.size,0);
    }
});


test('native page focus cancels foreign, stale or detached target ownership before deferred focus',async()=>{
    for (const phase of ['resolve','frame']) for (const defect of ['foreign','stale','detached','outside']) {
        const h=fixture();
        const foreign={dataset:{epcMode:'wide'},_epcWorkspace:{identity:'foreign-report'}};
        const page={isConnected:true,insideApp:true,stale:false,workspace:h.workspace,focuses:0,scrolls:0,
            closest(s){return s.includes('epc_workspace_monthly')?this.workspace:s==='[data-stale="true"]'&&this.stale?this:null;},
            setAttribute(){},focus(){this.focuses++;},scrollIntoView(){this.scrolls++;}};
        const change=()=>{if(defect==='foreign')page.workspace=foreign;else if(defect==='stale')page.stale=true;
            else if(defect==='detached')page.isConnected=false;else page.insideApp=false;};
        const originalId=h.context.document.getElementById;
        h.context.document.getElementById=id=>id==='source-page-context-first'?page:originalId(id);
        const originalQuery=h.app.querySelector;
        const request={isConnected:true,closest:s=>s.includes('epc_workspace_monthly')?h.workspace:null,
            dataset:{sourceId:'first',token:'owner-check'}};
        h.app.querySelector=s=>s==='.enfra-report-page-target'?request:originalQuery(s);
        if(phase==='resolve')change();
        const cleanup=h.install();
        if(phase==='frame'){await Promise.resolve();await Promise.resolve();change();}
        await h.flush();
        assert.equal(page.focuses,0,phase+' '+defect);assert.equal(page.scrolls,0);
        assert.equal(h.state.sourcePageFocusToken,undefined);cleanup();
    }
});

if(process.env.ENFRA_MANAGER_ACCEPTED_RECEIPT) test('actual server acceptance receipt keeps prior context and one visible Return, including failed durable save',async()=>{
    const receipt=JSON.parse(process.env.ENFRA_MANAGER_ACCEPTED_RECEIPT);
    assert.equal(receipt.saveFailed,Boolean(receipt.failure));
    const attributes=tag=>Object.fromEntries([...tag.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
    const markers=[...receipt.markup.matchAll(/<span[^>]+class="enfra-picture-correction"[^>]*>/g)].map(m=>attributes(m[0]));
    const accepted=markers.filter(marker=>marker['data-navigation-owner']==='exact-manager-page');
    const requests=[...receipt.markup.matchAll(/<a[^>]+class="enfra-page-correction-request"[^>]*>/g)].map(m=>attributes(m[0]));
    assert.equal(accepted.length,1);assert.equal(requests.length,1);
    const marker=accepted[0],request=requests[0];
    assert.equal(marker['data-navigation-owner'],'exact-manager-page');
    assert.ok(marker['data-navigation-token']);assert.equal(marker['data-navigation-token'],request['data-token']);
    assert.equal(request.href,'#'+marker.id);assert.equal(marker['data-report-identity'],request['data-report-identity']);
    const h=fixture();h.state.identity=marker['data-report-identity'];const cleanup=h.install();
    h.click(h.entries.first.link);await h.flush();const prior=h.state.sourceReviewReturn;
    const exact=exactManager(h);exact.marker.id=marker.id;
    exact.marker.dataset.navigationToken=marker['data-navigation-token'];exact.link.dataset.token=request['data-token'];
    clickExactManager(h);exact.reveal();await h.flush();
    const back=exact.parent.children.find(n=>n.className==='enfra-correction-return');
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(back.hidden,false);
    assert.ok(Object.values(h.entries).every(entry=>entry.back.hidden));
    exact.marker.isConnected=false;h.changed(h.app);await h.flush();
    assert.equal(h.state.sourceReviewReturn,prior);assert.equal(h.entries.first.back.hidden,false);assert.equal(back.hidden,true);
    cleanup();
});
