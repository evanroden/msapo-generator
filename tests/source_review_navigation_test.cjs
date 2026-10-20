const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture() {
    const frames=new Map(),timers=new Map(),observers=new Set();let seq=0;
    const state={},workspace={dataset:{epcMode:'wide'}};workspace._epcWorkspace=state;
    const scroll={scrollTop:800,scrollHeight:5000,clientHeight:750,parentElement:null};
    const review={parentElement:scroll,top:80,isConnected:true,focuses:0,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(o){assert.equal(o.preventScroll,true);this.focuses++;}};
    const entries={};
    for(const id of ['first','second']) {
        // Streamlit's native summary owns both its expanded state and the
        // inert body. Assigning details.open alone leaves controls inactive.
        function disclosure(parentElement) {
            const node={tagName:'DETAILS',open:false,expanded:false,inert:true,clicks:0,parentElement};
            node.summary={click(){node.clicks++;node.expanded=!node.expanded;node.open=node.expanded;node.inert=!node.expanded;}};
            node.querySelector=selector=>selector===':scope > summary'?node.summary:null;
            return node;
        }
        const outer=disclosure(scroll),details=disclosure(outer);
        const field={disabled:false,isConnected:true,stale:false,focuses:0,scrolls:0,closest(selector){return selector==='[inert]'?(outer.inert||details.inert?details:null):this.stale?this:null;},focus(o){assert.equal(o.preventScroll,true);if(!outer.inert&&!details.inert)this.focuses++;},scrollIntoView(){this.scrolls++;}};
        Object.defineProperty(field,'value',{get(){throw Error('navigation cannot read business values');},set(){throw Error('navigation cannot write business values');}});
        const dateWidget={querySelector:s=>s==='label'?{textContent:'Source date'}:s==='input'?field:null};
        const boundary={parentElement:outer,isConnected:true,ready:true,workspace,
            closest(selector){return selector.includes('epc_workspace_monthly')?this.workspace:null;},
            querySelector:s=>boundary.ready&&id==='first'&&s.includes('Source sites')?field:null,
            querySelectorAll:s=>s==='details'?[details]:boundary.ready&&s==='[data-testid="stDateInput"]'&&id==='second'?[dateWidget]:[],getAnimations:()=>[]};
        const marker={closest:()=>boundary};
        const link={isConnected:true,parentElement:scroll,top:400,classList:{contains:()=>false},closest(){return this;},getAttribute:()=>`#source-details-${id}--${id==='first'?'site':'date'}`,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(){this.focused=true;}};
        const back={dataset:{sourceId:id},hidden:true,classList:{contains:()=>true},closest(){return this;}};
        entries[id]={outer,details,field,boundary,marker,link,back};
    }
    const correctionMarkers=[];
    function inline(tag) {
        const attrs={};
        return {tagName:tag.toUpperCase(),isConnected:true,parentElement:scroll,
            textContent:'',getAttribute:key=>attrs[key],setAttribute:(key,value)=>{attrs[key]=value;},
            classList:{contains:()=>false},closest(){return this;},
            getBoundingClientRect:()=>({top:400}),focus(){this.focused=true;},
            after(replacement){this.alert.link=replacement;replacement.alert=this.alert;},
            remove(){if(this.alert.link===this)this.alert.link=null;}};
    }
    const app={listeners:new Map(),contains:()=>true,querySelector:()=>review,
        querySelectorAll:s=>s==='.enfra-source-correction'?correctionMarkers:Object.values(entries).map(v=>v.back),
        addEventListener(k,fn){this.listeners.set(k,fn);},removeEventListener(k,fn){if(this.listeners.get(k)===fn)this.listeners.delete(k);}};
    const addCorrection=id=>{
        const alert={querySelector:s=>s==='a[data-enfra-correction-link]'?alert.link:null,
            querySelectorAll:s=>s==='strong'?[alert.status]:[]};
        alert.status=inline('strong');alert.status.textContent='Loading correction controls…';alert.status.alert=alert;
        Object.defineProperty(alert,'control',{get:()=>alert.link||alert.status});
        const container={querySelector:()=>alert};
        const marker={dataset:{sourceId:id,kind:id==='first'?'site':'date',label:id==='first'?'Correct site':'Correct date'},
            closest:s=>s.includes('epc_workspace_monthly')?workspace:container};
        correctionMarkers.push(marker);return alert;
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
    return{entries,app,state,workspace,review,scroll,install,click,flush,changed,expire,observers,timers,pendingObservers,addCorrection};
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
