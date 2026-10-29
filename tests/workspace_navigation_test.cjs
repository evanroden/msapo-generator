const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const geometry=require('../app/workspace_geometry.js');

function harness(mode='wide', sequential=false) {
    const state={mode,ownsScroll:mode==='tabletop'}, document={activeElement:null};
    let scheduled=0, replacements=0, nativeEvents=0;
    // Native DOMRect properties are prototype getters, not enumerable fields.
    const rect=(top,height)=>Object.create({get top(){return top},get bottom(){return top+height},get height(){return height}});
    const scrollport={scrollTop:0,getBoundingClientRect:()=>rect(0,900)};
    const root={dataset:{},scrollTop:0,getBoundingClientRect:()=>rect(state.ownsScroll?500:300-scrollport.scrollTop,state.ownsScroll?400:3500)};
    const label={getBoundingClientRect:()=>rect(64,52)};
    const select={value:'',children:[],closest:()=>label,
        replaceChildren(...items){this.children=items;this.value=items[0]?.value||'';replacements++;}};
    const reviewButton={disabled:true,onclick:null};
    const backButton={disabled:true,onclick:null}, nextButton={disabled:true,onclick:null,textContent:'Next'};
    const progress={textContent:'Cover',dataset:{}};
    const nav={querySelector:selector=>({
        '.epc-review-shortcut':sequential?null:reviewButton,
        '.epc-section-selector':sequential?null:select,
        '.epc-section-back':sequential?backButton:null,
        '.epc-section-next':sequential?nextButton:null,
        '.epc-section-progress':sequential?progress:null,
    })[selector] || null,getBoundingClientRect:label.getBoundingClientRect};
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
    let clickHandler=null;
    const review=target(4000,60,true), app={querySelector:()=>review,contains:()=>true,
        addEventListener(type,handler){if(type==='click')clickHandler=handler},
        removeEventListener(type,handler){if(clickHandler===handler)clickHandler=null}};
    document.createElement=()=>({});
    const context={document,getComputedStyle:node=>node.style||{overflowY:"auto",overscrollBehaviorY:"auto"}};vm.runInNewContext(fs.readFileSync('app/workspace_navigation.js','utf8'),context);
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
    return {correct(href,options={}){let prevented=false; const link={getAttribute:()=>href};
        clickHandler({button:0,target:{closest:()=>link},preventDefault(){prevented=true},...options});
        measure();return prevented;},state,root,scrollport,select,reviewButton,backButton,nextButton,progress,field,pairs,review,app,document,measure,choose,nav,label,controller:()=>controller,
        land:request=>context.ENFRAWorkspaceNavigation.land(state,request),
        cancelLanding:()=>context.ENFRAWorkspaceNavigation.cancelLanding(state),
        input:event=>context.ENFRAWorkspaceNavigation.noteInput(state,event),
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

for(const mode of ['tabletop','confined'])test(`${mode} current section excludes the outside Review heading until explicitly selected`,()=>{
    const h=harness(mode);h.root.scrollTop=650;
    // Review remains in normal page flow when the editor is fixed in the
    // lower pane. Its viewport position is unrelated to this working root.
    h.review.getBoundingClientRect=()=>({top:550,bottom:610,height:60});
    h.measure();
    assert.equal(h.select.value,'monthly_activity');
    assert.equal(h.root.dataset.epcReviewOpen,'false');
    assert.equal(h.select.children.at(-1).value,'report_review','Review remains an explicit reachable destination');
    assert.equal(h.root.scrollTop,650);assert.equal(h.counts().nativeEvents,0);
});

test('reverse scroll from review restores tabletop at the visible paragraph without a trap',()=>{
    const h=harness('tabletop');h.root.scrollTop=650;h.measure();h.choose('report_review');
    h.input({isTrusted:true,type:'wheel',deltaY:-10,target:{}});
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

for(const mode of ['wide','compact'])test(`${mode} natural review entry keeps the selector reachable and reverse scroll restores its section`,()=>{
    const h=harness(mode);h.document.activeElement=h.field;
    const select=h.select,field=h.field;
    h.scrollport.scrollTop=3880;h.measure();
    assert.equal(h.review.getBoundingClientRect().top,120);
    assert.equal(h.root.dataset.epcReviewOpen,'true','natural entry retains the one selector beyond its editor container');
    assert.equal(h.select.value,'report_review');assert.equal(h.state.ownsScroll,false);
    assert.equal(h.scrollport.scrollTop,3880);assert.equal(h.document.activeElement,field);
    h.scrollport.scrollTop=4200;h.measure();
    assert.equal(h.root.dataset.epcReviewOpen,'true','review remains reachable below its heading');
    h.scrollport.scrollTop=3500;h.measure();
    assert.equal(h.root.dataset.epcReviewOpen,'false');assert.equal(h.select.value,'monthly_empty');
    assert.equal(h.scrollport.scrollTop,3500);assert.equal(h.state.mode,mode);
    assert.equal(h.select,select);assert.equal(h.field,field);assert.equal(h.field.value,'Unblurred human wording');
    assert.equal(h.counts().scheduled,0);assert.equal(h.counts().nativeEvents,0);
});

for(const mode of ['wide','compact'])test(`${mode} a short final Review enters when the editor ends, though its heading cannot reach the line`,()=>{
    // At the end of the page, Review's heading can stay below the reading
    // line while the workspace, and with it the sticky selector, scrolls away.
    const h=harness(mode);h.document.activeElement=h.field;
    h.scrollport.scrollTop=3750;h.measure();
    assert.ok(h.root.getBoundingClientRect().bottom<128 && h.review.getBoundingClientRect().top>128);
    assert.equal(h.root.dataset.epcReviewOpen,'true','the selector stays reachable once the editor has ended');
    assert.equal(h.select.value,'report_review');assert.equal(h.scrollport.scrollTop,3750);
    assert.equal(h.document.activeElement,h.field);
    // A small reverse movement near the end does not flap back.
    h.scrollport.scrollTop=3700;h.measure();
    assert.equal(h.root.dataset.epcReviewOpen,'true');assert.equal(h.select.value,'report_review');
    h.scrollport.scrollTop=3500;h.measure();
    assert.equal(h.root.dataset.epcReviewOpen,'false');assert.equal(h.select.value,'monthly_empty');
    assert.equal(h.scrollport.scrollTop,3500);assert.equal(h.counts().nativeEvents,0);
});

test('pinning the selector for Review never changes the measured navigation height',()=>{
    // Pinned, the label carries the container's padding and border; in flow
    // the container does. Previews are placed from this height, so a change
    // on Review would resize every section (WebKit has no scroll anchoring).
    const rect=(top,height)=>({top,bottom:top+height,height});
    const h=harness();
    h.nav.getBoundingClientRect=()=>rect(64,61);
    h.label.getBoundingClientRect=()=>rect(64,h.root.dataset.epcReviewOpen==='true'?61:52);
    h.measure();const closed=h.controller().height();
    h.scrollport.scrollTop=3880;h.measure();
    assert.equal(h.root.dataset.epcReviewOpen,'true');
    assert.equal(h.controller().height(),closed);
});

test('the selector keeps its space in the editor while it is pinned for Review',()=>{
    const css=fs.readFileSync('app/workspace_layout.css','utf8');
    const rule=css.split('.epc-workspace[data-epc-review-open="true"] .st-key-monthly_report_navigation {')[1]?.split('}')[0];
    assert.ok(rule && rule.includes('min-height:var(--epc-nav-space'),'pinning must not pull later content up under the reader');
    assert.ok(fs.readFileSync('app/workspace_layout.js','utf8').includes("css('nav-space'"));
});

test('a streamed navigation container binds through existing discovery and later replacement disposes its predecessor',()=>{
    const classes=()=>{const values=new Set();return {add:value=>values.add(value),remove:value=>values.delete(value),
        contains:value=>values.has(value),toggle:(value,on)=>on?values.add(value):values.delete(value)};};
    const element=()=>({isConnected:true,dataset:{},style:{setProperty(){}},classList:classes(),scrollTop:0,
        children:[],append(child){this.children.push(child)},remove(){},addEventListener(){},removeEventListener(){},
        querySelectorAll:()=>[],querySelector:()=>null,
        getBoundingClientRect:()=>({x:0,y:0,top:0,bottom:900,width:1180,height:900})});
    const root=element(),app=element(),scrollport=element();
    const field={value:'Pending native wording',selectionStart:5,selectionEnd:11};root.children.push(field);
    root.closest=selector=>selector.includes('stMainBlockContainer')?app:scrollport;
    root.dispatchEvent=()=>{};
    const review={isConnected:true,querySelector:()=>null,setAttribute(){},focus(){},
        getBoundingClientRect:()=>({top:4000-scrollport.scrollTop,bottom:4060-scrollport.scrollTop,height:60})};
    app.querySelector=()=>review;
    let mounted=null;
    const makeNav=()=>{
        const nav=element();nav.getBoundingClientRect=()=>({top:64,height:52});
        nav.select={value:'',disabled:true,closest:()=>nav,replaceChildren(...children){this.children=children;this.value=children[0]?.value||'';}};
        nav.querySelector=selector=>selector==='.epc-section-selector'?nav.select:null;return nav;
    };
    const document={activeElement:field,hidden:false,documentElement:{clientWidth:1180},body:element(),
        createElement:element,addEventListener(){},removeEventListener(){},querySelectorAll:()=>[],elementFromPoint:()=>null,
        querySelector:selector=>selector.includes('epc_workspace_')?root:selector.includes('monthly_report_navigation')?mounted:null};
    const observers=[],frames=new Map();let sequence=0;
    class Observer {
        constructor(callback){this.callback=callback;this.targets=new Set();observers.push(this);}
        observe(target){this.targets.add(target)}unobserve(target){this.targets.delete(target)}disconnect(){this.targets.clear()}
    }
    const window={innerHeight:900,addEventListener(){},removeEventListener(){},matchMedia:element};
    const context={document,window,navigator:{},CSS:{escape:value=>value},ENFRAWorkspaceGeometry:geometry,
        ResizeObserver:Observer,MutationObserver:Observer,CustomEvent:class {},
        getComputedStyle:()=>({paddingLeft:'0',paddingRight:'0',fontSize:'16px'}),
        requestAnimationFrame:callback=>{frames.set(++sequence,callback);return sequence},cancelAnimationFrame:id=>frames.delete(id)};
    vm.createContext(context);vm.runInContext(fs.readFileSync('app/workspace_navigation.js','utf8'),context);
    const render=vm.runInContext('('+fs.readFileSync('app/workspace_layout.js','utf8').replace('export default function','function')+')',context);
    const flush=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(callback=>callback())};
    const cleanup=render({data:{workflow:'monthly',identity:'one',navigationKey:'monthly_report_navigation'}});flush();
    const observerCount=observers.length;
    const mutation=observers.find(observer=>observer.targets.has(root));
    assert.ok(mutation,'the existing root child observer admits streamed content');
    mounted=makeNav();mutation.callback();flush();
    const first=mounted;
    assert.equal(typeof first.select.onchange,'function','late-mounted native selector binds without a business rerun');
    assert.equal(first.select.disabled,false);assert.equal(first.select.children[0].value,'report_review');
    assert.ok(observers[0].targets.has(first),'the existing resize observer measures the admitted navigation');
    mounted=makeNav();first.isConnected=false;mutation.callback();flush();
    assert.equal(first.select.onchange,null);assert.equal(typeof mounted.select.onchange,'function');
    assert.equal(observers[0].targets.has(first),false);assert.equal(observers[0].targets.has(mounted),true);
    assert.equal(root.children[0],field);assert.equal(document.activeElement,field);
    assert.equal(field.value,'Pending native wording');assert.equal(field.selectionStart,5);assert.equal(field.selectionEnd,11);
    assert.equal(scrollport.scrollTop,0);assert.equal(root.scrollTop,0);assert.equal(frames.size,0);
    assert.equal(observers.length,observerCount,'streaming/replacement reuses existing observers');
    cleanup();assert.equal(mounted.select.onchange,null);assert.ok(observers.every(observer=>observer.targets.size===0));
});

test('the adapter reuses existing measurement and cleanup with no display submission',()=>{
    const adapter=fs.readFileSync('app/workspace_layout.js','utf8');
    assert.ok(adapter.includes('navigation?.prepare(context,sample,pairs)'));
    assert.ok(adapter.includes('navigation?.update(context,sample)'));
    assert.ok(adapter.includes('navigation?.dispose()'));
    const source=fs.readFileSync('app/workspace_navigation.js','utf8');
    assert.ok(!/new (MutationObserver|ResizeObserver)|requestAnimationFrame|setStateValue|setTriggerValue|dispatchEvent|location\.|history\./.test(source));
    const css=fs.readFileSync('app/workspace_initial.css','utf8');
    assert.ok(css.includes('width:min(32rem,100%)'));assert.ok(css.includes('min-width:0'));
});

test('sticky navigation belongs to the direct workspace wrapper rather than its one-row child',()=>{
    const css=fs.readFileSync('app/workspace_layout.css','utf8');
    const selector='.epc-workspace > [data-testid="stLayoutWrapper"]:has(> .st-key-monthly_report_navigation)';
    const rule=css.split(selector+' {')[1]?.split('}')[0];
    assert.ok(rule,'the retained native snapshot has a short stLayoutWrapper between workspace and keyed navigation');
    assert.ok(rule.includes('position:sticky') && rule.includes('top:var(--epc-nav-top'));
    const inner=css.split('.st-key-monthly_report_navigation {')[1]?.split('}')[0];
    assert.ok(inner && !inner.includes('position:sticky'),'nested stickiness cannot escape the short wrapper');
});

for(const mode of ['wide','compact','tabletop'])test(`${mode} entering from report setup starts once at the first section`,()=>{
    // Continue replaces the setup review with the editor, yet the scroll
    // root keeps the review's offset, here deep in Training.
    const h=harness(mode),owner=mode==='tabletop'?h.root:h.scrollport;
    owner.scrollTop=2300;h.measure();assert.equal(h.select.value,'monthly_training');
    h.land(['entry-1','monthly_cover']);h.measure();
    if(mode==='tabletop')assert.ok(h.root.scrollTop<=0,'the owned root returns to its start');
    else assert.equal(h.pairs[0].pair.getBoundingClientRect().top,128);
    assert.equal(h.select.value,'monthly_cover');
    assert.equal(h.document.activeElement,h.pairs[0].pair);
    // Later renders repeat the consumed request or send none. Reading
    // position, the native field and its selection stay as the user left them.
    owner.scrollTop=1800;h.document.activeElement=h.field;
    for(const request of [['entry-1','monthly_cover'],undefined,null,[]]){h.land(request);h.measure();}
    h.rerender();
    assert.equal(owner.scrollTop,1800);assert.equal(h.document.activeElement,h.field);
    assert.equal(h.field.value,'Unblurred human wording');assert.equal(h.field.selectionStart,3);
    assert.equal(h.counts().nativeEvents,0);
    // A later deliberate entry is a new request. Its Continue replaced the
    // page, so the earlier field no longer holds focus.
    h.document.activeElement=null;h.land(['entry-2','monthly_cover']);h.measure();
    assert.equal(h.select.value,'monthly_cover');assert.equal(h.document.activeElement,h.pairs[0].pair);
});

test('an entry request waits for its section to render',()=>{
    const h=harness();h.scrollport.scrollTop=2300;
    h.land(['entry-1','monthly_rfi']);h.measure();
    assert.equal(h.scrollport.scrollTop,2300,'a section not yet rendered is not guessed');
    assert.equal(h.state.navigationRequest,'monthly_rfi');
});

test('a reader acting before the landing renders keeps their place, focus and later choices',()=>{
    const h=harness();h.scrollport.scrollTop=2300;h.document.activeElement=h.field;
    h.land(['entry-1','monthly_rfi']);  // Its section has not rendered yet.
    h.cancelLanding();                  // A trusted pointer or key arrives first.
    h.measure();
    assert.equal(h.scrollport.scrollTop,2300);assert.equal(h.document.activeElement,h.field);
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.landingRequest,null);
    h.land(['entry-1','monthly_cover']);h.measure();
    assert.equal(h.scrollport.scrollTop,2300,'the cancelled request is not replayed');
    // The reader's own selector choice is never cancelled by its own pointer.
    h.cancelLanding();h.document.activeElement=h.select;h.choose('monthly_training');
    assert.equal(h.pairs[3].pair.getBoundingClientRect().top,128);
});

test('a landing that already ran is not undone by later input',()=>{
    const h=harness();h.scrollport.scrollTop=2300;
    h.land(['entry-1','monthly_cover']);h.measure();
    assert.equal(h.pairs[0].pair.getBoundingClientRect().top,128);
    assert.equal(h.state.landingRequest,null);
    h.cancelLanding();h.scrollport.scrollTop=900;h.measure();
    assert.equal(h.scrollport.scrollTop,900);
});

test('a landing never takes focus or scroll from a control the reader already uses',()=>{
    // The page can be interactive before the adapter mounts, so a menu may
    // already be open when the landing first gets to run.
    const h=harness();h.scrollport.scrollTop=40;h.document.activeElement=h.field;
    h.land(['entry-1','monthly_cover']);h.measure();
    assert.equal(h.scrollport.scrollTop,40);assert.equal(h.document.activeElement,h.field);
    assert.equal(h.state.navigationRequest,null);assert.equal(h.state.landingRequest,null);
    assert.equal(h.field.value,'Unblurred human wording');assert.equal(h.counts().nativeEvents,0);
    // With nothing focused, the same entry would have landed.
    const fresh=harness();fresh.scrollport.scrollTop=2300;fresh.document.body={};fresh.document.activeElement=fresh.document.body;
    fresh.land(['entry-2','monthly_cover']);fresh.measure();
    assert.equal(fresh.pairs[0].pair.getBoundingClientRect().top,128);
});

function entryHarness({stale=false, disabled=false}={}) {
    const document={activeElement:null}, state={};
    let focused=0, scrolled=0;
    const context={document,CSS:{escape:value=>value}};
    vm.runInNewContext(fs.readFileSync('app/workspace_navigation.js','utf8'),context);
    const navigation=context.ENFRAWorkspaceNavigation;
    const field={disabled,focus(options){assert.equal(options.preventScroll,true);document.activeElement=field;focused++;},
        scrollIntoView(options){assert.equal(options.block,'nearest');scrolled++;}};
    const holder={querySelector:selector=>selector==='textarea, input'?field:null};
    const root={markers:[],querySelectorAll:selector=>selector==='[data-enfra-entry-focus]'?root.markers:[],
        querySelector:selector=>selector==='.st-key-row_request_field'?holder:null};
    const marker=nonce=>({dataset:{enfraEntryFocus:nonce,enfraEntryField:'row_request_field',enfraEntryOrigin:'row_add'},
        closest:selector=>stale&&selector==='[data-stale="true"]'?{}:null});
    const keyed=key=>({classList:['stElementContainer','st-key-'+key]});
    const input=(key,isTrusted=true,type='pointerdown',code)=>navigation.noteInput(state,{isTrusted,type,key:code,target:{closest:()=>keyed(key)}});
    return {state,root,field,document,marker,input,focus:()=>navigation.focusEntries(state,root),
        counts:()=>({focused,scrolled})};
}

test('one native Add moves focus into its new row field exactly once',()=>{
    const h=entryHarness();
    h.input('row_add');
    h.root.markers=[h.marker('first')];
    h.focus();
    assert.equal(h.document.activeElement,h.field);
    assert.deepEqual(h.counts(),{focused:1,scrolled:1});
    h.document.activeElement=null;h.input('row_add');h.focus();
    assert.deepEqual(h.counts(),{focused:1,scrolled:1},'a consumed request never focuses again');
});

test('input elsewhere after Add keeps the reader where they are',()=>{
    const h=entryHarness();
    h.input('row_add');h.input('another_section_field');
    h.root.markers=[h.marker('first')];
    h.focus();
    assert.equal(h.document.activeElement,null);
    h.input('row_add');h.focus();
    assert.deepEqual(h.counts(),{focused:0,scrolled:0},'the request is spent; no late focus');
});

test('scripted input never authorizes focus',()=>{
    const h=entryHarness();
    h.input('row_add',false);
    h.root.markers=[h.marker('first')];
    h.focus();
    assert.deepEqual(h.counts(),{focused:0,scrolled:0});
});

test('a stale marker or an unavailable field is consumed without focus',()=>{
    for (const options of [{stale:true},{disabled:true}]) {
        const h=entryHarness(options);
        h.input('row_add');
        h.root.markers=[h.marker('first')];
        h.focus();h.focus();
        assert.deepEqual(h.counts(),{focused:0,scrolled:0});
    }
});

test('the adapter consumes entry focus from its existing measurement and records native input',()=>{
    const layout=fs.readFileSync('app/workspace_layout.js','utf8');
    const measure=layout.split('function measure() {')[1].split('\n    function schedule()')[0];
    assert.match(measure,/ENFRAWorkspaceNavigation\?\.focusEntries\(state, root\)/);
    assert.match(layout,/for \(const type of \['pointerdown', 'keydown', 'wheel', 'touchstart', 'touchmove', 'touchend', 'touchcancel'\]\) \{\s*document\.addEventListener\(type, noteInput/,
        'presses, keys and wheel scrolling are all recorded');
    assert.doesNotMatch(layout,/setInterval|setTimeout/,'no polling or timers');
});

test('Enter or Space on Add authorizes focus like a press',()=>{
    for (const code of ['Enter',' ']) {
        const h=entryHarness();
        h.input('row_add',true,'keydown',code);
        h.root.markers=[h.marker('first')];
        h.focus();
        assert.deepEqual(h.counts(),{focused:1,scrolled:1},JSON.stringify(code));
    }
});

test('tabbing away from Add or scrolling before the row arrives keeps the reader where they went',()=>{
    for (const [type,code] of [['keydown','Tab'],['keydown','ArrowDown'],['wheel',undefined]]) {
        const h=entryHarness();
        h.input('row_add');
        h.input('row_add',true,type,code);
        h.root.markers=[h.marker('first')];
        h.focus();
        assert.deepEqual(h.counts(),{focused:0,scrolled:0},type+' '+code);
    }
});

function anchorHarness({hover, ownsScroll=false}={}) {
    const rect=(top,height)=>({top,bottom:top+height,height,left:80,right:1354});
    const node=(name,top,height,{inNav=false,inSlot=false,control=false}={})=>({name,isConnected:true,top,height,
        getBoundingClientRect(){return {...rect(this.top,this.height),width:this.height?173:0}},
        closest:selector=>inSlot&&selector==='[class*="st-key-epc_preview_slot_"]'||control&&selector==='.epc-preview-controls'?{}:null,inNav});
    const nav={getBoundingClientRect:()=>rect(60,52),contains:target=>Boolean(target?.inNav)};
    const reading=node('reading line',360,40);
    const scrollport={scrollTop:1000,getBoundingClientRect:()=>rect(0,900),contains:target=>Boolean(target)};
    const app={getBoundingClientRect:()=>rect(0,4000)};
    const document={querySelectorAll:selector=>selector===':hover'?(hover?[app,hover]:[]):[],
        elementFromPoint:(x,y)=>(x===104&&Math.round(y)===375?reading:null)};
    const context={document,CSS:{escape:value=>value}};
    vm.runInNewContext(fs.readFileSync('app/workspace_navigation.js','utf8'),context);
    const navigation=context.ENFRAWorkspaceNavigation, state={ownsScroll};
    return {node,reading,scrollport,
        capture:()=>navigation.readingAnchor({state,scrollport,app,nav}),
        keep:anchor=>navigation.keepAnchor(anchor,scrollport)};
}

test('the element under a resting pointer stays put across the adapter layout',()=>{
    const pointed=anchorHarness().node('render outputs',659,40);
    const h=anchorHarness({hover:pointed});
    const anchor=h.capture();
    assert.equal(anchor.node,pointed);
    pointed.top=785;h.keep(anchor);
    assert.equal(h.scrollport.scrollTop,1126,'scroll follows the 126px the layout added above');
});

test('without a usable hovered element the reading line below the selector is kept',()=>{
    const probe=anchorHarness();
    for (const hover of [null, probe.node('selector option',70,20,{inNav:true}),
        probe.node('preview page',300,200,{inSlot:true}), probe.node('page container',-400,5000),
        probe.node('View preview',400,36,{control:true})]) {
        const h=anchorHarness({hover});
        const anchor=h.capture();
        assert.equal(anchor.node,h.reading,String(hover?.name));
        h.reading.top=400;h.keep(anchor);
        assert.equal(h.scrollport.scrollTop,1040);
    }
});

test('a layout that moves nothing, or a scroll the workspace owns, is left alone',()=>{
    const h=anchorHarness();
    const anchor=h.capture();
    h.reading.top=360.4;h.keep(anchor);
    assert.equal(h.scrollport.scrollTop,1000);
    anchor.node.isConnected=false;anchor.node.top=900;h.keep(anchor);
    assert.equal(h.scrollport.scrollTop,1000);
    // A control the new mode hides keeps its node but loses its box. That
    // is not a shift of the content above it.
    const hidden=anchorHarness();const gone=hidden.capture();
    gone.node.top=0;gone.node.height=0;hidden.keep(gone);
    assert.equal(hidden.scrollport.scrollTop,1000);
    assert.equal(anchorHarness({ownsScroll:true}).capture(),null);
});

test('the adapter anchors only around its own layout writes, in page scroll',()=>{
    const layout=fs.readFileSync('app/workspace_layout.js','utf8');
    const measure=layout.split('function measure() {')[1].split('\n    function schedule()')[0];
    assert.match(measure,/readingAnchor\(\{state, scrollport, app, nav: findNav\(\)\}\)/,
        'the selector is known, and excluded, before discovery first binds it');
    const capture=measure.indexOf('readingAnchor(');
    assert.ok(capture>0 && capture<measure.indexOf("root.classList.add('epc-workspace')"),
        'the anchor is taken before the first layout write');
    const keep=measure.indexOf('keepAnchor(');
    assert.ok(keep>measure.indexOf("root.dataset.epcMode = context.mode") && keep<measure.indexOf('navigation?.update('),
        'it is kept after the layout writes and before navigation positions anything');
    assert.match(measure,/if \(previous !== context\.mode && !ownsScroll && !ownedScrollBefore\)\s*\S*keepAnchor\(/,
        'only a layout change in page scroll is compensated');
});

for (const mode of ['wide','compact','tabletop','confined']) test(`${mode} direct Review reuses navigation and preserves return once`,()=>{
    const h=harness(mode);
    if(h.state.ownsScroll) h.root.scrollTop=650; else h.scrollport.scrollTop=600;
    h.measure();
    const oldOffset=h.pairs[1].pair.getBoundingClientRect().top;
    const original={...h.field};
    assert.equal(h.reviewButton.disabled,false);
    h.reviewButton.onclick();h.measure();
    assert.equal(h.state.navigationActive,'report_review');
    assert.equal(h.document.activeElement,h.review);
    const saved=h.state.navigationReturn;
    h.scrollport.scrollTop+=250;
    h.reviewButton.onclick();h.measure();
    assert.equal(h.review.getBoundingClientRect().top,128,'Review remains a useful jump when already in Review');
    assert.equal(h.state.navigationReturn,saved,'repeated Review must not erase the editing return');
    h.choose('monthly_activity');
    assert.equal(h.pairs[1].pair.getBoundingClientRect().top,oldOffset);
    assert.equal(h.field.value,original.value);assert.equal(h.counts().nativeEvents,0);
    h.dispose();assert.equal(h.reviewButton.onclick,null);
});
test('direct Review binding survives a rerender without duplicate scheduling',()=>{
    const h=harness();h.rerender();
    const before=h.counts().scheduled;
    h.reviewButton.onclick();h.measure();
    assert.equal(h.counts().scheduled,before+1);
    h.dispose();assert.equal(h.reviewButton.onclick,null);
});

test('Review stays disabled until its destination exists and unbinds replaced controls',()=>{
    const h=harness();h.app.querySelector=()=>null;h.measure();
    assert.equal(h.reviewButton.disabled,true);
    const before=h.counts().scheduled;
    h.reviewButton.onclick();assert.equal(h.counts().scheduled,before);
    h.app.querySelector=()=>h.review;h.measure();
    assert.equal(h.reviewButton.disabled,false);
    const replacement={disabled:true,onclick:null};
    h.nav.querySelector=selector=>selector==='.epc-review-shortcut'?replacement:selector==='.epc-section-selector'?h.select:null;
    h.measure();assert.equal(h.reviewButton.onclick,null);
    assert.equal(replacement.disabled,false);
    replacement.onclick();h.measure();assert.equal(h.state.navigationActive,'report_review');
    h.dispose();assert.equal(replacement.onclick,null);
});

test('a deliberate Review click supersedes an unconsumed Activity landing',()=>{
    const h=harness();h.land(['entry-1','monthly_activity']);
    h.cancelLanding(); // native pointer/key capture precedes the click
    h.reviewButton.onclick();h.measure();
    assert.equal(h.state.navigationActive,'report_review');
    assert.equal(h.document.activeElement,h.review);
    h.land(['entry-1','monthly_activity']);h.measure();
    assert.equal(h.state.navigationActive,'report_review');
});

for(const mode of ['wide','compact','tabletop','confined'])test(`${mode} sequential controls work without a selector, preserve fields and reach Review`,()=>{
    const h=harness(mode,true);
    assert.equal(h.backButton.disabled,true);
    assert.equal(h.nextButton.disabled,false);
    assert.equal(h.progress.dataset.section,'monthly_cover');
    const click=button=>{assert.equal(button.disabled,false);button.onclick();h.measure()};
    for(let pass=0;pass<3;pass++){
        click(h.nextButton);assert.equal(h.progress.dataset.section,'monthly_activity');
        click(h.backButton);assert.equal(h.progress.dataset.section,'monthly_cover');
    }
    for(const id of ['monthly_activity','monthly_short','monthly_training','monthly_empty']){
        click(h.nextButton);assert.equal(h.progress.dataset.section,id);
    }
    assert.equal(h.nextButton.textContent,'Review');
    click(h.nextButton);assert.equal(h.progress.dataset.section,'report_review');
    assert.equal(h.nextButton.disabled,true);assert.equal(h.state.reviewNavigation,true);
    assert.equal(h.document.activeElement,h.review);
    h.rerender();assert.equal(h.progress.dataset.section,'report_review');
    click(h.backButton);assert.equal(h.progress.dataset.section,'monthly_empty');
    assert.equal(h.field.value,'Unblurred human wording');assert.equal(h.counts().nativeEvents,0);
    h.dispose();assert.equal(h.backButton.onclick,null);assert.equal(h.nextButton.onclick,null);
});

for(const mode of ['wide','tabletop','confined'])test(`${mode} final review correction links retain targeted access without jump menu`,()=>{
    const h=harness(mode,true);
    while(!h.nextButton.disabled){h.nextButton.onclick();h.measure()}
    assert.equal(h.progress.dataset.section,'report_review');
    assert.equal(h.correct('#report-section-activity',{ctrlKey:true}),false);
    assert.equal(h.progress.dataset.section,'report_review');
    assert.equal(h.correct('#report-section-missing'),false);
    assert.equal(h.correct('#report-section-activity'),true);
    assert.equal(h.progress.dataset.section,'monthly_activity');
    assert.equal(h.state.reviewNavigation,false);
    assert.equal(h.document.activeElement,h.pairs[1].pair);
    h.nextButton.onclick();h.measure();assert.equal(h.progress.dataset.section,'monthly_short');
});

for(const mode of ['tabletop','confined'])test(`${mode} mode entry and later sequential return share the unobscured reading line`,()=>{
    const h=harness(mode,true);
    h.state.navigationActive='monthly_activity';
    // Execute the real layout adapter's ownership-transition branch. The
    // navigation harness alone used to skip this branch and therefore missed
    // its different (toolbar-obscured) alignment before the first Next click.
    const adapter=fs.readFileSync('app/workspace_layout.js','utf8');
    const start=adapter.indexOf('        if (previous !== context.mode && activeBefore) {');
    const end=adapter.indexOf('\n        // When the layout itself changes',start);
    assert.ok(start>=0 && end>start);
    vm.runInNewContext(adapter.slice(start,end),{
        previous:'wide',context:{mode:mode==='tabletop'?'tabletop':'compact',editor:{y:500}},
        activeBefore:{pair:h.pairs[1].pair},ownsScroll:true,ownedScrollBefore:false,
        root:h.root,scrollport:h.scrollport,state:h.state,navigation:h.controller(),
    });
    h.measure();
    assert.equal(h.progress.dataset.section,'monthly_activity');
    const offset=()=>h.pairs[1].pair.getBoundingClientRect().top-h.root.getBoundingClientRect().top;
    const before=offset();
    assert.equal(before,h.controller().height()+12,'first entry is below the toolbar, not hidden at root top');
    while(!h.nextButton.disabled){h.nextButton.onclick();h.measure()}
    while(h.progress.dataset.section!=='monthly_activity'){h.backButton.onclick();h.measure()}
    assert.equal(offset(),before,'no toolbar-height jump on sequential return');
    assert.equal(h.field.value,'Unblurred human wording');
    assert.equal(h.counts().nativeEvents,0);
});

for(const mode of ['wide','compact','tabletop'])test(`${mode} passive Review scroll displacement cannot turn first Back into a skipped section`,()=>{
    const h=harness(mode,true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    // Hosted Chromium: no input between Review's confirmed progress and
    // scrollTop16865 ->16138. The old reverse-scroll heuristic exited Review.
    const reviewScroll=h.scrollport.scrollTop;
    h.scrollport.scrollTop=reviewScroll-727;h.measure();
    assert.equal(h.state.reviewNavigation,true);
    assert.equal(h.progress.dataset.section,'report_review');
    h.backButton.onclick();h.measure();
    assert.equal(h.progress.dataset.section,'monthly_empty');
});
for(const event of [
    {type:'wheel',deltaY:-10}, {type:'wheel',deltaY:-2,deltaX:20}, {type:'touchmove',touches:[{clientX:0,clientY:10}]}, {type:'keydown',key:'PageUp'},
    {type:'keydown',key:'ArrowUp'}, {type:'keydown',key:'Home'},
    {type:'keydown',key:' ',shiftKey:true},
    {type:'pointerdown',clientX:995,clientY:500,target:{matches:()=>true,closest:()=>null,clientLeft:0,clientTop:0,clientWidth:984,clientHeight:1000,getBoundingClientRect:()=>({left:0,right:1000,top:0,bottom:1000})}},
])test(`explicit Review yields to genuine ${event.type} ${event.key||'scrollbar'} scrolling`,()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    if(event.type==='touchmove') h.input({isTrusted:true,type:'touchstart',touches:[{clientX:0,clientY:0}],target:{}});
    h.input({isTrusted:true,target:{},...event});
    h.scrollport.scrollTop=2700;h.measure();
    assert.equal(h.state.reviewNavigation,false);
    assert.equal(h.progress.dataset.section,'monthly_training');
});
for(const event of [
    {isTrusted:false,type:'wheel'}, {isTrusted:true,type:'keydown',key:'Tab'},
    {isTrusted:true,type:'keydown',key:'Enter'},
    {isTrusted:true,type:'pointerdown'},
    {isTrusted:true,type:'pointerdown',clientX:500,clientY:500,target:{matches:()=>true,closest:()=>null,clientLeft:0,clientTop:0,clientWidth:984,clientHeight:1000,getBoundingClientRect:()=>({left:0,right:1000,top:0,bottom:1000})}},
    {isTrusted:true,type:'keydown',key:' ',target:{closest:selector=>selector.startsWith('button')?{}:null}},
    {isTrusted:true,type:'keydown',key:'ArrowUp',target:{closest:selector=>selector.startsWith('input')?{}:null}},
])test(`non-scroll ${JSON.stringify(event)} cannot release deliberate Review`,()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    h.input({target:{},...event});
    h.scrollport.scrollTop-=727;h.measure();
    assert.equal(h.state.reviewNavigation,true);
    assert.equal(h.progress.dataset.section,'report_review');
});

test('explicit Review guard transfers through Back, repeated Review and corrective links',()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    assert.equal(h.state.explicitReview,true);
    h.rerender();assert.equal(h.state.explicitReview,true);
    h.backButton.onclick();h.measure();assert.equal(h.state.explicitReview,false);
    assert.equal(h.progress.dataset.section,'monthly_empty');
    h.nextButton.onclick();h.measure();assert.equal(h.state.explicitReview,true);
    h.correct('#report-section-activity');assert.equal(h.state.explicitReview,false);
    assert.equal(h.progress.dataset.section,'monthly_activity');
    h.land(['new-entry','monthly_cover']);assert.equal(h.state.explicitReview,false);
});

for(const event of [
    {type:'wheel',deltaY:-20,ctrlKey:true}, {type:'wheel',deltaY:-20,metaKey:true},
    {type:'wheel',deltaY:0,deltaX:20},
    {type:'wheel',deltaY:-20,target:{scrollHeight:300,clientHeight:100,scrollTop:50}},
    {type:'touchmove',touches:[{clientX:0,clientY:20}],target:{scrollHeight:300,clientHeight:100,scrollTop:50}},
    {type:'touchmove',touches:[{clientX:20,clientY:0}]},
    {type:'touchmove',touches:[{clientX:0,clientY:20},{clientX:10,clientY:20}]},
    {type:'wheel',deltaY:-20,target:{scrollHeight:300,clientHeight:100,scrollTop:0,style:{overflowY:'auto',overscrollBehaviorY:'contain'}}},
])test(`non-page gesture ${JSON.stringify(event)} retains explicit Review`,()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    h.input({isTrusted:true,type:'touchstart',touches:[{clientX:0,clientY:0}],target:{}});
    h.input({isTrusted:true,target:{},...event});
    h.scrollport.scrollTop-=727;h.measure();
    assert.equal(h.state.reviewNavigation,true);
    assert.equal(h.progress.dataset.section,'report_review');
});
for(const type of ['wheel','touchmove'])test(`${type} chains from nested scroller boundary to page`,()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    h.input({isTrusted:true,type:'touchstart',touches:[{clientX:0,clientY:0}],target:{}});
    h.input({isTrusted:true,type,deltaY:-20,touches:[{clientX:0,clientY:20}],target:{scrollHeight:300,clientHeight:100,scrollTop:0}});
    h.scrollport.scrollTop=2700;h.measure();
    assert.equal(h.state.reviewNavigation,false);
    assert.equal(h.progress.dataset.section,'monthly_training');
});

test('stationary touch Add preserves pointerdown provenance until entry arrives',()=>{
    const h=entryHarness();h.input('row_add');
    h.input('row_add',true,'touchstart');h.input('row_add',true,'touchend');
    h.root.markers=[h.marker('touch-tap')];h.focus();
    assert.equal(h.document.activeElement,h.field);
    assert.equal(h.counts().focused,1);
});
for(const type of ['touchmove','touchcancel'])test(`${type} cancels pending Add focus provenance`,()=>{
    const h=entryHarness();h.input('row_add');h.input('row_add',true,'touchstart');
    h.input('row_add',true,type);h.input('row_add',true,'touchend');
    h.root.markers=[h.marker('touch-moved')];h.focus();
    assert.equal(h.counts().focused,0);
});

for(const roleButton of [false,true])test(`Space on ${roleButton?'role-button anchor activates':'plain anchor scrolls page'}`,()=>{
    const h=harness('wide',true);
    while(h.progress.dataset.section!=='report_review'){h.nextButton.onclick();h.measure();}
    const anchor={closest:selector=>selector.includes('a[href]') || roleButton&&selector.includes('[role="button"]') ? {} : null};
    h.input({isTrusted:true,type:'keydown',key:' ',target:anchor});
    h.scrollport.scrollTop-=727;h.measure();
    assert.equal(h.state.reviewNavigation,roleButton);
});
