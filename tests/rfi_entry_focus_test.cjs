const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');

function fixture() {
    const frames=new Map(), observers=new Set();let sequence=0;
    function events() {
        const listeners=new Map();
        return {listeners,addEventListener(type,fn){
            const values=listeners.get(type)||new Set();values.add(fn);listeners.set(type,values);
        },removeEventListener(type,fn){listeners.get(type)?.delete(fn);if(!listeners.get(type)?.size)listeners.delete(type);},
        emit(type,extra={}){const event={type,isTrusted:true,...extra};for(const fn of [...(listeners.get(type)||[])])fn(event);return event;}};
    }
    const body={},documentElement={},document={...events(),body,documentElement,activeElement:body,hidden:false};
    const window=events(),state={identity:'report-a'},root={...events(),isConnected:true};
    root._epcWorkspace=state;
    const markers=[],buttons=new Map(),fields=new Map(),origins=[];
    const editor={isConnected:true,stale:false,owner:root,
        closest(selector){return selector.includes('data-stale')?this.stale?this:null:this;},
        querySelectorAll(selector){return selector==='[data-epc-entry-focus]'?markers:selector==='[data-epc-entry-origin]'?origins:[];}};
    function element(extra={}) {
        return {isConnected:true,owner:root,editor,stale:false,inert:false,disabled:false,
            closest(selector){
                if(selector==='button')return this.button||null;
                if(selector.includes('data-stale'))return this.stale||this.inert?this:null;
                if(selector==='.st-key-epc_edit_monthly_rfi')return this.editor;
                return null;
            },getAttribute(){return null;},...extra};
    }
    root.contains=node=>node.owner===root;
    root.querySelectorAll=selector=>{
        if(selector==='.st-key-epc_edit_monthly_rfi')return [editor];
        for(const [key,button] of buttons)if(selector==='.st-key-'+key+' button')return [button];
        for(const [key,field] of fields)if(selector==='.st-key-'+key+' input:not([type="hidden"]),.st-key-'+key+' textarea')return [field];
        return [];
    };
    const origin='row-table-a_add',button=element();button.button=button;
    buttons.set(origin,button);
    origins.push(element({dataset:{epcEntryOrigin:origin}}));
    function acknowledge(token='new-draft',key='new-row_requested',from=origin) {
        const field=element({focuses:0,scrolls:0,getClientRects(){return this.visible===false?[]:[{}];},
            focus(options){assert.equal(options.preventScroll,true);this.focuses++;document.activeElement=this;document.emit('focusin',{target:this});},
            scrollIntoView(options){assert.equal(options.block,'nearest');assert.equal(options.inline,'nearest');this.scrolls++;}});
        for(const name of ['value','selectionStart','selectionEnd'])Object.defineProperty(field,name,{
            get(){throw Error('Focus must not read native business input or caret');},set(){throw Error('Focus must not change native business input or caret');}});
        const marker=element({dataset:{epcEntryFocus:token,epcFieldKey:key,epcOriginKey:from}});
        markers.push(marker);fields.set(key,field);
        return {marker,field,key};
    }
    class Observer {
        constructor(callback){this.callback=callback;}
        observe(target,options){assert.equal(target,root);assert.equal(options.subtree,true);observers.add(this);}
        disconnect(){observers.delete(this);}
    }
    const context={document,window,CSS:{escape:value=>value},MutationObserver:Observer,
        requestAnimationFrame:fn=>{frames.set(++sequence,fn);return sequence;},cancelAnimationFrame:id=>frames.delete(id),
        setTimeout(){throw Error('A one-shot focus request cannot poll or use a timer');}};
    vm.runInNewContext(fs.readFileSync('app/monthly_report_entry_focus.js','utf8'),context);
    const install=()=>context.ENFRAEntryFocus.install(root,state);
    const click=(extra={})=>root.emit('click',{target:button,button:0,defaultPrevented:false,...extra});
    const flush=()=>{for(const[id,fn]of [...frames]){frames.delete(id);fn();}};
    const changed=()=>{for(const observer of [...observers])observer.callback([]);};
    return{install,click,flush,changed,acknowledge,element,root,state,document,window,editor,button,origin,origins,markers,fields,frames,observers};
}

test('one trusted native Add focuses only its newly acknowledged request, without reading or changing values',()=>{
    const h=fixture(),cleanup=h.install();
    h.click();h.flush();assert.equal(h.document.activeElement,h.document.body);
    assert.equal(h.observers.size,1);
    const {field}=h.acknowledge();h.changed();h.flush();
    assert.equal(field.focuses,1);assert.equal(field.scrolls,1);assert.equal(h.document.activeElement,field);
    assert.equal(h.state.entryFocus.pending,null);assert.equal(h.observers.size,0);assert.equal(h.frames.size,0);
    h.changed();h.flush();assert.equal(field.focuses,1);
    cleanup();assert.equal(h.root.listeners.size,0);assert.equal(h.document.listeners.size,0);assert.equal(h.window.listeners.size,0);
});

test('native keyboard activation consumes the same one-shot receipt',()=>{
    const h=fixture(),cleanup=h.install();h.document.activeElement=h.button;
    h.document.emit('keydown',{target:h.button,key:'Enter'});h.click({detail:0});
    const {field}=h.acknowledge();h.changed();h.flush();assert.equal(field.focuses,1);
    cleanup();
});

test('a genuine delayed server acknowledgement has no timer-based focus or cancellation',()=>{
    const h=fixture(),cleanup=h.install();h.click();
    for(let count=0;count<10;count++){h.changed();h.flush();}
    assert.ok(h.state.entryFocus.pending);assert.equal(h.observers.size,1);
    const {field}=h.acknowledge();h.changed();h.flush();assert.equal(field.focuses,1);
    cleanup();
});

test('same-report adapter handoff preserves a pending Add but never replays an already consumed nonce',()=>{
    const h=fixture();let cleanup=h.install();h.click();h.flush();cleanup();
    assert.equal(h.observers.size,0);assert.ok(h.state.entryFocus.pending);
    cleanup=h.install();const {field}=h.acknowledge();h.changed();h.flush();assert.equal(field.focuses,1);
    cleanup();cleanup=h.install();h.changed();h.flush();assert.equal(field.focuses,1);
    assert.equal(h.observers.size,0);cleanup();
});

test('an old active draft on reload or layout refresh cannot steal focus',()=>{
    for(const active of ['body','other field']) {
        const h=fixture(),{field}=h.acknowledge('restored-draft');
        if(active==='other field')h.document.activeElement=h.element();
        const before=h.document.activeElement,cleanup=h.install();h.changed();h.flush();
        assert.equal(field.focuses,0);assert.equal(h.document.activeElement,before);assert.equal(h.observers.size,0);
        cleanup();
    }
});

test('a new Add waits for a fresh nonce and does not focus the prior rendered row',()=>{
    const h=fixture(),old=h.acknowledge('prior-draft','old_requested'),cleanup=h.install();
    h.click();h.flush();assert.equal(old.field.focuses,0);
    const next=h.acknowledge('next-draft');h.changed();h.flush();
    assert.equal(old.field.focuses,0);assert.equal(next.field.focuses,1);cleanup();
});

test('later pointer, keyboard, assistive click, wheel, touch, or focused control cancels a delayed focus request',()=>{
    for(const type of ['pointerdown','keydown','click','wheel','touchstart','focusin']) {
        const h=fixture(),cleanup=h.install();h.click();h.flush();
        const chosen=h.element();h.document.activeElement=chosen;
        h.document.emit(type,{target:chosen,key:'Tab'});
        const {field}=h.acknowledge();h.changed();h.flush();
        assert.equal(field.focuses,0,type);assert.equal(h.document.activeElement,chosen,type);
        assert.equal(h.observers.size,0,type);assert.equal(h.state.entryFocus.pending,null,type);cleanup();
    }
});

test('deliberately returning focus to the former input cancels the pending Add focus',()=>{
    const h=fixture(),cleanup=h.install(),previous=h.element();h.document.activeElement=previous;
    h.click();h.document.emit('focusin',{target:previous});
    const{field}=h.acknowledge();h.changed();h.flush();
    assert.equal(field.focuses,0);assert.equal(h.document.activeElement,previous);cleanup();
});

test('delivered paste, dictation or composition input in the still-focused previous field cancels delayed focus',()=>{
    for(const type of ['beforeinput','input','compositionstart','compositionupdate','compositionend']) {
        const h=fixture(),cleanup=h.install(),previous=h.element();h.document.activeElement=previous;
        h.click();h.flush();assert.ok(h.state.entryFocus.pending,type);
        h.document.emit(type,{target:previous,inputType:'insertFromPaste'});
        const{field}=h.acknowledge();h.changed();h.flush();
        assert.equal(field.focuses,0,type);assert.equal(h.document.activeElement,previous,type);
        assert.equal(h.observers.size,0,type);assert.equal(h.state.entryFocus.pending,null,type);cleanup();
    }
});

test('untrusted input notifications do not cancel an acknowledged native Add',()=>{
    for(const type of ['beforeinput','input','compositionstart','compositionupdate','compositionend']) {
        const h=fixture(),cleanup=h.install(),previous=h.element();h.document.activeElement=previous;
        h.click();h.document.emit(type,{target:previous,isTrusted:false});
        const{field}=h.acknowledge();h.changed();h.flush();
        assert.equal(field.focuses,1,type);assert.equal(h.state.entryFocus.pending,null,type);cleanup();
    }
});

test('hidden-tab and page exit cancellation cannot cause a jump on return',()=>{
    for(const type of ['visibilitychange','pagehide']) {
        const h=fixture(),cleanup=h.install();h.click();h.flush();
        if(type==='visibilitychange'){h.document.hidden=true;h.document.emit(type);h.document.hidden=false;}
        else h.window.emit(type);
        const {field}=h.acknowledge();h.changed();h.document.emit('visibilitychange');h.flush();
        assert.equal(field.focuses,0,type);assert.equal(h.observers.size,0,type);cleanup();
    }
});

test('already moved native focus cancels even when an earlier focus event was not observed',()=>{
    const h=fixture(),cleanup=h.install();h.click();
    const chosen=h.element();h.document.activeElement=chosen;
    const {field}=h.acknowledge();h.changed();h.flush();
    assert.equal(field.focuses,0);assert.equal(h.document.activeElement,chosen);cleanup();
});

test('a candidate is rechecked for stale, inert, disabled and visible state on a qualifying observed mutation',()=>{
    for(const reason of ['stale','inert','disabled','hidden']) {
        const h=fixture(),cleanup=h.install();h.click();const{field}=h.acknowledge();
        if(reason==='hidden')field.visible=false;else field[reason]=true;
        h.changed();h.flush();assert.equal(field.focuses,0,reason);
        // The model invokes an observer notification; this does not establish
        // that a CSS-only hidden-to-visible transition emits such a mutation.
        field.stale=false;field.inert=false;field.disabled=false;field.visible=true;
        h.changed();h.flush();assert.equal(field.focuses,1,reason);cleanup();
    }
});

test('a field or marker belonging to another workspace or request origin is not eligible',()=>{
    for(const reason of ['field owner','marker owner','field editor','origin','stale marker']) {
        const h=fixture(),cleanup=h.install();h.click();const{marker,field}=h.acknowledge();
        if(reason==='field owner')field.owner={};
        if(reason==='marker owner')marker.owner={};
        if(reason==='field editor')field.editor={};
        if(reason==='origin')marker.dataset.epcOriginKey='another-row_add';
        if(reason==='stale marker')marker.stale=true;
        h.changed();h.flush();assert.equal(field.focuses,0,reason);cleanup();
    }
});

test('ambiguous current focus markers cannot select an arbitrary request row',()=>{
    const h=fixture(),cleanup=h.install();h.click();
    const first=h.acknowledge('one','first_requested'),second=h.acknowledge('two','second_requested');
    h.changed();h.flush();assert.equal(first.field.focuses,0);assert.equal(second.field.focuses,0);
    h.document.emit('keydown',{target:h.document.body,key:'Tab'});
    h.markers.pop();h.changed();h.flush();assert.equal(first.field.focuses,0);cleanup();
});

test('synthetic, modified, disabled, stale or unrelated buttons cannot arm the consumer',()=>{
    for(const reason of ['untrusted','modified','disabled','aria disabled','stale','wrong editor','unrelated','prevented']) {
        const h=fixture(),cleanup=h.install(),extra={};
        if(reason==='untrusted')extra.isTrusted=false;
        if(reason==='modified')extra.ctrlKey=true;
        if(reason==='disabled')h.button.disabled=true;
        if(reason==='aria disabled')h.button.getAttribute=()=> 'true';
        if(reason==='stale')h.button.stale=true;
        if(reason==='wrong editor')h.button.editor=null;
        if(reason==='unrelated'){extra.target=h.element();extra.target.button=extra.target;}
        if(reason==='prevented')extra.defaultPrevented=true;
        h.click(extra);const{field}=h.acknowledge();h.changed();h.flush();
        assert.equal(field.focuses,0,reason);assert.equal(h.state.entryFocus.pending,null,reason);
        assert.equal(h.observers.size,0,reason);cleanup();
    }
});

test('replacing the report, root owner or connection rejects late focus before touching a field',()=>{
    for(const reason of ['report','owner','removed']) {
        const h=fixture(),cleanup=h.install();h.click();const{field}=h.acknowledge();
        if(reason==='report')h.state.identity='report-b';
        if(reason==='owner')h.root._epcWorkspace={};
        if(reason==='removed')h.root.isConnected=false;
        h.flush();assert.equal(field.focuses,0,reason);assert.equal(h.observers.size,0,reason);cleanup();
    }
});

test('new report installation cannot inherit another report pending focus',()=>{
    const h=fixture();let cleanup=h.install();h.click();cleanup();h.state.identity='report-b';
    cleanup=h.install();const{field}=h.acknowledge();h.changed();h.flush();
    assert.equal(field.focuses,0);assert.equal(h.state.entryFocus.pending,null);assert.equal(h.observers.size,0);cleanup();
});

test('cancel then a new deliberate Add may focus only the replacement draft',()=>{
    const h=fixture(),cleanup=h.install();h.click();h.document.emit('pointerdown',{target:h.element()});
    const old=h.acknowledge('canceled','canceled_requested');h.changed();h.flush();assert.equal(old.field.focuses,0);
    h.click();const next=h.acknowledge('replacement');h.changed();h.flush();
    assert.equal(next.field.focuses,1);assert.equal(old.field.focuses,0);cleanup();
});
