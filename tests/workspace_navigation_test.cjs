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
        nav.querySelector=()=>nav.select;return nav;
    };
    const document={activeElement:field,hidden:false,documentElement:{clientWidth:1180},body:element(),
        createElement:element,addEventListener(){},removeEventListener(){},
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
    const css=fs.readFileSync('app/workspace_layout.css','utf8');
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
