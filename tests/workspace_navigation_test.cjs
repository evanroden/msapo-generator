const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');

function harness(mode='wide') {
    const state={mode,ownsScroll:mode==='tabletop'}, document={activeElement:null};
    let scheduled=0, replacements=0, nativeEvents=0;
    // Native DOMRect properties are prototype getters, not enumerable fields.
    const rect=(top,height)=>Object.create({get top(){return top},get bottom(){return top+height},get height(){return height}});
    const scrollport={scrollTop:0,getBoundingClientRect:()=>rect(0,900)};
    const root={dataset:{},scrollTop:0,getBoundingClientRect:()=>rect(state.ownsScroll?500:300-scrollport.scrollTop,state.ownsScroll?400:3500)};
    const label={getBoundingClientRect:()=>rect(64,52)};
    const select={value:'',children:[],closest:()=>label,
        replaceChildren(...items){this.children=items;this.value=items[0]?.value||'';replacements++;}};
    const nav={querySelector:()=>select,getBoundingClientRect:label.getBoundingClientRect};
    const field={value:'Unblurred human wording',selectionStart:3,selectionEnd:9,dispatchEvent(){nativeEvents++}};
    const target=(offset,height,outside=false)=>{
        const node={isConnected:true,querySelector:()=>null,setAttribute(){},focus(options){assert.equal(options.preventScroll,true);document.activeElement=node;}};
        node.getBoundingClientRect=()=>rect(outside?offset-scrollport.scrollTop:
            (state.ownsScroll?500+offset-root.scrollTop:300+offset-scrollport.scrollTop),height);
        return node;
    };
    const pairs=[['monthly_cover','Cover',0,400],['monthly_activity','Monthly Activity Summary',400,1600],
        ['monthly_short','Short section',2000,80],['monthly_training','Training Summary',2080,1200],
        ['monthly_empty','Empty section',3280,220]].map(([id,title,offset,height])=>({id,title,pair:target(offset,height)}));
    const review=target(4000,60,true), app={querySelector:()=>review};
    document.createElement=()=>({});
    const context={document};vm.runInNewContext(fs.readFileSync('app/workspace_navigation.js','utf8'),context);
    const create=()=>context.ENFRAWorkspaceNavigation.create({root,app,scrollport,nav,state,geometry,schedule(){scheduled++}});
    let controller=create();
    const sample={chromeBottom:64,scrollport:{y:0},visual:{y:0}};
    const base={mode,reason:mode==='confined'?'segments-insufficient-space':'normal',editor:{y:500},preview:{y:64}};
    if(mode==='confined')base.mode='compact';
    function measure() {
        const resolved=controller.prepare(base,sample,pairs);
        state.mode=resolved.mode;state.ownsScroll=resolved.mode==='tabletop'||resolved.reason==='segments-insufficient-space';
        controller.update(resolved,sample);return resolved;
    }
    const choose=id=>{select.value=id;select.onchange();measure()};
    measure();
    return {state,root,scrollport,select,field,pairs,review,document,measure,choose,
        rerender(){controller.dispose();controller=create();measure()},dispose(){controller.dispose()},
        counts:()=>({scheduled,replacements,nativeEvents})};
}

test('one selector derives exact ordered labels including empty/short sections and review',()=>{
    const h=harness();
    assert.deepEqual(Array.from(h.select.children,o=>o.textContent),
        ['Cover','Monthly Activity Summary','Short section','Training Summary','Empty section','Review and download']);
    const options=[...h.select.children];h.measure();h.measure();
    assert.deepEqual(h.select.children,options,'ordinary measurements never rebuild an open menu');
    assert.equal(h.counts().replacements,1);assert.equal(h.counts().scheduled,0);
    h.rerender();assert.deepEqual(h.select.children,options,'full-render rebinding preserves existing native options');
    assert.equal(h.select.value,'monthly_cover');
    h.scrollport.scrollTop=1800;h.measure();assert.equal(h.select.value,'monthly_activity');
    h.scrollport.scrollTop=2500;h.measure();assert.equal(h.select.value,'monthly_training');
    h.scrollport.scrollTop=3500;h.measure();assert.equal(h.select.value,'monthly_empty');
});

test('a committed native selection moves once below chrome and focuses no business input',()=>{
    const h=harness();const original={...h.field};
    h.document.activeElement=h.select;h.choose('monthly_training');
    assert.equal(h.pairs[3].pair.getBoundingClientRect().top,128);
    assert.equal(h.document.activeElement,h.pairs[3].pair);
    assert.equal(h.counts().scheduled,1);assert.equal(h.counts().nativeEvents,0);
    assert.equal(h.field.value,original.value);assert.equal(h.field.selectionStart,3);assert.equal(h.field.selectionEnd,9);
    h.choose('monthly_short');h.measure();assert.equal(h.select.value,'monthly_short');
    h.choose('monthly_empty');assert.equal(h.select.value,'monthly_empty');
    h.dispose();assert.equal(h.select.onchange,null);
});

test('scroll measurement cannot change the native menu highlight during keyboard choice',()=>{
    const h=harness();h.document.activeElement=h.select;h.select.value='monthly_short';
    h.scrollport.scrollTop=2500;h.measure();assert.equal(h.select.value,'monthly_short');
    h.select.onchange();h.measure();assert.equal(h.select.value,'monthly_short');
    assert.equal(h.document.activeElement,h.pairs[2].pair);
});

for(const mode of ['tabletop','confined'])test(`${mode} review exits the owned scroll root and returns to the actual editing offset`,()=>{
    const h=harness(mode);h.root.scrollTop=650;h.measure();
    assert.equal(h.select.value,'monthly_activity');const oldOffset=h.pairs[1].pair.getBoundingClientRect().top-h.root.getBoundingClientRect().top;
    const select=h.select;h.choose('report_review');
    assert.equal(h.state.ownsScroll,false);assert.equal(h.root.dataset.epcReviewOpen,'true');
    assert.equal(h.review.getBoundingClientRect().top,128);assert.equal(h.select.value,'report_review');
    h.rerender();h.choose('monthly_activity');
    assert.equal(h.select,select);assert.equal(h.state.ownsScroll,true);
    assert.equal(h.root.dataset.epcReviewOpen,'false');
    assert.equal(h.pairs[1].pair.getBoundingClientRect().top-h.root.getBoundingClientRect().top,oldOffset);
    assert.equal(h.field.value,'Unblurred human wording');assert.equal(h.counts().nativeEvents,0);
});

test('reverse scroll from review restores tabletop at the visible paragraph without a trap',()=>{
    const h=harness('tabletop');h.root.scrollTop=650;h.measure();h.choose('report_review');
    h.scrollport.scrollTop=2700;
    const oldOffset=h.pairs[3].pair.getBoundingClientRect().top;
    h.measure();assert.equal(h.state.ownsScroll,true);assert.equal(h.state.reviewNavigation,false);
    assert.equal(h.pairs[3].pair.getBoundingClientRect().top-h.root.getBoundingClientRect().top,oldOffset);
    assert.equal(h.select.value,'monthly_training');assert.equal(h.counts().nativeEvents,0);
});

for(const mode of ['wide','compact'])test(`${mode} review keeps normal scrolling and the same selector`,()=>{
    const h=harness(mode);h.scrollport.scrollTop=1100;h.measure();
    const prior=h.scrollport.scrollTop;h.choose('report_review');
    assert.equal(h.state.mode,mode);assert.equal(h.state.ownsScroll,false);
    assert.equal(h.review.getBoundingClientRect().top,128);
    h.choose('monthly_activity');assert.equal(h.scrollport.scrollTop,prior);
    assert.equal(h.state.mode,mode);assert.equal(h.counts().nativeEvents,0);
});

test('the adapter reuses existing measurement and cleanup with no display submission',()=>{
    const adapter=fs.readFileSync('app/workspace_layout.js','utf8');
    assert.ok(adapter.includes('navigation?.prepare(context,sample,pairs)'));
    assert.ok(adapter.includes('navigation?.update(context,sample)'));
    assert.ok(adapter.includes('navigation?.dispose()'));
    const source=fs.readFileSync('app/workspace_navigation.js','utf8');
    assert.ok(!/new (MutationObserver|ResizeObserver)|requestAnimationFrame|setStateValue|setTriggerValue|dispatchEvent|location\.|history\./.test(source));
    const css=fs.readFileSync('app/workspace_layout.css','utf8');
    assert.ok(css.includes('width:min(32rem,100%)'));assert.ok(css.includes('min-width:0'));
});
