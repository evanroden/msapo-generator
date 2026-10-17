const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture() {
    const frames=new Map();let seq=0;
    const scroll={scrollTop:800,scrollHeight:5000,clientHeight:750,parentElement:null};
    const review={parentElement:scroll,top:80,isConnected:true,focuses:0,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(o){assert.equal(o.preventScroll,true);this.focuses++;}};
    const entries={};
    for(const id of ['first','second']) {
        const outer={tagName:'DETAILS',open:false,parentElement:scroll},details={open:false};
        const field={disabled:false,isConnected:true,focuses:0,scrolls:0,focus(o){assert.equal(o.preventScroll,true);this.focuses++;},scrollIntoView(){this.scrolls++;}};
        Object.defineProperty(field,'value',{get(){throw Error('navigation cannot read business values');},set(){throw Error('navigation cannot write business values');}});
        const boundary={parentElement:outer,querySelector:s=>s.includes(id==='first'?'Source sites':'Source date')?field:null,querySelectorAll:()=>[details],getAnimations:()=>[]};
        const marker={closest:()=>boundary};
        const link={isConnected:true,parentElement:scroll,top:400,classList:{contains:()=>false},closest(){return this;},getAttribute:()=>`#source-details-${id}--${id==='first'?'site':'date'}`,getBoundingClientRect(){return{top:this.top};},setAttribute(){},focus(){this.focused=true;}};
        const back={dataset:{sourceId:id},hidden:true,classList:{contains:()=>true},closest(){return this;}};
        entries[id]={outer,details,field,boundary,marker,link,back};
    }
    const app={request:null,listeners:new Map(),contains:()=>true,querySelector:s=>s==='#report-review'?review:app.request,querySelectorAll:()=>Object.values(entries).map(v=>v.back),addEventListener(k,fn){this.listeners.set(k,fn);},removeEventListener(k,fn){if(this.listeners.get(k)===fn)this.listeners.delete(k);}};
    const context={document:{getElementById:id=>entries[id.replace('source-details-','')]?.marker,scrollingElement:scroll},getComputedStyle:()=>({overflowY:'auto'}),Promise,requestAnimationFrame:fn=>{frames.set(++seq,fn);return seq;},cancelAnimationFrame:id=>frames.delete(id)};
    vm.runInNewContext(fs.readFileSync('app/monthly_report_source_navigation.js','utf8'),context);
    const state={};const install=()=>context.ENFRASourceReviewNavigation.install(app,state);
    const click=(target,other={})=>{const e={button:0,target,prevented:false,preventDefault(){this.prevented=true;},...other};app.listeners.get('click')(e);return e;};
    const flush=async()=>{await Promise.resolve();await Promise.resolve();for(const [id,fn]of frames){frames.delete(id);fn();}};
    return{entries,app,state,review,scroll,install,click,flush};
}

test('one correction opens its outer and exact source disclosure and focuses its native field',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first,b=h.entries.second;
    assert.equal(h.click(a.link).prevented,true);await h.flush();
    assert.equal(a.outer.open,true);assert.equal(a.details.open,true);assert.equal(a.field.focuses,1);assert.equal(a.field.scrolls,1);
    assert.equal(b.details.open,false);assert.equal(b.field.focuses,0);
    assert.equal(a.back.hidden,false);assert.equal(b.back.hidden,true);
    h.click(b.link);await h.flush();
    assert.equal(b.field.focuses,1);assert.equal(a.back.hidden,true);assert.equal(b.back.hidden,false);
    cleanup();assert.equal(h.app.listeners.size,0);
});

test('Return restores the same warning and accepts already-open disclosures',async()=>{
    const h=fixture(),cleanup=h.install(),a=h.entries.first;a.outer.open=true;a.details.open=true;
    h.click(a.link);await h.flush();a.link.top=100;
    h.click(a.back);assert.equal(h.scroll.scrollTop,500);assert.equal(a.link.focused,true);assert.equal(a.back.hidden,true);
    cleanup();
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

test('native warning action retains its callback and a new target focuses once after rerun',async()=>{
    const h=fixture(),a=h.entries.first;let cleanup=h.install();
    const warning={dataset:{sourceId:'first'}};
    const wrapper={querySelector:()=>warning};
    const button={isConnected:true,parentElement:h.scroll,getBoundingClientRect:()=>({top:420}),closest:()=>wrapper,setAttribute(){},focus(){this.focused=true;}};
    const target={closest:s=>s==='button'?button:null};
    assert.equal(h.click(target).prevented,false,'the native selection/open callback must still run');
    assert.equal(a.field.focuses,0);assert.equal(h.state.sourceReviewReturn.source,'first');
    cleanup();h.app.request={dataset:{sourceId:'first',field:'site',token:'new-native-action'}};
    cleanup=h.install();await h.flush();
    assert.equal(a.field.focuses,1);assert.equal(a.details.open,true);assert.equal(a.back.hidden,false);
    cleanup();cleanup=h.install();await h.flush();
    assert.equal(a.field.focuses,1,'an ordinary rerender cannot repeatedly steal editor focus');
    h.click(a.back);assert.equal(button.focused,true);assert.equal(h.state.sourceReviewReturn,null);
    cleanup();
});
