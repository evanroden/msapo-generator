const assert=require('node:assert/strict'),fs=require('node:fs');
const src=JSON.parse(fs.readFileSync(process.argv[2]));
// Exact native callbacks plus explicitly supplied measured geometry. This
// model is not a browser layout engine or a physical keyboard/pointer test.
function make(fixed, activation=1){
 const passive=[],cleanups=[],refs=[],timers=new Map(),animations=[],observations=[];let timerid=0;
 let expandedState=false;
 const K={useState:v=>[v,next=>{expandedState=next}],useRef:v=>{const r={current:v};refs.push(r);return r},useCallback:fn=>fn,
  useEffect:fn=>passive.push(fn)};
 class Node{constructor(parent){this.parentNode=parent;this.scrollTop=0;this.scrollLeft=0}contains(x){for(;x;x=x.parentNode)if(x===this)return true;return false}}
 class HTMLInputElement extends Node{};class HTMLTextAreaElement extends Node{};
 const document=new Node(),main=new Node(document),details=new Node(main),input=new HTMLInputElement(details);
 document.scrollingElement=main;const listeners=new Set();
 const window={addEventListener:(type,fn)=>listeners.add(fn),removeEventListener:(type,fn)=>listeners.delete(fn)};
 const content={getBoundingClientRect:()=>({height:521})},summary={getBoundingClientRect:()=>({height:38})};
 details.open=false;details.style={height:'',overflow:''};details.renderedHeight=null;
 details.getBoundingClientRect=()=>({height:details.renderedHeight??(details.style.height?parseFloat(details.style.height):(details.open?561:40))});
 details.animate=(frames,options)=>{
  const callbacks={};const a={playState:'running',frames,options,addEventListener:(kind,fn)=>callbacks[kind]=fn,
   cancel(){this.playState='idle';details.renderedHeight=null;callbacks.cancel?.()},
   finish(){this.playState='finished';details.renderedHeight=null;callbacks.finish?.()}};
  animations.push(a);return a;
 };
 const ResizeObserver=class{constructor(fn){this.fn=fn;observations.push(this)}observe(){}disconnect(){this.disconnected=true}};
 let debounced;const Yr=fn=>{debounced=fn;return{clear(){},restart(){fn()}}};
 const setTimeout=(fn,ms)=>{const id=++timerid;timers.set(id,{fn,ms});return id},clearTimeout=id=>timers.delete(id);
 const mount=new Function('K','H','Yr','ResizeObserver','Eu','Du','Ou','setTimeout','clearTimeout',
  src[fixed?'after':'before']+';return Mu')
  (K,v=>v==null,Yr,ResizeObserver,fixed?0:500,'cubic-bezier(0.23, 1, 0.32, 1)',1000,setTimeout,clearTimeout);
 const toggles=[];const h=mount({backendExpanded:false,label:'Training',onToggle:v=>toggles.push(v)});
 h.detailsRef.current=details;h.summaryRef.current=summary;h.contentRef.current=content;
 while(passive.length){const cleanup=passive.shift()();if(cleanup)cleanups.push(cleanup)}
 function toggle(){let prevented=false;h.handleToggle({type:"click",detail:activation,preventDefault(){prevented=true}});assert.ok(prevented)};
 let closes=0,scrollCleanup;const k={current:false},writes=[],filter={current:""};const u={useEffect:fn=>scrollCleanup=fn(),useRef:v=>({current:v}),useCallback:fn=>fn};
 const Jt=new Function('u','Xe','z','Node','HTMLInputElement','HTMLTextAreaElement','L','window','document','qt',
  src.latest+src.scroll+';return Jt')(u,fn=>fn(),e=>e.target,Node,HTMLInputElement,HTMLTextAreaElement,
  (parent,child)=>parent.contains(child),window,document,new WeakMap());
 const popup=()=>{k.current=true;Jt({triggerRef:{current:input},isOpen:true,onClose:()=>{closes++;k.current=false}})};
 const change=new Function("k","K","O","t","x","S","T","return "+src.change)(k,
  {current:[{id:"0",value:"Synthetic Person North"}]},filter,{maxSelections:0},[],
  pending=>writes.push(pending.value),value=>filter.current=value);
 const scroll=target=>{for(const fn of listeners)fn({target})};
 return{details,main,toggle,toggles,timers,animations,observations,popup,scroll,
  get expandedState(){return expandedState},
  select(){filter.current="Synthetic Person North";change(["0"]);return writes},
  get closes(){return closes},stop(){scrollCleanup?.();for(const fn of cleanups)fn();assert.equal(listeners.size,0)},
  resize(){observations[0].fn()}};
}
for(const fixed of [false,true]){
 const h=make(fixed);h.toggle();assert.equal(h.details.open,true);
 // Heights/offsets are measured in the retained browser trace. The model does
 // not pretend to be a browser layout engine: supply the observed geometry.
 if(!fixed){h.details.renderedHeight=555;h.details.scrollTop=6}
 h.popup();
 if(!fixed){h.details.renderedHeight=557;h.details.scrollTop=4;h.scroll(h.details)}
 else {assert.equal(h.details.getBoundingClientRect().height,561);assert.equal(h.details.style.overflow,'');h.scroll(h.details)}
 assert.equal(h.closes,fixed?0:1);
 assert.deepEqual(h.select(),fixed?[["Synthetic Person North"]]:[],"native selection needs the popup to survive the opening geometry");
 h.stop();assert.equal(h.timers.size,0);
 const real=make(fixed);real.toggle();real.popup();real.main.scrollTop=30;real.scroll(real.main);assert.equal(real.closes,1);real.stop();
}
// Pointer click and keyboard-generated summary click enter the same untouched
// native handleToggle callback; this is not physical-device acceptance.
for(const activationDetail of [1,0]){
 const h=make(true,activationDetail);h.toggle();h.toggle();h.toggle();
 assert.deepEqual(h.toggles,[true,false,true]);assert.equal(h.expandedState,true);assert.equal(h.details.open,true);
 assert.equal(h.animations.length,0);assert.equal(h.timers.size,0);
 h.resize();assert.equal(h.animations.length,0);h.toggle();assert.equal(h.details.open,false);assert.equal(h.expandedState,false);h.stop();assert.ok(h.observations.every(o=>o.disconnected));
}
console.log('Exact native expander/scroll model: measured animation movement closes old popup; instant geometry retains popup; real scroll still closes; rapid toggles/cleanup pass. Browser causality remains unproved.');
