const assert=require('node:assert/strict');
const fs=require('node:fs');
const crypto=require('node:crypto');
const sourcePath=process.argv[2], repairedPath=process.argv[3];
const source=fs.readFileSync(sourcePath,'utf8');
const digest=crypto.createHash('sha256').update(source).digest('hex');
assert.equal(digest,'1ebdea14d07b36247a221305bfbb455b368a7fe79c86b24f509743c278a29ce6');
function actualFunction(source,name){
 const start=source.indexOf('function '+name+'(');assert(start>=0);
 let quote=null,escaped=false,depth=0;
 for(let i=source.indexOf('{',start);i<source.length;i++){
  const c=source[i];
  if(quote){if(escaped)escaped=false;else if(c==='\\')escaped=true;else if(c===quote)quote=null;continue;}
  if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
  if(c==='{')depth++;
  if(c==='}'&&--depth===0)return source.slice(start,i+1);
 }
 throw Error('Unclosed '+name);
}
const candidate=fs.readFileSync(repairedPath,'utf8');
function model(raw,windowScrolling){
 const updates=[],writes=[],commits=[],listeners=new Map(),windowListeners=new Map(),cleanups=[],frames=new Map(),microtasks=[],timers=new Map();
 let inDelivery=false,phase='initial',nextFrame=0,nextTimer=0,observer;
 const root={clientWidth:468,clientHeight:480,scrollLeft:0,scrollTop:0,
  getBoundingClientRect(){return{x:0,y:0,width:this.clientWidth,height:this.clientHeight}}};
 const effects=callback=>{const cleanup=callback();if(typeof cleanup==='function')cleanups.push(cleanup)};
 const callback=(type,value)=>updates.push({type,phase,inDelivery,width:value.width,height:value.height,x:value.x,y:value.y});
 const add=(registry)=>(type,cb)=>{const rows=registry.get(type)||[];rows.push(cb);registry.set(type,rows)};
 const remove=(registry)=>(type,cb)=>registry.set(type,(registry.get(type)||[]).filter(x=>x!==cb));
 const window={innerWidth:1365,innerHeight:900,HTMLElement:class{},
  addEventListener:add(windowListeners),removeEventListener:remove(windowListeners),dispatchEvent:event=>updates.push({type:event.type,phase,inDelivery})};
 const document={addEventListener:add(listeners),removeEventListener:remove(listeners)};
 const scope={window,document,J:{useRef:value=>({current:value}),useCallback:cb=>cb,
  useState:value=>[value,changed=>updates.push({type:'state',phase,inDelivery,value:changed})],useEffect:effects},
  T:effects,f:cb=>cb,o:()=>({direction:'ltr'}),s:event=>event.target,c:(element,target)=>element===target,
  Sr:{flushSync:cb=>{commits.push({phase,inDelivery});cb()}},
  k:options=>{observer=options.onResize},Event:class{constructor(type){this.type=type}},
  requestAnimationFrame:cb=>{const id=nextFrame++;frames.set(id,cb);return id},cancelAnimationFrame:id=>frames.delete(id),
  queueMicrotask:cb=>microtasks.push(cb),setTimeout:cb=>{const id=nextTimer++;timers.set(id,cb);return id},clearTimeout:id=>timers.delete(id)};
 const start=raw.indexOf('X=class e{'),end=raw.indexOf(',or=0,',start);assert(start>0&&end>start);
 const code='var '+raw.slice(start,end)+';'+actualFunction(raw,'xr')+';'+actualFunction(raw,'Cr')+';return {Cr,Q};';
 const {Cr,Q}=new Function('scope','with(scope){'+code+'}')(scope);
 const content=new Q(468,480);
 const result=Cr({contentSize:content,allowsWindowScrolling:windowScrolling,onVisibleRectChange:rect=>callback('visibleRect',rect),
  onSizeChange:size=>{callback('size',size);
   // React commit/DOM adapter: one finite layout correction after width changes.
   // The cap418 comes from the trace, but this root-height transition is a
   // controlled model precondition, NOT a measured browser clientHeight.
   if(size.width===648&&root.clientHeight===480){
    writes.push({property:'clientHeight',before:480,after:418,phase,inDelivery});root.clientHeight=418;
   }}},{current:root});
 while(microtasks.length)microtasks.shift()();
 const initial=updates.filter(r=>r.type==='visibleRect'||r.type==='size');
 assert(initial.length>0&&initial.every(r=>!r.inDelivery));
 const deliver=()=>{phase='native-resize-delivery';inDelivery=true;try{observer()}finally{inDelivery=false}};
 const next=()=>{phase='next-animation-frame';const pending=[...frames.values()];frames.clear();for(const cb of pending)cb()};
 return {updates,writes,commits,frames,root,content,result,initial,deliver,next,
  changeWidth(){phase='external-finite-width-change';root.clientWidth=648;content.width=648},
  scroll(){phase='normal-scroll';root.scrollTop=180;for(const cb of listeners.get('scroll')||[])cb({target:root})},
  resizeWindow(){phase='normal-window-resize';window.innerWidth=1400;for(const cb of windowListeners.get('resize')||[])cb()},
  dispose(){for(const cleanup of cleanups.reverse())cleanup()},
  setPhase(value){phase=value}};
}
for(const windowScrolling of [false,true]) {
const old=model(source,windowScrolling),fixed=model(candidate,windowScrolling);
assert.deepEqual(old.initial,fixed.initial,'Normal initial layout/size updates are unchanged');
for(const state of [old,fixed])state.changeWidth();
old.deliver();fixed.deliver();fixed.deliver();
const oldNative=old.updates.filter(r=>r.inDelivery&&(r.type==='visibleRect'||r.type==='size'));
assert.deepEqual(oldNative.map(r=>[r.type,r.width,r.height]),[
 ['visibleRect',648,480],['size',648,480],['visibleRect',648,418],['size',648,418]
]);
assert.equal(old.writes.filter(r=>r.inDelivery).length,1);
assert.equal(fixed.updates.filter(r=>r.inDelivery).length,0);
assert.equal(fixed.frames.size,1,'Multiple native deliveries coalesce, including frame ID0');
fixed.next();
assert.deepEqual(fixed.updates.filter(r=>r.phase==='next-animation-frame'&&(r.type==='visibleRect'||r.type==='size'))
 .map(r=>[r.type,r.width,r.height]),oldNative.map(r=>[r.type,r.width,r.height]));
assert.equal(fixed.writes.filter(r=>r.inDelivery).length,0);
for(const state of [old,fixed])state.scroll();
assert.deepEqual(old.updates.filter(r=>r.phase==='normal-scroll'),fixed.updates.filter(r=>r.phase==='normal-scroll'),
 'Actual normal scroll flushSync/visibleRect/scroll lifecycle stays unchanged');
if(windowScrolling){const before=fixed.commits.length;fixed.resizeWindow();
 assert(fixed.commits.length>before,'Normal window resize remains synchronous');}
const beforeNoOp=fixed.updates.length;fixed.deliver();fixed.next();
assert.equal(fixed.updates.length,beforeNoOp,'An unchanged resize does not introduce virtual-list state updates');
fixed.deliver();assert.equal(fixed.frames.size,1);fixed.dispose();assert.equal(fixed.frames.size,0);fixed.next();
fixed.deliver();assert.equal(fixed.frames.size,0,'Late callback cannot restart disposed resize work');
}
{
 const fixed=model(candidate,false);fixed.changeWidth();fixed.deliver();
 Object.defineProperty(fixed.root,'clientWidth',{get(){throw Error('original virtual-list dimension failure')}});
 assert.throws(()=>fixed.next(),/original virtual-list dimension failure/,'Callback failures remain observable');
}
console.log('actual virtual-list resize: coalescing, exact geometry, scroll and cleanup passed');
