() => {
    // Passive synthetic QA only. No text, source, URL, DOM IDs or function source.
    // Existing exposed workspace state is read; private controller closures are not.
    const LIMIT = 1048576, RECORDS = 256, BUDGET = LIMIT - 4096;
    const ROOT = '.st-key-epc_workspace_monthly', NAV = '.st-key-monthly_report_navigation';
    const ids = new WeakMap(); let nextId = 0, records = [], bytes = 0, dropped = 0, errors = 0;
    let disposed = false, observer = null, observedApp = null, observedParent = null;
    let lastIdentity, identityOrdinal = 0, sequence = 0;
    const removals = [];
    const number = value => Number.isFinite(value) ? value : null;
    const id = value => value && ['object','function'].includes(typeof value)
        ? (ids.has(value) ? ids.get(value) : (ids.set(value,++nextId),nextId)) : 0;
    const query = (node,selector) => Array.from(node?.querySelectorAll?.(selector) || []);
    const unique = (node,selector) => {const nodes=query(node,selector);return nodes.length===1?nodes[0]:null;};
    const current = node => Boolean(node?.isConnected && !node.closest?.('[data-stale="true"]'));
    const closed = (node,boundary) => {
        for(let p=node;p&&p!==boundary;p=p.parentElement)
            if(p.dataset?.testid==='stExpanderDetails' && p.hasAttribute?.('inert') &&
                p.parentElement?.tagName==='DETAILS' && !p.parentElement.open) return true;
        return false;
    };
    const owner = node => ({id:id(node),connected:Boolean(node?.isConnected),current:current(node),
        direct_stale:node?.dataset?.stale==='true'});
    const readiness = item => {
        if(!item)return null;
        const target=item.target,focus=target?.querySelector?.('h1,h2,h3,h4')||target;
        const stale=query(target,'[data-stale="true"]');let hidden=0;
        for(const node of stale.slice(0,64))if(closed(node,target))hidden++;
        return {target:owner(target),marker:owner(item.marker),focus:owner(focus),
            focus_hidden:closed(focus,target),stale_count:stale.length,hidden_stale: hidden,
            visible_stale:Math.min(64,stale.length)-hidden,scan_truncated:stale.length>64};
    };
    const control = (nav,selector) => {
        const nodes=query(nav,selector),node=nodes.length===1?nodes[0]:null;
        return {node,data:{count:nodes.length,...owner(node),disabled:Boolean(node?.disabled),
            handler:id(node?.onclick),has_handler:typeof node?.onclick==='function'}};
    };
    const collect = () => {
        const roots=query(document,ROOT),root=roots.length===1?roots[0]:null;
        const app=root?.closest?.('[data-testid="stMainBlockContainer"]');
        const port=root?.closest?.('[data-testid="stMain"]'),nav=unique(root,NAV);
        const state=root?._epcWorkspace, markers=query(root,'[data-epc-pair]');
        const sections=markers.slice(0,32).map(marker=>({section:marker.dataset?.epcPair,marker,
            target:marker.closest?.('.st-key-epc_pair_' + CSS.escape(marker.dataset.epcPair))}));
        const reviews=query(app,'#report-review');
        if(reviews.length===1)sections.push({section:'report_review',marker:null,target:reviews[0]});
        const index=value=>value==null?-1:sections.findIndex(item=>item.section===value);
        const back=control(nav,'.epc-section-back'),next=control(nav,'.epc-section-next');
        const status=unique(nav,'.epc-section-progress'),intent=state?.navigationIntent;
        if(state && state.identity!==lastIdentity){lastIdentity=state.identity;identityOrdinal++;}
        const active=document.activeElement, kind=active===next.node?'next':active===back.node?'back':
            ['INPUT','TEXTAREA','SELECT'].includes(active?.tagName)?'editor':
            sections.some(item=>item.target?.contains?.(active))?'section':'other';
        const mode=['wide','compact','book','tabletop'].includes(state?.mode)?state.mode:null;
        const fullRender=root?.dataset?.epcFullRender;
        const snapshot={root_count:roots.length,root:owner(root),app:owner(app),port:owner(port),nav:owner(nav),
            state_id:id(state),controller_id:id(state?.navigationController),report_ordinal:identityOrdinal,
            // Render tokens are compared in-memory only; no raw identity is emitted.
            render_changed:fullRender!==collect.lastRender,mode,owns_scroll:Boolean(state?.ownsScroll),
            root_scroll:number(root?.scrollTop),port_scroll:number(port?.scrollTop),
            viewport:{width:number(window.innerWidth),height:number(window.innerHeight)},
            script_state:['running','notRunning'].includes(document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'))
                ?document.querySelector('[data-testid="stApp"]').getAttribute('data-test-script-state'):null,
            back:back.data,next:next.data,status:{...owner(status),index:index(status?.dataset?.section)},
            focus:{...owner(active),kind},active_index:index(state?.navigationActive),layout_active_index:index(state?.active),
            jump_index:index(state?.navigationJump?.id),jump_scroll:number(state?.navigationJump?.scroll),
            landing_index:index(state?.landingRequest),review_navigation:Boolean(state?.reviewNavigation),explicit_review:Boolean(state?.explicitReview),
            request_index:index(state?.navigationRequest),
            request_present:Boolean(state?.navigationRequest),input_serial:number(state?.navigationInputSerial||0),
            sections_count:markers.length,sections_truncated:markers.length>32,review_count:reviews.length,
            order:sections.map(item=>({marker:id(item.marker),target:id(item.target),connected:Boolean(item.target?.isConnected)})),
            origin:readiness(sections[index(intent?.origin ?? state?.navigationActive)]),
            destination:readiness(sections[index(intent?.target ?? state?.navigationRequest)]),
            intent:intent?{id:id(intent),owner_id:id(intent.owner),owner_matches:intent.owner===state?.navigationController,
                report_matches:intent.identity===state?.identity,origin_index:index(intent.origin),target_index:index(intent.target),
                origin_matches:intent.origin===state?.navigationActive,request_matches:intent.target===state?.navigationRequest,
                input_matches:intent.input===(state?.navigationInputSerial||0),back_matches:intent.back===back.node,next_matches:intent.next===next.node,
                nodes_match:Array.isArray(intent.nodes)&&intent.nodes.length===sections.length&&intent.nodes.every((item,i)=>
                    item.id===sections[i].section&&item.target===sections[i].target&&item.marker===sections[i].marker)}:null};
        collect.lastRender=fullRender;
        return {snapshot,root,app};
    };
    const append = record => {
        const text=JSON.stringify(record),size=new TextEncoder().encode(text).length+1;
        if(size>BUDGET){dropped++;return;}
        while(records.length>=(record.source==='finally'?RECORDS:RECORDS-1) || bytes+size>BUDGET){bytes-=records.shift().size;dropped++;}
        records.push({record,size});bytes+=size;
    };
    const sample = (source,event=null) => {
        if(disposed)return;
        try {
            const {snapshot,app}=collect();
            if(observer && (app!==observedApp || app?.parentElement!==observedParent))watch(app);
            const native=event?{type:event.type,trusted:Boolean(event.isTrusted),prevented:Boolean(event.defaultPrevented),
                target:id(event.target),key:['Enter',' ','Tab','ArrowUp','ArrowDown','Escape'].includes(event.key)?event.key:null,
                button:[0,1,2].includes(event.button)?event.button:null}:null;
            append({sequence:++sequence,at_ms:number(performance.now()),source,native,...snapshot});
        } catch {errors++;}
    };
    function watch(app) {
        observer.disconnect();observedApp=app;observedParent=app?.parentElement||null;
        if(app)observer.observe(app,{childList:true,subtree:true,attributes:true,
            attributeFilter:['data-stale','data-epc-full-render','data-epc-mode','data-section','disabled','open','inert']});
        if(observedParent)observer.observe(observedParent,{childList:true});
    }
    const listen = (target,type,callback,capture=false) => {
        target.addEventListener(type,callback,{capture,passive:true});
        removals.push(()=>target.removeEventListener(type,callback,{capture}));
    };
    const output = () => ({schema:1,limits:{records:RECORDS,bytes:LIMIT},dropped,errors,
        disposed,records:records.map(item=>item.record)});
    const stop = () => {
        if(disposed)return output();
        sample('finally');disposed=true;
        // Independent cleanup steps: one failure must not leave other listeners live.
        try {observer?.disconnect();} catch {errors++;}
        for(const remove of removals)try {remove();} catch {errors++;}
        removals.length=0;return output();
    };
    window.__enfraNavigationObservation={stop};
    try {
        observer=new MutationObserver(()=>sample('mutation'));
        watch(collect().app);
        for(const type of ['keydown','keyup','click','focusin','focusout'])listen(document,type,event=>{
            const root=unique(document,ROOT);
            if(!root?.contains?.(event.target)&&!observedApp?.contains?.(event.target))return;
            sample('native-capture',event);
            // Observe after normal dispatch; never wrap or invoke a product handler.
            queueMicrotask(()=>sample('native-after-dispatch',event));
        },true);
        listen(window,'resize',()=>sample('resize'));
        listen(document,'epc-workspace-layout',event=>{if(event.target===unique(document,ROOT))sample('layout');});
        sample('installed');
    } catch {errors++;stop();}
    return {schema:1,installed:!disposed};
}
