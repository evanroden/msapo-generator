const assert = require('node:assert/strict');
const fs = require('node:fs');

function actualFunction(source, name) {
    const start=source.indexOf('function '+name+'(');
    assert(start>=0, name);
    let quote=null, escaped=false, depth=0, begun=false;
    for(let i=source.indexOf('{',start);i<source.length;i++) {
        const c=source[i];
        if(quote) {if(escaped)escaped=false;else if(c==='\\')escaped=true;else if(c===quote)quote=null;continue;}
        if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
        if(c==='{'){depth++;begun=true;}
        if(c==='}'&&--depth===0&&begun)return source.slice(start,i+1);
    }
    throw Error('Unclosed '+name);
}

function model(source, shouldFlip=false) {
    const frames=new Map(), observers=[], cleanups=[], writes=[], layoutEffects=[], listeners=new Map(), feedback=[];
    let frame=0, inDelivery=false, stateChanges=0;
    class Element {
        constructor(tag,box){this.tagName=tag;this.box={...box};this.naturalHeight=box.height;
            this.scrollTop=0;this.scrollLeft=0;this.clientTop=0;this.clientLeft=0;
            this.clientWidth=box.width;this.clientHeight=box.height;this.scrollWidth=box.width;this.scrollHeight=box.height;
            this.style=new Proxy({}, {set:(object,key,value)=>{writes.push({key,value,inDelivery});object[key]=value;return true;}});}
        getBoundingClientRect(){const cap=parseFloat(this.style.maxHeight);return {...this.box,height:Math.min(this.naturalHeight,Number.isFinite(cap)?cap:Infinity)};}
        get offsetWidth(){return this.getBoundingClientRect().width;}
        get offsetHeight(){return this.getBoundingClientRect().height;}
        contains(target){for(let current=target;current;current=current.parentElement)if(current===this)return true;return false;}
    }
    const root=new Element('HTML',{top:0,left:0,width:1365,height:900});
    const body=new Element('BODY',{top:0,left:0,width:1365,height:900});body.parentElement=root;
    const target=new Element('DIV',{top:777,left:419,width:405.765625,height:38});target.parentElement=body;
    const overlay=new Element('DIV',{top:0,left:0,width:405.765625,height:120});overlay.parentElement=body;overlay.offsetParent=root;
    const document={documentElement:root,body,activeElement:null,defaultView:{HTMLElement:Element}};
    for(const element of [root,body,target,overlay])element.ownerDocument=document;
    const add=(type,callback)=>{const values=listeners.get(type)||[];values.push(callback);listeners.set(type,values);};
    const remove=(type,callback)=>listeners.set(type,(listeners.get(type)||[]).filter(value=>value!==callback));
    class ResizeObserver {
        constructor(callback){this.callback=callback;this.targets=[];observers.push(this);}
        observe(target){this.targets.push(target);}
        unobserve(target){this.targets=this.targets.filter(value=>value!==target);}
    }
    const visualViewport={width:1365,height:900,offsetTop:0,offsetLeft:0,pageTop:0,pageLeft:0,scale:1,
        addEventListener:add,removeEventListener:remove};
    const window={visualViewport,innerHeight:900,ResizeObserver,addEventListener:add,removeEventListener:remove,
        getComputedStyle:element=>({position:element===overlay?'fixed':'static',marginTop:'0px',marginBottom:'0px',
            marginLeft:'0px',marginRight:'0px',borderTopWidth:'0px',borderLeftWidth:'0px',transform:'none',willChange:'',filter:'none',contain:''})};
    const lifecycle=callback=>{const cleanup=callback();if(typeof cleanup==='function')cleanups.push(cleanup);};
    const scope={window,document,HTMLElement:Element,requestAnimationFrame:callback=>{const id=frame++;frames.set(id,callback);return id;},
        cancelAnimationFrame:id=>frames.delete(id),setTimeout:()=>0,clearTimeout:()=>{},
        u:{useRef:value=>({current:value}),useCallback:callback=>callback,useState:value=>[value,()=>{stateChanges++;}],useEffect:lifecycle},
        p:(callback)=>{layoutEffects.push(callback);lifecycle(callback);},ut:()=>({direction:'ltr'}),
        Ze:callback=>callback,ve:()=>false,R:()=>null,Jt:()=>{},I:()=>false,Ke:()=>false,Y:visualViewport,Yt:()=>true};
    const constantStart=source.indexOf('G={top:`top`,bottom:`top`');
    const constantEnd=source.indexOf(';function Nt(',constantStart);
    assert(constantStart>=0&&constantEnd>constantStart);
    const names=['U','Nt','Pt','Ft','It','Lt','Rt','Bt','zt','Vt','Ht','Ut','J','Wt','Gt','Kt','L','$t','Xt','Qt','Zt'];
    const code='var '+source.slice(constantStart,constantEnd)+';'+names.map(name=>actualFunction(source,name)).join(';')+';return Zt;';
    const hook=new Function('scope','with(scope){'+code+'}')(scope);
    hook({targetRef:{current:target},overlayRef:{current:overlay},placement:'bottom left',shouldFlip,isOpen:true});
    const initialWrites=writes.length;
    function deliver() {
        inDelivery=true;
        try {for(const observer of observers)for(const target of observer.targets) {
            const before=target.getBoundingClientRect();
            observer.callback([{target,contentRect:before}],observer);
            if(target.getBoundingClientRect().height!==before.height)feedback.push(target.tagName);
        }}
        finally {inDelivery=false;}
    }
    function nextFrame(){const pending=[...frames.values()];frames.clear();for(const callback of pending)callback();}
    return {frames,observers,writes,layoutEffects,initialWrites,overlay,target,deliver,nextFrame,feedback,
        get stateChanges(){return stateChanges;},resizeWindow(){for(const callback of listeners.get('resize')||[])callback();},
        dispose(){for(const cleanup of cleanups.reverse())cleanup();}};
}

const original=fs.readFileSync(process.argv[2],'utf8'), repaired=fs.readFileSync(process.argv[3],'utf8');
for(const flip of [false,true]) {
    // This is a controlled DOM/geometry adapter, not a browser's RO algorithm.
    // It executes the actual locked Zt -> Xt -> T -> Ht/math/style chain.
    const old=model(original,flip);
    assert(old.initialWrites>0);old.deliver();
    assert(old.writes.some(write=>write.inDelivery),'Original positioner writes layout during native resize delivery');
    const fixed=model(repaired,flip);
    assert.equal(fixed.initialWrites,old.initialWrites,'Initial layout positioning stays synchronous');
    const initialHeight=fixed.overlay.style.maxHeight;
    assert.equal(initialHeight,old.overlay.style.maxHeight);
    if(!flip)assert.equal(initialHeight,'73px','Actual finite viewport position math is exercised');
    fixed.deliver();fixed.deliver();
    assert.equal(fixed.writes.length,fixed.initialWrites,'Neither resize callback may synchronously write layout');
    assert.equal(fixed.frames.size,1,'Both target/overlay callbacks coalesce into one frame, including frame ID zero');
    fixed.nextFrame();
    assert(fixed.writes.length>fixed.initialWrites);
    assert.equal(fixed.overlay.style.maxHeight,initialHeight,'Actual placement/maxHeight result is preserved');
    assert(!fixed.writes.some(write=>write.inDelivery));
    // A finite target resize is a legitimate input to the real position math.
    // The nonflipping case changes the observed overlay height inside its own
    // old callback, the concrete feedback class that a native RO may reject.
    old.target.naturalHeight=60;old.target.box.height=60;old.deliver();
    fixed.target.naturalHeight=60;fixed.target.box.height=60;fixed.deliver();
    assert.equal(fixed.overlay.style.maxHeight,initialHeight,'Position writes wait for the one resize frame');
    if(!flip)assert(old.feedback.length>0,'Original callback changes its observed overlay during delivery');
    assert.equal(fixed.feedback.length,0);
    fixed.nextFrame();assert.equal(fixed.overlay.style.maxHeight,old.overlay.style.maxHeight);
    if(!flip)assert.equal(fixed.overlay.style.maxHeight,'51px');
    const writes=fixed.writes.length;fixed.resizeWindow();
    assert(fixed.writes.length>writes,'Normal window resize positioning remains immediate');
    fixed.deliver();assert.equal(fixed.frames.size,1);const beforeDispose=fixed.writes.length;
    fixed.dispose();assert.equal(fixed.frames.size,0,'Unmount cancels queued position work');
    fixed.nextFrame();assert.equal(fixed.writes.length,beforeDispose);
    assert(fixed.observers.every(observer=>observer.targets.length===0),'Original hook observer cleanup remains intact');
    for(const observer of fixed.observers)observer.callback([{target:fixed.overlay,contentRect:{}}],observer);
    assert.equal(fixed.frames.size,0,'Late native delivery cannot revive disposed position work');
}
{
    const fixed=model(repaired);fixed.deliver();
    fixed.overlay.getBoundingClientRect=()=>{throw Error('original layout failure');};
    assert.throws(()=>fixed.nextFrame(),/original layout failure/,'Scheduling does not swallow callback failures');
}
console.log('actual locked overlay callback chain: synchronous RO writes reproduced; coalescing, placement and cleanup passed');
